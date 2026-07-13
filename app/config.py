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

# --- Seed terms for the daily scan (Module 1, step 1) ---
SEED_TERMS = [
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
]

# A candidate keyword must contain at least one of these to be considered
# a digital-spreadsheet product opportunity.
RELEVANCE_TERMS = [
    "spreadsheet",
    "template",
    "excel",
    "sheet",
    "tracker",
    "planner",
    "budget",
    "calculator",
    "dashboard",
    "log",
]

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
