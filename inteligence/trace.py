"""Trace logging — the highest-leverage stretch goal per the brief.

Every pipeline step calls `trace(...)` exactly once with what it concluded and
why. Entries are validated against the TraceLog contract, appended to a local
JSONL bundle, and POSTed to Lane 1 /trace. The result is a readable reasoning
chain a judge can scroll top-to-bottom.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import spine
from models import TraceLog, TraceStep


def trace(
    opportunity_id: str,
    step: TraceStep,
    detail: str,
    evidence_refs: List[str] | None = None,
) -> None:
    entry = TraceLog(
        opportunity_id=opportunity_id,
        step=step,
        detail=detail,
        evidence_refs=evidence_refs or [],
        ts=datetime.now(timezone.utc).isoformat(),
    )
    spine.post_trace(entry.model_dump())
    print(f"  [trace:{step}] {detail[:110]}")
