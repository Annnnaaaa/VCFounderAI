# Hackathon Submission — VCFounderAI (copy-paste answers)

## Short Description *

VCFounderAI is a thesis-aware diligence brain for pre-seed AI-infrastructure investors. It ingests inbound applications (pitch deck PDFs) and proactively sources founders from GitHub and Hacker News, then breaks every opportunity into three separate axes — founder, market, idea-vs-market — with claim-level trust verdicts, cited evidence, honest cold-start intervals, and a gap-flagged IC memo with a recommendation an investor can act on in 24 hours. No averaged scores, no black boxes: every reasoning step is logged in a visible trace.

## 1. Problem & Challenge *

Pre-seed diligence is broken in three ways. **Noise:** funds drown in inbound decks while the best technical founders never apply at all. **Vanity scoring:** tools collapse a company into one blended number that hides *why* — and hides what the model doesn't actually know. **Unverified claims:** decks say "$30K MRR" and "2,000 paying developers", and nobody checks before the partner meeting. The hardest case is the cold-start founder — a solo builder with no company, no deck, and a thin public track record — where most systems either fake confidence or ignore them entirely.

## 2. Target Audience *

Pre-seed and seed VC funds writing fast, small checks (our reference thesis: pre-seed AI infra, $100K, 5–8% ownership, high risk) — specifically the analyst/GP who has to turn a ranked pipeline into a defensible investment memo in 24 hours. Secondary: angels and scouts who want outbound founder discovery, and founders themselves, who get evaluated on verifiable evidence instead of pitch polish.

## 3. Solution & Core Features *

- **Thesis-first pipeline:** the fund thesis is a live config; screening and ranking re-run through it — change the lens, the pipeline re-ranks.
- **Deck ingestion:** `POST /apply` takes a PDF; a vision model extracts claims tagged to their exact slide (`deck_slide_4`).
- **Outbound sourcing:** workers scan GitHub and Hacker News for founder-shaped signals and push them into the same pipeline — founders who never applied.
- **Per-claim Trust Score:** every claim is verified against gathered evidence and chipped `corroborated` / `unverified` / `contradicted`, with source snippet, URL, and confidence. Our demo catches a deck claiming $30K MRR with no purchasable product live.
- **Three separate axes** (founder / market / idea-vs-market) — never averaged, each with rationale, trend, and evidence refs.
- **Cold-start honesty:** thin-track-record founders get a band + interval (e.g. "MEDIUM, 0.36–0.64, 3 weak signals"), never a fake point score.
- **Cited IC memo:** five sections, inline `[claim:id]` citations, amber gap flags ("Cap table: not disclosed"), and an invest / pass / needs-call recommendation.
- **Founder memory:** scores persist per founder identity across applications — a sparkline that never resets.
- **Full reasoning trace:** every pipeline step writes a trace row; the detail page shows the entire timeline (deck_extract → screen → verify → axis_score → cold_start → memo → validate).

## 4. Unique Selling Proposition (USP) *

**Trust is engineered, not prompted.** Where competitors output one blended score from one LLM call, VCFounderAI enforces its epistemic guarantees *in code*: the three axes are never averaged (no combined field exists in the schema — a DB-level rule); the trust verifier cites evidence **by index**, so it cannot invent a URL; the cold-start interval width is set by code based on signal count — a prompt cannot talk the system into false confidence; and a validator pass flags any memo statement without claim backing as a hallucination. Add persistent founder memory across applications and a fully visible reasoning trace, and you get the only diligence tool whose answer to "why?" is auditable end to end.

## 5. Implementation & Technology *

Four independent lanes against one frozen API contract, built in parallel:

- **Spine (`spine/`):** FastAPI + Supabase (Postgres + Storage for deck PDFs), deployed on Render. Owns the contract: opportunities, claims, trust patches, axis scores, cold-start, memos, founder-score history, trace log, thesis config. Bulk upserts, claim dedupe, and derived fields enforced by DB constraints.
- **Intelligence (`inteligence/`):** Python pipeline — `deck_extract → screen → verify → axis_score → cold_start → memo → validate`. OpenAI GPT-4o (vision for deck extraction, structured outputs everywhere via Pydantic `response_format` with `strict: true` — zero defensive JSON parsing). PyMuPDF renders decks for the vision call. Cheap-model fast-pass screening against the live thesis.
- **Sourcing (`sourcing/`):** Tavily + GitHub + Hacker News workers that discover founders, attach evidence to claims, and post seed rows through the same API.
- **UX:** React app built in Lovable at vcfounderai.amiracle.net — pipeline table, three-axis detail page, claims & trust chips, cold-start interval bar, cited memo view, reasoning-trace timeline. Swapping mock → live API was a one-constant change.

## 6. Results & Impact *

A fully live system: 37 real opportunities in the deployed pipeline, most sourced autonomously from GitHub/HN — founders who never applied. End-to-end runs produce memos with 10+ resolvable citations and 2+ gap flags per company; the trace timeline for one opportunity shows 79 auditable steps. The system correctly corroborates real traction (a Show HN front-page launch) while catching a seeded fraudulent deck — "$30K MRR" contradicted at 0.8 confidence because no pricing page exists. Cold-start founders get honest intervals instead of rejection. For a fund, this compresses days of manual diligence into minutes while *increasing* auditability — every number on screen can be clicked back to its evidence.

## What was your most fun moment during the hackathon? *

Our verifier suddenly marked every GitHub-sourced founder's "actively maintained" claim as CONTRADICTED at 1.0 confidence. The model had looked at 2026 commit dates, decided they were "in the future", and concluded the entire pipeline was lying to it. A wall of red chips — burying the one *real* contradiction our demo depends on. The fix was telling the model today's date and to trust it over its intuition. There was something delightful about debugging an AI that was so confidently skeptical of reality itself — it felt like arguing with a time traveler.

## Additional Information (Optional)

Built as four parallel lanes (two Claude Code sessions, a Lovable session, and a sourcing worker) coordinated only through a frozen REST contract — the lanes never edited each other's directories. The repo's `RUNBOOK.md` and `kickoff/` directory contain the full parallelization plan. Honest-by-design rules we committed to and kept: no combined score exists anywhere in the schema or UI; trust is per-claim, never per-company; cold start reports a band + interval, never a point; every write endpoint auto-logs a trace row.

## Live Project URL *

https://vcfounderai.amiracle.net

## GitHub Repository URL *

https://github.com/Annnnaaaa/VCFounderAI

## Technologies/Tags

React, TypeScript, Python, FastAPI, Supabase, PostgreSQL, OpenAI GPT-4o, Tavily, PyMuPDF, Render, Lovable

## Additional Tags

multi-agent, structured-outputs, evidence-citation, trust-score, cold-start, investment-memo, agentic-traceability, deck-parsing, vc-tooling

---

# Tech Video (60 sec)

## Script (~140 words — rehearse to hit 55 s)

| Time | Visual | Voiceover |
|---|---|---|
| 0–8 s | Architecture diagram (full) | "VCFounderAI is a diligence engine for pre-seed investors — four services built in parallel around one frozen REST contract." |
| 8–22 s | Zoom left/bottom of diagram | "Sourcing workers scan GitHub and Hacker News for founders who never applied. Inbound decks hit /apply, where GPT-4o vision extracts claims slide by slide. Everything lands in a FastAPI spine backed by Supabase." |
| 22–40 s | Zoom right of diagram (pipeline chain) | "The intelligence pipeline verifies every claim against evidence — citing it by index, so it can't invent a URL — then scores three separate axes that are never averaged. Cold-start founders get an interval whose width is set in code, not by the model. These guarantees are engineered, not prompted." |
| 40–55 s | Live app: AgentStack contradiction → trace timeline | "Here it catches a deck claiming thirty-K MRR — contradicted, no pricing page exists. And every step is auditable in the reasoning trace." |
| 55–60 s | Pipeline page | "VCFounderAI — diligence at the speed of thought." |

## Recording tips

1. **Tool:** OBS Studio (free) or Loom. Record at 1080p, screen + mic.
2. **Two scenes:** open `architecture.svg` full-screen in a browser (Ctrl+scroll to zoom into regions on cue), and a second browser window with the live app pre-loaded on the AgentStack detail page (contradicted chips visible) and the trace expanded.
3. **Rehearse the script aloud twice** before recording — 60 s is unforgiving; cut words, not content. Speak ~10% slower than feels natural.
4. Record audio and screen in one take if possible; if not, record the screen actions silently, then narrate over it in an editor (Clipchamp is preinstalled on Windows).
5. Kill notifications (Win+A → focus assist), hide bookmarks bar, 100% browser zoom.
6. Do 2–3 full takes and keep the calmest one.

## Pre-submission checklist (from the earlier gap review)

- [ ] Run `POST /opportunities/{id}/claims/dedupe` on VectorForge (duplicate claim visible).
- [ ] Delete test rows (Acceptance Labs ×4, Second Venture ×4, "Lane2 Wiring Test", Dedupe Co, Unicode Deck Co) so the public pipeline looks clean.
- [ ] `python process.py --all` so no row shows score 0 / status `new`.
- [ ] If time: paste Lovable prompt #1 (Apply page) — the video doesn't need it, but judges clicking around might.
