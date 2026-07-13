"""Etsy public signals: search-box autocomplete (real buyer queries) and the
"X results" competition count. Polite scraper: random 2-5s delays, realistic
User-Agent, and every failure degrades to an empty/None result — never raises.
"""

from __future__ import annotations

import logging
import random
import re
import time
from typing import Any

import httpx

from app.config import SCRAPE_DELAY_RANGE

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

# Etsy has changed its suggest endpoint over the years; try newest first.
SUGGEST_ENDPOINTS = [
    "https://www.etsy.com/api/v3/ajax/public/search/autosuggest",
    "https://www.etsy.com/suggestions_ajax.php",
]

TIMEOUT = 20.0

SUGGESTION_KEYS = {"query", "text", "suggestion", "value"}


def _polite_delay() -> None:
    time.sleep(random.uniform(*SCRAPE_DELAY_RANGE))


def _extract_suggestions(node: Any, found: list[str]) -> None:
    """Walk arbitrary JSON and collect plausible suggestion strings."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SUGGESTION_KEYS and isinstance(value, str):
                found.append(value)
            else:
                _extract_suggestions(value, found)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, str):
                found.append(item)
            else:
                _extract_suggestions(item, found)


def autocomplete(prefix: str, limit: int = 10) -> list[str]:
    """Buyer-query suggestions for a seed prefix. Empty list on any failure."""
    for endpoint in SUGGEST_ENDPOINTS:
        try:
            with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
                resp = client.get(endpoint, params={"search_query": prefix})
            if resp.status_code != 200:
                continue
            found: list[str] = []
            _extract_suggestions(resp.json(), found)
            seen: set[str] = set()
            unique: list[str] = []
            for s in found:
                s = s.strip().lower()
                if s and s != prefix and s not in seen:
                    seen.add(s)
                    unique.append(s)
            if unique:
                return unique[:limit]
        except Exception as exc:  # noqa: BLE001 — fail soft per endpoint
            log.debug("autosuggest endpoint %s failed for %r: %s", endpoint, prefix, exc)
    log.warning("Etsy autocomplete yielded nothing for %r", prefix)
    return []


_RESULTS_RE = re.compile(r"([\d,\.]+)\s*(?:results|items)", re.IGNORECASE)


def competition_count(keyword: str) -> int | None:
    """Number of Etsy listings for the keyword; None if scraping fails."""
    _polite_delay()
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
            resp = client.get("https://www.etsy.com/search", params={"q": keyword})
        if resp.status_code != 200:
            log.warning("Etsy search HTTP %s for %r", resp.status_code, keyword)
            return None
        match = _RESULTS_RE.search(resp.text)
        if not match:
            return None
        return int(match.group(1).replace(",", "").replace(".", ""))
    except Exception as exc:  # noqa: BLE001
        log.warning("Etsy competition check failed for %r: %s", keyword, exc)
        return None
