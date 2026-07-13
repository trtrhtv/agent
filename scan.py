"""Module 1 — daily trend scanner. Railway cron entrypoint: `python scan.py`.

Flow: seeds -> Google Trends growth + Etsy autocomplete -> relevance filter ->
competition counts -> scoring formula -> LLM re-rank with performance context ->
insert top N into `opportunities` -> Telegram digest with per-item buttons.

Idempotent: if today's opportunities already exist the run exits early
(override with TRENDMILL_FORCE=1). Fail soft: each source degrades
independently; any fatal error is reported to Telegram, never swallowed.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys

from app import db, notify
from app.config import (
    DIGEST_SIZE,
    MAX_COMPETITION_CHECKS,
    SEED_TERMS,
    SHORTLIST_SIZE,
)
from app.llm import chat_json
from app.scanner import etsy, trends
from app.scanner.scoring import Candidate, build_candidates, finalize_scores

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scan")


def rerank_with_llm(candidates: list[Candidate]) -> list[Candidate]:
    """LLM re-ranks the shortlist using past performance; adds a rationale per
    item. If the call fails, the numeric ranking stands (fail soft)."""
    perf = db.performance_context()
    perf_lines = {
        "top_sellers": [
            {"title": (p.get("product_jobs") or {}).get("title"), "revenue_usd": p.get("revenue_usd")}
            for p in perf["top"]
        ],
        "worst_sellers": [
            {"title": (p.get("product_jobs") or {}).get("title"), "revenue_usd": p.get("revenue_usd")}
            for p in perf["bottom"]
        ],
    }
    items = [
        {
            "keyword": c.keyword,
            "trend_score": c.trend_score,
            "competition_count": c.competition_count,
            "final_score": c.final_score,
        }
        for c in candidates
    ]
    prompt = (
        "You rank keyword opportunities for sellable Excel/Google Sheets templates "
        "on Gumroad (US/global buyers).\n"
        f"Past sales performance (may be empty):\n{json.dumps(perf_lines)}\n\n"
        f"Candidates:\n{json.dumps(items)}\n\n"
        "Re-rank them best-first by expected revenue for a solo seller: favor "
        "specific buyer intent, purchase-ready niches, low competition, and "
        "similarity to past top sellers; penalize similarity to past flops.\n"
        'Reply with ONLY a JSON array: [{"keyword": str, "rationale": str}] '
        "covering every candidate exactly once. rationale: one short sentence, "
        "in English."
    )
    try:
        ranked = chat_json([{"role": "user", "content": prompt}])
        by_kw = {c.keyword: c for c in candidates}
        result: list[Candidate] = []
        for entry in ranked:
            cand = by_kw.pop(entry.get("keyword", ""), None)
            if cand:
                cand.rationale = str(entry.get("rationale", ""))[:300]
                result.append(cand)
        result.extend(by_kw.values())  # anything the LLM dropped keeps its slot
        return result
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM re-rank failed, keeping numeric order: %s", exc)
        notify.report_error("scan/rerank", exc)
        return candidates


def run() -> None:
    today = dt.date.today().isoformat()

    existing = db.opportunities_for_date(today)
    if existing and os.environ.get("TRENDMILL_FORCE") != "1":
        log.info("Opportunities for %s already exist (%d) — idempotent exit.", today, len(existing))
        return

    # 1. Signals (each source fails soft on its own)
    seed_scores = trends.trend_scores(SEED_TERMS)
    log.info("Google Trends scores: %d/%d seeds", len(seed_scores), len(SEED_TERMS))

    suggestions_by_seed: dict[str, list[str]] = {}
    for seed in SEED_TERMS:
        suggestions_by_seed[seed] = etsy.autocomplete(seed)
    total_suggestions = sum(len(v) for v in suggestions_by_seed.values())
    log.info("Etsy autocomplete suggestions: %d", total_suggestions)

    candidates = build_candidates(seed_scores, suggestions_by_seed)
    if not candidates:
        raise RuntimeError("No candidates from any source — both signals down?")

    # 2. Competition check for the strongest candidates only (politeness cap)
    for cand in candidates[:MAX_COMPETITION_CHECKS]:
        cand.competition_count = etsy.competition_count(cand.keyword)

    # 3. Scoring formula
    candidates = finalize_scores(candidates)
    shortlist = candidates[:SHORTLIST_SIZE]

    # 4. LLM re-rank with learning context
    shortlist = rerank_with_llm(shortlist)

    # 5. Persist top N + Telegram digest
    top = shortlist[:DIGEST_SIZE]
    rows = [
        {
            "scan_date": today,
            "keyword": c.keyword,
            "source": c.source,
            "trend_score": c.trend_score,
            "competition_count": c.competition_count,
            "final_score": c.final_score,
            "rationale": c.rationale,
            "status": "new",
        }
        for c in top
    ]
    db.insert_opportunities(rows)
    inserted = db.opportunities_for_date(today)
    inserted.sort(key=lambda r: float(r.get("final_score") or 0), reverse=True)

    notify.send_daily_digest(inserted[:DIGEST_SIZE])
    log.info("Digest sent with %d opportunities.", min(len(inserted), DIGEST_SIZE))


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # noqa: BLE001 — fail soft, report loud
        log.exception("scan failed")
        notify.report_error("scan", exc)
        sys.exit(1)
