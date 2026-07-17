-- ============================================================
-- TrendMill: ALL migrations combined (001-006), safe to run once
-- on a fresh Supabase project. Idempotent (IF NOT EXISTS).
-- ============================================================

-- ==================== migrations/001_init.sql ====================
-- TrendMill initial schema.
-- Run in the Supabase SQL editor (or via psql) once per project.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- opportunities: one row per candidate keyword per scan day.
-- scan_date + the unique constraint make cron reruns idempotent.
-- ---------------------------------------------------------------------------
create table if not exists opportunities (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    scan_date date not null default current_date,
    keyword text not null,
    source text not null check (source in ('google_trends', 'etsy_autocomplete')),
    trend_score numeric,
    competition_count int,
    final_score numeric,
    rationale text,
    status text not null default 'new'
        check (status in ('new', 'shortlisted', 'approved', 'rejected', 'expired')),
    unique (keyword, scan_date)
);

create index if not exists idx_opportunities_status on opportunities (status);
create index if not exists idx_opportunities_scan_date on opportunities (scan_date desc);

-- ---------------------------------------------------------------------------
-- product_jobs: one row per generation attempt for an approved opportunity.
-- ---------------------------------------------------------------------------
create table if not exists product_jobs (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    opportunity_id uuid not null references opportunities (id),
    title text,
    description text,
    tags jsonb check (tags is null or jsonb_array_length(tags) <= 13),
    suggested_price_usd numeric,
    spec jsonb,
    file_path text,
    status text not null default 'pending_generation'
        check (status in ('pending_generation', 'pending_approval', 'approved',
                          'rejected', 'uploaded', 'failed')),
    gumroad_product_id text,
    error text
);

create index if not exists idx_product_jobs_status on product_jobs (status);
create index if not exists idx_product_jobs_opportunity on product_jobs (opportunity_id);

-- ---------------------------------------------------------------------------
-- performance: weekly sales snapshot per product (Module 5).
-- unique(week_start, product_job_id) makes the weekly cron idempotent.
-- ---------------------------------------------------------------------------
create table if not exists performance (
    id uuid primary key default gen_random_uuid(),
    week_start date not null,
    product_job_id uuid not null references product_jobs (id),
    views int,
    sales_count int,
    revenue_usd numeric,
    raw jsonb,
    unique (week_start, product_job_id)
);

-- ---------------------------------------------------------------------------
-- events: audit log of every state transition (Module 3 requirement).
-- ---------------------------------------------------------------------------
create table if not exists events (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    entity text not null,          -- 'opportunity' | 'product_job'
    entity_id uuid not null,
    from_status text,
    to_status text not null,
    meta jsonb
);

create index if not exists idx_events_entity on events (entity, entity_id);

-- ==================== migrations/002_niches.sql ====================
-- Multi-niche support: each opportunity belongs to a niche (vertical), so
-- several product lines can run in parallel through the same pipeline.

alter table opportunities
    add column if not exists niche text not null default 'spreadsheets';

create index if not exists idx_opportunities_niche on opportunities (niche, scan_date desc);

-- ==================== migrations/003_brain.sql ====================
-- Learning brain: distilled lessons, causal post-mortems, signal calibration,
-- and competitor snapshots taken at generation time.

create table if not exists insights (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    niche text,                     -- null = applies to all niches
    kind text not null check (kind in ('lesson', 'post_mortem', 'calibration')),
    content text not null,          -- the text injected into prompts / shown to owner
    evidence jsonb,                 -- structured backing data (job ids, bucket stats, causes)
    active boolean not null default true
);

create index if not exists idx_insights_active on insights (kind, active, created_at desc);

create table if not exists competitor_snapshots (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    keyword text not null,
    listings jsonb not null         -- [{"title": ..., "price": ...}, ...]
);

create index if not exists idx_competitor_snapshots_keyword
    on competitor_snapshots (keyword, created_at desc);

-- ==================== migrations/004_actions.sql ====================
-- Active learning loop: products can be retired, and bundle products enter
-- the pipeline through a synthetic opportunity with source='bundle'.

alter table product_jobs drop constraint if exists product_jobs_status_check;
alter table product_jobs add constraint product_jobs_status_check
    check (status in ('pending_generation', 'pending_approval', 'approved',
                      'rejected', 'uploaded', 'failed', 'retired'));

alter table opportunities drop constraint if exists opportunities_source_check;
alter table opportunities add constraint opportunities_source_check
    check (source in ('google_trends', 'etsy_autocomplete', 'bundle'));

-- ==================== migrations/005_scout.sql ====================
-- Niche scout: proposals for new niches are stored as insights so they are
-- never proposed twice.

alter table insights drop constraint if exists insights_kind_check;
alter table insights add constraint insights_kind_check
    check (kind in ('lesson', 'post_mortem', 'calibration', 'niche_idea'));

-- ==================== migrations/006_foresight.sql ====================
-- Module 9 (foresight): mined from up to 5 years of Google Trends history.

-- "leader spikes now => follower spikes lag_weeks later"
create table if not exists trend_links (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    niche text not null,
    leader text not null,
    follower text not null,
    lag_weeks int not null,
    correlation numeric not null,
    samples int not null,          -- overlapping weeks the correlation is based on
    unique (leader, follower)
);

-- "this keyword reliably starts rising at week N every year"
create table if not exists seasonal_profiles (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    niche text not null,
    keyword text not null unique,
    rise_week int not null,        -- ISO week the climb historically starts
    peak_week int not null,        -- ISO week of the historical peak
    strength numeric not null,     -- peak avg / overall avg (>= 1.5 to be stored)
    years int not null             -- how many years of data support this
);

