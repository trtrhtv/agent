"""Telegram notifications. All user-facing text is Hebrew (owner-facing bot);
code and product content stay English per project rules."""

from __future__ import annotations

import html
import traceback
from typing import Any

import httpx

from app.config import env

TIMEOUT = 60.0


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/{method}"


def send_message(
    text: str,
    reply_markup: dict[str, Any] | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id or env("TELEGRAM_OWNER_CHAT_ID"),
        "text": text[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.post(_api("sendMessage"), json=payload)
        resp.raise_for_status()
        return resp.json()


def send_document(
    file_path: str,
    caption: str,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "chat_id": env("TELEGRAM_OWNER_CHAT_ID"),
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    if reply_markup:
        import json as _json

        data["reply_markup"] = _json.dumps(reply_markup)
    with open(file_path, "rb") as fh:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(_api("sendDocument"), data=data, files={"document": fh})
            resp.raise_for_status()
            return resp.json()


def send_photo(file_path: str, caption: str = "") -> dict[str, Any]:
    data: dict[str, Any] = {
        "chat_id": env("TELEGRAM_OWNER_CHAT_ID"),
        "caption": caption[:1024],
        "parse_mode": "HTML",
    }
    with open(file_path, "rb") as fh:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(_api("sendPhoto"), data=data, files={"photo": fh})
            resp.raise_for_status()
            return resp.json()


def answer_callback(callback_query_id: str, text: str) -> None:
    with httpx.Client(timeout=TIMEOUT) as client:
        client.post(
            _api("answerCallbackQuery"),
            json={"callback_query_id": callback_query_id, "text": text[:200]},
        )


def report_error(module: str, exc: BaseException) -> None:
    """Fail soft, report loud: send a Hebrew error alert with a traceback tail."""
    tb = "".join(traceback.format_exception(exc))[-1500:]
    text = (
        f"⚠️ <b>שגיאה במודול {html.escape(module)}</b>\n"
        f"<code>{html.escape(tb)}</code>"
    )
    try:
        send_message(text)
    except Exception:
        # Never let error reporting crash the caller.
        pass


# --- Daily digest (Module 1, step 5) ---

def _fmt_competition(count: int | None) -> str:
    return "לא ידוע" if count is None else f"{count:,}"


def send_daily_digest(opportunities: list[dict[str, Any]], label: str | None = None) -> None:
    """One message per niche: ranked list + one button row (✅/❌) per opportunity."""
    header = f"📊 <b>סריקת טרנדים יומית</b> — {opportunities[0]['scan_date']}"
    if label:
        header += f"\n🗂 נישה: <b>{html.escape(label)}</b>"
    lines = [header + "\n"]
    keyboard: list[list[dict[str, str]]] = []

    for i, opp in enumerate(opportunities, start=1):
        keyword = html.escape(opp["keyword"])
        # Keep the whole 10-item digest safely under Telegram's 4096-char cap.
        rationale = html.escape((opp.get("rationale") or "")[:160])
        trend = round(float(opp.get("trend_score") or 0))
        score = round(float(opp.get("final_score") or 0), 1)
        comp = _fmt_competition(opp.get("competition_count"))
        lines.append(
            f"<b>{i}. {keyword}</b>\n"
            f"   ציון סופי: {score} | טרנד: {trend} | תחרות: {comp}\n"
            f"   💡 {rationale}\n"
        )
        keyboard.append(
            [
                {"text": f"✅ צור מוצר {i}", "callback_data": f"gen:{opp['id']}"},
                {"text": f"❌ דלג {i}", "callback_data": f"skip:{opp['id']}"},
            ]
        )

    lines.append("בחר אילו מוצרים לייצר 👇")
    send_message("\n".join(lines), reply_markup={"inline_keyboard": keyboard})
