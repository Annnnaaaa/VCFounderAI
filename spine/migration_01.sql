-- Migration 01 — additive only, safe to re-run.
-- Run in the Supabase SQL editor, then redeploy the spine.

-- Lane 3 needs a first-class field for the falsifiability section of the memo.
-- jsonb so it accepts either a string or a list of conditions.
alter table memos
  add column if not exists what_would_change_my_mind jsonb default '[]'::jsonb;

-- deck_present must imply an openable deck. Six inbound rows were written with
-- deck_present=true and deck_url=null because a storage upload failed silently;
-- the UI rendered a deck affordance that resolved to nothing.
update opportunities
   set deck_present = false
 where deck_present is true
   and (deck_url is null or deck_url = '');

-- Enforce the invariant from here on, so no lane can reintroduce it.
alter table opportunities
  drop constraint if exists deck_present_implies_url;
alter table opportunities
  add constraint deck_present_implies_url
  check (deck_present is false or deck_url is not null);
