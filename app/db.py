"""Supabase persistence layer. All DB access goes through this module."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from app.config import env


@lru_cache(maxsize=1)
def client() -> Client:
    return create_client(env("SUPABASE_URL"), env("SUPABASE_SERVICE_KEY"))


# --- opportunities ---

def opportunities_for_date(scan_date: str) -> list[dict[str, Any]]:
    res = (
        client().table("opportunities")
        .select("*")
        .eq("scan_date", scan_date)
        .execute()
    )
    return res.data or []


def insert_opportunities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upsert on (keyword, scan_date) so cron reruns never duplicate rows."""
    res = (
        client().table("opportunities")
        .upsert(rows, on_conflict="keyword,scan_date", ignore_duplicates=True)
        .execute()
    )
    return res.data or []


def get_opportunity(opportunity_id: str) -> dict[str, Any] | None:
    res = (
        client().table("opportunities")
        .select("*")
        .eq("id", opportunity_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def set_opportunity_status(opportunity_id: str, status: str) -> None:
    client().table("opportunities").update({"status": status}).eq(
        "id", opportunity_id
    ).execute()


# --- product_jobs ---

def get_job_for_opportunity(opportunity_id: str) -> dict[str, Any] | None:
    res = (
        client().table("product_jobs")
        .select("*")
        .eq("opportunity_id", opportunity_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def create_job(opportunity_id: str) -> dict[str, Any]:
    res = (
        client().table("product_jobs")
        .insert({"opportunity_id": opportunity_id, "status": "pending_generation"})
        .execute()
    )
    return res.data[0]


def get_job(job_id: str) -> dict[str, Any] | None:
    res = (
        client().table("product_jobs")
        .select("*")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def update_job(job_id: str, fields: dict[str, Any]) -> None:
    client().table("product_jobs").update(fields).eq("id", job_id).execute()


# --- performance (learning context for Module 1, step 4) ---

def performance_context(limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Top and bottom performers with product titles, for the re-rank prompt."""
    base = client().table("performance").select(
        "revenue_usd, sales_count, views, week_start, product_jobs(title)"
    )
    try:
        top = base.order("revenue_usd", desc=True).limit(limit).execute().data or []
        bottom = base.order("revenue_usd", desc=False).limit(limit).execute().data or []
    except Exception:
        # Table empty or query failed — learning context is optional.
        return {"top": [], "bottom": []}
    return {"top": top, "bottom": bottom}


# --- events (audit log of state transitions) ---

def log_event(
    entity: str,
    entity_id: str,
    to_status: str,
    from_status: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    try:
        client().table("events").insert(
            {
                "entity": entity,
                "entity_id": entity_id,
                "from_status": from_status,
                "to_status": to_status,
                "meta": meta or {},
            }
        ).execute()
    except Exception:
        # The audit log must never take down the main flow.
        pass
