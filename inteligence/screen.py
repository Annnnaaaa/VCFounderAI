"""Fast-pass viability screen — one cheap call before the expensive pipeline.

The thesis is NOT hardcoded: it's read live from Lane 1's GET /thesis, so when
the fund lens is retuned in the UI the screen follows without a redeploy.
Non-viable rows get status=passed and skip deck vision / scoring / memo.
Conservative by design: when unsure, viable=true (a human still reviews).
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from llm import CHEAP_MODEL, structured
from models import ScreenResult

SCREEN_SYSTEM = (
    "You are the first-pass filter for a VC fund. You are given the fund's "
    "THESIS as JSON and one opportunity. Decide whether the opportunity is "
    "plausibly in-thesis and worth a full, expensive analysis. Be inclusive: "
    "only mark viable=false when it clearly does NOT fit the thesis (e.g. "
    "consumer social, biotech, hardware retail, or a stage far beyond the "
    "fund's). Missing/sparse detail is NOT grounds to reject — when unsure, "
    "return viable=true. Give a one-sentence reason."
)


def screen(
    one_liner: str,
    sector: str,
    stage: str,
    thesis: Optional[Dict[str, Any]] = None,
) -> ScreenResult:
    if thesis is None:
        import spine

        thesis = spine.get_thesis()
    user = (
        f"FUND THESIS:\n{json.dumps(thesis, indent=2)}\n\n"
        f"OPPORTUNITY:\n  one-liner: {one_liner or '(none given)'}\n"
        f"  sector: {sector or '(unknown)'}\n  stage: {stage or '(unknown)'}\n\n"
        "Is this in-thesis and worth full analysis?"
    )
    return structured(ScreenResult, SCREEN_SYSTEM, user, model=CHEAP_MODEL)
