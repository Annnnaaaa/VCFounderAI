"""Cold-start scorer — honest INTERVAL, never a fake-confident point.

When a founder has <3 strong signals (no funding history, no company, thin
GitHub) we refuse to emit a point score. Instead: a band (low/medium/high) and
a probability INTERVAL whose width GROWS as signals shrink, a list of the weak
signals we leaned on, and a caveat naming how thin the track record is.

The model proposes band + signals; WE enforce the interval-width floor in code
so the honesty guarantee can't be prompted away:
  * 2 weak signals  -> width >= 0.25
  * fewer signals   -> wider still.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel

from llm import structured
from models import ColdStart, ColdStartSignal, FounderQuality

COLD_SYSTEM = (
    "You assess a founder with a THIN track record (no funding, maybe no "
    "company, limited public footprint). List the weak SIGNALS you can find "
    "(public_writing, side_project, oss, community, domain_insight), each with "
    "an evidence_ref (URL or claim_id) and a weight 0..1 for how much it "
    "informs founder quality. Then pick a band (low/medium/high) and a CENTER "
    "estimate of founder quality in 0..1. Be honest: thin evidence means a "
    "modest, uncertain estimate. Do NOT output a wide/narrow interval yourself "
    "— just the center; the system computes the interval."
)


class _ColdInner(BaseModel):
    signals: List[ColdStartSignal]
    band: str  # low|medium|high
    center: float  # 0..1 point estimate BEFORE we widen into an interval
    caveat: str


def _interval(center: float, n_signals: float) -> List[float]:
    """Width grows as signals shrink. >=2 signals -> width~0.27 (>=0.25 floor
    from the brief); each missing signal below 2 adds 0.10. Clamped to [0,1]."""
    base = 0.27
    if n_signals < 2:
        base += (2 - n_signals) * 0.10
    half = base / 2
    lo = max(0.0, round(center - half, 2))
    hi = min(1.0, round(center + half, 2))
    return [lo, hi]


def score_cold_start(opportunity_id: str, founder_ctx: str) -> ColdStart:
    inner: _ColdInner = structured(
        _ColdInner,
        COLD_SYSTEM,
        f"Founder context:\n{founder_ctx}\n\nAssess the weak signals and give a "
        "band + center estimate.",
    )
    n = len(inner.signals)
    interval = _interval(inner.center, n)
    band = inner.band if inner.band in {"low", "medium", "high"} else "medium"
    return ColdStart(
        opportunity_id=opportunity_id,
        is_cold_start=True,
        founder_quality=FounderQuality(band=band, interval=interval, signals_used=n),
        signals=inner.signals,
        caveat=inner.caveat
        or f"Based on {n} weak signals; wide interval reflects thin track record.",
    )
