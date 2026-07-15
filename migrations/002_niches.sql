-- Multi-niche support: each opportunity belongs to a niche (vertical), so
-- several product lines can run in parallel through the same pipeline.

alter table opportunities
    add column if not exists niche text not null default 'spreadsheets';

create index if not exists idx_opportunities_niche on opportunities (niche, scan_date desc);
