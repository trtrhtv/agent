"""Central configuration: environment variables, seed terms, scan constants."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str | None = None) -> str:
    """Read an env var; raise a clear error at call time if it's missing."""
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# --- Models ---
ROUTINE_MODEL = os.environ.get("ROUTINE_MODEL", "deepseek/deepseek-chat")
GENERATION_MODEL = os.environ.get("GENERATION_MODEL", "anthropic/claude-sonnet-4-6")

# --- Niches: parallel product lines through the same pipeline ---
# Each niche has its own seed terms, relevance filter, and Telegram label.
# Activate a subset via TRENDMILL_NICHES="spreadsheets,trader_tools".
NICHES: dict[str, dict] = {
    "spreadsheets": {
        "label": "תבניות ספרדשיט",
        "seeds": [
            "budget spreadsheet",
            "planner template",
            "tracker excel",
            "wedding spreadsheet",
            "small business template",
            "expense tracker",
            "habit tracker template",
            "meal planner spreadsheet",
            "budget template google sheets",
            "inventory spreadsheet",
            "wedding budget template",
            "adhd planner digital",
            "finance tracker spreadsheet",
            "content calendar template",
            "workout tracker spreadsheet",
        ],
        "relevance_terms": [
            "spreadsheet", "template", "excel", "sheet", "tracker",
            "planner", "budget", "calculator", "dashboard", "log",
        ],
        "audience": "US/global consumers and small businesses buying ready-made templates",
    },
    # Picks-and-shovels for prediction-market / retail traders (see docs/RESEARCH.md):
    # sell tools TO traders instead of trading — zero capital at risk.
    "trader_tools": {
        "label": "כלים לסוחרים",
        "seeds": [
            "trading journal spreadsheet",
            "bet tracker spreadsheet",
            "bankroll management spreadsheet",
            "sports betting tracker",
            "crypto portfolio spreadsheet",
            "options trading journal",
            "prediction market tracker",
            "stock portfolio template",
            "day trading log excel",
            "dividend tracker spreadsheet",
        ],
        "relevance_terms": [
            "tracker", "journal", "spreadsheet", "excel", "template",
            "log", "calculator", "portfolio", "dashboard", "sheet", "bankroll",
        ],
        "audience": "retail traders and bettors who track performance in spreadsheets",
    },
}


# Seasonal seed boosts, merged into a niche's seeds for the current and next
# month — catches demand at its rise instead of after it.
SEASONAL_SEEDS: dict[str, dict[int, list[str]]] = {
    "spreadsheets": {
        1: ["new year goals template", "annual budget spreadsheet"],
        2: ["tax deduction tracker", "tax prep checklist spreadsheet"],
        3: ["tax spreadsheet", "spring cleaning checklist template"],
        4: ["tax filing tracker", "garden planner spreadsheet"],
        5: ["wedding season budget", "graduation party planner"],
        6: ["summer camp planner", "vacation budget spreadsheet"],
        7: ["back to school budget", "teacher planner template"],
        8: ["back to school checklist", "college budget spreadsheet"],
        9: ["holiday savings tracker", "halloween party planner"],
        10: ["christmas budget spreadsheet", "black friday deal tracker"],
        11: ["christmas gift tracker", "holiday meal planner"],
        12: ["new year resolution tracker", "yearly review template"],
    },
    "trader_tools": {
        1: ["tax lot tracker", "trading goals template"],
        3: ["capital gains tax spreadsheet", "crypto tax tracker"],
        9: ["nfl betting tracker", "fantasy football spreadsheet"],
        10: ["nba betting tracker"],
        12: ["portfolio year review template"],
    },
}


def seasonal_seeds(niche_key: str, month: int) -> list[str]:
    table = SEASONAL_SEEDS.get(niche_key, {})
    next_month = month % 12 + 1
    return list(dict.fromkeys(table.get(month, []) + table.get(next_month, [])))


def _extra_niches() -> dict[str, dict]:
    """Niches added WITHOUT a code change: TRENDMILL_EXTRA_NICHES holds a JSON
    dict of niche definitions (the niche scout proposes ready-to-paste blocks).
    Malformed JSON fails loudly — a silent typo must not drop a product line."""
    raw = os.environ.get("TRENDMILL_EXTRA_NICHES", "").strip()
    if not raw:
        return {}
    import json

    extra = json.loads(raw)
    if not isinstance(extra, dict):
        raise RuntimeError("TRENDMILL_EXTRA_NICHES must be a JSON object")
    for key, cfg in extra.items():
        if not isinstance(cfg, dict) or not cfg.get("seeds") or not cfg.get("relevance_terms"):
            raise RuntimeError(f"Extra niche {key!r} needs 'seeds' and 'relevance_terms'")
        cfg.setdefault("label", key)
        cfg.setdefault("audience", "online buyers")
    return extra


def all_niches() -> dict[str, dict]:
    return {**NICHES, **_extra_niches()}


def active_niches() -> dict[str, dict]:
    catalog = all_niches()
    raw = os.environ.get("TRENDMILL_NICHES", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()] or list(catalog)
    unknown = [k for k in keys if k not in catalog]
    if unknown:
        raise RuntimeError(f"Unknown niches in TRENDMILL_NICHES: {unknown}")
    return {k: catalog[k] for k in keys}

# --- Scan tuning ---
MAX_COMPETITION_CHECKS = 25   # cap Etsy result-count scrapes per run (politeness)
SHORTLIST_SIZE = 15           # candidates sent to the LLM re-ranker
DIGEST_SIZE = 10              # opportunities inserted + sent to Telegram
SCRAPE_DELAY_RANGE = (2.0, 5.0)  # polite random delay between Etsy requests, seconds

# Growth-to-score mapping: growth ratio of 1.0 (flat interest) -> 50 points,
# 2.0 (doubled interest) -> 100 points, capped to [0, 100].
GROWTH_SCORE_FACTOR = 50.0

# --- Files ---
OUTPUT_DIR = os.environ.get("TRENDMILL_OUTPUT_DIR", "output")
