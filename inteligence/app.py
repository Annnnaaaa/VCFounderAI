"""HTTP surface over the pipeline — deployed alongside the Spine.

    uvicorn app:app --reload --port 8010

    POST /process/{opportunity_id}      -> runs the full chain, returns artifacts
    POST /rescreen[?dry_run=true]       -> re-screen EVERY opportunity against the
                                           CURRENT thesis (background job)
    GET  /rescreen/status               -> progress of the running/last job
    POST /nl_query   {"q": "..."}       -> NL search -> matching opportunities

The CLI (`python process.py <id>`) still works; this is what the UI calls.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests as _requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import process
import screen as screen_mod
import spine
from trace import trace

app = FastAPI(title="VC Brain — Intelligence Lane")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "spine_live": spine.is_live()}


@app.post("/process/{opportunity_id}")
def run(opportunity_id: str):
    try:
        process.process(opportunity_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))
    return _bundle(opportunity_id)


def _bundle(opportunity_id: str):
    d = spine.OUT_DIR / opportunity_id
    out = {"opportunity_id": opportunity_id, "artifacts": {}}
    for name in ["claims", "axis_scores", "cold_start", "memo", "status"]:
        p = d / f"{name}.json"
        if p.exists():
            out["artifacts"][name] = json.loads(p.read_text(encoding="utf-8"))
    trace_path = d / "trace.jsonl"
    if trace_path.exists():
        out["trace"] = [
            json.loads(l)
            for l in trace_path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
    return out


# ───────────────────────────── re-screen job ────────────────────────────────
# Changing the thesis in the UI only rewrites a DB row; THIS is what makes the
# change bite. For every opportunity we re-run the cheap viability screen
# against the current thesis:
#   * viable=false                -> status=passed (drops out of consideration)
#   * viable=true, was passed     -> full pipeline re-run (it earns its way back)
#   * viable=true, never analyzed -> full pipeline run (new/screened rows)
#   * viable=true, memo_ready     -> untouched (its memo already exists)
# One job at a time; progress is polled via GET /rescreen/status.
_job_lock = threading.Lock()
_job: Dict[str, Any] = {"state": "idle"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outcome_label(opportunity_id: str) -> str:
    """Post-run status of a row, mapped to a word the UI can show."""
    try:
        r = _requests.get(
            f"{spine.SPINE_URL}/opportunities/{opportunity_id}/bundle",
            timeout=spine.TIMEOUT,
        )
        r.raise_for_status()
        status = (r.json().get("opportunity") or {}).get("status") or ""
    except Exception:  # noqa: BLE001
        return "analyzed"
    return {
        "memo_ready": "analyzed",
        "screened": "analyzed",
        "needs_evidence": "needs evidence",
        "passed": "passed",
    }.get(status, status or "analyzed")


def _rescreen_worker(opps: List[Dict[str, Any]], dry_run: bool) -> None:
    changes: List[Dict[str, str]] = []
    try:
        thesis = spine.get_thesis()
        for o in opps:
            oid = o["id"]
            company = o.get("company") or {}
            name = company.get("name") or "(untitled)"
            status = o.get("status") or "new"
            _job["current"] = {"id": oid, "company": name, "phase": "screening"}
            try:
                sr = screen_mod.screen(
                    company.get("one_liner", ""),
                    company.get("sector", ""),
                    company.get("stage", ""),
                    thesis,
                )
                raw = {k: v for k, v in o.items() if k != "axes"}
                if not sr.viable:
                    if status != "passed":
                        changes.append({"id": oid, "company": name, "from": status,
                                        "to": "would pass" if dry_run else "passed",
                                        "reason": sr.reason})
                        if not dry_run:
                            trace(oid, "screen",
                                  f"re-screen vs current thesis: viable=false — {sr.reason}")
                            spine.set_status(oid, "passed", raw)
                elif status != "memo_ready":
                    # in-thesis but not fully analyzed (incl. previously passed)
                    changes.append({"id": oid, "company": name, "from": status,
                                    "to": "would analyze" if dry_run else "analyzing",
                                    "reason": sr.reason})
                    if not dry_run:
                        _job["current"] = {"id": oid, "company": name,
                                           "phase": "full analysis"}
                        trace(oid, "screen",
                              f"re-screen vs current thesis: viable=true — {sr.reason}; "
                              "running full pipeline")
                        process.process(oid)
                        # Report what actually happened, not what we attempted:
                        # a row with no deck stops early and stays unanalyzed.
                        changes[-1]["to"] = _outcome_label(oid)
                else:
                    changes.append({"id": oid, "company": name, "from": status,
                                    "to": "unchanged", "reason": sr.reason})
            except Exception as e:  # noqa: BLE001 — one bad row must not kill the job
                changes.append({"id": oid, "company": name, "from": status,
                                "to": "error", "reason": str(e)[:200]})
            _job["done"] = _job.get("done", 0) + 1
            _job["changes"] = changes
        _job["state"] = "finished"
    except Exception as e:  # noqa: BLE001
        _job["state"] = "failed"
        _job["error"] = str(e)
    finally:
        _job["current"] = None
        _job["finished_at"] = _now()


@app.post("/rescreen")
def rescreen(dry_run: bool = False):
    with _job_lock:
        if _job.get("state") == "running":
            raise HTTPException(409, "a re-screen is already running")
        opps = spine.list_opportunities()
        if not opps:
            raise HTTPException(503, "spine unreachable or no opportunities")
        _job.clear()
        _job.update(
            {
                "state": "running",
                "dry_run": dry_run,
                "total": len(opps),
                "done": 0,
                "changes": [],
                "current": None,
                "started_at": _now(),
            }
        )
        threading.Thread(
            target=_rescreen_worker, args=(opps, dry_run), daemon=True
        ).start()
    return {"started": True, "dry_run": dry_run, "total": len(opps)}


@app.get("/rescreen/status")
def rescreen_status():
    return _job


# ───────────────────────────── NL query ─────────────────────────────────────
class NLQ(BaseModel):
    q: str


# NLQueryFilter.source values -> Spine `source` column values
_SOURCE_MAP = {
    "github": "outbound_github",
    "hn": "outbound_hn",
    "tavily": "outbound_tavily",
    "inbound": "inbound_apply",
}


@app.post("/nl_query")
def nl_query(body: NLQ):
    """Parse the query into filters, then RESOLVE them against the Spine so the
    caller gets opportunities back, not just filter params."""
    import nlquery

    # Ground the parser in the sector values that actually exist so it never
    # invents a synonym ("AI infra") that matches nothing.
    sectors: List[str] = sorted(
        {
            ((o.get("company") or {}).get("sector") or "").strip()
            for o in spine.list_opportunities()
        }
        - {""}
    )
    f = nlquery.parse_query(body.q, known_sectors=sectors)
    params: Dict[str, Any] = {"limit": 200}
    if f.sector:
        params["sector"] = f.sector
    if f.stage:
        params["stage"] = f.stage
    if f.min_founder_score is not None:
        params["min_founder_score"] = f.min_founder_score
    if f.source:
        params["source"] = _SOURCE_MAP.get(f.source.lower(), f.source)

    try:
        r = _requests.get(
            f"{spine.SPINE_URL}/opportunities", params=params, timeout=spine.TIMEOUT
        )
        r.raise_for_status()
        opps = r.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"spine query failed: {e}")

    if f.location:
        needle = f.location.lower()
        opps = [
            o for o in opps
            if needle in ((o.get("founder") or {}).get("location") or "").lower()
        ]

    return {"filters": f.model_dump(), "opportunities": opps}
