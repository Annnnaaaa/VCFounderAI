# Lane 2 — Intelligence / Reasoning

Produces every score, trust verdict, and memo for VC Brain. Every output carries
rationale, evidence refs, and explicit uncertainty. Every step posts a trace_log
entry.

## Run

```bash
pip install -r requirements.txt          # Python 3.10+
python process.py vectorforge            # one opportunity
python process.py vectorforge agentstack priya petpal   # batch
```

Optional HTTP surface (for Lane 3 / integrators):

```bash
uvicorn app:app --port 8010
# POST /process/{opportunity_id}   POST /nl_query {"q": "..."}
```

Reads `OPENAI_API_KEY` and `SPINE_URL` from the **repo-root `.env`** (shared by
all lanes). Until Lane 1 is live, `spine.py` falls back to `mocks/<id>.json` and
writes artifacts to `out/<id>/` — no config change needed when the API comes up,
it's detected per-run via `GET {SPINE_URL}/health`.

## Pipeline

```
deck_extract → screen → verify → axis_score → [cold_start] → memo → validate
```

- **deck_extract** — PDF → page images (PyMuPDF, no poppler needed) → one vision
  call → `claims[]` tagged `source: deck_slide_N` + one-liner/sector/stage. If the
  bundle already carries claims (mocks, re-runs), the vision call is skipped.
- **screen** — cheap in-thesis filter (pre-seed AI infra). Non-viable →
  `status: passed`, skips everything expensive.
- **verify** — per-claim Trust Score. The model sees only the claim + the evidence
  Lane 4 attached, and cites evidence **by index**, so it cannot invent a URL.
  No external support → `unverified`/low confidence. Direct conflict → `contradicted`.
- **axis_score** — 3 independent axes, **never averaged**: founder 0–100 + trend,
  market bull/neutral/bear, idea_vs_market survives/needs_pivot. Each cites claim_ids.
- **cold_start** — only for thin-track-record founders. Model proposes band +
  signals + a center; **the interval width is enforced in code** (`cold_start.py::_interval`)
  so the honesty guarantee can't be prompted away: ≥2 signals → width ~0.27,
  narrower signal counts widen it further. Never a point score.
- **memo** — the five required sections only. Every factual sentence cites
  `[claim:uuid]`. Contradicted claims appear in the body *with* the contradiction
  stated. Missing data → `gap_flags`. Ends with `recommendation` +
  `what_would_change_my_mind`.
- **validate** — re-reads axes + memo against claims/evidence/founder_ctx and logs
  any unbacked factual statement as a `hallucination_flag` in the trace.

## Strict structured outputs

Every call goes through `llm.py::structured()`, which uses the SDK's `.parse`
helper with a Pydantic `response_format` — that sets `strict: true` and
`additionalProperties: false`, so the model cannot return an off-contract shape.
There is no defensive JSON parsing anywhere downstream. `models.py` is the single
source of truth and mirrors the frozen contract exactly.

Models are env-overridable: `OPENAI_MODEL` (default `gpt-4o`, vision) and
`OPENAI_CHEAP_MODEL` (default `gpt-4o-mini`, screen + NL query).

## Verified results (mock profiles)

| Profile | Result |
|---|---|
| `vectorforge` (strong) | 4/4 corroborated, founder 85/100 ↑, market bull, survives, **invest**, validator clean |
| `agentstack` (seeded contradiction) | MRR claim **contradicted** (conf 0.90) with evidence; memo body states it; founder 40/100, **pass** |
| `priya` (cold start) | band **medium**, interval **[0.42, 0.69]**, `signals_used: 2`, caveat present — no point score |
| `petpal` (out of thesis) | screened out at `screen`, `status: passed`, expensive steps skipped |

Artifacts land in `out/<id>/`: `claims.json`, `axis_scores.json`,
`cold_start.json`, `memo.json`, `status.json`, and `trace.jsonl` (the readable
reasoning chain).

## Notes for integrators

- Bundle fields consumed: `opportunity_id`, `one_liner`, `sector`, `stage`,
  `founder_ctx`, `is_cold_start`, and either `deck_path` or `claims[]` (with any
  evidence Lane 4 attached under `trust.evidence`).
- PPTX is not converted in-process — convert to PDF first (no LibreOffice assumed).
- A failing row in a batch is caught and reported; it never kills the batch.
