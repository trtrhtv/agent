"""Module 6 — the learning brain.

Three capabilities, all guarded against small-sample overfitting:

1. Post-mortems (run_post_mortem): for every product that has been live long
   enough and sold nothing, an LLM produces a CAUSAL analysis — why it didn't
   sell (causes with evidence and confidence), what to improve — contrasted
   against the niche's winners and the competitor snapshot taken when the
   product was generated. Each post-mortem also distills one generalizable
   lesson that future scans and product generations inject into their prompts.

2. Calibration (run_calibration): pure-Python statistics over actual outcomes —
   which signals (source, competition bucket, price band, niche) actually
   predicted sales. Buckets below MIN_BUCKET_SIZE report "insufficient data"
   instead of fake conclusions.

3. Lessons memory (active_lessons): the accumulated, deduplicated set of
   lessons + latest calibration, capped so prompts stay lean.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import logging
from collections import defaultdict
from typing import Any

from app import db, notify
from app.llm import chat_json

log = logging.getLogger("brain")

POST_MORTEM_MIN_AGE_DAYS = 14     # don't judge a product before it had a chance
MAX_POST_MORTEMS_PER_RUN = 10     # cost cap per weekly run
MIN_BUCKET_SIZE = 5               # calibration buckets below this stay silent
MAX_LESSONS_INJECTED = 8          # prompt-bloat cap


# --- data access -------------------------------------------------------------

def products_with_outcomes() -> list[dict[str, Any]]:
    """Uploaded products joined with their opportunity signals and sales."""
    res = (
        db.client().table("product_jobs")
        .select(
            "id, title, suggested_price_usd, tags, created_at, "
            "opportunities(keyword, niche, trend_score, competition_count, "
            "final_score, source), performance(sales_count, revenue_usd)"
        )
        .eq("status", "uploaded")
        .execute()
    )
    rows = []
    for r in res.data or []:
        perf = r.get("performance") or []
        rows.append({
            **r,
            "total_sales": sum(int(p.get("sales_count") or 0) for p in perf),
            "total_revenue": round(sum(float(p.get("revenue_usd") or 0) for p in perf), 2),
        })
    return rows


def _insert_insight(kind: str, content: str, evidence: dict | None, niche: str | None) -> None:
    db.client().table("insights").insert({
        "kind": kind, "content": content, "evidence": evidence or {}, "niche": niche,
    }).execute()


def _deactivate(kind: str) -> None:
    db.client().table("insights").update({"active": False}).eq("kind", kind).eq("active", True).execute()


def _analyzed_job_ids() -> set[str]:
    res = (
        db.client().table("insights")
        .select("evidence")
        .eq("kind", "post_mortem")
        .execute()
    )
    return {(r.get("evidence") or {}).get("job_id") for r in res.data or []}


def latest_competitor_snapshot(keyword: str) -> list[dict[str, Any]] | None:
    res = (
        db.client().table("competitor_snapshots")
        .select("listings")
        .eq("keyword", keyword)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0]["listings"] if res.data else None


def active_lessons(niche: str | None = None, limit: int = MAX_LESSONS_INJECTED) -> list[str]:
    """Lessons + latest calibration summary for prompt injection. Fail-soft."""
    try:
        query = (
            db.client().table("insights")
            .select("content, niche, kind")
            .eq("active", True)
            .in_("kind", ["lesson", "calibration"])
            .order("created_at", desc=True)
            .limit(limit * 3)
        )
        rows = query.execute().data or []
    except Exception:  # noqa: BLE001 — the brain must never break the pipeline
        return []
    picked = [r["content"] for r in rows if r["niche"] in (None, niche)]
    return picked[:limit]


def lessons_block(niche: str | None = None) -> str:
    lessons = active_lessons(niche)
    if not lessons:
        return ""
    joined = "\n".join(f"- {l}" for l in lessons)
    return f"\nLessons learned from this operation's actual sales history:\n{joined}\n"


# --- 1. calibration (pure statistics, no LLM) --------------------------------

def _competition_bucket(count: int | None) -> str:
    if count is None:
        return "unknown"
    if count < 1_000:
        return "<1k"
    if count < 5_000:
        return "1k-5k"
    if count < 20_000:
        return "5k-20k"
    return ">20k"


def _price_band(price: float | None) -> str:
    if not price:
        return "unknown"
    if price < 12:
        return "$9-11"
    if price < 16:
        return "$12-15"
    return "$16-19"


def calibrate(rows: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    """Bucket outcomes by signal; only speak where the sample is big enough."""
    dims: dict[str, dict[str, list[dict[str, Any]]]] = {
        "source": defaultdict(list),
        "competition": defaultdict(list),
        "price_band": defaultdict(list),
        "niche": defaultdict(list),
    }
    for r in rows:
        opp = r.get("opportunities") or {}
        dims["source"][opp.get("source") or "unknown"].append(r)
        dims["competition"][_competition_bucket(opp.get("competition_count"))].append(r)
        dims["price_band"][_price_band(r.get("suggested_price_usd"))].append(r)
        dims["niche"][opp.get("niche") or "unknown"].append(r)

    lines: list[str] = []
    evidence: dict[str, Any] = {"total_products": len(rows), "buckets": {}}
    for dim, buckets in dims.items():
        for bucket, items in sorted(buckets.items()):
            n = len(items)
            stats = {
                "n": n,
                "sold_share": round(sum(1 for i in items if i["total_sales"] > 0) / n, 2),
                "avg_revenue": round(sum(i["total_revenue"] for i in items) / n, 2),
            }
            evidence["buckets"][f"{dim}:{bucket}"] = stats
            if n >= MIN_BUCKET_SIZE:
                lines.append(
                    f"Signal calibration — {dim}={bucket}: {stats['sold_share']:.0%} of "
                    f"{n} products sold at least once, avg revenue ${stats['avg_revenue']}."
                )
    return lines, evidence


def run_calibration() -> int:
    rows = products_with_outcomes()
    if len(rows) < MIN_BUCKET_SIZE:
        log.info("calibration skipped: only %d products with outcomes", len(rows))
        return 0
    lines, evidence = calibrate(rows)
    if not lines:
        return 0
    _deactivate("calibration")
    _insert_insight("calibration", " ".join(lines), evidence, niche=None)
    return len(lines)


# --- 2. causal post-mortems (LLM) --------------------------------------------

POST_MORTEM_PROMPT = """You are doing a rigorous post-mortem on a digital product that did NOT sell.

PRODUCT (no sales after {age_days} days live):
{product}

ITS SIGNALS AT SCAN TIME: {signals}

TOP COMPETING LISTINGS for its keyword at generation time (may be empty):
{competitors}

THE OPERATION'S CURRENT WINNERS for contrast (may be empty):
{winners}

Analyze causally. Be skeptical: "no distribution/traffic" is the default cause
for marketplace products with zero views — only blame product quality or price
if the evidence supports it. Reply with ONLY JSON:
{{
  "causes": [{{"cause": "one sentence", "evidence": "what supports this", "confidence": "high|medium|low"}}],
  "improvements": ["concrete, actionable change 1", "..."],
  "lesson": "ONE generalizable rule for future keyword selection or product design, or null if this failure teaches nothing general"
}}"""


def run_post_mortem() -> list[str]:
    """Analyze dead products; returns the new lessons (for the owner report)."""
    rows = products_with_outcomes()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=POST_MORTEM_MIN_AGE_DAYS)
    analyzed = _analyzed_job_ids()

    def _old_enough(r: dict[str, Any]) -> bool:
        try:
            created = dt.datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
        except ValueError:
            return False
        return created <= cutoff

    losers = [r for r in rows
              if r["total_sales"] == 0 and r["id"] not in analyzed and _old_enough(r)]
    winners = sorted((r for r in rows if r["total_sales"] > 0),
                     key=lambda r: r["total_revenue"], reverse=True)[:3]
    winners_ctx = [
        {"title": w["title"], "price": w["suggested_price_usd"],
         "keyword": (w.get("opportunities") or {}).get("keyword"),
         "revenue": w["total_revenue"]}
        for w in winners
    ]

    new_lessons: list[str] = []
    for job in losers[:MAX_POST_MORTEMS_PER_RUN]:
        opp = job.get("opportunities") or {}
        try:
            analysis = chat_json([{"role": "user", "content": POST_MORTEM_PROMPT.format(
                age_days=POST_MORTEM_MIN_AGE_DAYS,
                product=json.dumps({
                    "title": job["title"],
                    "price_usd": job["suggested_price_usd"],
                    "tags": job["tags"],
                    "keyword": opp.get("keyword"),
                    "niche": opp.get("niche"),
                }),
                signals=json.dumps({
                    "trend_score": opp.get("trend_score"),
                    "competition_count": opp.get("competition_count"),
                    "final_score": opp.get("final_score"),
                    "source": opp.get("source"),
                }),
                competitors=json.dumps(latest_competitor_snapshot(opp.get("keyword") or "") or "none"),
                winners=json.dumps(winners_ctx or "none"),
            )}])
            causes = analysis.get("causes") or []
            summary = "; ".join(
                f"{c.get('cause')} ({c.get('confidence')})" for c in causes[:3] if isinstance(c, dict)
            )
            _insert_insight(
                "post_mortem",
                f"'{job['title']}' didn't sell: {summary}",
                {"job_id": job["id"], "analysis": analysis},
                niche=opp.get("niche"),
            )
            lesson = analysis.get("lesson")
            if lesson and isinstance(lesson, str) and lesson.lower() != "null":
                _insert_insight("lesson", lesson.strip()[:400],
                                {"job_id": job["id"]}, niche=opp.get("niche"))
                new_lessons.append(lesson.strip())
        except Exception as exc:  # noqa: BLE001 — one bad analysis must not stop the rest
            log.warning("post-mortem failed for job %s: %s", job["id"], exc)
    return new_lessons


# --- weekly entrypoint --------------------------------------------------------

def run_weekly() -> None:
    """Called from learn.py after the sales report. Fail-soft, report loud."""
    try:
        calibration_lines = run_calibration()
        lessons = run_post_mortem()
        if lessons or calibration_lines:
            parts = ["🧠 <b>המוח למד השבוע:</b>"]
            if calibration_lines:
                parts.append(f"📐 כיול אותות עודכן ({calibration_lines} ממצאים מבוססי-מדגם).")
            for lesson in lessons[:5]:
                parts.append(f"• {html.escape(lesson)}")
            if len(lessons) > 5:
                parts.append(f"(+{len(lessons) - 5} לקחים נוספים נשמרו)")
            notify.send_message("\n".join(parts))
    except Exception as exc:  # noqa: BLE001
        notify.report_error("brain", exc)
