"""Acceptance harness — run after any pipeline change.

    python check.py

Verifies (a) no mock fixture leaked into the live DB, and (b) every artifact in
out/ still validates against the frozen contract.
"""
from __future__ import annotations

import json
import pathlib

import spine
from models import AxisScores, Claim, ColdStart, Memo, TraceLog

MOCK_SLUGS = {"priya", "petpal", "vectorforge", "agentstack"}


def check_no_leak() -> bool:
    if not spine.is_live():
        print("spine not live — skipping leak check")
        return True
    rows = spine.list_opportunities()
    leaked = [r["id"] for r in rows if r["id"] in MOCK_SLUGS]
    leaked += [
        r["id"] for r in rows
        if (r.get("company", {}) or {}).get("name", "").lower() in {"petpal", "priya"}
    ]
    print(f"live opportunities: {len(rows)}")
    print(f"mock leak into live DB: {leaked or 'NONE (ok)'}")
    return not leaked


def check_contract() -> bool:
    n, bad = 0, []
    for d in sorted(pathlib.Path("out").iterdir()):
        if not d.is_dir():
            continue
        for name, M in [("axis_scores", AxisScores), ("cold_start", ColdStart), ("memo", Memo)]:
            p = d / f"{name}.json"
            if p.exists():
                try:
                    M.model_validate(json.loads(p.read_text(encoding="utf-8")))
                    n += 1
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{d.name}/{name}: {e}")
        p = d / "claims.json"
        if p.exists():
            for c in json.loads(p.read_text(encoding="utf-8"))["claims"]:
                try:
                    Claim.model_validate(c)
                    n += 1
                except Exception as e:  # noqa: BLE001
                    bad.append(f"{d.name}/claim: {e}")
        p = d / "trace.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        TraceLog.model_validate(json.loads(line))
                        n += 1
                    except Exception as e:  # noqa: BLE001
                        bad.append(f"{d.name}/trace: {e}")
    print(f"artifacts validated: {n}")
    for b in bad:
        print("  FAIL", b)
    return not bad


def check_cold_start_interval() -> bool:
    """The honesty guarantee: cold-start founders never get a point score, and
    the interval never narrows below the 0.25 floor."""
    ok = True
    for p in pathlib.Path("out").glob("*/cold_start.json"):
        cs = ColdStart.model_validate(json.loads(p.read_text(encoding="utf-8")))
        lo, hi = cs.founder_quality.interval
        width = round(hi - lo, 3)
        good = width >= 0.25
        ok &= good
        print(f"{p.parent.name}: band={cs.founder_quality.band} "
              f"interval=[{lo}, {hi}] width={width} "
              f"signals={cs.founder_quality.signals_used} "
              f"{'ok' if good else 'FAIL (width < 0.25)'}")
    return ok


def check_evidence_preserved() -> bool:
    """Verification must never delete evidence Lane 4 attached.

    Regression guard: the verifier once wrote back only the CITED evidence
    subset, which PATCHed the uncited items out of the DB permanently. Feed a
    claim mixed-relevance evidence and assert every item survives.
    """
    import scorers
    from models import Claim, Evidence, Trust

    ev = [
        Evidence(url="https://github.com/acme/repo",
                 snippet="acme/repo - 12000 stars, active daily commits over 3 years.",
                 source="github"),
        Evidence(url="https://weather.example/forecast",
                 snippet="Cloudy with a chance of rain on Tuesday.", source="tavily"),
        Evidence(url="https://blog.example/unrelated",
                 snippet="A recipe for sourdough bread starter.", source="tavily"),
    ]
    c = Claim(claim_id="guard", opportunity_id="guard",
              text="The project has over 10,000 GitHub stars.", type="traction",
              source="deck_slide_2",
              trust=Trust(status="unverified", confidence=0.0, evidence=ev, note="pending"))
    t = scorers.verify_claim(c, ev)
    ok = len(t.evidence) == len(ev)
    print(f"evidence preservation: {len(ev)} supplied -> {len(t.evidence)} retained "
          f"{'ok' if ok else 'FAIL (evidence destroyed)'}")
    return ok


if __name__ == "__main__":
    results = [check_no_leak(), check_contract(), check_cold_start_interval(),
               check_evidence_preserved()]
    print("\nALL CHECKS PASSED" if all(results) else "\nSOME CHECKS FAILED")
