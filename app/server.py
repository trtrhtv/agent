"""Module 3 — FastAPI webhook server for Telegram button callbacks.

Run on Railway web service: uvicorn app.server:app --host 0.0.0.0 --port $PORT

Idempotency: every callback re-reads current status from Supabase and only
performs legal transitions; double-taps get a "already handled" toast and no
side effects. Every transition is logged to the `events` table.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from app import db, notify

log = logging.getLogger("server")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="TrendMill")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _check_secret(header_value: str | None) -> None:
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if expected and header_value != expected:
        raise HTTPException(status_code=403, detail="bad webhook secret")


# --- opportunity callbacks (daily digest buttons) ---

def _handle_generate(opportunity_id: str, callback_id: str, background: BackgroundTasks) -> None:
    opp = db.get_opportunity(opportunity_id)
    if opp is None:
        notify.answer_callback(callback_id, "לא נמצאה ההזדמנות הזו 🤔")
        return
    if opp["status"] not in ("new", "shortlisted"):
        notify.answer_callback(callback_id, f"כבר טופל (סטטוס: {opp['status']})")
        return

    db.set_opportunity_status(opportunity_id, "approved")
    db.log_event("opportunity", opportunity_id, "approved", opp["status"],
                 {"via": "telegram_callback"})

    # Idempotency: one job per opportunity unless the previous one failed.
    job = db.get_job_for_opportunity(opportunity_id)
    if job is None or job["status"] == "failed":
        job = db.create_job(opportunity_id)
        db.log_event("product_job", job["id"], "pending_generation",
                     meta={"opportunity_id": opportunity_id})
        background.add_task(_run_generation, job["id"])

    notify.answer_callback(callback_id, "✅ נכנס לתור הייצור")
    notify.send_message(
        f"🏗 מתחיל לייצר מוצר עבור: <b>{opp['keyword']}</b>\n"
        "אשלח את הקובץ לאישור כשיהיה מוכן."
    )


def _handle_skip(opportunity_id: str, callback_id: str) -> None:
    opp = db.get_opportunity(opportunity_id)
    if opp is None:
        notify.answer_callback(callback_id, "לא נמצאה ההזדמנות הזו 🤔")
        return
    if opp["status"] not in ("new", "shortlisted"):
        notify.answer_callback(callback_id, f"כבר טופל (סטטוס: {opp['status']})")
        return
    db.set_opportunity_status(opportunity_id, "rejected")
    db.log_event("opportunity", opportunity_id, "rejected", opp["status"],
                 {"via": "telegram_callback"})
    notify.answer_callback(callback_id, "❌ דילגתי")


def _run_generation(job_id: str) -> None:
    """Bridge to Module 2. Until the generator ships (Milestone 2), mark the
    intent and tell the owner — never fail silently."""
    try:
        from app.generator import generate_product

        generate_product(job_id)
    except NotImplementedError:
        notify.send_message(
            "ℹ️ מחולל המוצרים (מיילסטון 2) עדיין לא פרוס — "
            "המשימה נשמרה בסטטוס pending_generation ותרוץ ברגע שיעלה."
        )
    except Exception as exc:  # noqa: BLE001
        db.update_job(job_id, {"status": "failed", "error": str(exc)[:2000]})
        db.log_event("product_job", job_id, "failed", "pending_generation",
                     {"error": str(exc)[:500]})
        notify.report_error("generate", exc)


# --- product job callbacks (Milestone 2/3 wire-up; transitions are ready) ---

def _handle_job_action(action: str, job_id: str, callback_id: str,
                       background: BackgroundTasks) -> None:
    job = db.get_job(job_id)
    if job is None:
        notify.answer_callback(callback_id, "לא נמצאה המשימה הזו 🤔")
        return

    if action == "approve":
        if job["status"] != "pending_approval":
            notify.answer_callback(callback_id, f"כבר טופל (סטטוס: {job['status']})")
            return
        db.update_job(job_id, {"status": "approved"})
        db.log_event("product_job", job_id, "approved", "pending_approval")
        notify.answer_callback(callback_id, "✅ מאושר — מעלה ל-Gumroad")
        background.add_task(_run_upload, job_id)
    elif action == "regen":
        if job["status"] not in ("pending_approval", "failed"):
            notify.answer_callback(callback_id, f"אי אפשר לחולל מחדש (סטטוס: {job['status']})")
            return
        db.update_job(job_id, {"status": "pending_generation"})
        db.log_event("product_job", job_id, "pending_generation", job["status"],
                     {"regenerate": True})
        notify.answer_callback(callback_id, "✏️ מחולל מחדש")
        background.add_task(_run_generation, job_id)
    elif action == "reject":
        if job["status"] not in ("pending_approval", "failed"):
            notify.answer_callback(callback_id, f"כבר טופל (סטטוס: {job['status']})")
            return
        db.update_job(job_id, {"status": "rejected"})
        db.log_event("product_job", job_id, "rejected", job["status"])
        notify.answer_callback(callback_id, "❌ נדחה")


def _run_upload(job_id: str) -> None:
    try:
        from app.uploader import get_product_url, upload_product

        job = db.get_job(job_id)
        product_id = upload_product(job)
        db.update_job(job_id, {"status": "uploaded", "gumroad_product_id": product_id})
        db.log_event("product_job", job_id, "uploaded", "approved")
        url = get_product_url(product_id)
        notify.send_message(
            "🚀 <b>המוצר עלה ל-Gumroad!</b>\n"
            f"{job.get('title', '')}\n"
            + (f"🔗 {url}" if url else f"מזהה מוצר: {product_id}")
        )
    except Exception as exc:  # noqa: BLE001 — fail soft, report loud
        db.update_job(job_id, {"status": "failed", "error": str(exc)[:2000]})
        db.log_event("product_job", job_id, "failed", "approved",
                     {"error": str(exc)[:500]})
        notify.report_error("upload", exc)


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    background: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    _check_secret(x_telegram_bot_api_secret_token)
    update: dict[str, Any] = await request.json()

    callback = update.get("callback_query")
    if not callback:
        return {"ok": True}  # ignore plain messages for now

    callback_id = callback["id"]
    data = callback.get("data") or ""
    action, _, entity_id = data.partition(":")

    try:
        if action == "gen":
            _handle_generate(entity_id, callback_id, background)
        elif action == "skip":
            _handle_skip(entity_id, callback_id)
        elif action in ("approve", "regen", "reject"):
            _handle_job_action(action, entity_id, callback_id, background)
        else:
            notify.answer_callback(callback_id, "פעולה לא מוכרת")
    except Exception as exc:  # noqa: BLE001 — fail soft, report loud
        log.exception("callback handling failed")
        notify.answer_callback(callback_id, "⚠️ שגיאה — נשלח דיווח")
        notify.report_error("webhook", exc)

    return {"ok": True}
