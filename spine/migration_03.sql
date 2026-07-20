-- Migration 03 — durable job runs. Additive, safe to re-run.
-- Run in the Supabase SQL editor, then redeploy the spine.
--
-- Why: re-screen progress lived only in the intelligence service's memory. A
-- free-tier restart (or any redeploy) wiped it mid-run, so the UI fell back to
-- "no re-screen running" while work was still happening — or had happened, with
-- no record of it. The opportunity statuses were durable, but the story of what
-- the run did was not. This table is that record.

create table if not exists job_runs (
  id          uuid primary key default gen_random_uuid(),
  kind        text not null default 'rescreen',   -- rescreen | analyze
  state       text not null default 'running',    -- running | finished | failed
  dry_run     boolean not null default false,
  total       integer not null default 0,
  done        integer not null default 0,
  current     jsonb,                              -- {id, company, phase}
  changes     jsonb not null default '[]'::jsonb,
  error       text,
  started_at  timestamptz not null default now(),
  finished_at timestamptz
);

-- GET /jobs/latest reads the newest row.
create index if not exists job_runs_started_idx on job_runs (started_at desc);
