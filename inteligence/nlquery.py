"""Stretch: natural-language query -> Lane 1 filter params.

"technical founder, Berlin, AI infra, no prior VC backing"
  -> {sector, stage, location, min_founder_score, source}
Nulls for unspecified fields (strict schema keeps every key present).
"""
from __future__ import annotations

from llm import CHEAP_MODEL, structured
from models import NLQueryFilter

NL_SYSTEM = (
    "Translate a natural-language founder/deal search into structured filter "
    "params for a VC pipeline. Fields: sector (e.g. 'AI infra'), stage "
    "(e.g. 'pre-seed'), location (city/country), min_founder_score (0-100 int; "
    "infer a floor only if the query implies quality, else null), source "
    "(github|hn|tavily|inbound if the query names an origin, else null). Use "
    "null for anything not stated. 'no prior VC backing' is a constraint on "
    "history, not a source — leave source null unless a channel is named."
)


def parse_query(text: str) -> NLQueryFilter:
    return structured(NLQueryFilter, NL_SYSTEM, text, model=CHEAP_MODEL)
