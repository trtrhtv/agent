"""Module 5 — weekly performance loop (Milestone 4).

Contract: run() pulls the past week's sales via the Gumroad API, writes rows
into `performance` (idempotent on week_start+product_job_id), and sends the
weekly Hebrew report to Telegram. The data automatically feeds the scanner's
LLM re-rank via db.performance_context().
"""

from __future__ import annotations


def run() -> None:
    raise NotImplementedError("Milestone 4: performance loop not implemented yet")
