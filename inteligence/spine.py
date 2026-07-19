"""Lane 1 (Spine) API client — wired to the live contract, with mock fallback.

Live endpoints (verified against https://vcbrain-spine.onrender.com):
  GET   /health
  GET   /thesis                          -> fund lens (drives the screen prompt)
  GET   /opportunities/{id}/bundle       -> {opportunity, claims, axis_scores, cold_start, memo}
  POST  /opportunities                   -> UPSERT (full object! see set_status)
  POST  /claims                          -> creates one claim, RETURNS server claim_id
  PATCH /claims/{claim_id}/trust         -> attach a Trust verdict
  POST  /axis-scores | /cold-start | /memos | /trace | /founder-score

Two live behaviors that shape the pipeline:
  1. The server assigns claim_ids. We push claims BEFORE scoring so every
     citation references an id that actually exists in Lane 1's DB.
  2. POST /opportunities is a full upsert, not a patch — a partial body wipes
     founder/deck_url. set_status() re-sends the preserved record.
  3. Status auto-advances to memo_ready when a memo is posted; we only set
     status explicitly for the screened-out ("passed") path.

Without a reachable SPINE_URL we read `mocks/<id>.json` and write to `out/<id>/`.
Artifacts are ALWAYS written locally too, so the demo bundle stays inspectable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# Load the shared repo-root .env before reading SPINE_URL (import order matters:
# spine may be imported before llm, which also calls load_dotenv).
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv()

SPINE_URL = os.getenv("SPINE_URL", "").rstrip("/")
_HERE = Path(__file__).parent
MOCK_DIR = _HERE / "mocks"
OUT_DIR = _HERE / "out"
TIMEOUT = 45  # Render free tier can cold-start slowly


def _api_up() -> bool:
    if not SPINE_URL or SPINE_URL.startswith("http://localhost"):
        if not SPINE_URL:
            return False
    try:
        r = requests.get(f"{SPINE_URL}/health", timeout=TIMEOUT)
        return r.ok
    except Exception:
        return False


_LIVE = _api_up()


def is_live() -> bool:
    return _LIVE


# Ids that resolved from mocks/ rather than the API. Their artifacts must never
# be written to the live DB — the fixtures use readable slugs ("priya"), not
# uuids, and would pollute the real pipeline. Populated by get_opportunity().
_MOCK_IDS: set[str] = set()


def _writes_live(opportunity_id: str | None) -> bool:
    return _LIVE and opportunity_id is not None and opportunity_id not in _MOCK_IDS


def _out_path(opportunity_id: str, name: str) -> Path:
    d = OUT_DIR / opportunity_id
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def _write_local(opportunity_id: str, name: str, payload: Any) -> None:
    _out_path(opportunity_id, name).write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )


# ───────────────────────────────── thesis ───────────────────────────────────
_DEFAULT_THESIS = {
    "stage": "pre-seed",
    "domain": "AI infrastructure",
    "sectors": ["inference", "agent frameworks", "vector/data tooling", "eval & observability"],
    "geo": "global",
    "revenue": "pre-revenue",
}


def get_thesis() -> Dict[str, Any]:
    """The fund lens. Everything filters through it — the screen prompt reads
    this live rather than hardcoding the thesis."""
    if _LIVE:
        try:
            r = requests.get(f"{SPINE_URL}/thesis", timeout=TIMEOUT)
            r.raise_for_status()
            return r.json().get("params", _DEFAULT_THESIS)
        except Exception as e:  # noqa: BLE001
            print(f"[spine] thesis GET failed ({e}); using default lens")
    return _DEFAULT_THESIS


# ─────────────────────────────── read side ──────────────────────────────────
def _adapt_bundle(b: Dict[str, Any]) -> Dict[str, Any]:
    """Live bundle (nested) -> the flat shape the pipeline consumes."""
    opp = b.get("opportunity", {})
    company = opp.get("company", {}) or {}
    founder = opp.get("founder", {}) or {}
    handles = founder.get("handles", {}) or {}
    fs = opp.get("founder_score", {}) or {}
    history = fs.get("history", []) or []

    handle_str = ", ".join(f"{k}:{v}" for k, v in handles.items() if v) or "none public"
    founder_ctx = (
        f"Founder: {founder.get('name') or 'undisclosed'}. "
        f"Location: {founder.get('location') or 'undisclosed'}. "
        f"Handles: {handle_str}. "
        f"Company: {company.get('name','')} — {company.get('one_liner','') or 'no one-liner given'}. "
        f"Prior founder-score history points: {len(history)}"
        + (f" (latest {fs.get('value')})" if history else " (none — no track record on file)")
    )

    # NOTE: cold-start is NOT derived from founder_score history — that history
    # includes scores WE wrote, so a second run would silently mark a cold-start
    # founder as established. The real determination happens post-verification
    # in process.py, from external signal strength. We only pass the raw inputs.
    return {
        "opportunity_id": opp.get("id"),
        "company_name": company.get("name", ""),
        "one_liner": company.get("one_liner", "") or company.get("name", ""),
        "sector": company.get("sector", ""),
        "stage": company.get("stage", ""),
        "deck_url": opp.get("deck_url"),
        "founder_identity": founder.get("identity"),
        "founder_ctx": founder_ctx,
        "founder_handles": {k: v for k, v in handles.items() if v},
        "external_history_points": len(history),
        "claims": b.get("claims", []) or [],
        "_raw_opportunity": opp,  # preserved so set_status can upsert safely
    }


def get_opportunity(opportunity_id: str) -> Dict[str, Any]:
    if _LIVE:
        try:
            r = requests.get(
                f"{SPINE_URL}/opportunities/{opportunity_id}/bundle", timeout=TIMEOUT
            )
            r.raise_for_status()
            return _adapt_bundle(r.json())
        except Exception as e:  # noqa: BLE001
            print(f"[spine] live bundle GET failed ({e}); falling back to mock")
    path = MOCK_DIR / f"{opportunity_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No live bundle and no mock at {path}. "
            f"Available mocks: {[p.stem for p in MOCK_DIR.glob('*.json')]}"
        )
    _MOCK_IDS.add(opportunity_id)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    _MOCK_IDS.add(bundle.get("opportunity_id", opportunity_id))
    return bundle


def list_opportunities() -> List[Dict[str, Any]]:
    if not _LIVE:
        return []
    try:
        r = requests.get(f"{SPINE_URL}/opportunities", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[spine] list failed ({e})")
        return []


def fetch_deck(deck_url: str) -> bytes:
    r = requests.get(deck_url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.content


# ─────────────────────────────── write side ─────────────────────────────────
def push_claims(
    opportunity_id: str, claims: List[dict], already_persisted: bool = False
) -> List[dict]:
    """POST each claim; return the claims carrying SERVER-assigned claim_ids so
    downstream citations reference ids that exist in Lane 1's DB.

    `already_persisted=True` means these claims came back from the bundle and
    already live in Lane 1 — re-POSTing them would duplicate every row (there
    is no DELETE endpoint to undo that), so we keep their existing ids and let
    the caller PATCH trust onto them instead."""
    _write_local(opportunity_id, "claims.json", {"opportunity_id": opportunity_id, "claims": claims})
    if not _writes_live(opportunity_id) or already_persisted:
        return claims
    out: List[dict] = []
    for c in claims:
        body = {k: v for k, v in c.items() if k != "claim_id"}
        body["opportunity_id"] = opportunity_id
        try:
            r = requests.post(f"{SPINE_URL}/claims", json=body, timeout=TIMEOUT)
            r.raise_for_status()
            created = r.json()
            created = created[0] if isinstance(created, list) else created
            out.append(created)
        except Exception as e:  # noqa: BLE001
            print(f"[spine] claim POST failed ({e}); keeping local id")
            out.append(c)
    _write_local(opportunity_id, "claims.json", {"opportunity_id": opportunity_id, "claims": out})
    return out


def patch_trust(claim_id: str, trust: dict, opportunity_id: str | None = None) -> None:
    if not _writes_live(opportunity_id or claim_id):
        return
    try:
        requests.patch(
            f"{SPINE_URL}/claims/{claim_id}/trust", json=trust, timeout=TIMEOUT
        ).raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[spine] trust PATCH {claim_id} failed ({e})")


def save_claims_local(opportunity_id: str, claims: List[dict]) -> None:
    _write_local(opportunity_id, "claims.json", {"opportunity_id": opportunity_id, "claims": claims})


def _post(path: str, payload: dict, out_name: str) -> None:
    oid = payload.get("opportunity_id")
    if oid:
        _write_local(oid, out_name, payload)
    if _writes_live(oid):
        try:
            requests.post(f"{SPINE_URL}{path}", json=payload, timeout=TIMEOUT).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] POST {path} failed ({e}); saved locally only")


def save_axis_scores(payload: dict) -> None:
    _post("/axis-scores", payload, "axis_scores.json")


def save_cold_start(payload: dict) -> None:
    _post("/cold-start", payload, "cold_start.json")


# Lane 1's memos table has no column for this yet, and posting it 500s. We keep
# it in the local artifact + the contract; strip it on the wire until Lane 1
# adds the column (see README "Open integration asks").
_MEMO_FIELDS_LANE1_REJECTS = {"what_would_change_my_mind"}


def save_memo(payload: dict) -> None:
    """Posting a memo auto-advances opportunity status to memo_ready."""
    oid = payload.get("opportunity_id")
    if oid:
        _write_local(oid, "memo.json", payload)  # full memo, incl. stripped field
    if _writes_live(oid):
        wire = {k: v for k, v in payload.items() if k not in _MEMO_FIELDS_LANE1_REJECTS}
        try:
            requests.post(f"{SPINE_URL}/memos", json=wire, timeout=TIMEOUT).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] POST /memos failed ({e}); saved locally only")


def push_founder_score(
    identity: Optional[str], value: int, confidence: float, reason: str, opportunity_id: str
) -> None:
    """Feed the founder axis into Lane 1's persistent founder score so the
    detail page's score history / sparkline accumulates across opportunities."""
    if not _writes_live(opportunity_id) or not identity:
        return
    try:
        requests.post(
            f"{SPINE_URL}/founder-score",
            json={
                "identity": identity,
                "value": value,
                "confidence": confidence,
                "reason": reason,
                "opportunity_id": opportunity_id,
            },
            timeout=TIMEOUT,
        ).raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[spine] founder-score POST failed ({e})")


def set_status(opportunity_id: str, status: str, raw_opportunity: dict | None = None) -> None:
    """POST /opportunities is a FULL UPSERT — a partial body wipes founder and
    deck_url. Re-send the preserved record with only status changed."""
    _write_local(opportunity_id, "status.json", {"opportunity_id": opportunity_id, "status": status})
    if not _writes_live(opportunity_id):
        return
    body = dict(raw_opportunity or {})
    body["id"] = opportunity_id
    body["status"] = status
    body.pop("created_at", None)
    body.pop("founder_score", None)  # server-owned, don't clobber history
    try:
        requests.post(f"{SPINE_URL}/opportunities", json=body, timeout=TIMEOUT).raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"[spine] status upsert failed ({e})")


def post_trace(entry: dict) -> None:
    oid = entry["opportunity_id"]
    with _out_path(oid, "trace.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    if _writes_live(oid):
        try:
            requests.post(f"{SPINE_URL}/trace", json=entry, timeout=TIMEOUT).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] trace POST failed ({e})")
