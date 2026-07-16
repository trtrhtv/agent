"""Module 9 — foresight: mine up to 5 years of Google Trends history to
predict demand BEFORE it shows up in today's numbers.

Two signals, both guarded against statistical hallucination:

1. Seasonal profiles — average each keyword's interest by ISO week across
   years; keep only keywords with real seasonality (peak >= 1.5x the yearly
   average, >= 2 full years of data). Yields "this keyword starts climbing at
   week N every year", which the daily scanner uses to scan it BEFORE the rise.

2. Lead-lag links — cross-correlate WEEK-OVER-WEEK CHANGES (never raw levels —
   raw levels make everything spuriously correlate) between keyword pairs at
   lags of 1-12 weeks. Keep pairs with correlation >= MIN_CORRELATION over
   >= MIN_OVERLAP_WEEKS weeks. Yields "A spikes now => B spikes in k weeks",
   which the scanner uses to chase followers the moment a leader moves.

Analysis is monthly (rate-limit friendly); consumption is daily and fail-soft.
"""

from __future__ import annotations

import logging
import random
import time

from app import db
from app.config import SCRAPE_DELAY_RANGE

log = logging.getLogger("foresight")

HISTORY_TIMEFRAME = "today 5-y"   # weekly resolution
BATCH_SIZE = 5                     # pytrends comparison limit
MAX_KEYWORDS_PER_NICHE = 15        # rate-limit budget per monthly run

MIN_YEARS = 2
MIN_SEASONAL_STRENGTH = 1.5
MAX_LAG_WEEKS = 12
MIN_CORRELATION = 0.45
MIN_OVERLAP_WEEKS = 80
RISE_THRESHOLD = 1.2               # weekly avg >= 1.2x yearly avg counts as "risen"
FORESIGHT_HORIZON_WEEKS = 4        # scanner looks this far ahead
SPIKE_SCORE = 65.0                 # leader considered "spiking" at/above this


# --- history fetch ------------------------------------------------------------

def fetch_history(keywords: list[str]) -> dict[str, "object"]:
    """{keyword: weekly pandas Series over ~5y}. Fails soft per batch."""
    try:
        from pytrends.request import TrendReq
    except Exception as exc:  # pragma: no cover
        log.warning("pytrends unavailable: %s", exc)
        return {}

    series: dict[str, object] = {}
    pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 30))
    for start in range(0, len(keywords), BATCH_SIZE):
        batch = keywords[start : start + BATCH_SIZE]
        try:
            pytrends.build_payload(batch, timeframe=HISTORY_TIMEFRAME, geo="US")
            df = pytrends.interest_over_time()
            if df is None or df.empty:
                continue
            for kw in batch:
                if kw in df.columns:
                    series[kw] = df[kw].astype(float)
        except Exception as exc:  # noqa: BLE001
            log.warning("history batch failed for %s: %s", batch, exc)
        time.sleep(random.uniform(*SCRAPE_DELAY_RANGE))
    return series


# --- 1. seasonal profiles (pure math) ------------------------------------------

def seasonal_profile(series) -> dict | None:
    """rise/peak week + strength, or None when seasonality isn't real enough."""
    import pandas as pd  # pytrends dependency, always present

    s = pd.Series(series).dropna()
    if s.empty:
        return None
    years = s.index.year.nunique()
    if years < MIN_YEARS + 1:  # need >= 2 FULL years; 5y window spans 3+ calendar years
        return None

    weekly_avg = s.groupby(s.index.isocalendar().week.astype(int)).mean()
    weekly_avg = weekly_avg[weekly_avg.index <= 52]
    overall = float(s.mean())
    if overall <= 0 or weekly_avg.empty:
        return None

    peak_week = int(weekly_avg.idxmax())
    strength = float(weekly_avg.max() / overall)
    if strength < MIN_SEASONAL_STRENGTH:
        return None

    # Walk back from the peak while interest stays elevated — the start of that
    # run-up is the "rise week" the scanner should get ahead of.
    rise_week = peak_week
    for back in range(1, 13):
        week = (peak_week - back - 1) % 52 + 1
        if float(weekly_avg.get(week, 0.0)) >= overall * RISE_THRESHOLD:
            rise_week = week
        else:
            break
    return {"rise_week": rise_week, "peak_week": peak_week,
            "strength": round(strength, 2), "years": int(years)}


# --- 2. lead-lag links (pure math) ---------------------------------------------

def lead_lag(leader_series, follower_series) -> dict | None:
    """Best positive-correlation lag (1..MAX_LAG_WEEKS) on weekly CHANGES."""
    import numpy as np
    import pandas as pd

    a = pd.Series(leader_series).dropna().pct_change().replace(
        [float("inf"), float("-inf")], None).dropna()
    b = pd.Series(follower_series).dropna().pct_change().replace(
        [float("inf"), float("-inf")], None).dropna()
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    if len(joined) < MIN_OVERLAP_WEEKS:
        return None

    best: dict | None = None
    av, bv = joined["a"].to_numpy(), joined["b"].to_numpy()
    for lag in range(1, MAX_LAG_WEEKS + 1):
        x, y = av[:-lag], bv[lag:]
        if len(x) < MIN_OVERLAP_WEEKS or x.std() == 0 or y.std() == 0:
            continue
        corr = float(np.corrcoef(x, y)[0, 1])
        if corr >= MIN_CORRELATION and (best is None or corr > best["correlation"]):
            best = {"lag_weeks": lag, "correlation": round(corr, 3), "samples": int(len(x))}
    return best


# --- monthly analysis run -------------------------------------------------------

def _keywords_for_niche(niche_key: str, niche: dict) -> list[str]:
    """Seeds + the niche's historically best-scoring scanned keywords."""
    keywords = list(niche["seeds"])
    try:
        res = (
            db.client().table("opportunities")
            .select("keyword").eq("niche", niche_key)
            .order("final_score", desc=True).limit(20).execute()
        )
        for r in res.data or []:
            if r["keyword"] not in keywords:
                keywords.append(r["keyword"])
    except Exception:  # noqa: BLE001
        pass
    return keywords[:MAX_KEYWORDS_PER_NICHE]


def analyze_niche(niche_key: str, niche: dict) -> tuple[int, int]:
    """Returns (profiles_stored, links_stored)."""
    keywords = _keywords_for_niche(niche_key, niche)
    history = fetch_history(keywords)
    log.info("[%s] history fetched for %d/%d keywords", niche_key, len(history), len(keywords))

    profiles = links = 0
    for kw, series in history.items():
        profile = seasonal_profile(series)
        if profile:
            db.client().table("seasonal_profiles").upsert(
                {"keyword": kw, "niche": niche_key, **profile}, on_conflict="keyword"
            ).execute()
            profiles += 1

    kws = list(history)
    for i, leader in enumerate(kws):
        for follower in kws[i + 1:]:
            for a, b in ((leader, follower), (follower, leader)):
                link = lead_lag(history[a], history[b])
                if link:
                    db.client().table("trend_links").upsert(
                        {"niche": niche_key, "leader": a, "follower": b, **link},
                        on_conflict="leader,follower",
                    ).execute()
                    links += 1
    return profiles, links


# --- daily consumption (called from scan.py, fail-soft) --------------------------

def upcoming_seasonal_keywords(niche_key: str, iso_week: int) -> list[str]:
    """Keywords whose historical rise starts within the foresight horizon."""
    try:
        res = (
            db.client().table("seasonal_profiles")
            .select("keyword, rise_week").eq("niche", niche_key).execute()
        )
    except Exception:  # noqa: BLE001
        return []
    picked = []
    for r in res.data or []:
        weeks_until_rise = (int(r["rise_week"]) - iso_week) % 52
        if weeks_until_rise <= FORESIGHT_HORIZON_WEEKS:
            picked.append(r["keyword"])
    return picked[:6]


def followers_of_spiking_leaders(niche_key: str, seed_scores: dict[str, float]) -> list[str]:
    """Followers whose leader is spiking in TODAY's data — scan them early."""
    spiking = [kw for kw, score in seed_scores.items() if score >= SPIKE_SCORE]
    if not spiking:
        return []
    try:
        res = (
            db.client().table("trend_links")
            .select("leader, follower").eq("niche", niche_key)
            .in_("leader", spiking).order("correlation", desc=True).limit(6)
            .execute()
        )
    except Exception:  # noqa: BLE001
        return []
    return [r["follower"] for r in res.data or []]
