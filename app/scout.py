"""Niche scout (Module 8): weekly LLM pass that proposes NEW niches for the
machine, based on what already sells here and what the current niches miss.
Each proposal arrives in Telegram with a ready-to-paste JSON block for the
TRENDMILL_EXTRA_NICHES env var — activating a niche is copy-paste, no deploy.
Proposals are stored as `niche_idea` insights so nothing is proposed twice.
"""

from __future__ import annotations

import html
import json
import logging

from app import db, notify
from app.config import all_niches
from app.llm import chat_json

log = logging.getLogger("scout")

MAX_PROPOSALS_PER_RUN = 2

SCOUT_PROMPT = """You scout NEW product niches for an automated machine that sells
Excel/Google Sheets templates on Gumroad (US/global buyers, $9-39 price range).

CURRENT NICHES (do not re-propose these or trivial variations):
{current}

ALREADY PROPOSED BEFORE (do not repeat):
{proposed}

WHAT ACTUALLY SELLS IN THIS OPERATION SO FAR (may be empty):
{performance}

Propose up to {max_n} niches that are: specific (a buyer group with a burning
tracking/planning problem), underserved (not the saturated generic template
space), and spreadsheet-shaped (the solution is genuinely a spreadsheet).

Reply with ONLY a JSON array:
[{{"key": "snake_case_key", "label": "short Hebrew label", "rationale": "one sentence why now",
  "seeds": ["8-12 English search seed terms"], "relevance_terms": ["8-12 filter words"],
  "audience": "one line who buys"}}]"""


def _already_proposed() -> list[str]:
    res = (
        db.client().table("insights")
        .select("evidence")
        .eq("kind", "niche_idea")
        .execute()
    )
    return [(r.get("evidence") or {}).get("key", "") for r in res.data or []]


def run() -> None:
    """Weekly: propose new niches. Fail-soft — scouting must never break learn."""
    try:
        from app import brain

        performance = [
            {"title": r["title"], "revenue": r["total_revenue"],
             "niche": (r.get("opportunities") or {}).get("niche")}
            for r in brain.products_with_outcomes() if r["total_sales"] > 0
        ][:10]

        proposals = chat_json([{"role": "user", "content": SCOUT_PROMPT.format(
            current=json.dumps({k: v.get("audience") for k, v in all_niches().items()}),
            proposed=json.dumps(_already_proposed()),
            performance=json.dumps(performance),
            max_n=MAX_PROPOSALS_PER_RUN,
        )}], max_tokens=1500)

        if not isinstance(proposals, list):
            return
        for p in proposals[:MAX_PROPOSALS_PER_RUN]:
            key = str(p.get("key", "")).strip()
            if not key or not p.get("seeds") or not p.get("relevance_terms"):
                continue
            niche_json = json.dumps({key: {
                "label": p.get("label", key),
                "seeds": p["seeds"],
                "relevance_terms": p["relevance_terms"],
                "audience": p.get("audience", ""),
            }}, ensure_ascii=False)
            db.client().table("insights").insert({
                "kind": "niche_idea",
                "content": f"Proposed niche: {key} — {p.get('rationale', '')}",
                "evidence": {"key": key, "definition": json.loads(niche_json)},
                "niche": None,
            }).execute()
            notify.send_message(
                f"🧭 <b>הצעת נישה חדשה: {html.escape(str(p.get('label', key)))}</b>\n"
                f"{html.escape(str(p.get('rationale', '')))}\n"
                f"👥 {html.escape(str(p.get('audience', '')))}\n\n"
                "להפעלה: הוסף את הבלוק הזה ל-<code>TRENDMILL_EXTRA_NICHES</code> "
                "ב-Railway ואת המפתח ל-<code>TRENDMILL_NICHES</code>:\n"
                f"<pre>{html.escape(niche_json)}</pre>"
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("niche scout failed: %s", exc)
