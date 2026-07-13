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
