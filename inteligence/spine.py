"""Lane 1 (Spine) API client with a local-mock fallback.

Until Lane 1 shares SPINE_URL (~T+1:00) we read opportunities from
`mocks/<opportunity_id>.json` and write every artifact to `out/<id>/`.
Once the API is live, the same calls hit real endpoints. Detection is lazy:
we try the API and fall back to files on any connection error, so switching
over is zero-config.

Endpoints assumed (per the shared contract):
  GET  {SPINE}/opportunities/{id}          -> opportunity + attached claims/evidence
  POST {SPINE}/opportunities/{id}/claims   -> upsert scored claims
  POST {SPINE}/opportunities/{id}/axis_scores
  POST {SPINE}/opportunities/{id}/cold_start
  POST {SPINE}/opportunities/{id}/memo
  POST {SPINE}/trace                        -> one trace_log entry
  PATCH {SPINE}/opportunities/{id}          -> status updates
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import requests

SPINE_URL = os.getenv("SPINE_URL", "").rstrip("/")
_HERE = Path(__file__).parent
MOCK_DIR = _HERE / "mocks"
OUT_DIR = _HERE / "out"
TIMEOUT = 8


def _api_up() -> bool:
    if not SPINE_URL:
        return False
    try:
        requests.get(f"{SPINE_URL}/health", timeout=2)
        return True
    except Exception:
        return False


_LIVE = _api_up()


def _out_path(opportunity_id: str, name: str) -> Path:
    d = OUT_DIR / opportunity_id
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def get_opportunity(opportunity_id: str) -> Dict[str, Any]:
    """Fetch the opportunity bundle (deck ref, founder info, claims w/ evidence
    that Lane 4 attached). Falls back to mocks/<id>.json."""
    if _LIVE:
        try:
            r = requests.get(
                f"{SPINE_URL}/opportunities/{opportunity_id}", timeout=TIMEOUT
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 — degrade to mock, never crash pipeline
            print(f"[spine] live GET failed ({e}); using mock")
    path = MOCK_DIR / f"{opportunity_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No live API and no mock at {path}. "
            f"Available mocks: {[p.stem for p in MOCK_DIR.glob('*.json')]}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _post(path_suffix: str, payload: Any, out_name: str) -> None:
    opportunity_id = payload.get("opportunity_id") if isinstance(payload, dict) else None
    # Always persist locally so the demo bundle is inspectable even when live.
    if opportunity_id:
        _out_path(opportunity_id, out_name).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
    if _LIVE:
        try:
            requests.post(f"{SPINE_URL}{path_suffix}", json=payload, timeout=TIMEOUT).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] live POST {path_suffix} failed ({e}); saved locally only")


def save_claims(opportunity_id: str, claims: list) -> None:
    _post(f"/opportunities/{opportunity_id}/claims",
          {"opportunity_id": opportunity_id, "claims": claims}, "claims.json")


def save_axis_scores(payload: dict) -> None:
    _post(f"/opportunities/{payload['opportunity_id']}/axis_scores", payload, "axis_scores.json")


def save_cold_start(payload: dict) -> None:
    _post(f"/opportunities/{payload['opportunity_id']}/cold_start", payload, "cold_start.json")


def save_memo(payload: dict) -> None:
    _post(f"/opportunities/{payload['opportunity_id']}/memo", payload, "memo.json")


def set_status(opportunity_id: str, status: str) -> None:
    payload = {"opportunity_id": opportunity_id, "status": status}
    if _LIVE:
        try:
            requests.patch(
                f"{SPINE_URL}/opportunities/{opportunity_id}",
                json={"status": status}, timeout=TIMEOUT,
            ).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] status PATCH failed ({e})")
    _out_path(opportunity_id, "status.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def post_trace(entry: dict) -> None:
    """One trace_log entry — appended to out/<id>/trace.jsonl AND POSTed live."""
    oid = entry["opportunity_id"]
    line = json.dumps(entry, default=str)
    with _out_path(oid, "trace.jsonl").open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if _LIVE:
        try:
            requests.post(f"{SPINE_URL}/trace", json=entry, timeout=TIMEOUT).raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"[spine] trace POST failed ({e})")


def is_live() -> bool:
    return _LIVE
