-- Niche scout: proposals for new niches are stored as insights so they are
-- never proposed twice.

alter table insights drop constraint if exists insights_kind_check;
alter table insights add constraint insights_kind_check
    check (kind in ('lesson', 'post_mortem', 'calibration', 'niche_idea'));
