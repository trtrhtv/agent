"""Module 1 — daily trend scanner. Railway cron entrypoint: `python scan.py`.

Runs once per active niche (see config.NICHES / TRENDMILL_NICHES), so several
product lines operate in parallel through the same pipeline. Per niche:
seeds -> Google Trends growth + Etsy autocomplete -> relevance filter ->
competition counts -> scoring formula -> LLM re-rank with that niche's
performance context -> top N inserted into `opportunities` -> its own Telegram
digest with per-item buttons.

Idempotent per (day, niche); override with TRENDMILL_FORCE=1. Fail soft: a
niche or source failure is reported to Telegram and the run continues.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sys

from app import brain, db, notify
from app.config import (
    DIGEST_SIZE,
    MAX_COMPETITION_CHECKS,
    SHORTLIST_SIZE,
    active_niches,
    seasonal_seeds,
)
from app.llm import chat_json
from app.scanner import etsy, foresight, trends
from app.scanner.scoring import Candidate, build_candidates, finalize_scores

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("scan")


def rerank_with_llm(candidates: list[Candidate], niche_key: str, niche: dict) -> list[Candidate]:
    """LLM re-ranks the shortlist using the niche's past performance; adds a
    rationale per item. If the call fails, the numeric ranking stands."""
    perf = db.performance_context(niche=niche_key)
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
        "You rank keyword opportunities for sellable Excel/Google Sheets products "
        f"in the '{niche_key}' niche. Target audience: {niche.get('audience', 'online buyers')}.\n"
        f"{brain.lessons_block(niche_key)}"
        f"Past sales performance in this niche (may be empty):\n{json.dumps(perf_lines)}\n\n"
        f"Candidates:\n{json.dumps(items)}\n\n"
        "Re-rank them best-first by expected revenue for a solo seller: favor "
        "specific buyer intent, purchase-ready sub-niches, low competition, and "
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
        log.warning("LLM re-rank failed for %s, keeping numeric order: %s", niche_key, exc)
        notify.report_error(f"scan/rerank/{niche_key}", exc)
        return candidates


def scan_niche(niche_key: str, niche: dict, today: str) -> None:
    existing = db.opportunities_for_date(today, niche=niche_key)
    if existing and os.environ.get("TRENDMILL_FORCE") != "1":
        log.info("[%s] opportunities for %s already exist (%d) — idempotent skip.",
                 niche_key, today, len(existing))
        return

    today_date = dt.date.fromisoformat(today)
    month, iso_week = today_date.month, today_date.isocalendar().week

    # Foresight (Module 9): keywords whose historical seasonal rise starts soon
    # get scanned BEFORE the demand shows up in today's numbers.
    predicted = foresight.upcoming_seasonal_keywords(niche_key, iso_week)
    if predicted:
        log.info("[%s] foresight seasonal seeds: %s", niche_key, predicted)
    seeds: list[str] = list(dict.fromkeys(
        niche["seeds"] + seasonal_seeds(niche_key, month) + predicted
    ))

    # 1. Signals (each source fails soft on its own)
    seed_scores = trends.trend_scores(seeds)
    log.info("[%s] Google Trends scores: %d/%d seeds", niche_key, len(seed_scores), len(seeds))

    suggestions_by_seed = {seed: etsy.autocomplete(seed) for seed in seeds}

    # Foresight: when a known leader spikes TODAY, chase its followers now —
    # they enter as high-priority suggestions and go through normal scoring.
    followers = foresight.followers_of_spiking_leaders(niche_key, seed_scores)
    if followers:
        log.info("[%s] foresight followers of spiking leaders: %s", niche_key, followers)
        suggestions_by_seed["__foresight__"] = followers
    log.info("[%s] Etsy suggestions: %d", niche_key,
             sum(len(v) for v in suggestions_by_seed.values()))

    candidates = build_candidates(seed_scores, suggestions_by_seed, niche["relevance_terms"])
    if not candidates:
        raise RuntimeError(f"[{niche_key}] no candidates from any source — both signals down?")

    # 2. Competition check for the strongest candidates only (politeness cap)
    for cand in candidates[:MAX_COMPETITION_CHECKS]:
        cand.competition_count = etsy.competition_count(cand.keyword)

    # 3. Scoring formula, then 4. LLM re-rank with this niche's learning context
    candidates = finalize_scores(candidates)
    shortlist = rerank_with_llm(candidates[:SHORTLIST_SIZE], niche_key, niche)

    # 5. Persist top N + per-niche Telegram digest
    rows = [
        {
            "scan_date": today,
            "niche": niche_key,
            "keyword": c.keyword,
            "source": c.source,
            "trend_score": c.trend_score,
            "competition_count": c.competition_count,
            "final_score": c.final_score,
            "rationale": c.rationale,
            "status": "new",
        }
        for c in shortlist[:DIGEST_SIZE]
    ]
    db.insert_opportunities(rows)
    inserted = db.opportunities_for_date(today, niche=niche_key)
    inserted.sort(key=lambda r: float(r.get("final_score") or 0), reverse=True)

    notify.send_daily_digest(inserted[:DIGEST_SIZE], label=niche["label"])
    log.info("[%s] digest sent with %d opportunities.", niche_key, min(len(inserted), DIGEST_SIZE))


def run() -> None:
    today = dt.date.today().isoformat()
    failures = 0
    for niche_key, niche in active_niches().items():
        try:
            scan_niche(niche_key, niche, today)
        except Exception as exc:  # noqa: BLE001 — one niche must not kill the rest
            failures += 1
            log.exception("scan failed for niche %s", niche_key)
            notify.report_error(f"scan/{niche_key}", exc)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — fail soft, report loud
        log.exception("scan failed")
        notify.report_error("scan", exc)
        sys.exit(1)
