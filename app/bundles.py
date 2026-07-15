"""Bundles: package a niche's proven sellers into one higher-priced product.
Enters the normal approval flow (pending_approval -> Telegram buttons ->
upload), so no special casing downstream — the "file" is a zip.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import logging
import os
import zipfile

from app import db, notify
from app.config import OUTPUT_DIR
from app.llm import chat_json

log = logging.getLogger("bundles")

BUNDLE_PRICE_MIN, BUNDLE_PRICE_MAX = 24.0, 39.0
BUNDLE_SHARE_OF_SUM = 0.6  # bundle price ≈ 60% of buying items separately

COPY_PROMPT = """Write the sales listing for a BUNDLE of digital spreadsheet templates.

Niche: {niche}
Included products (each is a complete multi-sheet Excel/Google Sheets template):
{members}

Reply with ONLY valid JSON:
{{
  "title": "bundle listing title, max 140 chars, emphasizes the savings and completeness",
  "description_md": "markdown: hook, what's included (one bullet per template with its benefit), savings math, instant-download note",
  "tags": ["exactly 13 short buyer-search tags"]
}}
All content in English."""


def create_bundle(niche: str, member_jobs: list[dict], opportunity_id: str) -> str:
    """Build the zip + listing and push a job into the approval flow. Returns job id."""
    job = db.create_job(opportunity_id)
    job_id = job["id"]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    zip_path = os.path.join(OUTPUT_DIR, f"bundle-{niche}-{dt.date.today().isoformat()}-{job_id[:8]}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for member in member_jobs:
            path = member.get("file_path")
            if path and os.path.exists(path):
                zf.write(path, arcname=os.path.basename(path))

    members_ctx = [
        {"title": m["title"], "price_usd": m["suggested_price_usd"]}
        for m in member_jobs
    ]
    copy = chat_json([{"role": "user", "content": COPY_PROMPT.format(
        niche=niche, members=json.dumps(members_ctx))}], max_tokens=1500)

    total = sum(float(m.get("suggested_price_usd") or 12) for m in member_jobs)
    price = round(min(BUNDLE_PRICE_MAX, max(BUNDLE_PRICE_MIN, total * BUNDLE_SHARE_OF_SUM)), 2)

    title = str(copy.get("title") or f"{niche.title()} Mega Bundle — {len(member_jobs)} Templates")[:140]
    tags = [str(t).lower()[:20] for t in (copy.get("tags") or [])][:13]
    db.update_job(job_id, {
        "title": title,
        "description": str(copy.get("description_md") or ""),
        "tags": tags,
        "suggested_price_usd": price,
        "spec": {"bundle_members": [m["id"] for m in member_jobs]},
        "file_path": zip_path,
        "status": "pending_approval",
    })
    db.log_event("product_job", job_id, "pending_approval", "pending_generation",
                 {"bundle": True, "members": len(member_jobs)})

    members_lines = "\n".join(f"   • {html.escape(str(m['title'])[:60])}" for m in member_jobs)
    notify.send_document(
        zip_path,
        caption=(
            f"📦 <b>באנדל מוכן לאישור</b>\n\n<b>{html.escape(title)}</b>\n"
            f"💵 מחיר מוצע: ${price} (במקום ${total:.0f} בנפרד)\n\n"
            f"כולל:\n{members_lines}"
        ),
        reply_markup={"inline_keyboard": [
            [{"text": "✅ אשר והעלה", "callback_data": f"approve:{job_id}"}],
            [{"text": "❌ דחה", "callback_data": f"reject:{job_id}"}],
        ]},
    )
    return job_id
