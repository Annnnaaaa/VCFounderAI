"""Two scorers: per-claim Trust Score, and the 3 independent axes.

TRUST — for each claim we pass ONLY the claim text and the evidence snippets
Lane 4 attached. The model classifies corroborated/unverified/contradicted and
points at which evidence items justify it (by index — it cannot fabricate a
URL, it can only cite one we gave it). Zero external support => unverified,
low confidence. Direct conflict => contradicted.

AXES — one call, three independent sections. The prompt forbids blending them
into a single number and requires every section to cite claim_ids/URLs in
evidence_refs. Founder 0-100 + trend, market bull/neutral/bear, idea_vs_market
survives/needs_pivot.
"""
from __future__ import annotations

from typing import Dict, List

from llm import structured
from models import (
    AxisScores,
    Claim,
    Evidence,
    Trust,
    TrustVerdict,
)

# ─────────────────────────────── Trust ──────────────────────────────────────
TRUST_SYSTEM = (
    "You verify a single startup CLAIM against external evidence snippets. "
    "Rules:\n"
    "- corroborated: at least one evidence item independently supports the "
    "claim's substance.\n"
    "- contradicted: an evidence item directly conflicts with the claim "
    "(e.g. claim says '$30K MRR, 2000 paying devs' but the repo is 3 weeks old "
    "with 40 stars and no pricing page — the traction is implausible/conflicting).\n"
    "- unverified: no evidence item addresses the claim either way. A deck "
    "claim with zero external support is unverified with LOW confidence.\n"
    "Confidence is your certainty in the STATUS you assigned (0..1). Cite the "
    "0-based indices of the evidence items that drove your verdict; cite none "
    "if unverified. Never invent evidence."
)


def verify_claim(claim: Claim, evidence: List[Evidence]) -> Trust:
    ev_lines = (
        "\n".join(
            f"[{i}] ({e.source}) {e.url}\n    {e.snippet}"
            for i, e in enumerate(evidence)
        )
        or "(no external evidence attached)"
    )
    user = (
        f"CLAIM ({claim.type}, from {claim.source}): {claim.text}\n\n"
        f"EVIDENCE:\n{ev_lines}"
    )
    v: TrustVerdict = structured(TrustVerdict, TRUST_SYSTEM, user)
    cited = [evidence[i] for i in v.evidence_indices if 0 <= i < len(evidence)]
    return Trust(
        status=v.status,
        confidence=v.confidence,
        evidence=cited,
        note=v.note,
    )


def verify_all(claims: List[Claim]) -> List[Claim]:
    """Attach a Trust verdict to every claim using its own attached evidence."""
    for c in claims:
        c.trust = verify_claim(c, c.trust.evidence)
    return claims


# ──────────────────────────────── Axes ──────────────────────────────────────
AXES_SYSTEM = (
    "You are a pre-seed VC analyst scoring an AI-infra opportunity on THREE "
    "INDEPENDENT axes. CRITICAL: never blend them into a single number and "
    "never let one axis's verdict drive another.\n"
    "1) founder: integer 0-100 quality score + trend (up/down/flat vs prior "
    "signal) + rationale. Base it on team claims and their trust status.\n"
    "2) market: rating bull/neutral/bear on the market this plays in.\n"
    "3) idea_vs_market: verdict survives/needs_pivot — does the idea hold up "
    "against current market reality?\n"
    "For EVERY axis, evidence_refs MUST list the claim_ids (or evidence URLs) "
    "you relied on. Weight CONTRADICTED claims against the founder; do not "
    "reward unverified traction as if it were real."
)


def _claims_digest(claims: List[Claim]) -> str:
    lines = []
    for c in claims:
        ev = "; ".join(e.url for e in c.trust.evidence) or "none"
        lines.append(
            f"- claim_id={c.claim_id} [{c.type}] \"{c.text}\" "
            f"trust={c.trust.status}({c.trust.confidence:.2f}) evidence={ev}"
        )
    return "\n".join(lines)


def score_axes(opportunity_id: str, claims: List[Claim], founder_ctx: str = "") -> AxisScores:
    user = (
        f"Opportunity {opportunity_id}. Founder context: {founder_ctx or 'n/a'}\n\n"
        f"CLAIMS (with trust verdicts):\n{_claims_digest(claims)}\n\n"
        "Score the three independent axes. Cite claim_ids in evidence_refs."
    )
    inner = structured(_AxesInner, AXES_SYSTEM, user)
    return AxisScores(opportunity_id=opportunity_id, axes=inner.axes)


# The model shouldn't echo opportunity_id (we own it), so score into an inner
# schema that carries only the axes.
from models import Axes  # noqa: E402
from pydantic import BaseModel  # noqa: E402


class _AxesInner(BaseModel):
    axes: Axes
