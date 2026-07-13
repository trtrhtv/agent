"""Milestone 0 spike: can we CREATE a Gumroad product via the official API?

Background (researched July 2026):
- Gumroad's v2 API historically supported only reading products
  (GET /v2/products) plus enable/disable/delete — no create endpoint.
- antiwork/gumroad issue #4019 ("API for creating and editing products")
  was closed in March 2026, but public docs are inconsistent about whether
  POST /v2/products actually shipped.
- This script settles it empirically. Run it with a real access token:

    GUMROAD_ACCESS_TOKEN=xxx python spike/gumroad_create_spike.py

It performs, in order:
  1. GET  /v2/user               — sanity-check the token.
  2. POST /v2/products           — attempt a minimal product creation.
  3. If created: PUT  /v2/products/:id            — attempt an edit.
  4. If created: probe file attachment options.
  5. If created: DELETE /v2/products/:id          — clean up after ourselves.

It prints a final verdict line:
  VERDICT: STRATEGY_A  -> API creation works, implement uploader via API.
  VERDICT: STRATEGY_B  -> API creation unsupported, implement Playwright UI uploader.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE = "https://api.gumroad.com/v2"
TIMEOUT = 30.0


def pretty(resp: httpx.Response) -> str:
    try:
        return json.dumps(resp.json(), indent=2)[:2000]
    except Exception:
        return resp.text[:2000]


def main() -> int:
    token = os.environ.get("GUMROAD_ACCESS_TOKEN", "").strip()
    if not token:
        print("ERROR: set GUMROAD_ACCESS_TOKEN in the environment before running.")
        return 2

    client = httpx.Client(timeout=TIMEOUT, params={"access_token": token})

    # 1. Token sanity check
    print("== Step 1: GET /user (token check) ==")
    r = client.get(f"{BASE}/user")
    print(f"HTTP {r.status_code}\n{pretty(r)}\n")
    if r.status_code != 200:
        print("Token is invalid or lacks scopes; fix the token and rerun.")
        return 2

    # 2. Attempt product creation
    print("== Step 2: POST /products (create attempt) ==")
    payload = {
        "name": "TrendMill Spike Test (safe to delete)",
        "price": 900,  # cents
        "description": "Automated API spike test product. Will be deleted.",
        "url": "trendmill-spike-test",
    }
    r = client.post(f"{BASE}/products", data=payload)
    print(f"HTTP {r.status_code}\n{pretty(r)}\n")

    created_id = None
    if r.status_code in (200, 201):
        try:
            body = r.json()
            created_id = (body.get("product") or {}).get("id")
        except Exception:
            pass

    if not created_id:
        print("Product creation via API did NOT work.")
        print("VERDICT: STRATEGY_B")
        return 1

    print(f"Product created! id={created_id}")

    # 3. Attempt an edit (price change) to confirm write scope end-to-end
    print("== Step 3: PUT /products/:id (edit attempt) ==")
    r = client.put(f"{BASE}/products/{created_id}", data={"price": 1100})
    print(f"HTTP {r.status_code}\n{pretty(r)}\n")

    # 4. Probe file attachment routes (undocumented; try common shapes)
    print("== Step 4: file attachment probes ==")
    for path in (f"/products/{created_id}/files", f"/products/{created_id}/content"):
        try:
            probe = client.post(
                f"{BASE}{path}",
                files={"file": ("spike.txt", b"spike", "text/plain")},
            )
            print(f"POST {path} -> HTTP {probe.status_code}\n{pretty(probe)}\n")
        except Exception as exc:  # noqa: BLE001 — spike must report, not crash
            print(f"POST {path} -> exception: {exc}\n")

    # 5. Clean up
    print("== Step 5: DELETE /products/:id (cleanup) ==")
    r = client.delete(f"{BASE}/products/{created_id}")
    print(f"HTTP {r.status_code}\n{pretty(r)}\n")
    if r.status_code != 200:
        print(f"WARNING: cleanup failed — delete product {created_id} manually "
              "from the Gumroad dashboard.")

    print("VERDICT: STRATEGY_A")
    return 0


if __name__ == "__main__":
    sys.exit(main())
