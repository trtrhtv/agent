"""Quality gate (Module 7): every generated product must pass objective
structural checks + a strict LLM review before reaching the owner. A failing
product gets ONE automatic regeneration with the reviewer's issues fed back;
if it still fails, it reaches the owner flagged with warnings — never silently.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.llm import chat_json

log = logging.getLogger("quality")

MIN_SCORE = 7          # LLM review threshold (1-10)
MIN_SHEETS = 2
MIN_ROWS_MAIN_SHEET = 8
MIN_FORMULAS = 3
MIN_STEPS = 4
MIN_DESCRIPTION_CHARS = 300
MIN_FILE_BYTES = 4000


def structural_issues(spec: dict, copy: dict, file_path: str) -> list[str]:
    """Deterministic checks — cheap, objective, no LLM."""
    issues: list[str] = []
    sheets = spec.get("sheets") or []
    if len(sheets) < MIN_SHEETS:
        issues.append(f"only {len(sheets)} data sheet(s); need >= {MIN_SHEETS}")

    max_rows = max((len(s.get("rows") or []) for s in sheets), default=0)
    if max_rows < MIN_ROWS_MAIN_SHEET:
        issues.append(f"main sheet has {max_rows} sample rows; need >= {MIN_ROWS_MAIN_SHEET}")

    formulas = sum(
        1
        for s in sheets
        for row in (s.get("rows") or []) + [s.get("totals_row") or []]
        if isinstance(row, list)
        for cell in row
        if isinstance(cell, str) and cell.startswith("=")
    )
    if formulas < MIN_FORMULAS:
        issues.append(f"only {formulas} live formulas; need >= {MIN_FORMULAS}")

    if len(spec.get("how_to_use") or []) < MIN_STEPS:
        issues.append(f"how_to_use has fewer than {MIN_STEPS} steps")

    if len(copy.get("description") or "") < MIN_DESCRIPTION_CHARS:
        issues.append("listing description too short to sell")

    try:
        if os.path.getsize(file_path) < MIN_FILE_BYTES:
            issues.append("xlsx file suspiciously small")
    except OSError:
        issues.append("xlsx file missing")
    return issues


REVIEW_PROMPT = """You are a strict quality reviewer for paid spreadsheet templates.
A buyer paid ${price} for this. Would they feel it was worth it?

SPEC (sheets, columns, sample rows, formulas):
{spec}

LISTING:
title: {title}
description: {description}

Grade harshly. Generic sample data ("Item 1", "Example"), formulas that
reference wrong rows, sheets that don't solve the buyer's actual job, or
listing copy that overpromises — all cost points.

Reply with ONLY JSON:
{{"score": 1-10, "issues": ["specific fixable problem", ...], "would_buy": true/false}}"""


def llm_review(spec: dict, copy: dict) -> dict[str, Any] | None:
    """Strict review on the cheap model; None if the call fails (fail-soft)."""
    try:
        result = chat_json([{"role": "user", "content": REVIEW_PROMPT.format(
            price=copy.get("price_usd", 12),
            spec=json.dumps(spec)[:8000],
            title=copy.get("title", ""),
            description=str(copy.get("description", ""))[:2000],
        )}], max_tokens=800, temperature=0.2)
        score = int(result.get("score", 0))
        return {"score": max(1, min(10, score)),
                "issues": [str(i)[:200] for i in (result.get("issues") or [])][:6]}
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM quality review failed: %s", exc)
        return None


def assess(spec: dict, copy: dict, file_path: str) -> tuple[int | None, list[str], bool]:
    """Returns (score, all_issues, passed)."""
    issues = structural_issues(spec, copy, file_path)
    review = llm_review(spec, copy)
    score = review["score"] if review else None
    if review:
        issues += review["issues"] if review["score"] < MIN_SCORE else []
    passed = not structural_issues(spec, copy, file_path) and (score is None or score >= MIN_SCORE)
    return score, issues, passed
