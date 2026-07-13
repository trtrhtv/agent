"""Module 4 — Gumroad uploader (Milestone 3).

Strategy decision comes from the Milestone 0 spike (spike/gumroad_create_spike.py):
  STRATEGY_A — official API: POST /v2/products works with the token's scopes.
  STRATEGY_B — Playwright UI automation with stored credentials.

Both strategies live behind this single interface so the choice is swappable:
    upload_product(job: dict) -> gumroad_product_id: str
"""

from __future__ import annotations

from typing import Any


def upload_product(job: dict[str, Any]) -> str:
    raise NotImplementedError(
        "Milestone 3: run spike/gumroad_create_spike.py first, then implement "
        "Strategy A (API) or Strategy B (Playwright) behind this interface"
    )
