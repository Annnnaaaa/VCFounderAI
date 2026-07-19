"""Stretch: natural-language query -> Lane 1 filter params.

"technical founder, Berlin, AI infra, no prior VC backing"
  -> {sector, stage, location, min_founder_score, source}
Nulls for unspecified fields (strict schema keeps every key present).
"""
from __future__ import annotations

from typing import List, Optional

from llm import CHEAP_MODEL, structured
from models import NLQueryFilter

NL_SYSTEM = (
    "Translate a natural-language founder/deal search into structured filter "
    "params for a VC pipeline. Fields: sector, stage (e.g. 'pre-seed'), "
    "location (city/country), min_founder_score (0-100 int; infer a floor only "
    "if the query implies quality, else null), source (github|hn|tavily|inbound "
    "if the query names an origin, else null). Use null for anything not "
    "stated. 'no prior VC backing' is a constraint on history, not a source — "
    "leave source null unless a channel is named."
)


def parse_query(text: str, known_sectors: Optional[List[str]] = None) -> NLQueryFilter:
    """`known_sectors` are the sector values actually present in the pipeline.
    The filter is matched with substring semantics downstream, so the model
    must emit one of these exact values (or null) — a synonym like 'AI infra'
    would match nothing."""
    system = NL_SYSTEM
    if known_sectors:
        system += (
            "\nSector values present in the pipeline: "
            + ", ".join(repr(s) for s in known_sectors)
            + ". For `sector`, return EXACTLY one of these values (the closest "
            "match to what the query means) or null if none applies."
        )
    return structured(NLQueryFilter, system, text, model=CHEAP_MODEL)
