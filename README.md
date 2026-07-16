# TrendMill — Automated Digital Product Machine

A fully automated pipeline that scans the web daily for rising demand in
digital spreadsheet products, generates ready-to-sell Excel/Google Sheets
templates, gates every candidate behind a one-tap Telegram approval, uploads
approved products to Gumroad, and learns weekly from sales data.

Owner attention budget: ~5 minutes/day (Telegram approvals only).

## Architecture

```
Railway cron (daily)   ->  scan.py      Module 1: trends + Etsy signals -> scored
                                        opportunities -> Telegram digest with buttons
Telegram callback      ->  app/server.py Module 3: approval gate (FastAPI webhook)
   ✅ Generate          ->  app/generator.py Module 2: LLM spec -> openpyxl .xlsx ->
                                        listing copy -> Telegram approval message
   ✅ Approve & Upload  ->  app/uploader.py  Module 4: Gumroad upload (Strategy A/B)
Railway cron (weekly)  ->  learn.py     Module 5: sales -> performance table ->
                                        feeds Module 1's LLM re-rank
Supabase (Postgres)    — all persistence (opportunities, product_jobs,
                          performance, events audit log)
```

## Repo structure

```
migrations/001_init.sql        DB schema (run once in Supabase SQL editor)
spike/gumroad_create_spike.py  Milestone 0: decides upload Strategy A vs B
app/
  config.py                    env vars, seed terms, scan constants
  db.py                        Supabase access layer
  llm.py                       OpenRouter client (ROUTINE_MODEL / GENERATION_MODEL)
  notify.py                    Telegram messages (Hebrew), daily digest, error alerts
  scanner/trends.py            Google Trends growth signal (pytrends)
  scanner/etsy.py              Etsy autocomplete + competition count (polite scraping)
  scanner/scoring.py           spec scoring formula + candidate assembly
  server.py                    FastAPI webhook: idempotent button callbacks
  generator.py                 Module 2: LLM spec -> xlsx -> listing copy -> approval
  xlsx_builder.py              openpyxl renderer for LLM specs (theming, formulas)
  uploader.py                  Module 4 (Milestone 3 — stub, strategy-swappable)
  learner.py                   Module 5 (Milestone 4 — stub)
scan.py / generate.py / upload.py / learn.py   worker entrypoints
scripts/set_webhook.py         one-time Telegram webhook registration
```

## Setup

1. **Supabase**: create a project, run `migrations/001_init.sql` in the SQL editor.
2. **Telegram**: create a bot via @BotFather; get your chat id (message the bot,
   then check `getUpdates`).
3. **Env**: copy `.env.example` to `.env` and fill everything in.
4. **Milestone 0 spike** (before wiring the uploader):
   `GUMROAD_ACCESS_TOKEN=... python spike/gumroad_create_spike.py`
   The last line prints `VERDICT: STRATEGY_A` (API works) or
   `VERDICT: STRATEGY_B` (Playwright UI automation needed).

## Railway deployment (single repo, four services)

Create one Railway project and add four services all pointing at this repo:

| Service    | Type | Start command                                        | Cron            |
|------------|------|------------------------------------------------------|-----------------|
| web        | web  | `uvicorn app.server:app --host 0.0.0.0 --port $PORT` | —               |
| scan-cron  | cron | `python scan.py`                                     | `23 6 * * *`    |
| learn-cron | cron | `python learn.py`                                    | `41 6 * * 1`    |

All services share the same environment variables (Railway shared variables).
After the web service is live, register the Telegram webhook once:

```
python scripts/set_webhook.py https://<web-service>.up.railway.app
```

## Operating principles

- **Fail soft, report loud** — every module error becomes a Telegram alert with
  a traceback tail; the daily scan completes even if one source is down.
- **Idempotency** — `opportunities` is unique on `(keyword, scan_date)`; the
  scan exits early if today already ran (`TRENDMILL_FORCE=1` overrides);
  webhook callbacks re-read status and only perform legal transitions, so
  double-taps never double-generate or double-upload; `performance` is unique
  on `(week_start, product_job_id)`.
- **Cost ceiling** — one cheap ROUTINE_MODEL call per daily scan; the strong
  GENERATION_MODEL is used only for product content (Module 2). Target
  < $0.30/day.
- **Language** — Telegram UI in Hebrew; code + product content in English.

## Milestones

- [x] **M0** — Gumroad spike script (`spike/`). Research (July 2026): the
  create-products API was an open feature request (antiwork/gumroad#4019,
  closed March 2026); docs are inconsistent, so the spike's live verdict with a
  real token decides Strategy A vs B. The uploader interface
  (`upload_product(job) -> product_id`) is strategy-swappable either way.
- [x] **M1** — schema + scanner + daily Telegram digest (this commit).
  Acceptance: ranked digest with real data for 3 consecutive days.
- [x] **M2** — generator + approval flow: LLM spec (GENERATION_MODEL) →
  `app/xlsx_builder.py` (styled, frozen headers, live formulas, instructions
  sheet) → listing copy (ROUTINE_MODEL, 13 tags, $9–19) → Telegram approval
  message with the .xlsx attached. Acceptance: ✅ on a digest item produces a
  polished .xlsx in Telegram within ~3 minutes.
- [x] **M3 (code)** — uploader behind `upload_product(job)` with both
  strategies: A = official API (auto-detects unsupported endpoints and says
  so), B = Playwright UI automation (selectors need one live verification).
  ⬜ Acceptance still pending: run the spike with a real token, set
  `UPLOAD_STRATEGY`, and push one real product live.
- [x] **M4 (code)** — weekly sales pull (paginated /v2/sales, refunds
  excluded), idempotent `performance` upsert, Hebrew weekly report; feeds the
  scanner's per-niche re-rank. ⬜ Acceptance pending live products.
- **Multi-niche**: parallel product lines via `config.NICHES` +
  `TRENDMILL_NICHES` (currently `spreadsheets`, `trader_tools`); per-niche
  digests, idempotency, and learning context.
- **Learning brain (`app/brain.py` + migration 003)** — runs weekly after the
  sales report: causal post-mortems for products that didn't sell (causes with
  evidence + confidence, improvements, one generalizable lesson each; only
  after 14 days live, capped per run), pure-statistics signal calibration
  (buckets under 5 samples stay silent instead of overfitting), and a lessons
  memory injected into the daily re-rank and into product generation.
  Competitor snapshots (`app/scanner/competitors.py`, Etsy JSON-LD) are taken
  at generation time so every product is designed against what already ranks.
- **Foresight (`app/scanner/foresight.py` + migration 006)** — monthly cron
  mines 5 years of Google Trends history per niche: data-driven seasonal
  profiles (rise/peak week, strength >= 1.5x, >= 2 years of support) and
  lead-lag links computed on week-over-week changes (never raw levels; lag
  1-12w, corr >= 0.45 over >= 80 weeks). The daily scanner then scans
  seasonal keywords up to 4 weeks BEFORE their historical rise and chases
  followers the moment a known leader spikes.

Owner-facing roadmap, deploy checklist, and platform comparison: [docs/ROADMAP.md](docs/ROADMAP.md).
