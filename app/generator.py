"""Module 2 — product generator.

generate_product(job_id):
  1. GENERATION_MODEL -> strict JSON spreadsheet spec (validated; chat_json retries once)
  2. openpyxl build via app.xlsx_builder
  3. ROUTINE_MODEL -> listing copy (title <=140, markdown description, exactly 13 tags,
     price $9-19, hard floor $7)
  4. job -> pending_approval + Telegram message with the .xlsx attached and
     Approve / Regenerate / Reject buttons.

Regeneration: if the job already has a spec, the prompt instructs the model to
vary structure and angle relative to the previous sheets.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from typing import Any

from app import brain, db, notify
from app.config import GENERATION_MODEL, OUTPUT_DIR
from app.llm import chat_json
from app.scanner import competitors
from app.xlsx_builder import build_xlsx

log = logging.getLogger("generator")

PRICE_MIN, PRICE_MAX, PRICE_FLOOR = 9.0, 19.0, 7.0
TAG_COUNT = 13


SPEC_PROMPT = """You design premium, ready-to-sell Excel/Google Sheets templates.

Design a multi-sheet spreadsheet template for the product keyword: "{keyword}"
Buyer rationale: {rationale}
{vary_clause}{lessons_clause}{competitors_clause}
Reply with ONLY valid JSON matching exactly this schema:
{{
  "product_name": "short product name",
  "tagline": "one-line value proposition",
  "theme": {{"primary": "RRGGBB hex", "secondary": "light RRGGBB hex", "accent": "RRGGBB hex"}},
  "sheets": [
    {{
      "name": "sheet name (<=25 chars)",
      "description": "one line on what this sheet does",
      "columns": [{{"header": "Column name", "width": 18, "format": "currency|percent|date|number|null"}}],
      "rows": [["realistic sample value", 123.0, "=B4*C4"]],
      "totals_row": ["Total", "=SUM(B4:B18)"] or null
    }}
  ],
  "how_to_use": ["step 1 ...", "step 2 ..."]
}}

Requirements:
- 2 to 4 data sheets that together fully solve the buyer's job-to-be-done.
- 8-15 realistic, helpful sample rows per sheet (real-looking data, not "Item 1").
- Real working Excel formulas as strings starting with "=". Data starts at row 4
  (rows 1-3 are title/tagline/header), so a 10-row sheet spans rows 4-13 —
  reference those rows in formulas (e.g. "=SUM(B4:B13)").
- Cohesive professional color theme appropriate to the niche.
- 5-8 concise how_to_use steps; one step MUST explain importing into Google
  Sheets (File > Import > Upload) so the product serves both Excel and Sheets buyers.
- All content in English (US/global buyers)."""


COPY_PROMPT = """Write the sales listing for a digital spreadsheet template.

Keyword: "{keyword}"
Product name: {product_name}
Sheets included: {sheet_names}
{competitors_clause}
Reply with ONLY valid JSON:
{{
  "title": "listing title, max 140 chars, benefit-led, includes the keyword naturally and mentions it works in both Excel and Google Sheets",
  "description_md": "markdown: opening hook, benefits, a 'What's inside' bullet list (one bullet per sheet), instant-download note",
  "tags": ["exactly 13 short buyer-search tags"],
  "price_usd": 14.0
}}

Pricing: choose within $9-$19 based on perceived value (fixed marketplace fees
make cheap products unprofitable). All content in English."""


def _validate_spec(spec: Any) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("spec is not an object")
    sheets = spec.get("sheets")
    if not isinstance(sheets, list) or not sheets:
        raise ValueError("spec.sheets missing or empty")
    for sheet in sheets:
        if not isinstance(sheet, dict) or not sheet.get("columns"):
            raise ValueError("spec sheet missing columns")
    return spec


def _finalize_copy(copy: Any, keyword: str) -> dict:
    """Enforce the hard listing constraints regardless of what the LLM returned."""
    if not isinstance(copy, dict):
        copy = {}
    title = str(copy.get("title") or f"{keyword.title()} — Excel & Google Sheets Template")[:140]
    description = str(copy.get("description_md") or f"Instant-download {keyword} template.")

    tags = [re.sub(r"\s+", " ", str(t)).strip().lower()[:20] for t in (copy.get("tags") or [])]
    tags = [t for t in dict.fromkeys(tags) if t]
    filler = [w for w in re.split(r"\s+", keyword.lower()) if w] + [
        "spreadsheet", "excel template", "google sheets", "digital download",
        "planner", "tracker", "editable", "instant download", "budget", "template",
        "organizer", "printable", "editable template",
    ]
    for f in filler:
        if len(tags) >= TAG_COUNT:
            break
        if f not in tags:
            tags.append(f[:20])
    tags = tags[:TAG_COUNT]

    try:
        price = float(copy.get("price_usd", 0))
    except (TypeError, ValueError):
        price = 0.0
    price = min(PRICE_MAX, max(PRICE_MIN, price)) if price else 14.0
    price = max(PRICE_FLOOR, price)

    return {"title": title, "description": description, "tags": tags, "price_usd": round(price, 2)}


def _safe_filename(keyword: str, job_id: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")[:50] or "template"
    return f"{stem}-{job_id[:8]}.xlsx"


def _send_approval_message(job_id: str, keyword: str, copy: dict, spec: dict, file_path: str) -> None:
    sheet_lines = "\n".join(
        f"   • {html.escape(str(s.get('name', '?')))} — {html.escape(str(s.get('description', ''))[:80])}"
        for s in spec.get("sheets", [])
    )
    caption = (
        f"🆕 <b>מוצר מוכן לאישור</b>\n\n"
        f"<b>{html.escape(copy['title'])}</b>\n"
        f"💵 מחיר מוצע: ${copy['price_usd']}\n"
        f"🔎 מילת מפתח: {html.escape(keyword)}\n\n"
        f"📑 גיליונות:\n{sheet_lines}\n\n"
        f"🏷 תגיות: {html.escape(', '.join(copy['tags']))}"
    )
    keyboard = {
        "inline_keyboard": [
            [{"text": "✅ אשר והעלה", "callback_data": f"approve:{job_id}"}],
            [
                {"text": "✏️ צור מחדש", "callback_data": f"regen:{job_id}"},
                {"text": "❌ דחה", "callback_data": f"reject:{job_id}"},
            ],
        ]
    }
    notify.send_document(file_path, caption, reply_markup=keyboard)


def generate_product(job_id: str) -> None:
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    opp = db.get_opportunity(job["opportunity_id"])
    if opp is None:
        raise ValueError(f"opportunity for job {job_id} not found")

    keyword = opp["keyword"]
    rationale = opp.get("rationale") or "high buyer intent"

    previous_spec = job.get("spec")
    vary_clause = ""
    if previous_spec:
        prev_sheets = [s.get("name") for s in (previous_spec.get("sheets") or [])]
        vary_clause = (
            "This is a REGENERATION: the previous version of this product "
            f"(sheets: {prev_sheets}) did not perform. Take a noticeably different "
            "structure and angle.\n"
        )
        improvements = previous_spec.get("improvements")
        if improvements:
            vary_clause += (
                "A causal post-mortem identified these specific improvements — "
                f"apply them: {json.dumps(improvements)}\n"
            )

    # Brain context: accumulated lessons + a fresh competitor snapshot, so the
    # product is designed to beat what already ranks for this keyword.
    lessons_clause = brain.lessons_block(opp.get("niche"))
    listings = competitors.snapshot(keyword)
    competitors_clause = ""
    if listings:
        db.save_competitor_snapshot(keyword, listings)
        competitors_clause = (
            "\nTop competing listings for this keyword right now:\n"
            f"{json.dumps(listings)}\n"
            "Design to beat them: cover the gaps their titles suggest they miss, "
            "and justify a price near the top of the allowed range only if the "
            "product is clearly more complete.\n"
        )

    # LLM call #1 — spreadsheet spec (the only place the strong model is used)
    spec = _validate_spec(
        chat_json(
            [{"role": "user", "content": SPEC_PROMPT.format(
                keyword=keyword, rationale=rationale, vary_clause=vary_clause,
                lessons_clause=lessons_clause, competitors_clause=competitors_clause)}],
            model=GENERATION_MODEL,
            max_tokens=8000,
        )
    )

    # Build the workbook + a themed cover image (conversion asset)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_path = os.path.join(OUTPUT_DIR, _safe_filename(keyword, job_id))
    build_xlsx(spec, file_path)
    cover_path: str | None = None
    try:
        from app.cover import render_cover

        cover_path = render_cover(spec, file_path.replace(".xlsx", ".png"))
    except Exception as exc:  # noqa: BLE001 — a cover is never load-bearing
        log.warning("cover render failed: %s", exc)

    # LLM call #2 — listing copy on the cheap model
    raw_copy = chat_json(
        [{"role": "user", "content": COPY_PROMPT.format(
            keyword=keyword,
            product_name=spec.get("product_name", keyword),
            sheet_names=json.dumps([s.get("name") for s in spec["sheets"]]),
            competitors_clause=competitors_clause,
        )}],
        max_tokens=2000,
    )
    copy = _finalize_copy(raw_copy, keyword)

    db.update_job(job_id, {
        "title": copy["title"],
        "description": copy["description"],
        "tags": copy["tags"],
        "suggested_price_usd": copy["price_usd"],
        "spec": spec,
        "file_path": file_path,
        "status": "pending_approval",
    })
    db.log_event("product_job", job_id, "pending_approval", job["status"])

    if cover_path:
        try:
            notify.send_photo(cover_path, caption=f"🖼 קאבר: {html.escape(copy['title'][:80])}")
        except Exception as exc:  # noqa: BLE001
            log.warning("cover send failed: %s", exc)
    _send_approval_message(job_id, keyword, copy, spec, file_path)
    log.info("job %s -> pending_approval (%s)", job_id, file_path)
