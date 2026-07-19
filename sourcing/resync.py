"""Rebuild the local store from the live spine — the DB is the source of truth.

The local store is a write-through cache, so a failed live write leaves a row
that exists here but not in the DB. Those ghosts then look real to enrich.py
and verify.py. Run this after any run that reported failed POSTs/PATCHes.

    py resync.py
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import requests

import spine


def main() -> None:
    if not spine.is_live():
        print("[resync] spine is not live — nothing to resync against")
        return

    opps = spine.load_opportunities()
    claims: List[Dict[str, Any]] = []
    failed = 0
    for o in opps:
        try:
            r = requests.get(f"{spine.SPINE_URL}/opportunities/{o['id']}/bundle",
                             timeout=20)
            r.raise_for_status()
            claims.extend(r.json().get("claims") or [])
        except Exception:  # noqa: BLE001
            failed += 1

    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for c in claims:
        cid = c.get("claim_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        unique.append(c)

    before = len(spine._read(spine.CLAIMS_FILE))  # noqa: SLF001 — same package
    spine.OUT_DIR.mkdir(parents=True, exist_ok=True)
    spine.OPPS_FILE.write_text(json.dumps(opps, indent=2, default=str), encoding="utf-8")
    spine.CLAIMS_FILE.write_text(json.dumps(unique, indent=2, default=str),
                                 encoding="utf-8")
    print(f"[resync] opportunities: {len(opps)}")
    print(f"[resync] claims: {before} local -> {len(unique)} from live "
          f"({before - len(unique)} ghosts dropped)")
    if failed:
        print(f"[resync] WARNING: {failed} bundle(s) failed to load; "
              f"their claims are not represented")


if __name__ == "__main__":
    main()
