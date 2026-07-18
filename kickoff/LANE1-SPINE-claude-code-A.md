# LANE 1 — Claude Code #A: Data Spine + API (owns the contract)

Copy-paste everything below this line into Claude Code session A.

---

You are building the **data spine** of "VC Brain" — a 2-hour hackathon MVP (Hack-Nation Challenge 02, Maschmeyer Group) that sources, screens, and produces evidence-backed investment memos for pre-seed AI-infra founders with $100K checks. Four lanes build in parallel against the JSON contract below. **You own the contract and the database — everyone else codes against your API.** Ship fast, mock nothing you can persist.

## Stack (locked — do not debate)
- Python 3.11+, **FastAPI** + uvicorn, `supabase-py` against a Supabase Postgres project.
- Env vars from `.env`: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`. CORS: allow `*` (Lovable calls you from the browser).
- Repo dir: `spine/`. Single `main.py` is fine; don't over-structure.

## Fund thesis (default row, seed it)
Pre-seed / pre-revenue AI infrastructure, global, $100K checks, ownership 5–8%, high risk appetite. Sectors: inference, agent frameworks, vector/data tooling, eval & observability.

## THE SHARED CONTRACT (frozen — all lanes code to this)
```jsonc
// opportunities
{ "id": "uuid", "source": "inbound_apply | outbound_github | outbound_hn | outbound_arxiv",
  "founder": { "name": "", "handles": { "github": "", "twitter": "", "linkedin": "" }, "location": "" },
  "company": { "name": "", "one_liner": "", "sector": "", "stage": "" },
  "deck_present": true, "created_at": "iso", "status": "new | screened | memo_ready | passed",
  "founder_score": { "value": 0, "confidence": 0.0, "trend": "up|down|flat", "history": [] } }

// claims (Trust Score unit — per claim, never per company)
{ "claim_id": "uuid", "opportunity_id": "uuid", "text": "'$2M ARR, 3x YoY'",
  "type": "traction | revenue | team | market | tech", "source": "deck_slide_4 | tavily | github | hn",
  "trust": { "status": "corroborated | unverified | contradicted", "confidence": 0.0,
             "evidence": [ { "url": "", "snippet": "", "source": "tavily" } ], "note": "why" } }

// axis_scores (3 independent axes — NEVER averaged into one number)
{ "opportunity_id": "uuid", "axes": {
    "founder":        { "score": 0, "trend": "up|down|flat", "rationale": "", "evidence_refs": [] },
    "market":         { "rating": "bull|neutral|bear",       "rationale": "", "evidence_refs": [] },
    "idea_vs_market": { "verdict": "survives|needs_pivot",   "rationale": "", "evidence_refs": [] } } }

// cold_start (honest interval, not a fake point score)
{ "opportunity_id": "uuid", "is_cold_start": true,
  "founder_quality": { "band": "low|medium|high", "interval": [0.4, 0.7], "signals_used": 2 },
  "signals": [ { "kind": "public_writing|side_project|oss|community|domain_insight", "weight": 0.5, "evidence_ref": "" } ],
  "caveat": "Based on N weak signals; wide interval reflects thin track record." }

// memo
{ "opportunity_id": "uuid", "sections": { "company_snapshot": "", "investment_hypotheses": [], "swot": {},
  "problem_product": "", "traction_kpis": "" }, "gap_flags": ["Cap table: not disclosed"],
  "claim_refs": ["claim_id..."], "recommendation": "invest | pass | needs_call" }

// trace_log (agentic traceability)
{ "id": "uuid", "opportunity_id": "uuid", "step": "deck_extract | enrich | verify | axis_score | cold_start | memo",
  "detail": "", "evidence_refs": [], "ts": "iso" }
```

## Your tasks, time-boxed
1. **T+0:10 — Schema.** Supabase tables: `opportunities`, `claims`, `axis_scores`, `cold_start`, `memos`, `founder_scores` (keyed by founder identity, e.g. github handle or normalized name), `thesis`, `trace_log`. JSONB columns for nested objects — don't normalize aggressively. Post the SQL in the team channel so it's on record.
2. **T+0:40 — Write endpoints.**
   - `POST /apply` — `{company_name, one_liner?, founder_name, github_handle?, deck_url?/deck_base64?}` → creates opportunity (`source: inbound_apply`, `status: new`), stores deck bytes to Supabase storage, returns full opportunity row. Minimum bar is deck + company name — do NOT add required fields.
   - `POST /opportunities` (Lane 4 bulk insert), `POST /claims` (bulk), `PATCH /claims/{id}/trust`, `POST /axis-scores`, `POST /cold-start`, `POST /memos`, `POST /trace`.
3. **T+1:10 — Founder Score store.** `POST /founder-score` upserts by founder identity, appends `{value, ts, reason}` to `history`, computes `trend` from last two values. **Persists across opportunities, never resets** — a second application by the same founder must show prior history. `GET /founder-score/{identity}`.
4. **T+1:40 — Read APIs for the UI.**
   - `GET /opportunities?sector=&stage=&min_founder_score=&source=` — ranked list (order by founder axis score desc), filtered by thesis params.
   - `GET /opportunities/{id}/bundle` — one call returning opportunity + claims + axis_scores + cold_start + memo + founder_score + trace_log. Lovable renders the detail page from this single response.
   - `GET/PUT /thesis`.
5. **Seed** with the synthetic rows Lane 4 hands you (~T+1:00). Until then, insert 2 placeholder opportunities yourself so the UI lane is never blocked.

## Acceptance criteria (integration test at T+2:00)
- [ ] `curl POST /apply` with just company name + deck creates a row and returns it with an id.
- [ ] `GET /opportunities/{id}/bundle` returns every contract object in one payload, exact field names above.
- [ ] Founder Score: two POSTs for the same identity → history length 2, trend computed, value survives across two different opportunity ids.
- [ ] Thesis filter works: `?sector=eval` returns only eval-sector rows.
- [ ] Every write endpoint also accepts and stores a `trace_log` entry.
- [ ] Deployed/reachable URL (or localhost + tunnel, e.g. `uvicorn` + ngrok/cloudflared) shared with Lanes 2, 3, 4 by T+1:00.

## Do NOT
- Rename/restructure contract fields after T+10 without telling all lanes.
- Build auth, multi-user, portfolio-monitoring, or exit features (explicitly out of scope).
- Average the 3 axes anywhere, even as a convenience field.
