"""Module 5 — weekly performance loop (Milestone 4).

run(): pulls the past week's sales from the Gumroad API (view_sales scope),
aggregates per product, upserts into `performance` (idempotent on
week_start + product_job_id), and sends the weekly Hebrew Telegram report.
The data automatically feeds Module 1's LLM re-rank via db.performance_context().
"""

from __future__ import annotations

import datetime as dt
import html
import logging
from collections import defaultdict
from typing import Any

import httpx

from app import db, notify
from app.config import env

log = logging.getLogger("learner")

API_BASE = "https://api.gumroad.com/v2"
TIMEOUT = 60.0


def fetch_sales(after: dt.date, before: dt.date) -> list[dict[str, Any]]:
    """All sales in [after, before), following Gumroad's page_key pagination."""
    sales: list[dict[str, Any]] = []
    params: dict[str, Any] = {
        "access_token": env("GUMROAD_ACCESS_TOKEN"),
        "after": after.isoformat(),
        "before": before.isoformat(),
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        while True:
            resp = client.get(f"{API_BASE}/sales", params=params)
            resp.raise_for_status()
            body = resp.json()
            sales.extend(body.get("sales") or [])
            next_key = body.get("next_page_key")
            if not next_key:
                return sales
            params["page_key"] = next_key


def aggregate_sales(sales: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per Gumroad product_id: sales count + revenue in USD.
    Gumroad reports `price` in cents; refunded sales are excluded."""
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"sales_count": 0, "revenue_usd": 0.0})
    for sale in sales:
        if sale.get("refunded") or sale.get("chargedback"):
            continue
        product_id = sale.get("product_id")
        if not product_id:
            continue
        agg[product_id]["sales_count"] += 1
        agg[product_id]["revenue_usd"] += float(sale.get("price") or 0) / 100.0
    return dict(agg)


def _uploaded_jobs() -> list[dict[str, Any]]:
    res = (
        db.client().table("product_jobs")
        .select("id, title, gumroad_product_id")
        .eq("status", "uploaded")
        .not_.is_("gumroad_product_id", "null")
        .execute()
    )
    return res.data or []


def _upsert_performance(week_start: dt.date, job: dict[str, Any], stats: dict[str, Any],
                        raw: dict[str, Any]) -> None:
    db.client().table("performance").upsert(
        {
            "week_start": week_start.isoformat(),
            "product_job_id": job["id"],
            "views": None,  # not exposed by the sales API
            "sales_count": stats["sales_count"],
            "revenue_usd": round(stats["revenue_usd"], 2),
            "raw": raw,
        },
        on_conflict="week_start,product_job_id",
    ).execute()


def _send_weekly_report(week_start: dt.date, rows: list[dict[str, Any]], total: float) -> None:
    rows = sorted(rows, key=lambda r: r["revenue_usd"], reverse=True)
    top = [r for r in rows if r["revenue_usd"] > 0][:5]
    dead = [r for r in rows if r["sales_count"] == 0]

    lines = [f"📈 <b>דוח מכירות שבועי</b> — שבוע שהתחיל ב-{week_start}\n",
             f"💰 סך הכנסות: <b>${total:,.2f}</b>",
             f"🛒 מוצרים פעילים: {len(rows)} | ללא מכירות: {len(dead)}\n"]
    if top:
        lines.append("🏆 <b>המובילים:</b>")
        lines += [
            f"   {i}. {html.escape(str(r['title'])[:60])} — ${r['revenue_usd']:,.2f} ({r['sales_count']} מכירות)"
            for i, r in enumerate(top, start=1)
        ]
    else:
        lines.append("😴 לא היו מכירות השבוע.")
    if dead:
        names = ", ".join(html.escape(str(r["title"])[:40]) for r in dead[:5])
        lines.append(f"\n🪦 מוצרים מתים (0 מכירות): {names}" + (" ..." if len(dead) > 5 else ""))
    lines.append("\nהנתונים מוזנים אוטומטית לדירוג הסריקה היומית.")
    notify.send_message("\n".join(lines))


def run() -> None:
    today = dt.date.today()
    week_start = today - dt.timedelta(days=7)

    jobs = _uploaded_jobs()
    if not jobs:
        log.info("No uploaded products yet — skipping performance pull.")
        return

    sales = fetch_sales(after=week_start, before=today)
    agg = aggregate_sales(sales)
    log.info("Fetched %d sales across %d products.", len(sales), len(agg))

    report_rows: list[dict[str, Any]] = []
    total = 0.0
    for job in jobs:
        stats = agg.get(job["gumroad_product_id"], {"sales_count": 0, "revenue_usd": 0.0})
        _upsert_performance(week_start, job, stats,
                            raw={"gumroad_product_id": job["gumroad_product_id"]})
        report_rows.append({"title": job["title"], **stats})
        total += stats["revenue_usd"]

    _send_weekly_report(week_start, report_rows, total)

    # Module 6: with fresh outcome data in place, run the learning brain —
    # signal calibration + causal post-mortems + distilled lessons.
    from app import brain, scout

    brain.run_weekly()

    # Module 8: scout new niches based on what the operation now knows.
    scout.run()
