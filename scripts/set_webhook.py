"""One-time setup: point the Telegram bot's webhook at the Railway web service.

Usage:
    python scripts/set_webhook.py https://your-service.up.railway.app
"""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    base_url = sys.argv[1].rstrip("/")
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

    payload = {
        "url": f"{base_url}/telegram/webhook",
        "allowed_updates": ["callback_query", "message"],
    }
    if secret:
        payload["secret_token"] = secret

    resp = httpx.post(
        f"https://api.telegram.org/bot{token}/setWebhook", json=payload, timeout=30
    )
    print(resp.json())
    return 0 if resp.json().get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
