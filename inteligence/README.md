# Lane 2 — Intelligence / Reasoning

Produces every score, trust verdict, and memo for VC Brain. Every output carries
rationale, evidence refs, and explicit uncertainty. Every step posts a trace_log
entry.

Wired live against `https://vcbrain-spine.onrender.com` (Lane 1).

## Run

```bash
pip install -r requirements.txt          # Python 3.10+
python process.py <opportunity_uuid>     # one row
python process.py --all                  # every row awaiting analysis
python process.py --all --force          # also re-do memo_ready rows
python check.py                          # acceptance harness
python make_demo_deck.py                 # generate real demo PDFs
```

Offline regression suite (fixtures, never touches the live DB):

```bash
python process.py vectorforge agentstack priya petpal
```

Optional HTTP surface for Lane 3:

```bash
uvicorn app:app --port 8010
# POST /process/{opportunity_id}   POST /nl_query {"q": "..."}
```

`OPENAI_API_KEY` and `SPINE_URL` come from the **repo-root `.env`**.

## Pipeline

```
deck_extract → screen → [persist claims] → verify → axis_score
             → [cold_start] → memo → validate
```

- **deck_extract** — claims already attached to the opportunity win; otherwise
  the deck (remote `deck_url` or local path) is rendered with PyMuPDF and sent
  to one vision call, producing claims tagged `source: deck_slide_N`.
- **screen** — cheap filter against the **live** `GET /thesis`, so retuning the
  fund lens in the UI changes screening with no redeploy. Non-viable → `passed`.
- **verify** — per-claim Trust Score. The model sees the claim plus the evidence
  Lane 4 attached and cites evidence **by index**, so it cannot invent a URL.
- **axis_score** — 3 independent axes, **never averaged**. Also feeds
  `POST /founder-score` so the detail-page sparkline accumulates across rows.
- **cold_start** — band + interval + signals + caveat, never a point score.
- **memo** — five required sections, `[claim:uuid]` citations, `gap_flags`,
  recommendation.
- **validate** — logs any unbacked factual statement as a `hallucination_flag`.

## Guarantees enforced in code, not prompts

- **Cold-start interval width** (`cold_start.py::_interval`) — the model only
  proposes a center; the code sets the width (≥2 signals → 0.27, widening as
  signals shrink). A prompt cannot talk the system into false confidence.
- **Cold-start detection** (`process.py::_is_cold_start`) — based on externally
  corroborated claims + public handles, deliberately **not** on founder_score
  history, because that history contains scores this pipeline itself wrote. See
  "Bugs found and fixed" below.
- **Evidence citation by index** — the trust verifier can only point at evidence
  it was given.
- **Strict structured outputs** — every call goes through `llm.py::structured()`
  using the SDK `.parse` helper with a Pydantic `response_format`, which sets
  `strict: true` and `additionalProperties: false`. No defensive JSON parsing
  anywhere. `models.py` is the single source of truth.

Models are env-overridable: `OPENAI_MODEL` (default `gpt-4o`) and
`OPENAI_CHEAP_MODEL` (default `gpt-4o-mini`).

## Live API notes (verified against the deployed Spine)

| Behavior | Consequence for this lane |
|---|---|
| `POST /claims` assigns the `claim_id` | Claims are persisted **before** scoring, so memo citations resolve in the UI |
| No `DELETE` for claims | Re-POSTing attached claims would permanently duplicate them → `push_claims(already_persisted=True)` skips the POST and PATCHes trust instead |
| `POST /opportunities` is a **full upsert** | A partial body wipes `founder`/`deck_url` → `set_status()` re-sends the preserved record |
| `POST /memos` auto-advances status | We only set status explicitly for the `passed` path |
| Bundle shape is nested | `_adapt_bundle()` flattens `{opportunity, claims, …}` for the pipeline |

## Bugs found and fixed during live integration

1. **Claim duplication** — re-POSTing already-attached claims doubled every row
   (VectorForge went 5 → 10). Fixed; those 10 rows are still on the server, see
   open asks.
2. **Self-referential cold-start** — cold-start was derived from `founder_score`
   history, but this pipeline *writes* that history, so a second run silently
   promoted a cold-start founder to "established". Now derived from external
   signal strength.
3. **Validator false positives** — it flagged founder-background statements as
   hallucinations because it only saw `claim_ids`. It now receives claims,
   evidence, and founder context as known backing.
4. **Mock/live cross-contamination** — running fixtures while `SPINE_URL` was
   set would have POSTed `priya`/`petpal` into the production DB. `_writes_live()`
   now isolates mock-sourced ids from all live writes.
5. **Spurious contradictions from date confusion** (worst of the batch) — the
   model treated 2026 dates as "in the future" and marked every Lane 4 GitHub
   row's "actively maintained" claim as `contradicted` at **1.0 confidence**.
   That would have buried AgentStack's real contradiction — the demo's key
   moment — under a wall of false red chips. The verify and axis prompts now
   carry today's date with an instruction to trust it over intuition. Re-running
   the affected rows took them from 1 contradicted to 0, while AgentStack's
   genuine contradiction still fires.
6. **Unreadable decks** — the seeded decks are 24-byte stubs
   (`%PDF-1.4 fake deck bytes`); PyMuPDF raised an unhandled error. Now raises
   `UnreadableDeck`, which is traced and yields zero claims rather than an
   evidence-free memo.

## Open integration asks (Lane 1)

- **`what_would_change_my_mind` 500s on `POST /memos`** — no column for it. The
  field is in the contract and the local artifact but is **stripped on the wire**
  (`spine.py::_MEMO_FIELDS_LANE1_REJECTS`). Add the column and delete that line.
- **10 duplicate claims on VectorForge** (`0a7f6ac8-…`) from bug #1 above. There
  is no DELETE endpoint, so they need removing server-side before the demo or
  the claim list renders each claim twice.
- **`GET /opportunities/{id}/bundle` intermittently 500s** (e.g.
  `a8a38ba1-…`); the pipeline falls back and reports it, but those rows can't be
  processed.
- **`deck_present: true` with `deck_url: null`** on 6 rows, including VectorForge
  and AgentStack — the UI will show a deck affordance that resolves to nothing.

## Demo assets

`make_demo_deck.py` generates genuine two-slide PDFs for VectorForge and
AgentStack (including AgentStack's seeded contradiction) into `decks/`. These
replace the placeholder decks and are what `/apply` should be demoed with —
vision extraction is verified working against them, with correct per-slide
attribution.
