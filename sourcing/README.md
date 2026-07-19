# Lane 4 — Sourcing, Verification & Seed Data

Sources founders (GitHub / Hacker News), seeds the demo dataset, and attaches
evidence-backed trust verdicts to every claim. Writes to Lane 1's spine API,
with a local write-through cache in `out/` so nothing blocks on the API.

## Setup

```bash
py -m pip install -r requirements.txt   # tavily-python, requests, openai, python-dotenv
```

Reads the shared repo-root `.env`: `TAVILY_API_KEY`, `GITHUB_PAT`,
`OPENAI_API_KEY`, `SPINE_URL`.

## Run

```bash
py run_all.py          # full pipeline in order
py check.py            # acceptance criteria only
```

Or individually:

| Script | Does |
|---|---|
| `seed.py` | Scripted demo profiles + OpenAI-generated fillers. Idempotent. |
| `outbound_github.py` | Authenticated repo search across thesis topics -> founders |
| `outbound_hn.py` | Show HN launches -> founders |
| `enrich.py` | Tavily evidence attached to existing claims (`--all` for outbound too) |
| `verify.py` | Trust verdict for every pending claim |
| `resync.py` | Rebuild the local cache from the live DB |
| `check.py` | Pass/fail against the T+2:00 acceptance criteria |

`SOURCING_DRY_RUN=1` exercises any script end-to-end without writing —
use it when tuning result quality against the shared DB.

## How trust is decided

Three statuses, per claim, never per company:

- **corroborated** — an external source substantively supports the claim.
  GitHub/HN claims are corroborated at 0.95 because the platform *is* the
  primary source for its own star and point counts.
- **contradicted** — evidence directly conflicts with the claim.
- **unverified** — nothing found, or nothing decisive. This is the honest
  default and the most common outcome, not a failure.

`verify.py` hands the claim plus the *real* Tavily snippets to a judge model
which must cite URLs from the supplied results. If Tavily returns nothing we
skip the model entirely and record `unverified` with empty evidence. A verdict
that cannot cite evidence is downgraded to `unverified`. Evidence is only ever
built from fields an API actually returned — see `research.to_evidence`.

For `unverified`, confidence is capped at 0.25: it sits inside `trust`, so the
UI reads it as "how much do we trust this claim", and a judge that is *certain*
it found nothing must not render as a high-trust chip.

## Dedupe / memory

`contract.founder_identity` keys on github handle, falling back to a
normalized name. Both outbound connectors and the seeder resolve against
existing rows, so re-running attaches new claims to the founder's existing
opportunity instead of creating a duplicate.

## Seed fixtures vs real evidence

The four scripted demo profiles (VectorForge, AgentStack, Priya Nair, plus
fillers) are fictional, so their evidence is necessarily synthetic. Every
seeded trust note is therefore prefixed `[seed fixture]` so scripted evidence
is never mistaken for something an API returned. Everything produced by
`enrich.py`, `verify.py` and the outbound connectors is real.

## Files

`out/opportunities.json`, `out/claims.json`, `out/trace.jsonl` mirror the DB;
`out/seed_handoff.json` is the bulk-import bundle for Lane 1;
`out/fillers.json` caches generated fillers so re-seeding is idempotent.
