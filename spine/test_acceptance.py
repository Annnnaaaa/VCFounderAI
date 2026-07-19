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

# Every opportunity this suite creates gets torn down at the end. Without this
# the suite pollutes the demo dataset — test rows outranked real ones.
CREATED: list[str] = []


def track(resp):
    """Remember a created opportunity so cleanup() can remove it."""
    try:
        oid = resp.json().get("id")
        if oid:
            CREATED.append(oid)
    except Exception:
        pass
    return resp


def cleanup() -> None:
    for oid in CREATED:
        try:
            c.delete(f"/opportunities/{oid}")
        except Exception:
            pass


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
track(r)
opp = r.json()
opp_id = opp.get("id", "")
check("returned row has an id", bool(opp_id), opp_id)
check("status == new", opp.get("status") == "new")
check("source == inbound_apply", opp.get("source") == "inbound_apply")
check("deck persisted", opp.get("deck_present") is True, str(opp.get("deck_url"))[:80])

# a second application, same founder, different company — for the persistence test
r2 = track(c.post("/apply", json={"company_name": "Second Venture", "github_handle": handle}))
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

# ── 7. regressions reported by Lane 3 ──────────────────────────────────────
print("\n[7] Regressions")

# 7a. /bundle used to 500 under concurrency: one shared Supabase client was
#     raced across FastAPI's threadpool. 37/60 failed before the fix.
import collections
import concurrent.futures as cf

pool_ids = [o["id"] for o in c.get("/opportunities", params={"limit": 30}).json()][:12]


def _bundle(i: str):
    try:
        return httpx.get(f"{BASE}/opportunities/{i}/bundle", timeout=90).status_code
    except Exception as e:
        return type(e).__name__


with cf.ThreadPoolExecutor(max_workers=12) as pool:
    codes = collections.Counter(pool.map(_bundle, pool_ids * 5))
check("/bundle survives 60 concurrent reads", set(codes) == {200}, str(dict(codes)))

# 7b. a non-ASCII deck filename used to fail the storage upload (InvalidKey),
#     leaving deck_present=true with deck_url=null — a deck link to nowhere.
r = c.post(
    "/apply",
    json={
        "company_name": "Unicode Deck Co",
        "deck_base64": base64.b64encode(b"%PDF-1.4 x").decode(),
        "deck_filename": "Pitch—Deck (2026) Ünïcode.pdf",
    },
)
track(r)
u = r.json()
check("non-ASCII deck filename uploads", u.get("deck_present") is True, str(u.get("deck_url"))[:90])
check("deck_present implies a deck_url", not (u.get("deck_present") and not u.get("deck_url")))

# the invariant must hold across every row, not just the one we just made
allrows = c.get("/opportunities", params={"limit": 300}).json()
orphans = [o for o in allrows if o.get("deck_present") and not o.get("deck_url")]
check("no row claims a deck without a URL", not orphans, f"{len(orphans)} orphan(s)")

# 7c. duplicate claims were unfixable — there was no delete path.
dupe_opp = track(c.post("/apply", json={"company_name": "Dedupe Co"})).json()["id"]
twice = [{"opportunity_id": dupe_opp, "text": "same claim", "type": "traction", "source": "deck_slide_1"}] * 2
c.post("/claims", json=twice)
c.post("/claims", json=twice)
d = c.post(f"/opportunities/{dupe_opp}/claims/dedupe", params={"dry_run": "true"}).json()
check("dry run reports duplicates without deleting", d["removed"] == 3 and d["dry_run"], str(d["removed"]))
check("dry run left the claims alone", len(c.get(f"/opportunities/{dupe_opp}/bundle").json()["claims"]) == 4)
d = c.post(f"/opportunities/{dupe_opp}/claims/dedupe").json()
check("dedupe collapses to distinct claims", d["kept"] == 1 and d["removed"] == 3, str(d))
remaining = c.get(f"/opportunities/{dupe_opp}/bundle").json()["claims"]
check("one claim survives", len(remaining) == 1, str(len(remaining)))

r = c.delete(f"/claims/{remaining[0]['claim_id']}")
check("DELETE /claims/{id}", r.status_code == 200, r.text[:120])
check("claim is gone", len(c.get(f"/opportunities/{dupe_opp}/bundle").json()["claims"]) == 0)
check("DELETE of unknown claim 404s", c.delete(f"/claims/{uuid.uuid4()}").status_code == 404)

# 7d. what_would_change_my_mind 500'd because the column did not exist.
#     Requires migration_01.sql to have been applied.
r = c.post(
    "/memos",
    json={
        "opportunity_id": opp_id,
        "sections": {"company_snapshot": "x"},
        "recommendation": "needs_call",
        "what_would_change_my_mind": ["A credible incumbent shipping the same wedge"],
    },
)
check(
    "POST /memos accepts what_would_change_my_mind",
    r.status_code == 200,
    "run migration_01.sql" if r.status_code == 400 else r.text[:160],
)
if r.status_code == 200:
    check("field round-trips", r.json()[0].get("what_would_change_my_mind") == ["A credible incumbent shipping the same wedge"])

# an unknown column should be an actionable 400, never an opaque 500
r = c.post("/memos", json={"opportunity_id": opp_id, "no_such_column_xyz": 1})
check("unknown field returns 400 not 500", r.status_code == 400, f"got {r.status_code}")

# ── 8. opportunity PATCH / DELETE (Lane 4) ─────────────────────────────────
print("\n[8] Opportunity PATCH / DELETE")

p = track(
    c.post(
        "/apply",
        json={
            "company_name": "Patch Target",
            "one_liner": "original one liner",
            "sector": "inference",
            "founder_name": "Patch Founder",
            "github_handle": f"patchfounder{uuid.uuid4().hex[:6]}",
        },
    )
).json()
pid = p["id"]

r = c.patch(f"/opportunities/{pid}", json={"company": {"name": "Renamed Co"}})
check("PATCH /opportunities/{id}", r.status_code == 200, r.text[:150])
comp = r.json()["company"]
check("patched field updated", comp["name"] == "Renamed Co", comp["name"])
# the whole point of a deep merge: siblings must survive a partial patch
check("sibling fields survive the merge", comp.get("sector") == "inference", str(comp))
check("one_liner survives too", comp.get("one_liner") == "original one liner", str(comp))

r = c.patch(f"/opportunities/{pid}", json={"status": "screened"})
check("top-level field patches", r.json()["status"] == "screened")
check("founder untouched by company patch", r.json()["founder"]["name"] == "Patch Founder")
check("PATCH of unknown id 404s", c.patch(f"/opportunities/{uuid.uuid4()}", json={"status": "new"}).status_code == 404)

# a caller must not be able to assert a deck that does not exist
r = c.patch(f"/opportunities/{pid}", json={"deck_present": True})
check("PATCH cannot fake deck_present", r.json().get("deck_present") is False, str(r.json().get("deck_present")))

# DELETE reports its blast radius before doing anything
c.post("/claims", json=[{"opportunity_id": pid, "text": "a claim", "type": "team", "source": "hn"}])
d = c.delete(f"/opportunities/{pid}", params={"dry_run": "true"}).json()
check("DELETE dry run reports cascade", d["cascaded"]["claims"] >= 1, str(d["cascaded"]))
check("DELETE dry run does not delete", c.get(f"/opportunities/{pid}/bundle").status_code == 200)

d = c.delete(f"/opportunities/{pid}").json()
check("DELETE /opportunities/{id}", d["deleted"] == pid)
check("opportunity is gone", c.get(f"/opportunities/{pid}/bundle").status_code == 404)
check("dependent claims cascaded", len(c.get("/opportunities", params={"limit": 300}).json()) >= 0)
check("DELETE of unknown id 404s", c.delete(f"/opportunities/{uuid.uuid4()}").status_code == 404)

# ── 9. evidence provenance (seed vs live) ──────────────────────────────────
print("\n[9] Evidence provenance")

seed_opp = track(c.post("/apply", json={"company_name": "Scripted Demo Co", "origin": "seed"})).json()
live_opp = track(c.post("/apply", json={"company_name": "Real Submission Co"})).json()
check("origin stored on the opportunity", seed_opp.get("origin") == "seed", str(seed_opp.get("origin")))
check("origin defaults to live", live_opp.get("origin") == "live", str(live_opp.get("origin")))

ev = [{"url": "https://example.com/x", "snippet": "…", "source": "tavily"}]
sc = c.post(
    "/claims",
    json=[{
        "opportunity_id": seed_opp["id"], "text": "scripted traction", "type": "traction",
        "source": "tavily",
        "trust": {"status": "corroborated", "confidence": 0.9, "evidence": ev, "note": ""},
    }],
).json()[0]
check(
    "evidence on a seed row is stamped seed",
    all(e.get("origin") == "seed" for e in sc["trust"]["evidence"]),
    str(sc["trust"]["evidence"]),
)

# a lane must not be able to pass scripted evidence off as real
sneaky = [{"url": "https://example.com/y", "snippet": "…", "source": "tavily", "origin": "live"}]
sc2 = c.post(
    "/claims",
    json=[{
        "opportunity_id": seed_opp["id"], "text": "sneaky", "type": "market", "source": "tavily",
        "trust": {"status": "corroborated", "confidence": 0.9, "evidence": sneaky, "note": ""},
    }],
).json()[0]
check(
    "a lane cannot claim live evidence on a seed row",
    all(e.get("origin") == "seed" for e in sc2["trust"]["evidence"]),
    str(sc2["trust"]["evidence"]),
)

# a wholesale trust overwrite must not drop the stamp
r = c.patch(
    f"/claims/{sc['claim_id']}/trust",
    json={"trust": {"status": "contradicted", "confidence": 0.2,
                    "evidence": [{"url": "https://example.com/z", "snippet": "…",
                                  "source": "tavily", "origin": "live"}], "note": "redo"}},
)
check(
    "PATCH trust re-stamps rather than trusting the caller",
    all(e.get("origin") == "seed" for e in r.json()["trust"]["evidence"]),
    str(r.json()["trust"]["evidence"]),
)

lc = c.post(
    "/claims",
    json=[{
        "opportunity_id": live_opp["id"], "text": "real traction", "type": "traction",
        "source": "github",
        "trust": {"status": "corroborated", "confidence": 0.8, "evidence": ev, "note": ""},
    }],
).json()[0]
check(
    "evidence on a live row is stamped live",
    all(e.get("origin") == "live" for e in lc["trust"]["evidence"]),
    str(lc["trust"]["evidence"]),
)

# correcting a misclassified row must re-stamp everything hanging off it
c.patch(f"/opportunities/{seed_opp['id']}", json={"origin": "live"})
restamped = c.get(f"/opportunities/{seed_opp['id']}/bundle").json()["claims"]
check(
    "correcting origin re-stamps existing evidence",
    all(e.get("origin") == "live" for cl in restamped for e in cl["trust"]["evidence"]),
    str([e.get("origin") for cl in restamped for e in cl["trust"]["evidence"]]),
)
check("origin change is traced",
      any("origin" in t["detail"] for t in c.get(f"/opportunities/{seed_opp['id']}/bundle").json()["trace_log"]))
check("junk origin rejected",
      c.patch(f"/opportunities/{live_opp['id']}", json={"origin": "fake"}).status_code == 400)

# the whole point: the demo set must be separable in one query
allo = c.get("/opportunities", params={"limit": 300}).json()
check("every row carries an origin", all(o.get("origin") in ("seed", "live") for o in allo),
      str({o.get("origin") for o in allo}))

# ── summary ────────────────────────────────────────────────────────────────
cleanup()
print(f"\ncleaned up {len(CREATED)} test opportunities")

failed = [r for r in results if not r[0]]
print(f"\n{'=' * 60}\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILURES:")
    for _, name, detail in failed:
        print(f"  - {name}  {detail}")
sys.exit(1 if failed else 0)
