-- Active learning loop: products can be retired, and bundle products enter
-- the pipeline through a synthetic opportunity with source='bundle'.

alter table product_jobs drop constraint if exists product_jobs_status_check;
alter table product_jobs add constraint product_jobs_status_check
    check (status in ('pending_generation', 'pending_approval', 'approved',
                      'rejected', 'uploaded', 'failed', 'retired'));

alter table opportunities drop constraint if exists opportunities_source_check;
alter table opportunities add constraint opportunities_source_check
    check (source in ('google_trends', 'etsy_autocomplete', 'bundle'));
