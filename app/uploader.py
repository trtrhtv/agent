"""Module 4 — Gumroad uploader (Milestone 3).

Single interface, swappable strategy (spec requirement):
    upload_product(job: dict) -> gumroad_product_id: str

Strategy selection via UPLOAD_STRATEGY env:
  "api"        — Strategy A: official v2 API (POST /v2/products). The spike
                 (spike/gumroad_create_spike.py) determines whether this is
                 supported for your account; if the endpoint is missing the
                 upload raises UploadUnsupportedError with clear guidance.
  "playwright" — Strategy B: UI automation with stored credentials
                 (GUMROAD_EMAIL / GUMROAD_PASSWORD). Requires
                 `pip install playwright && playwright install chromium`.
                 NOTE: selectors were written against the 2026 Gumroad UI and
                 must be verified once on a real account before trusting.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.config import env

log = logging.getLogger("uploader")

API_BASE = "https://api.gumroad.com/v2"
TIMEOUT = 120.0


class UploadUnsupportedError(RuntimeError):
    """The chosen strategy cannot work in this account/environment."""


def upload_product(job: dict[str, Any]) -> str:
    strategy = os.environ.get("UPLOAD_STRATEGY", "api").strip().lower()
    if strategy == "api":
        return _upload_via_api(job)
    if strategy == "playwright":
        return _upload_via_playwright(job)
    raise ValueError(f"Unknown UPLOAD_STRATEGY: {strategy!r} (use 'api' or 'playwright')")


# --- Strategy A: official API -------------------------------------------------

def _upload_via_api(job: dict[str, Any]) -> str:
    token = env("GUMROAD_ACCESS_TOKEN")
    client = httpx.Client(timeout=TIMEOUT, params={"access_token": token})

    price_cents = int(round(float(job["suggested_price_usd"]) * 100))
    create = client.post(
        f"{API_BASE}/products",
        data={
            "name": job["title"][:255],
            "price": price_cents,
            "description": job["description"],
        },
    )
    if create.status_code == 404:
        raise UploadUnsupportedError(
            "Gumroad API returned 404 for POST /v2/products — product creation "
            "is not supported for this account/API version. Run "
            "spike/gumroad_create_spike.py to confirm, then set "
            "UPLOAD_STRATEGY=playwright (Strategy B)."
        )
    create.raise_for_status()
    body = create.json()
    product = body.get("product") or {}
    product_id = product.get("id")
    if not product_id:
        raise UploadUnsupportedError(f"Create returned no product id: {str(body)[:300]}")
    log.info("created Gumroad product %s", product_id)

    # Attach the .xlsx. The v2 docs don't document a file endpoint; try the
    # shapes the spike probes. Failure here leaves a draft product — we delete
    # it to stay idempotent, then surface a clear error.
    attached = False
    file_path = job["file_path"]
    for path in (f"/products/{product_id}/files", f"/products/{product_id}"):
        try:
            with open(file_path, "rb") as fh:
                method = client.post if path.endswith("/files") else client.put
                resp = method(f"{API_BASE}{path}", files={"file": (os.path.basename(file_path), fh)})
            if resp.status_code in (200, 201) and resp.json().get("success", True):
                attached = True
                break
        except Exception as exc:  # noqa: BLE001 — try the next shape
            log.debug("file attach via %s failed: %s", path, exc)
    if not attached:
        client.delete(f"{API_BASE}/products/{product_id}")
        raise UploadUnsupportedError(
            f"Product {product_id} was created but the file could not be attached "
            "via the API (draft deleted). Use UPLOAD_STRATEGY=playwright."
        )

    publish = client.put(f"{API_BASE}/products/{product_id}", data={"published": "true"})
    if publish.status_code not in (200, 201):
        log.warning("publish returned HTTP %s — product may remain a draft", publish.status_code)

    return str(product_id)


def get_product_url(product_id: str) -> str | None:
    """Live product URL for the owner notification; None if lookup fails."""
    try:
        resp = httpx.get(
            f"{API_BASE}/products/{product_id}",
            params={"access_token": env("GUMROAD_ACCESS_TOKEN")},
            timeout=30,
        )
        if resp.status_code == 200:
            return (resp.json().get("product") or {}).get("short_url")
    except Exception:  # noqa: BLE001
        pass
    return None


# --- Strategy B: Playwright UI automation ------------------------------------

def _upload_via_playwright(job: dict[str, Any]) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise UploadUnsupportedError(
            "Playwright is not installed. Run: pip install playwright && "
            "playwright install chromium"
        ) from exc

    email = env("GUMROAD_EMAIL")
    password = env("GUMROAD_PASSWORD")
    price = float(job["suggested_price_usd"])

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            # Login
            page.goto("https://gumroad.com/login", wait_until="domcontentloaded")
            page.get_by_label("Email").fill(email)
            page.get_by_label("Password").fill(password)
            page.get_by_role("button", name="Login").click()
            page.wait_for_url("**/dashboard**", timeout=30_000)

            # New product
            page.goto("https://app.gumroad.com/products/new", wait_until="domcontentloaded")
            page.get_by_label("Name").fill(job["title"][:255])
            page.get_by_role("radio", name="Digital product").check()
            page.get_by_label("Price").fill(f"{price:.2f}")
            page.get_by_role("button", name="Next: Customize").click()

            # Description + file
            page.get_by_role("textbox", name="Description").fill(job["description"])
            with page.expect_file_chooser() as chooser_info:
                page.get_by_text("Upload files").click()
            chooser_info.value.set_files(job["file_path"])
            page.wait_for_selector("text=uploaded", timeout=120_000)

            # Publish and extract the product id from the URL
            page.get_by_role("button", name="Save and continue").click()
            page.get_by_role("button", name="Publish and continue").click()
            page.wait_for_url("**/products/**", timeout=60_000)
            product_id = page.url.rstrip("/").split("/")[-1].split("?")[0]
            if not product_id:
                raise UploadUnsupportedError(f"Could not extract product id from URL {page.url}")
            return product_id
        finally:
            browser.close()
