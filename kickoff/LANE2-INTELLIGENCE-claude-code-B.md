# LANE 2 — Claude Code #B: Intelligence / Reasoning (OpenAI strict structured outputs)

Copy-paste everything below this line into Claude Code session B.

---

You are building the **reasoning layer** of "VC Brain" — a 2-hour hackathon MVP (Hack-Nation Challenge 02) that screens pre-seed AI-infra founders and produces evidence-backed memos. Lane 1 owns the DB/API (FastAPI + Supabase); you produce every score, trust verdict, and memo. **Transparency beats confidence: every output carries rationale, evidence refs, and explicit uncertainty.** Rubric weight rides on honest reasoning (55% data+intelligence combined) and the judges' favorite stretch goal is per-step traceability — log everything.

## Stack (locked)
- Python 3.11+, `openai` SDK with **strict structured outputs** (`response_format` with `json_schema`, `strict: true` — NOT legacy JSON mode). Pydantic models mirror the contract below.
- Env: `OPENAI_API_KEY`, `SPINE_URL` (Lane 1 base URL — until it's live, work off local mock JSON files with the same shapes).
- Repo dir: `intelligence/`. Expose your pipeline as `POST /process/{opportunity_id}` (tiny FastAPI app) OR a CLI `python process.py <opportunity_id>` that reads/writes via Lane 1's API. CLI is fine.

## THE SHARED CONTRACT (frozen — your Pydantic models must match exactly)
```jsonc
// claims (Trust Score unit — per claim)
{ "claim_id": "uuid", "opportunity_id": "uuid", "text": "'$2M ARR, 3x YoY'",
  "type": "traction | revenue | team | market | tech", "source": "deck_slide_4 | tavily | github | hn",
  "trust": { "status": "corroborated | unverified | contradicted", "confidence": 0.0,
             "evidence": [ { "url": "", "snippet": "", "source": "tavily" } ], "note": "why" } }

// axis_scores (3 independent axes — NEVER averaged)
{ "opportunity_id": "uuid", "axes": {
    "founder":        { "score": 0, "trend": "up|down|flat", "rationale": "", "evidence_refs": [] },
    "market":         { "rating": "bull|neutral|bear",       "rationale": "", "evidence_refs": [] },
    "idea_vs_market": { "verdict": "survives|needs_pivot",   "rationale": "", "evidence_refs": [] } } }

// cold_start (honest interval, never a fake-confident point)
{ "opportunity_id": "uuid", "is_cold_start": true,
  "founder_quality": { "band": "low|medium|high", "interval": [0.4, 0.7], "signals_used": 2 },
  "signals": [ { "kind": "public_writing|side_project|oss|community|domain_insight", "weight": 0.5, "evidence_ref": "" } ],
  "caveat": "Based on N weak signals; wide interval reflects thin track record." }

// memo
{ "opportunity_id": "uuid", "sections": { "company_snapshot": "", "investment_hypotheses": [], "swot": {},
  "problem_product": "", "traction_kpis": "" }, "gap_flags": ["Cap table: not disclosed"],
  "claim_refs": ["claim_id..."], "recommendation": "invest | pass | needs_call" }

// trace_log — POST one entry to Lane 1 /trace for EVERY step below
{ "opportunity_id": "uuid", "step": "deck_extract | screen | enrich | verify | axis_score | cold_start | validate | memo",
  "detail": "what was concluded and why", "evidence_refs": [], "ts": "iso" }
```

## Your tasks, time-boxed
1. **T+0:20 — Schemas + harness.** Pydantic models for all shapes above; wire one strict-structured-output call end-to-end on a mock row. Model: use the best vision-capable GPT model available on the key.
2. **T+0:50 — Deck extraction.** PDF/PPTX → page images (pdf2image / pptx→pdf→images) → vision call extracting `claims[]`, each tagged `source: "deck_slide_N"`, plus company one_liner/sector/stage. Also a **fast-pass screen**: one cheap call returning `{viable: bool, reason}` against the thesis (pre-seed AI infra) — non-viable rows get `status: passed` and skip the expensive steps.
3. **T+1:15 — Scorers.**
   - **3-axis scorer**: independent calls (or one call, three independent sections) producing founder score 0–100, market bull/neutral/bear, idea_vs_market survives/needs_pivot — each with trend, rationale, and `evidence_refs` pointing at claim_ids/evidence URLs. Never combine into one number.
   - **Per-claim Trust Score**: given a claim + evidence snippets (Lane 4 attaches Tavily results to claims), classify corroborated/unverified/contradicted with confidence + note. A deck claim with zero external support = `unverified`, low confidence. Direct conflict (deck says $30K MRR, web shows 3-week-old repo, no pricing page) = `contradicted`.
4. **T+1:35 — Cold-start scorer + Validator.**
   - Cold-start: when a founder has <3 strong signals (no funding history, no company, thin GitHub), emit band + **interval** + signals list + caveat. Interval width must grow as signals shrink — 2 weak signals ≈ width ≥ 0.25. Never emit a confident point score for a cold-start founder.
   - Validator pass: re-read the generated axis scores + memo against the stored claims; flag any statement not backed by a claim_id/evidence ref as `hallucination_flag` in trace_log.
5. **T+1:55 — Memo generator.** Required sections ONLY: Company snapshot, Investment hypotheses, SWOT, Problem & product, Traction & KPIs. Every factual sentence cites a `claim_id` (inline `[claim:uuid]` markers are fine — the UI turns them into popovers). Missing data → explicit `gap_flags` ("Cap table: not disclosed", "Financials: pre-revenue, none"). Contradicted claims must appear in the memo body with the contradiction stated. End with `recommendation` + a short "what would change my mind" line if time allows.
6. **Stretch (only if ahead) — NL query.** One call translating "technical founder, Berlin, AI infra, no prior VC backing" → Lane 1 filter params `{sector, stage, location, min_founder_score, source}`.

## Acceptance criteria (T+2:00)
- [ ] Given seeded profile "VectorForge" (strong): claims mostly `corroborated`, healthy 3 axes, clean memo, zero unflagged gaps.
- [ ] Given "AgentStack" (seeded contradiction: deck "2,000 paying devs, $30K MRR" vs 3-week-old 40-star repo): the MRR claim is `contradicted` with evidence attached, and the memo states it.
- [ ] Given the cold-start solo builder (120-star repo + one blog post): output is band `medium`, interval ≈ [0.45, 0.72], `signals_used: 2`, caveat present — NOT a point score.
- [ ] Every pipeline step posted a trace_log entry; the bundle shows a readable reasoning chain.
- [ ] All outputs validate against the contract (strict schema = no parse failures).

## Do NOT
- Average the axes. Fabricate financials, cap tables, or evidence URLs. Give cold-start founders confident point scores. Skip trace logging to save time — traceability is the highest-leverage stretch goal per the brief.
