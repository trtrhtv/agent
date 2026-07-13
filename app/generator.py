"""Module 2 — product generator (Milestone 2).

Contract (already wired from app.server):
    generate_product(job_id) ->
        builds the .xlsx from an LLM spec, writes listing copy, sets the job
        to pending_approval and sends the file to Telegram with
        Approve/Regenerate/Reject buttons.
"""

from __future__ import annotations


def generate_product(job_id: str) -> None:
    raise NotImplementedError("Milestone 2: product generator not implemented yet")
