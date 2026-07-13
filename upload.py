"""Worker entrypoint: upload all approved jobs to Gumroad (Milestone 3)."""

from __future__ import annotations

import sys

from app import db, notify


def run() -> None:
    from app.uploader import upload_product

    res = (
        db.client().table("product_jobs")
        .select("*")
        .eq("status", "approved")
        .execute()
    )
    for job in res.data or []:
        product_id = upload_product(job)
        db.update_job(job["id"], {"status": "uploaded", "gumroad_product_id": product_id})
        db.log_event("product_job", job["id"], "uploaded", "approved")


if __name__ == "__main__":
    try:
        run()
    except NotImplementedError:
        print("Uploader not implemented yet (Milestone 3 — run the spike first).")
    except Exception as exc:  # noqa: BLE001
        notify.report_error("upload", exc)
        sys.exit(1)
