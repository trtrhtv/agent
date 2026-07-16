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
