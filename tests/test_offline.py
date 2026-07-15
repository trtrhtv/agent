"""Offline test suite — no network, no real credentials. Run: pytest -q"""

import os

os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "dummy")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("TELEGRAM_OWNER_CHAT_ID", "1")
os.environ.setdefault("OPENROUTER_API_KEY", "dummy")
os.environ.setdefault("GUMROAD_ACCESS_TOKEN", "dummy")


def test_scoring_formula():
    from app.scanner.scoring import competition_penalty

    assert competition_penalty(500) == 1.0
    assert competition_penalty(3000) == 0.6
    assert competition_penalty(10000) == 0.3
    assert competition_penalty(50000) == 0.1
    assert competition_penalty(None) == 0.5


def test_candidates_relevance_and_dedupe():
    from app.config import NICHES
    from app.scanner.scoring import build_candidates, finalize_scores

    terms = NICHES["spreadsheets"]["relevance_terms"]
    cands = build_candidates(
        {"budget spreadsheet": 80.0, "dog collar": 90.0},
        {"budget spreadsheet": ["wedding budget spreadsheet", "dog leash"]},
        terms,
    )
    kws = {c.keyword for c in cands}
    assert "dog collar" not in kws and "wedding budget spreadsheet" in kws
    finalize_scores(cands)


def test_llm_json_extraction():
    from app.llm import extract_json

    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('prose {"a": 1} prose') == {"a": 1}


def test_listing_copy_constraints():
    from app.generator import _finalize_copy

    c = _finalize_copy({"title": "T" * 300, "tags": ["a", "a"], "price_usd": 3}, "wedding budget")
    assert len(c["title"]) == 140
    assert len(c["tags"]) == 13 == len(set(c["tags"]))
    assert c["price_usd"] == 9.0
    assert _finalize_copy({"price_usd": 99}, "x")["price_usd"] == 19.0


def test_xlsx_builder(tmp_path):
    from openpyxl import load_workbook

    from app.xlsx_builder import build_xlsx

    spec = {
        "product_name": "Test",
        "theme": {"primary": "112233"},
        "sheets": [{
            "name": "Data",
            "columns": [{"header": "A", "format": "currency"}, {"header": "B"}],
            "rows": [["x", "=A4*2"]],
            "totals_row": ["T", "=SUM(B4:B4)"],
        }],
        "how_to_use": ["Step"],
    }
    out = str(tmp_path / "t.xlsx")
    build_xlsx(spec, out)
    wb = load_workbook(out)
    ws = wb["Data"]
    assert ws.freeze_panes == "A4"
    assert ws["B4"].value == "=A4*2"
    assert ws["B5"].value == "=SUM(B4:B4)"


def test_cover_render(tmp_path):
    from PIL import Image

    from app.cover import render_cover

    spec = {"product_name": "Wedding Budget Pro", "tagline": "Plan it all",
            "theme": {"primary": "6B4E71", "secondary": "F3EDF5", "accent": "D4A947"},
            "sheets": [{"columns": [{"header": "Item"}, {"header": "Cost"}],
                        "rows": [["Venue", 5000], ["Food", "=B4*2"]]}]}
    out = str(tmp_path / "cover.png")
    render_cover(spec, out)
    img = Image.open(out)
    assert img.size == (1280, 720)


def test_calibration_sample_guards():
    from app.brain import calibrate

    def product(source, sales):
        return {"total_sales": sales, "total_revenue": 10.0 * sales, "suggested_price_usd": 12,
                "opportunities": {"source": source, "competition_count": 100, "niche": "n"}}

    rows = [product("etsy_autocomplete", 1) for _ in range(6)] + [product("google_trends", 5)]
    lines, evidence = calibrate(rows)
    text = " ".join(lines)
    assert "etsy_autocomplete" in text
    assert "google_trends" not in text  # n=1 bucket must stay silent
    assert evidence["buckets"]["source:google_trends"]["n"] == 1


def test_competitor_ldjson_parser():
    from app.scanner.competitors import _listings_from_ldjson

    html = '''<script type="application/ld+json">
    {"@type":"ItemList","itemListElement":[
      {"item":{"name":"Tracker Pro","offers":{"price":"12.99"},
       "aggregateRating":{"ratingValue":"4.9","reviewCount":"88"}}}]}</script>'''
    listings = _listings_from_ldjson(html)
    assert listings == [{"title": "Tracker Pro", "price": "12.99", "rating": "4.9", "reviews": "88"}]


def test_seasonal_seeds():
    from app.config import seasonal_seeds

    july = seasonal_seeds("spreadsheets", 7)
    assert "back to school budget" in july          # current month
    assert "back to school checklist" in july       # next month
    assert seasonal_seeds("unknown_niche", 7) == []


def test_niche_activation():
    import pytest

    from app.config import active_niches

    os.environ["TRENDMILL_NICHES"] = "trader_tools"
    assert list(active_niches()) == ["trader_tools"]
    os.environ["TRENDMILL_NICHES"] = "nope"
    with pytest.raises(RuntimeError):
        active_niches()
    os.environ.pop("TRENDMILL_NICHES")


def test_uploader_dispatch_error():
    import pytest

    from app.uploader import upload_product

    os.environ["UPLOAD_STRATEGY"] = "bogus"
    with pytest.raises(ValueError):
        upload_product({})
    os.environ.pop("UPLOAD_STRATEGY")


def test_learner_aggregation():
    from app.learner import aggregate_sales

    agg = aggregate_sales([
        {"product_id": "p", "price": 1000},
        {"product_id": "p", "price": 1000, "refunded": True},
    ])
    assert agg["p"] == {"sales_count": 1, "revenue_usd": 10.0}


def test_server_routes():
    from app.server import app

    paths = {r.path for r in app.routes}
    assert {"/health", "/telegram/webhook"} <= paths
