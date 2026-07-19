-- Migration 02 — evidence provenance. Additive, safe to re-run.
-- Run in the Supabase SQL editor, then redeploy the spine.
--
-- Why: claims.trust.evidence[].source names the TOOL that fetched an item
-- (tavily | github | hn). It cannot express whether the item is real or
-- scripted for the demo, so a fabricated company and a genuinely sourced one
-- are indistinguishable in the DB. `origin` answers "how do you know this
-- is real?" — which is the question a judge will actually ask.

alter table opportunities
  add column if not exists origin text not null default 'live'
  check (origin in ('seed', 'live'));

create index if not exists opportunities_origin_idx on opportunities (origin);

-- ── backfill ───────────────────────────────────────────────────────────────
-- Everything defaults to 'live', so only the scripted rows are named here.
-- Listed explicitly rather than inferred from `source`: origin and source are
-- independent. Tensorwake and Groundtruth carry outbound_* sources but were
-- invented as placeholders, while the other outbound_* rows are real repos.

-- Lane 1 placeholder rows (invented so the UI lane was not blocked)
update opportunities set origin = 'seed'
 where id in (
   '11111111-1111-1111-1111-111111111111',  -- Tensorwake
   '22222222-2222-2222-2222-222222222222'   -- Groundtruth
 );

-- Lane 2 wiring probe
update opportunities set origin = 'seed'
 where company->>'name' = 'Lane2 Wiring Test';

-- Scripted inbound demo applications. NOTE: verify this list before the demo.
-- These are believed fictional (generic names, and VectorForge's "corroborating"
-- evidence points at a different real company that shares the name). If any of
-- these is a genuine submission, PATCH its origin back to 'live'.
update opportunities set origin = 'seed'
 where source = 'inbound_apply'
   and company->>'name' in (
     'DataNexus Tools',
     'EvalGuard Tech',
     'InfiAgent Solutions',
     'VectorForge',
     'AgentStack',
     'InferBoost Systems'
   );

-- The pre-company cold-start demo founder (blank company name by design)
update opportunities set origin = 'seed'
 where source = 'inbound_apply'
   and coalesce(company->>'name', '') = ''
   and founder->>'name' = 'Priya Nair';

-- ── stamp existing evidence from its opportunity ───────────────────────────
-- Evidence about a scripted company is scripted regardless of which tool
-- retrieved it, so origin is inherited, never asserted per item.
update claims c
   set trust = jsonb_set(
         c.trust,
         '{evidence}',
         (
           select coalesce(jsonb_agg(e || jsonb_build_object('origin', o.origin)), '[]'::jsonb)
             from jsonb_array_elements(coalesce(c.trust->'evidence', '[]'::jsonb)) e
         )
       )
  from opportunities o
 where o.id = c.opportunity_id
   and jsonb_array_length(coalesce(c.trust->'evidence', '[]'::jsonb)) > 0;
