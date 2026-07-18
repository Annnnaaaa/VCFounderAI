# VC Brain — Runbook (what remains, in order)

## 0. Pre-flight — do BEFORE the 2h window starts (~15 min, you personally)
1. **Supabase**: create a project → copy Project URL + `service_role` key into `.env` (template in repo root). Enable Storage (default bucket `decks`).
2. **OpenAI**: confirm the credit key works: needs a vision-capable model + structured outputs.
3. **Tavily**: grab API key from app.tavily.com.
4. **GitHub PAT**: github.com/settings/tokens → classic token, scopes `public_repo`, `read:user`.
5. **Lovable**: workspace open, logged in.
6. Fill `.env.template` → save as `.env`; have it ready to paste into each lane.
7. Create the git repo / 4 dirs: `spine/`, `intelligence/`, `sourcing/`, (Lovable is hosted). One repo, lanes never edit each other's dirs.
8. Decide how Lane 1 is reachable by Lovable: easiest = `uvicorn --host 0.0.0.0` + `cloudflared tunnel --url http://localhost:8000` (no account needed) → HTTPS URL.
9. Fake demo assets: 2 one-page PDF "decks" (VectorForge, AgentStack — a title slide + a traction slide with the claims). Any slide tool, 5 min. Needed for the /apply demo.

## 1. Kickoff (T+0) — paste and go
- Claude Code session A ← `kickoff/LANE1-SPINE-claude-code-A.md`
- Claude Code session B ← `kickoff/LANE2-INTELLIGENCE-claude-code-B.md`
- Lovable ← `kickoff/LANE3-UX-lovable.md` (main prompt; follow-ups at bottom of file)
- Session 4 ← `kickoff/LANE4-SOURCING-tavily-worker.md`
- Paste `.env` contents into lanes 1, 2, 4.

## 2. Sync points (you are the integrator)
| Time | Checkpoint |
|---|---|
| T+0:10 | Lane 1 confirms schema created; contract frozen — announce to all |
| T+1:00 | Lane 1 shares `SPINE_URL` → lanes 2 & 4 switch from mocks to API; Lane 4 hands seed JSON to Lane 1 |
| T+1:30 | Lovable follow-up prompt #1 (wire to `API_BASE`); Lane 4 runs outbound live |
| T+1:55 | Lane 2 runs full pipeline on all seeded opportunities; Lane 4 verification pass |
| T+2:00–2:20 | Integration smoke test (below) |

## 3. Smoke test (one pass per demo profile)
1. **VectorForge**: `POST /apply` with deck → Lane 2 processes → detail page shows corroborated claims, healthy 3 axes, memo with citation popovers.
2. **AgentStack**: detail page shows red `contradicted` chips on MRR/traction claims; memo states the contradiction.
3. **Cold-start (Priya)**: cold-start panel shows band medium, interval bar 0.45–0.72, 2 signals, caveat.
4. **Outbound live**: pipeline shows real GitHub/HN-sourced rows; open one → "Draft outreach" modal.
5. **Founder Score persistence**: re-apply as Lena Vogt with a second opportunity → score history shows 2 points, sparkline renders.
6. Reasoning trace timeline visible on a detail page (traceability stretch goal).

## 4. Demo script (~3 min)
Thesis config (10s: "fund lens, everything filters through it") → Pipeline ranked list (outbound rows: "these founders never applied — we found them") → AgentStack contradiction (the trust wow) → Priya cold-start ("honest interval, not fake confidence — this is the rubric's named hard case") → VectorForge memo with citation popovers + gap flags → founder score sparkline ("memory that never resets"). Close on the trace timeline.

## 5. Cut list if behind (in order)
NL query bar → outbound HN (keep GitHub) → outreach draft modal → validator pass → sparkline (keep history in API). **Never cut**: 3 separate axes, per-claim trust with real evidence, cold-start interval, gap-flagged memo, trace log.

## 6. Known gaps I patched vs. your plan
- Brief MVP #4 requires a fast-pass screen before full analysis → added to Lane 2 (cheap viable/non-viable call).
- Brief MVP #3 (NL multi-attribute query) was backlog #5 → added as Lane 2 stretch + UI input already in Lane 3, so a thin version demos if time allows.
- Memo needs a `recommendation` field to satisfy "a decision an investor can act on in 24h" (30% rubric) → added to contract.
- `status` field on opportunities (new/screened/memo_ready/passed) so the funnel Sourcing→Screening→Diligence→Decision is visible in the UI.
