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
  generator.py                 Module 2 (Milestone 2 — stub)
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

## Railway deployment (single repo, three services)

Create one Railway project and add three services all pointing at this repo:

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
- [ ] **M2** — generator + approval flow (webhook transitions already wired).
- [ ] **M3** — uploader per spike verdict.
- [ ] **M4** — weekly performance loop + learning context (context plumbing to
  the scanner prompt already in place via `db.performance_context()`).
