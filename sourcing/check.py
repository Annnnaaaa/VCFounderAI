"""Acceptance check for Lane 4 â€” run against the live spine.

Verifies the T+2:00 criteria from the kickoff brief and prints a pass/fail
line per item.

    py check.py
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

import contract as C
import spine

FIXTURE_MARK = "[seed fixture]"


def _pass(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _founder(o: Dict[str, Any]) -> str:
    """Other lanes write rows too, and not all of them fill every field."""
    return ((o.get("founder") or {}).get("name") or "").strip()


def _company(o: Dict[str, Any]) -> str:
    return ((o.get("company") or {}).get("name") or "").strip()


def _trust(c: Dict[str, Any]) -> Dict[str, Any]:
    return c.get("trust") or {}


def _status(c: Dict[str, Any]) -> str:
    return _trust(c).get("status") or "MISSING"


def main() -> None:
    opps = spine.load_opportunities()
    claims = spine.load_claims()
    by_id = {o["id"]: o for o in opps}
    mine = [o for o in opps if o["source"] in
            {"inbound_apply", "outbound_github", "outbound_hn"}]

    print(f"opportunities={len(opps)}  claims={len(claims)}\n")

    # 1 â€” seeded demo profiles
    names = {(_company(o) or _founder(o)) for o in opps}
    scripted = ["VectorForge", "AgentStack", "Priya Nair"]
    found = [n for n in scripted if n in names]
    seeded = [o for o in opps if o["source"] == "inbound_apply"]
    print(f"[{_pass(len(found) == 3)}] scripted demo profiles present: {found}")
    print(f"[{_pass(6 <= len(seeded) <= 20)}] seeded inbound opportunities: {len(seeded)}")

    # 2 â€” outbound live
    gh = [o for o in opps if o["source"] == "outbound_github"]
    hn = [o for o in opps if o["source"] == "outbound_hn"]
    gh_claims = [c for c in claims if c["source"] == "github"
                 and _status(c) == "corroborated"]
    print(f"[{_pass(len(gh) >= 3)}] outbound_github opportunities: {len(gh)} "
          f"(>=3 required)")
    print(f"[{_pass(len(gh_claims) >= 3)}] corroborated github claims: {len(gh_claims)}")
    print(f"[{_pass(len(hn) >= 1)}] outbound_hn opportunities: {len(hn)}")

    # 3 â€” every claim has a trust status
    missing = [c for c in claims if not c.get("trust")
               or _trust(c).get("status") not in C.TRUST_STATUSES]
    pending = [c for c in claims if C.is_pending(c)]
    print(f"[{_pass(not missing)}] every claim has a valid trust status "
          f"(missing={len(missing)})")
    print(f"[{_pass(not pending)}] no claims left pending verification "
          f"(pending={len(pending)})")

    # AgentStack contradictions
    agent = next((o for o in opps if _company(o) == "AgentStack"), None)
    if agent:
        ac = [c for c in claims if c["opportunity_id"] == agent["id"]]
        contra = [c for c in ac if _status(c) == "contradicted"]
        with_urls = [c for c in contra
                     if all(e.get("url") for e in (_trust(c).get("evidence") or []))
                     and (_trust(c).get("evidence") or [])]
        print(f"[{_pass(len(contra) >= 2 and len(with_urls) == len(contra))}] "
              f"AgentStack contradicted claims: {len(contra)} "
              f"(all with evidence URLs: {len(with_urls)})")
    else:
        print("[FAIL] AgentStack not found")

    # Priya cold-start signals
    priya = next((o for o in opps if _founder(o) == "Priya Nair"), None)
    if priya:
        pc = [c for c in claims if c["opportunity_id"] == priya["id"]]
        print(f"[{_pass(len(pc) == 2)}] Priya Nair cold-start signals: {len(pc)} "
              f"(exactly 2 required)")
    else:
        print("[FAIL] Priya Nair not found")

    # 4 â€” evidence integrity
    bad_ev = []
    for c in claims:
        for e in _trust(c).get("evidence", []) or []:
            if not e.get("url") or not e.get("snippet"):
                bad_ev.append(c["claim_id"])
    print(f"[{_pass(not bad_ev)}] every evidence item has a URL and snippet "
          f"(bad={len(bad_ev)})")

    # Real vs scripted evidence split
    live_ev = sum(1 for c in claims for e in (_trust(c).get("evidence") or [])
                  if not str(_trust(c).get("note", "")).startswith(FIXTURE_MARK))
    fixture_ev = sum(1 for c in claims for e in (_trust(c).get("evidence") or [])
                     if str(_trust(c).get("note", "")).startswith(FIXTURE_MARK))
    print(f"       evidence items: {live_ev} from live APIs, "
          f"{fixture_ev} scripted seed fixtures")

    # 5 â€” trace log
    traces: List[Dict[str, Any]] = []
    if spine.TRACE_FILE.exists():
        traces = [json.loads(l) for l in
                  spine.TRACE_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    steps = Counter(t["step"] for t in traces)
    covered = {t["opportunity_id"] for t in traces}
    print(f"[{_pass(len(traces) > 0)}] trace_log entries: {len(traces)} {dict(steps)} "
          f"across {len(covered)} opportunities")

    print(f"\nstatus mix: {dict(Counter(_status(c) for c in claims))}")
    print(f"source mix: {dict(Counter(o['source'] for o in opps))}")
    print(f"spine live={spine.is_live()} url={spine.SPINE_URL}")


if __name__ == "__main__":
    main()

