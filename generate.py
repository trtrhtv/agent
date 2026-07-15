"""Worker entrypoint: process all jobs stuck in pending_generation.
Useful as a Railway cron safety net alongside the webhook's background task."""

from __future__ import annotations

import sys

from app import db, notify


def run() -> None:
    from app.generator import generate_product

    res = (
        db.client().table("product_jobs")
        .select("id, spec")
        .eq("status", "pending_generation")
        .execute()
    )
    for row in res.data or []:
        # Bundle jobs are built by app.bundles, not the product generator —
        # skip them here so the safety-net cron can't mangle one mid-build.
        if (row.get("spec") or {}).get("bundle_members") is not None:
            continue
        generate_product(row["id"])


if __name__ == "__main__":
    try:
        run()
    except NotImplementedError:
        print("Generator not implemented yet (Milestone 2).")
    except Exception as exc:  # noqa: BLE001
        notify.report_error("generate", exc)
        sys.exit(1)
