# LANE 3 — Lovable: Investor Experience

Copy-paste everything below this line as the Lovable prompt. (Lovable works best with one rich initial prompt + short follow-ups per screen — the follow-up prompts are at the bottom.)

---

Build **"VC Brain"** — an investor dashboard for a pre-seed AI-infrastructure fund writing $100K checks in 24 hours. Target feel: **Notion-level approachability, Bloomberg-level analytical depth.** Clean, dense but calm; dark-on-light; generous whitespace; no dashboard clichés.

Start fully working against the MOCK DATA below (keep it in a `mockData.ts` file), with a single `API_BASE` constant so we can swap to the real REST API later by changing one line.

## Screens

### 1. Thesis Config (settings page)
Form: sectors (multi-select chips: inference, agent frameworks, vector/data tooling, eval & observability), stage (pre-seed default), geography (global), check size ($100K fixed display), ownership target (5–8% slider), risk appetite (low/med/high). Save button → persists (mock for now). Show a one-line summary banner of the active thesis on every other page: "Pre-seed AI infra · global · $100K · 5–8% · high risk".

### 2. Pipeline (home)
Ranked table of opportunities filtered through the thesis. Columns: company, one-liner, founder (with source badge: Inbound / GitHub / HN), sector, **Founder Score badge with tiny sparkline** (history), 3-axis mini-summary (three separate cells: Founder 0–100, Market bull/neutral/bear icon, Idea survives/needs-pivot icon), status, created. **Never show a single combined/average score anywhere.** Row click → detail page. Top bar: natural-language query input (placeholder: "technical founder, Berlin, AI infra, no prior VC backing") — for now it filters mock data by keyword; will call the API later.

### 3. Opportunity Detail
- Header: company, one-liner, founder + handles, source badge, Founder Score badge + sparkline (persistent across applications — show history tooltip "82 → 85, updated after Show HN launch").
- **Three separate axis cards side by side** (Founder / Market / Idea-vs-Market) — each with its score/rating/verdict, a trend arrow (improving/declining/stable), rationale text, and linked evidence chips. Explicit design rule: these are NEVER visually merged or averaged into one number.
- **Claims & Trust panel**: list of claims, each with a status chip — `corroborated` (green + check icon), `unverified` (gray + question icon), `contradicted` (red + alert icon). Color is never the only signal — always icon + label. Click a claim → popover with evidence: source snippet, URL (external link), confidence bar, and note.
- **Cold-start panel** (renders only when `is_cold_start: true`): headline "Founder quality: MEDIUM — interval 0.45–0.72, based on 2 weak signals", an interval bar visual (not a point), the signals list (kind + weight + evidence link), and the caveat sentence in muted text. This panel is a differentiator — make it beautiful and honest, not apologetic.
- **Reasoning trace** (collapsible timeline): trace_log steps in order — deck_extract → enrich → verify → axis_score → cold_start → memo — each with its detail line. This is our "agentic traceability" stretch goal, keep it visible.

### 4. Memo View
Rendered memo with sections: Company snapshot, Investment hypotheses, SWOT (2×2 grid), Problem & product, Traction & KPIs. Inline citation markers `[claim:id]` render as small superscript chips → click opens the same evidence popover (snippet + URL + confidence). **Gap flags** render as amber callouts: "⚠ Cap table: not disclosed". Contradicted claims referenced in the memo get the red icon treatment inline. Footer: recommendation banner (invest / pass / needs call) + "Draft outreach" button for outbound-sourced opportunities (opens a modal with a pre-filled friendly email, mock text fine).

## Mock data (use exactly these shapes — they are the API contract)
```ts
export const opportunities = [
 { id: "opp-1", source: "inbound_apply",
   founder: { name: "Lena Vogt", handles: { github: "lvogt", twitter: "", linkedin: "" }, location: "Berlin" },
   company: { name: "VectorForge", one_liner: "Sub-ms vector search for on-prem LLM stacks", sector: "vector/data tooling", stage: "pre-seed" },
   deck_present: true, status: "memo_ready", created_at: "2026-07-18T10:00:00Z",
   founder_score: { value: 85, confidence: 0.8, trend: "up", history: [{v:82,ts:"2026-06-01"},{v:85,ts:"2026-07-18"}] } },
 { id: "opp-2", source: "inbound_apply",
   founder: { name: "Marc Idris", handles: { github: "midris", twitter: "", linkedin: "" }, location: "Austin" },
   company: { name: "AgentStack", one_liner: "Drop-in agent orchestration for enterprises", sector: "agent frameworks", stage: "pre-seed" },
   deck_present: true, status: "memo_ready", created_at: "2026-07-18T11:00:00Z",
   founder_score: { value: 41, confidence: 0.6, trend: "down", history: [{v:55,ts:"2026-06-10"},{v:41,ts:"2026-07-18"}] } },
 { id: "opp-3", source: "inbound_apply",
   founder: { name: "Priya Nair", handles: { github: "pnair-dev", twitter: "", linkedin: "" }, location: "remote" },
   company: { name: "(no company yet)", one_liner: "LLM eval tooling — solo builder", sector: "eval & observability", stage: "pre-seed" },
   deck_present: false, status: "screened", created_at: "2026-07-18T12:00:00Z",
   founder_score: { value: 58, confidence: 0.4, trend: "flat", history: [{v:58,ts:"2026-07-18"}] } },
 { id: "opp-4", source: "outbound_github",
   founder: { name: "Tomas Ruiz", handles: { github: "truiz", twitter: "", linkedin: "" }, location: "Madrid" },
   company: { name: "TraceRAG", one_liner: "RAG observability, OSS, 1.2k stars in 6 weeks", sector: "eval & observability", stage: "pre-seed" },
   deck_present: false, status: "new", created_at: "2026-07-19T08:00:00Z",
   founder_score: { value: 74, confidence: 0.65, trend: "up", history: [{v:74,ts:"2026-07-19"}] } }
];

// Example claims for opp-2 (the contradiction demo):
export const claims = [
 { claim_id: "c-21", opportunity_id: "opp-2", text: "2,000 paying developers", type: "traction", source: "deck_slide_4",
   trust: { status: "contradicted", confidence: 0.85,
     evidence: [{ url: "https://github.com/midris/agentstack", snippet: "Repo created 3 weeks ago, 40 stars, no releases", source: "github" }],
     note: "Repo age and adoption inconsistent with claimed paid user base; no pricing page found." } },
 { claim_id: "c-22", opportunity_id: "opp-2", text: "$30K MRR", type: "revenue", source: "deck_slide_5",
   trust: { status: "contradicted", confidence: 0.8, evidence: [{ url: "https://agentstack.dev", snippet: "No pricing or signup page live", source: "tavily" }], note: "No purchasable product found." } },
 { claim_id: "c-11", opportunity_id: "opp-1", text: "800 GitHub stars, Show HN front page", type: "traction", source: "deck_slide_3",
   trust: { status: "corroborated", confidence: 0.95, evidence: [{ url: "https://news.ycombinator.com/item?id=XXXX", snippet: "Show HN: VectorForge — 412 points", source: "hn" }], note: "Matches public record." } }
];

// axis_scores, cold_start (opp-3), memo (opp-1, opp-2), trace_log: follow the same contract —
// axes = { founder:{score,trend,rationale,evidence_refs}, market:{rating,...}, idea_vs_market:{verdict,...} }
// cold_start = { is_cold_start:true, founder_quality:{band:"medium",interval:[0.45,0.72],signals_used:2},
//   signals:[{kind:"oss",weight:0.6,evidence_ref:"github repo 120 stars"},{kind:"public_writing",weight:0.5,evidence_ref:"blog: eval methodology"}],
//   caveat:"Based on 2 weak signals; wide interval reflects thin track record." }
// memo = { sections:{company_snapshot, investment_hypotheses[], swot{}, problem_product, traction_kpis},
//   gap_flags:["Cap table: not disclosed","Financials: pre-revenue"], claim_refs:[], recommendation:"invest|pass|needs_call" }
```
Generate plausible mock rows for the remaining objects following those comments.

## Later follow-up prompts (paste one at a time as needed)
1. "Wire the app to a REST API at `API_BASE`: `GET /opportunities?sector=&source=`, `GET /opportunities/{id}/bundle` (returns opportunity+claims+axis_scores+cold_start+memo+founder_score+trace_log in one payload), `GET/PUT /thesis`. Keep mock data as fallback when the fetch fails."
2. "Add an 'Apply' page: company name + optional deck upload + optional GitHub handle → `POST API_BASE/apply`. Keep the form minimal — deck + name is the whole bar."

## Acceptance criteria
- [ ] All four screens work on mock data with zero console errors.
- [ ] Three axis cards are visually separate; no combined score exists anywhere in the UI.
- [ ] Claim chips use icon + label + color (accessible, never color-only); evidence popover shows snippet, URL, confidence.
- [ ] Cold-start panel shows a band + interval bar + signals + caveat, not a point score.
- [ ] Memo shows citation chips and amber gap-flag callouts.
- [ ] API swap requires changing only `API_BASE`.
