"""Competitor snapshots: top Etsy listings for a keyword, taken at product
generation time. Parsed from the search page's schema.org JSON-LD (ItemList),
which is the most stable part of the page. Polite and fail-soft — a failed
snapshot returns None and the pipeline continues without competitor context.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.scanner.etsy import HEADERS, TIMEOUT, _polite_delay

log = logging.getLogger(__name__)

MAX_LISTINGS = 8
_LDJSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _listings_from_ldjson(html_text: str) -> list[dict[str, Any]]:
    listings: list[dict[str, Any]] = []
    for match in _LDJSON_RE.finditer(html_text):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict) or node.get("@type") != "ItemList":
                continue
            for element in node.get("itemListElement") or []:
                item = element.get("item", element) if isinstance(element, dict) else {}
                if not isinstance(item, dict):
                    continue
                title = item.get("name")
                offers = item.get("offers") or {}
                price = offers.get("price") or offers.get("lowPrice")
                rating = (item.get("aggregateRating") or {}).get("ratingValue")
                reviews = (item.get("aggregateRating") or {}).get("reviewCount")
                if title:
                    listings.append({
                        "title": str(title)[:160],
                        "price": price,
                        "rating": rating,
                        "reviews": reviews,
                    })
    return listings[:MAX_LISTINGS]


def snapshot(keyword: str) -> list[dict[str, Any]] | None:
    """Top competing listings for the keyword; None on any failure."""
    _polite_delay()
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
            resp = client.get("https://www.etsy.com/search", params={"q": keyword})
        if resp.status_code != 200:
            log.warning("competitor snapshot HTTP %s for %r", resp.status_code, keyword)
            return None
        listings = _listings_from_ldjson(resp.text)
        return listings or None
    except Exception as exc:  # noqa: BLE001
        log.warning("competitor snapshot failed for %r: %s", keyword, exc)
        return None
