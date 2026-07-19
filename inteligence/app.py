"""Optional tiny FastAPI surface over the pipeline.

    uvicorn app:app --reload --port 8010

    POST /process/{opportunity_id}   -> runs the full chain, returns artifacts
    POST /nl_query   {"q": "..."}    -> NL search -> filter params (stretch)

The CLI (`python process.py <id>`) is the primary interface; this just lets
Lane 3 / integrators trigger a run over HTTP.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import process
import spine

app = FastAPI(title="VC Brain — Intelligence Lane")


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
    trace = d / "trace.jsonl"
    if trace.exists():
        out["trace"] = [json.loads(l) for l in trace.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


class NLQ(BaseModel):
    q: str


@app.post("/nl_query")
def nl_query(body: NLQ):
    import nlquery

    return nlquery.parse_query(body.q).model_dump()
