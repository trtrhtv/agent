"""Google Trends signal via pytrends.

For each seed we compute growth = mean(last 14 days) / mean(previous 76 days)
over a 90-day window, then map it to a 0-100 trend_score
(flat interest -> 50, doubled interest -> 100).
"""

from __future__ import annotations

import logging
import random
import time

from app.config import GROWTH_SCORE_FACTOR, SCRAPE_DELAY_RANGE

log = logging.getLogger(__name__)

BATCH_SIZE = 5  # pytrends compares at most 5 terms per request


def _growth_to_score(growth: float) -> float:
    return max(0.0, min(100.0, growth * GROWTH_SCORE_FACTOR))


def trend_scores(seeds: list[str]) -> dict[str, float]:
    """Return {seed: trend_score}. Fails soft: seeds we couldn't fetch are
    simply absent from the result."""
    try:
        from pytrends.request import TrendReq
    except Exception as exc:  # pragma: no cover — import-time env issues
        log.warning("pytrends unavailable: %s", exc)
        return {}

    scores: dict[str, float] = {}
    pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 30))

    for start in range(0, len(seeds), BATCH_SIZE):
        batch = seeds[start : start + BATCH_SIZE]
        try:
            pytrends.build_payload(batch, timeframe="today 3-m", geo="US")
            df = pytrends.interest_over_time()
            if df is None or df.empty:
                continue
            for seed in batch:
                if seed not in df.columns:
                    continue
                series = df[seed].astype(float)
                if len(series) < 20:
                    continue
                recent = series.tail(14).mean()
                baseline = series.iloc[:-14].mean()
                growth = recent / baseline if baseline > 0 else (2.0 if recent > 0 else 0.0)
                scores[seed] = round(_growth_to_score(growth), 1)
        except Exception as exc:  # noqa: BLE001 — one bad batch must not kill the run
            log.warning("Google Trends batch failed for %s: %s", batch, exc)
        time.sleep(random.uniform(*SCRAPE_DELAY_RANGE))

    return scores
