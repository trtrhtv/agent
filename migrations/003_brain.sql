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
