"""Pydantic models mirroring the FROZEN shared contract (LANE 2).

These are the single source of truth for every shape the reasoning layer
produces. They double as the JSON schemas handed to OpenAI strict structured
outputs, so keep them:
  * flat where the contract is flat,
  * every field required (strict mode forbids optional-with-default),
  * additionalProperties disabled (Pydantic + the parse helper handle this).

Nothing here is averaged, inferred, or fabricated downstream — models only
describe shapes; the reasoning lives in the prompts.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ─────────────────────────── claims (Trust Score unit) ──────────────────────
ClaimType = Literal["traction", "revenue", "team", "market", "tech"]
TrustStatus = Literal["corroborated", "unverified", "contradicted"]


class Evidence(BaseModel):
    url: str
    snippet: str
    source: str  # tavily | github | hn | deck ...


class Trust(BaseModel):
    status: TrustStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: List[Evidence]
    note: str  # why this verdict


class Claim(BaseModel):
    claim_id: str
    opportunity_id: str
    text: str
    type: ClaimType
    source: str  # deck_slide_4 | tavily | github | hn
    trust: Trust


# ─────────────────────── axis_scores (3 independent axes) ───────────────────
class FounderAxis(BaseModel):
    score: int = Field(ge=0, le=100)
    trend: Literal["up", "down", "flat"]
    rationale: str
    evidence_refs: List[str]


class MarketAxis(BaseModel):
    rating: Literal["bull", "neutral", "bear"]
    rationale: str
    evidence_refs: List[str]


class IdeaVsMarketAxis(BaseModel):
    verdict: Literal["survives", "needs_pivot"]
    rationale: str
    evidence_refs: List[str]


class Axes(BaseModel):
    founder: FounderAxis
    market: MarketAxis
    idea_vs_market: IdeaVsMarketAxis


class AxisScores(BaseModel):
    opportunity_id: str
    axes: Axes


# ───────────────────────────── cold_start ───────────────────────────────────
SignalKind = Literal[
    "public_writing", "side_project", "oss", "community", "domain_insight"
]


class ColdStartSignal(BaseModel):
    kind: SignalKind
    weight: float = Field(ge=0.0, le=1.0)
    evidence_ref: str


class FounderQuality(BaseModel):
    band: Literal["low", "medium", "high"]
    interval: List[float] = Field(min_length=2, max_length=2)  # [lo, hi] in 0..1
    signals_used: int


class ColdStart(BaseModel):
    opportunity_id: str
    is_cold_start: bool
    founder_quality: FounderQuality
    signals: List[ColdStartSignal]
    caveat: str


# ───────────────────────────────── memo ─────────────────────────────────────
class Swot(BaseModel):
    strengths: List[str]
    weaknesses: List[str]
    opportunities: List[str]
    threats: List[str]


class MemoSections(BaseModel):
    company_snapshot: str
    investment_hypotheses: List[str]
    swot: Swot
    problem_product: str
    traction_kpis: str


class Memo(BaseModel):
    opportunity_id: str
    sections: MemoSections
    gap_flags: List[str]
    claim_refs: List[str]
    recommendation: Literal["invest", "pass", "needs_call"]
    what_would_change_my_mind: str


# ───────────────────────────── trace_log ────────────────────────────────────
TraceStep = Literal[
    "deck_extract",
    "screen",
    "enrich",
    "verify",
    "axis_score",
    "cold_start",
    "validate",
    "memo",
]


class TraceLog(BaseModel):
    opportunity_id: str
    step: TraceStep
    detail: str
    evidence_refs: List[str]
    ts: str  # iso


# ─────────────────── LLM-only response envelopes (not persisted as-is) ───────
# These wrap the raw model output before we stamp ids/opportunity_id ourselves,
# because we never let the model invent uuids or evidence urls.
class ScreenResult(BaseModel):
    viable: bool
    reason: str


class ExtractedClaim(BaseModel):
    """A claim as the vision model reports it — no ids, no trust yet."""
    text: str
    type: ClaimType
    slide: int  # source slide number, becomes source="deck_slide_N"


class DeckExtraction(BaseModel):
    company_one_liner: str
    sector: str
    stage: str
    claims: List[ExtractedClaim]


class TrustVerdict(BaseModel):
    """Trust classification for a single claim (no evidence fabrication:
    evidence_indices point back into the caller-supplied evidence list)."""
    status: TrustStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_indices: List[int]
    note: str


class ValidatorFinding(BaseModel):
    statement: str
    location: str  # e.g. "axes.founder.rationale" | "memo.traction_kpis"
    backed: bool
    reason: str


class ValidatorReport(BaseModel):
    findings: List[ValidatorFinding]


class NLQueryFilter(BaseModel):
    sector: Optional[str]
    stage: Optional[str]
    location: Optional[str]
    min_founder_score: Optional[int]
    source: Optional[str]
