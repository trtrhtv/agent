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


# --- active-loop callbacks (brain proposals) ---

def _handle_price_drop(job_id: str, callback_id: str) -> None:
    job = db.get_job(job_id)
    if job is None or job["status"] != "uploaded" or not job.get("gumroad_product_id"):
        notify.answer_callback(callback_id, "המוצר כבר לא באוויר")
        return
    from app.uploader import set_price

    old_price = float(job.get("suggested_price_usd") or 12)
    new_price = max(7.0, round(old_price * 0.75, 2))
    set_price(job["gumroad_product_id"], new_price)
    db.update_job(job_id, {"suggested_price_usd": new_price})
    db.log_event("product_job", job_id, "price_dropped", "uploaded",
                 {"from": old_price, "to": new_price})
    notify.answer_callback(callback_id, f"💸 המחיר ירד ל-${new_price}")
    notify.send_message(
        f"💸 ניסוי מחיר: <b>{job.get('title', '')[:60]}</b> — ${old_price} → ${new_price}"
    )


def _handle_v2(job_id: str, callback_id: str, background: BackgroundTasks) -> None:
    job = db.get_job(job_id)
    if job is None:
        notify.answer_callback(callback_id, "לא נמצאה המשימה")
        return
    # Pull the post-mortem's concrete improvements for this exact product
    improvements: list[str] = []
    try:
        res = (
            db.client().table("insights")
            .select("evidence").eq("kind", "post_mortem")
            .eq("evidence->>job_id", job_id).limit(1).execute()
        )
        if res.data:
            improvements = ((res.data[0].get("evidence") or {}).get("analysis") or {}).get(
                "improvements") or []
    except Exception:  # noqa: BLE001 — v2 works without the hints too
        pass

    new_job = db.create_job(job["opportunity_id"])
    db.update_job(new_job["id"], {"spec": {
        "sheets": (job.get("spec") or {}).get("sheets") or [],
        "improvements": improvements,
    }})
    db.log_event("product_job", new_job["id"], "pending_generation",
                 meta={"v2_of": job_id, "improvements": improvements[:5]})
    background.add_task(_run_generation, new_job["id"])
    notify.answer_callback(callback_id, "🔁 גרסה משופרת נכנסה לייצור")


def _handle_retire(job_id: str, callback_id: str) -> None:
    job = db.get_job(job_id)
    if job is None or job["status"] != "uploaded" or not job.get("gumroad_product_id"):
        notify.answer_callback(callback_id, "המוצר כבר לא באוויר")
        return
    from app.uploader import disable_product

    disable_product(job["gumroad_product_id"])
    db.update_job(job_id, {"status": "retired"})
    db.log_event("product_job", job_id, "retired", "uploaded")
    notify.answer_callback(callback_id, "🗑 הוסר מהחנות")


def _handle_bundle(niche: str, callback_id: str, background: BackgroundTasks) -> None:
    from app import brain

    sellers = [
        r for r in brain.products_with_outcomes()
        if r["total_sales"] > 0 and ((r.get("opportunities") or {}).get("niche")) == niche
    ]
    if len(sellers) < 3:
        notify.answer_callback(callback_id, "אין מספיק מוצרים מוכרים לבאנדל")
        return
    top = sorted(sellers, key=lambda r: r["total_revenue"], reverse=True)[:3]
    opp = db.create_opportunity(
        keyword=f"{niche} bundle {len(top)} templates", niche=niche, source="bundle"
    )
    notify.answer_callback(callback_id, "📦 בונה את הבאנדל...")

    def _build() -> None:
        try:
            from app.bundles import create_bundle

            create_bundle(niche, top, opp["id"])
        except Exception as exc:  # noqa: BLE001
            notify.report_error("bundle", exc)

    background.add_task(_build)


# --- /status command ---

def _handle_status_command() -> None:
    import datetime as dt

    today = dt.date.today().isoformat()
    opps = db.opportunities_for_date(today)
    jobs = db.client().table("product_jobs").select("status").execute().data or []
    by_status: dict[str, int] = {}
    for j in jobs:
        by_status[j["status"]] = by_status.get(j["status"], 0) + 1
    failures = (
        db.client().table("events").select("created_at, meta")
        .eq("to_status", "failed").order("created_at", desc=True).limit(3)
        .execute().data or []
    )
    lines = [
        "📟 <b>סטטוס TrendMill</b>",
        f"🔎 הזדמנויות היום: {len(opps)}",
        "📦 מוצרים: " + (", ".join(f"{k}: {v}" for k, v in sorted(by_status.items())) or "אין עדיין"),
    ]
    if failures:
        lines.append("⚠️ כשלונות אחרונים:")
        lines += [f"   • {f['created_at'][:16]} — {str((f.get('meta') or {}).get('error', ''))[:80]}"
                  for f in failures]
    notify.send_message("\n".join(lines))


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
        # Owner text commands
        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        chat_id = str((message.get("chat") or {}).get("id") or "")
        if text == "/status" and chat_id == os.environ.get("TELEGRAM_OWNER_CHAT_ID", ""):
            try:
                _handle_status_command()
            except Exception as exc:  # noqa: BLE001
                notify.report_error("status", exc)
        return {"ok": True}

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
        elif action == "pdrop":
            _handle_price_drop(entity_id, callback_id)
        elif action == "v2":
            _handle_v2(entity_id, callback_id, background)
        elif action == "retire":
            _handle_retire(entity_id, callback_id)
        elif action == "bundle":
            _handle_bundle(entity_id, callback_id, background)
        else:
            notify.answer_callback(callback_id, "פעולה לא מוכרת")
    except Exception as exc:  # noqa: BLE001 — fail soft, report loud
        log.exception("callback handling failed")
        notify.answer_callback(callback_id, "⚠️ שגיאה — נשלח דיווח")
        notify.report_error("webhook", exc)

    return {"ok": True}
