"""Module 5 entrypoint — weekly cron: `python learn.py` (Milestone 4)."""

from __future__ import annotations

import sys

from app import notify


if __name__ == "__main__":
    try:
        from app.learner import run

        run()
    except NotImplementedError:
        print("Performance loop not implemented yet (Milestone 4).")
    except Exception as exc:  # noqa: BLE001
        notify.report_error("learn", exc)
        sys.exit(1)
