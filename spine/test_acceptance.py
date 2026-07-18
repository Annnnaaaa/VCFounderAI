"""Acceptance suite for the T+2:00 integration test. Hits a running server.

Run: python test_acceptance.py [base_url]     (default http://localhost:8000)
"""
import base64
import sys
import uuid

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
c = httpx.Client(base_url=BASE, timeout=60)
results: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


# ── 1. POST /apply with just company name + deck ───────────────────────────
print("\n[1] POST /apply — minimum bar is deck + company name")
handle = f"testfounder{uuid.uuid4().hex[:6]}"
r = c.post(
    "/apply",
    json={
        "company_name": "Acceptance Labs",
        "founder_name": "Test Founder",
        "github_handle": handle,
        "sector": "eval & observability",
        "deck_base64": base64.b64encode(b"%PDF-1.4 fake deck bytes").decode(),
        "deck_filename": "deck.pdf",
    },
)
check("POST /apply returns 200", r.status_code == 200, r.text[:200])
opp = r.json()
opp_id = opp.get("id", "")
check("returned row has an id", bool(opp_id), opp_id)
check("status == new", opp.get("status") == "new")
check("source == inbound_apply", opp.get("source") == "inbound_apply")
check("deck persisted", opp.get("deck_present") is True, str(opp.get("deck_url"))[:80])

# a second application, same founder, different company — for the persistence test
r2 = c.post("/apply", json={"company_name": "Second Venture", "github_handle": handle})
opp2_id = r2.json().get("id", "")
check("second opportunity created for same founder", bool(opp2_id))

# ── 2. every contract object, then the bundle ──────────────────────────────
print("\n[2] Write every contract object")
r = c.post(
    "/claims",
    json=[
        {
            "opportunity_id": opp_id,
            "text": "$2M ARR, 3x YoY",
            "type": "revenue",
            "source": "deck_slide_4",
        }
    ],
)
check("POST /claims", r.status_code == 200, r.text[:200])
claim_id = r.json()[0]["claim_id"]

r = c.patch(
    f"/claims/{claim_id}/trust",
    json={
        "trust": {
            "status": "corroborated",
            "confidence": 0.82,
            "evidence": [{"url": "https://example.com/a", "snippet": "…", "source": "tavily"}],
            "note": "two independent sources",
        }
    },
)
check("PATCH /claims/{id}/trust", r.status_code == 200, r.text[:200])
check("trust status stored", r.json()["trust"]["status"] == "corroborated")

r = c.post(
    "/axis-scores",
    json={
        "opportunity_id": opp_id,
        "axes": {
            "founder": {"score": 78, "trend": "up", "rationale": "shipped OSS", "evidence_refs": []},
            "market": {"rating": "bull", "rationale": "inference spend growing", "evidence_refs": []},
            "idea_vs_market": {"verdict": "survives", "rationale": "wedge holds", "evidence_refs": []},
        },
    },
)
check("POST /axis-scores", r.status_code == 200, r.text[:200])

r = c.post(
    "/cold-start",
    json={
        "opportunity_id": opp_id,
        "is_cold_start": True,
        "founder_quality": {"band": "medium", "interval": [0.4, 0.7], "signals_used": 2},
        "signals": [{"kind": "oss", "weight": 0.5, "evidence_ref": "https://github.com/x"}],
        "caveat": "Based on 2 weak signals; wide interval reflects thin track record.",
    },
)
check("POST /cold-start", r.status_code == 200, r.text[:200])

r = c.post(
    "/memos",
    json={
        "opportunity_id": opp_id,
        "sections": {
            "company_snapshot": "Acceptance Labs builds eval harnesses.",
            "investment_hypotheses": ["Evals become a CI primitive"],
            "swot": {"strengths": ["team"], "weaknesses": ["no revenue"]},
            "problem_product": "Agent regressions ship silently.",
            "traction_kpis": "40 design partners",
        },
        "gap_flags": ["Cap table: not disclosed"],
        "claim_refs": [claim_id],
        "recommendation": "needs_call",
    },
)
check("POST /memos", r.status_code == 200, r.text[:200])

r = c.post("/trace", json={"opportunity_id": opp_id, "step": "enrich", "detail": "manual trace"})
check("POST /trace", r.status_code == 200, r.text[:200])

# ── 3. bundle returns every contract object in one payload ─────────────────
print("\n[3] GET /opportunities/{id}/bundle — one call, every object")
b = c.get(f"/opportunities/{opp_id}/bundle").json()
for key in ["opportunity", "claims", "axis_scores", "cold_start", "memo", "founder_score", "trace_log"]:
    check(f"bundle.{key} present", b.get(key) not in (None, []), "")
axes = (b.get("axis_scores") or {}).get("axes", {})
check("bundle axes has all 3, unaveraged", set(axes) == {"founder", "market", "idea_vs_market"}, str(list(axes)))
check("bundle exposes no averaged score field", "overall" not in axes and "average" not in axes)

# ── 4. founder score persists across opportunities ─────────────────────────
print("\n[4] Founder Score — history, trend, cross-opportunity persistence")
identity = f"github:{handle}"
c.post("/founder-score", json={"identity": identity, "value": 60, "reason": "first pass", "opportunity_id": opp_id})
fs = c.post(
    "/founder-score",
    json={"identity": identity, "value": 78, "reason": "shipped OSS", "opportunity_id": opp2_id},
).json()
check("history length == 2", len(fs["history"]) == 2, f"got {len(fs['history'])}")
check("trend == up (60 -> 78)", fs["trend"] == "up", fs["trend"])
check("value == 78", fs["value"] == 78)

got = c.get(f"/founder-score/{identity}").json()
check("GET /founder-score/{identity}", got["identity"] == identity)

# the real test: score survives onto a *different* opportunity id
b2 = c.get(f"/opportunities/{opp2_id}/bundle").json()
check(
    "score persists onto the 2nd opportunity",
    (b2.get("founder_score") or {}).get("value") == 78,
    str((b2.get("founder_score") or {}).get("value")),
)
check("history rides along to 2nd opportunity", len((b2.get("founder_score") or {}).get("history", [])) == 2)

# ── 5. thesis filter ───────────────────────────────────────────────────────
print("\n[5] Thesis filter")
lst = c.get("/opportunities", params={"sector": "eval"}).json()
check("?sector=eval returns rows", len(lst) > 0, f"{len(lst)} rows")
check(
    "every returned row is eval-sector",
    all("eval" in (o.get("company") or {}).get("sector", "").lower() for o in lst),
    str([(o.get("company") or {}).get("sector") for o in lst][:5]),
)
scores = [float(((o.get("axes") or {}).get("founder") or {}).get("score") or (o.get("founder_score") or {}).get("value") or 0) for o in lst]
check("ranked by founder axis score desc", scores == sorted(scores, reverse=True), str(scores[:5]))

filtered = c.get("/opportunities", params={"min_founder_score": 70}).json()
check("min_founder_score filter applies", all(
    float(((o.get("axes") or {}).get("founder") or {}).get("score") or (o.get("founder_score") or {}).get("value") or 0) >= 70
    for o in filtered), f"{len(filtered)} rows")

t = c.get("/thesis").json()
check("GET /thesis has seeded params", bool((t.get("params") or {}).get("sectors")), str(t.get("params"))[:120])
put = c.put("/thesis", json={"params": {**t["params"], "risk_appetite": "high"}})
check("PUT /thesis", put.status_code == 200, put.text[:150])

# ── 6. every write endpoint traced ─────────────────────────────────────────
print("\n[6] Trace coverage")
steps = {e["step"] for e in c.get(f"/opportunities/{opp_id}/bundle").json()["trace_log"]}
for step in ["deck_extract", "verify", "axis_score", "cold_start", "memo"]:
    check(f"trace step '{step}' recorded", step in steps, str(sorted(steps)))

# ── summary ────────────────────────────────────────────────────────────────
failed = [r for r in results if not r[0]]
print(f"\n{'=' * 60}\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILURES:")
    for _, name, detail in failed:
        print(f"  - {name}  {detail}")
sys.exit(1 if failed else 0)
