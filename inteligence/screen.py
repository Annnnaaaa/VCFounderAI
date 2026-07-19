"""Fast-pass viability screen — one cheap call before the expensive pipeline.

Thesis: pre-seed AI-infrastructure. Non-viable rows get status=passed and skip
deck vision / scoring / memo, so we don't burn tokens on out-of-thesis founders.
Conservative by design: when unsure, viable=true (a human still reviews).
"""
from __future__ import annotations

from llm import CHEAP_MODEL, structured
from models import ScreenResult

SCREEN_SYSTEM = (
    "You are the first-pass filter for a VC fund whose thesis is PRE-SEED "
    "AI-INFRASTRUCTURE (developer tools, model/vector/data infra, agent "
    "frameworks, ML ops, inference/training tooling). Decide if an opportunity "
    "is plausibly in-thesis and worth a full analysis. Be inclusive: only mark "
    "viable=false when it clearly does NOT fit (e.g. consumer social, "
    "biotech, hardware retail, or clearly post-Series-B scale). Give a "
    "one-sentence reason."
)


def screen(one_liner: str, sector: str, stage: str) -> ScreenResult:
    user = (
        f"Company: {one_liner}\nSector: {sector}\nStage: {stage}\n\n"
        "Is this in-thesis (pre-seed AI infrastructure) and worth full analysis?"
    )
    return structured(ScreenResult, SCREEN_SYSTEM, user, model=CHEAP_MODEL)
