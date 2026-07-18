# LANE 4 — Sourcing + Verification + Seed Data (Tavily / GitHub / HN)

Copy-paste everything below this line into the fourth session (Claude Code or any agent with a terminal).

---

You are building the **sourcing and verification layer** of "VC Brain" — a 2-hour hackathon MVP (Hack-Nation Challenge 02). Sourcing is the single highest-weighted rubric area ("go further here than anywhere else"). You do three jobs: (1) seed the demo dataset, (2) outbound sourcing from GitHub + Hacker News, (3) Tavily-powered evidence/verification on every claim. You write results into Lane 1's API (FastAPI + Supabase); until it's live (~T+1:00), write JSON files matching the contract exactly.

## Stack (locked)
- Python 3.11+. Libs: `tavily-python`, `requests`, `openai` (for synthetic data gen). Env: `TAVILY_API_KEY`, `GITHUB_PAT`, `OPENAI_API_KEY`, `SPINE_URL`.
- Repo dir: `sourcing/`. Plain scripts: `seed.py`, `enrich.py`, `outbound_github.py`, `outbound_hn.py`, `verify.py`.
- GitHub REST **must be authenticated** with the PAT (30 search req/min vs 10; 5000/hr core vs 60).

## Fund thesis (targeting)
Pre-seed AI infrastructure: inference, agent frameworks, vector/data tooling, eval & observability. Founders with public builder footprints.

## THE SHARED CONTRACT (frozen — emit exactly these shapes)
```jsonc
// opportunity
{ "source": "inbound_apply | outbound_github | outbound_hn",
  "founder": { "name": "", "handles": { "github": "", "twitter": "", "linkedin": "" }, "location": "" },
  "company": { "name": "", "one_liner": "", "sector": "", "stage": "pre-seed" }, "deck_present": false }

// claim + trust (verification unit)
{ "opportunity_id": "", "text": "", "type": "traction | revenue | team | market | tech", "source": "deck_slide_N | tavily | github | hn",
  "trust": { "status": "corroborated | unverified | contradicted", "confidence": 0.0,
             "evidence": [ { "url": "", "snippet": "", "source": "tavily|github|hn" } ], "note": "" } }
```
POST to `SPINE_URL`: `/opportunities`, `/claims`, `PATCH /claims/{id}/trust`, `/trace` (log every sourcing/verification step: `{opportunity_id, step: "enrich"|"verify", detail, evidence_refs, ts}`).

## Your tasks, time-boxed

1. **T+0:30 — Seed dataset (do this FIRST, Lane 1 + 3 depend on it).** Generate 6–8 synthetic founder profiles with OpenAI, including these four scripted demo profiles exactly:
   - **VectorForge (strong inbound)** — Lena Vogt, Berlin, ex-inference engineer; deck claims "800 GitHub stars + Show HN front page" → evidence corroborates.
   - **AgentStack (seeded contradiction)** — deck claims "2,000 paying devs, $30K MRR"; reality: 3-week-old repo, 40 stars, no pricing page → claims must end up `contradicted`.
   - **Cold-start solo builder** — Priya Nair; no company, no funding, no LinkedIn; only a 120-star LLM-eval repo + one thoughtful blog post on eval methodology. Include exactly these 2 signals so Lane 2 scores band `medium`, interval ≈ [0.45, 0.72].
   - **Filler**: 3–4 mediocre profiles (so ranking looks real).
   For each: opportunity row + 3–6 claims (deck-sourced) + synthetic evidence snippets. Hand the JSON to Lane 1 (or POST once the API is up).

2. **T+1:00 — Enrichment (`enrich.py`).** `enrich(opportunity)` → Tavily `search` "<founder> <company> funding OR revenue OR launch" (+ site-specific if handles known), `extract` top 2–3 hits → attach `evidence[] {url, snippet, source:"tavily"}` to matching claims; create new web-sourced claims for notable finds. Log to `/trace`.

3. **T+1:30 — Outbound connectors (the live wow moment).**
   - `outbound_github.py`: authenticated repo search — topics `llm`, `rag`, `agents`, `inference`, `llm-eval`, `vector-database`, filter `stars:>30 pushed:>2026-05-01`, exclude org-owned/big-co repos; for each hit fetch owner profile (name, location, followers, other repos, commit recency). Map to opportunity (`source: outbound_github`) + claims like "1.2k stars in 6 weeks" (`source: github`, trust `corroborated` — it IS the primary source, confidence 0.95, evidence = repo URL).
   - `outbound_hn.py`: `https://hn.algolia.com/api/v1/search?query=Show HN llm OR agent OR inference&tags=show_hn&numericFilters=points>20` — recent launches; map poster → opportunity + claim ("Show HN, 412 points", evidence = HN item URL).
   - Dedupe: same github handle → same founder; if the founder already exists, add claims to the existing opportunity instead of creating a duplicate (this is the Memory/dedup rubric line).
   - Target output: 3–10 real, current opportunities inserted live. Cap API calls; don't paginate deep.

4. **T+1:55 — Verification pass (`verify.py`).** For every deck-sourced claim in the DB without a trust status: run Tavily, compare, set `corroborated` (external match), `unverified` (nothing found — NOT a failure, honesty is scored), or `contradicted` (conflict) with confidence + note + evidence. Ensure the AgentStack claims come out `contradicted` with the seeded evidence attached. Log every verdict to `/trace`.

## Acceptance criteria (T+2:00)
- [ ] 6–8 seeded opportunities in the DB, including the 4 scripted demo profiles with correct claim/trust setups.
- [ ] `outbound_github.py` run live inserts ≥3 real current AI-infra opportunities with corroborated GitHub claims.
- [ ] Every claim in the DB has a trust status; AgentStack's traction/MRR claims are `contradicted` with evidence URLs.
- [ ] Evidence snippets are real (from Tavily/GitHub/HN responses), never invented; every evidence item has a URL.
- [ ] All sourcing/verification steps appear in trace_log.

## Do NOT
- Scrape LinkedIn or Crunchbase (ToS — the brief says synthesize equivalents instead).
- Invent evidence URLs or snippets. Mark unknown as `unverified` — never guess `corroborated`.
- Burn time on arXiv/Product Hunt (stretch only, skip unless everything else is done).
