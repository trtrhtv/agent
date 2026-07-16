"""Module 9 entrypoint — monthly cron: `python foresight.py`.

Mines 5 years of Google Trends history per active niche into seasonal profiles
and lead-lag links; the daily scanner consumes both automatically.
"""

from __future__ import annotations

import logging
import sys

from app import notify
from app.config import active_niches
from app.scanner import foresight

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("foresight-run")


def run() -> None:
    total_profiles = total_links = 0
    for niche_key, niche in active_niches().items():
        try:
            profiles, links = foresight.analyze_niche(niche_key, niche)
            total_profiles += profiles
            total_links += links
        except Exception as exc:  # noqa: BLE001 — one niche must not kill the rest
            log.exception("foresight failed for %s", niche_key)
            notify.report_error(f"foresight/{niche_key}", exc)

    notify.send_message(
        "🔮 <b>ניתוח ראיית הנולד הושלם</b>\n"
        f"📅 פרופילים עונתיים מזוהים: {total_profiles}\n"
        f"🔗 קשרי מוביל→עוקב מובהקים: {total_links}\n"
        "הסריקה היומית תשתמש בהם אוטומטית כדי להקדים ביקושים."
    )


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:  # noqa: BLE001
        notify.report_error("foresight", exc)
        sys.exit(1)
