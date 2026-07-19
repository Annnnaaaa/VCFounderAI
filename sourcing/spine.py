"""Lane 1 (Spine) API client with a local-store fallback.

Until Lane 1 shares a live SPINE_URL (~T+1:00) every write lands in
`out/` as JSON matching the frozen contract exactly; once the API is up the
same calls also POST. Detection is lazy (one /health probe at import), so
switching over is zero-config — rerun any script and it goes live.

The local store doubles as "the DB" for the scripts that need to read back
what earlier steps wrote (verify.py needs every claim; the outbound
connectors need existing founders to dedupe against).

Endpoints (per the Lane 4 kickoff contract):
  POST  {SPINE}/opportunities        bulk insert
  POST  {SPINE}/claims               bulk insert
  PATCH {SPINE}/claims/{id}/trust    set trust verdict
  POST  {SPINE}/trace                one trace_log entry
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests
from dotenv import load_dotenv

# Live repo descriptions and HN titles contain emoji and non-Latin text. The
# Windows console defaults to cp1252, where printing those raises
# UnicodeEncodeError and kills the run — so degrade unencodable characters
# instead of crashing. Every script imports spine, so this covers all of them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # not a reconfigurable stream
        pass

# One shared .env at the repo root, same as the other lanes.
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv()

SPINE_URL = os.getenv("SPINE_URL", "").rstrip("/")
TIMEOUT = 8

_HERE = Path(__file__).parent
OUT_DIR = _HERE / "out"
OPPS_FILE = OUT_DIR / "opportunities.json"
CLAIMS_FILE = OUT_DIR / "claims.json"
TRACE_FILE = OUT_DIR / "trace.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def _probe() -> bool:
    if not SPINE_URL:
        return False
    for path in ("/health", "/opportunities"):
        try:
            requests.get(f"{SPINE_URL}{path}", timeout=2)
            return True
        except Exception:  # noqa: BLE001 — any connection error means not live
            continue
    return False


_LIVE = _probe()

# Set SOURCING_DRY_RUN=1 to exercise a connector end-to-end without writing
# anything — useful while tuning result quality against a shared DB.
DRY_RUN = os.getenv("SOURCING_DRY_RUN", "").strip() in {"1", "true", "yes"}
if DRY_RUN:
    print("[spine] DRY RUN — no writes will be persisted or POSTed")


def is_live() -> bool:
    return _LIVE and not DRY_RUN


# ── local store ────────────────────────────────────────────────────────────

def _read(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, rows: List[Dict[str, Any]]) -> None:
    if DRY_RUN:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")


def load_opportunities() -> List[Dict[str, Any]]:
    """All known opportunities — live API first, local store otherwise."""
    if _LIVE:
        try:
            r = requests.get(f"{SPINE_URL}/opportunities", timeout=TIMEOUT)
            r.raise_for_status()
            rows = r.json()
            if isinstance(rows, dict):
                rows = rows.get("opportunities", [])
            if rows:
                return rows
        except Exception as e:  # noqa: BLE001
            print(f"[spine] GET /opportunities failed ({e}); using local store")
    return _read(OPPS_FILE)


def existing_by_identity() -> Dict[str, Dict[str, Any]]:
    """Index of every known opportunity keyed by founder identity.

    Powers both idempotent re-seeding and the outbound dedupe rule: same
    founder => attach claims to the existing opportunity, never a duplicate row.
    """
    import contract  # local import to avoid a circular import at module load

    index: Dict[str, Dict[str, Any]] = {}
    for o in load_opportunities():
        index.setdefault(contract.founder_identity(o), o)
    return index


def load_claims() -> List[Dict[str, Any]]:
    """Every claim in the DB.

    There is no GET /claims on the spine, so when live we fan out over
    /opportunities/{id}/bundle — which also picks up claims written by other
    lanes (e.g. Lane 2's deck extraction), not just the ones we wrote.
    """
    if _LIVE:
        rows: List[Dict[str, Any]] = []
        ok = False
        for o in load_opportunities():
            try:
                r = requests.get(f"{SPINE_URL}/opportunities/{o['id']}/bundle",
                                 timeout=TIMEOUT)
                r.raise_for_status()
                rows.extend(r.json().get("claims", []) or [])
                ok = True
            except Exception:  # noqa: BLE001 — partial bundles are fine
                continue
        if ok:
            # Merge in anything we hold locally but the API hasn't accepted yet.
            seen = {c.get("claim_id") for c in rows}
            rows.extend(c for c in _read(CLAIMS_FILE) if c["claim_id"] not in seen)
            return rows
        print("[spine] bundle fan-out failed; using local store")
    return _read(CLAIMS_FILE)


# ── writes ─────────────────────────────────────────────────────────────────

def save_opportunities(opps: List[Dict[str, Any]]) -> None:
    """Upsert opportunities by id into the store, then bulk POST if live."""
    existing = {o["id"]: o for o in _read(OPPS_FILE)}
    for o in opps:
        existing[o["id"]] = o
    _write(OPPS_FILE, list(existing.values()))
    if _LIVE and opps:
        try:
            requests.post(f"{SPINE_URL}/opportunities", json=opps,
                          timeout=TIMEOUT).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] POST /opportunities failed ({e}); saved locally only")


def save_claims(claims: List[Dict[str, Any]]) -> None:
    """Upsert claims by claim_id into the store, then bulk POST if live."""
    existing = {c["claim_id"]: c for c in _read(CLAIMS_FILE)}
    for c in claims:
        existing[c["claim_id"]] = c
    _write(CLAIMS_FILE, list(existing.values()))
    if _LIVE and claims:
        try:
            requests.post(f"{SPINE_URL}/claims", json=claims,
                          timeout=TIMEOUT).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] POST /claims failed ({e}); saved locally only")


def patch_claim_trust(claim_id: str, trust: Dict[str, Any],
                      claim: Dict[str, Any] | None = None) -> None:
    """Set one claim's trust verdict (verify.py's and enrich.py's main write).

    Upserts: a 404 means the claim never made it into the DB (an earlier write
    failed), so when the caller supplies the full claim we create it instead of
    silently dropping the verdict.
    """
    rows = _read(CLAIMS_FILE)
    for c in rows:
        if c["claim_id"] == claim_id:
            c["trust"] = trust
            break
    _write(CLAIMS_FILE, rows)
    if not is_live():
        return
    try:
        r = requests.patch(f"{SPINE_URL}/claims/{claim_id}/trust", json=trust,
                           timeout=TIMEOUT)
        if r.status_code == 404 and claim is not None:
            body = dict(claim)
            body["trust"] = trust
            requests.post(f"{SPINE_URL}/claims", json=[body],
                          timeout=TIMEOUT).raise_for_status()
            return
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[spine] trust write failed for {claim_id}: {e}")


def trace(opportunity_id: str, step: str, detail: str,
          evidence_refs: List[str] | None = None) -> None:
    """Append one trace_log entry. Every sourcing/verification step calls this."""
    entry = {
        "opportunity_id": opportunity_id,
        "step": step,
        "detail": detail,
        "evidence_refs": evidence_refs or [],
        "ts": now_iso(),
    }
    if DRY_RUN:
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with TRACE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    if _LIVE:
        try:
            requests.post(f"{SPINE_URL}/trace", json=entry,
                          timeout=TIMEOUT).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] POST /trace failed ({e})")
