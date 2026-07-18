-- VC Brain — Lane 1 data spine schema (frozen contract, see kickoff/LANE1)
-- Run in Supabase SQL editor. Idempotent.

create extension if not exists "pgcrypto";

-- ── opportunities ──────────────────────────────────────────────────────────
create table if not exists opportunities (
  id            uuid primary key default gen_random_uuid(),
  source        text not null default 'inbound_apply',
  founder       jsonb not null default '{}'::jsonb,
  company       jsonb not null default '{}'::jsonb,
  deck_present  boolean not null default false,
  deck_url      text,
  created_at    timestamptz not null default now(),
  status        text not null default 'new',
  founder_score jsonb not null default '{"value":0,"confidence":0.0,"trend":"flat","history":[]}'::jsonb
);
-- filter/sort helpers for GET /opportunities
create index if not exists opportunities_sector_idx on opportunities ((company->>'sector'));
create index if not exists opportunities_stage_idx  on opportunities ((company->>'stage'));
create index if not exists opportunities_source_idx on opportunities (source);

-- ── claims (Trust Score unit — per claim, never per company) ───────────────
create table if not exists claims (
  claim_id       uuid primary key default gen_random_uuid(),
  opportunity_id uuid not null references opportunities(id) on delete cascade,
  text           text not null,
  type           text,
  source         text,
  trust          jsonb not null default '{"status":"unverified","confidence":0.0,"evidence":[],"note":""}'::jsonb,
  created_at     timestamptz not null default now()
);
create index if not exists claims_opp_idx on claims (opportunity_id);

-- ── axis_scores (3 independent axes — NEVER averaged) ──────────────────────
create table if not exists axis_scores (
  opportunity_id uuid primary key references opportunities(id) on delete cascade,
  axes           jsonb not null default '{}'::jsonb,
  updated_at     timestamptz not null default now()
);

-- ── cold_start (honest interval, not a fake point score) ───────────────────
create table if not exists cold_start (
  opportunity_id  uuid primary key references opportunities(id) on delete cascade,
  is_cold_start   boolean not null default true,
  founder_quality jsonb not null default '{}'::jsonb,
  signals         jsonb not null default '[]'::jsonb,
  caveat          text,
  updated_at      timestamptz not null default now()
);

-- ── memos ──────────────────────────────────────────────────────────────────
create table if not exists memos (
  opportunity_id uuid primary key references opportunities(id) on delete cascade,
  sections       jsonb not null default '{}'::jsonb,
  gap_flags      jsonb not null default '[]'::jsonb,
  claim_refs     jsonb not null default '[]'::jsonb,
  recommendation text,
  updated_at     timestamptz not null default now()
);

-- ── founder_scores (keyed by founder identity — persists across opportunities) ──
create table if not exists founder_scores (
  identity   text primary key,
  name       text,
  value      double precision not null default 0,
  confidence double precision not null default 0,
  trend      text not null default 'flat',
  history    jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

-- ── thesis ─────────────────────────────────────────────────────────────────
create table if not exists thesis (
  id         uuid primary key default gen_random_uuid(),
  params     jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- ── trace_log (agentic traceability) ───────────────────────────────────────
create table if not exists trace_log (
  id             uuid primary key default gen_random_uuid(),
  opportunity_id uuid references opportunities(id) on delete cascade,
  step           text not null,
  detail         text,
  evidence_refs  jsonb not null default '[]'::jsonb,
  ts             timestamptz not null default now()
);
create index if not exists trace_log_opp_idx on trace_log (opportunity_id, ts);

-- ── default fund thesis row ────────────────────────────────────────────────
insert into thesis (params)
select '{
  "stage": "pre-seed",
  "revenue": "pre-revenue",
  "domain": "AI infrastructure",
  "geo": "global",
  "check_size_usd": 100000,
  "ownership_target": [0.05, 0.08],
  "risk_appetite": "high",
  "sectors": ["inference", "agent frameworks", "vector/data tooling", "eval & observability"]
}'::jsonb
where not exists (select 1 from thesis);

-- ── deck storage bucket ────────────────────────────────────────────────────
insert into storage.buckets (id, name, public)
select 'decks', 'decks', true
where not exists (select 1 from storage.buckets where id = 'decks');
