"""Memo generator — evidence-cited, gap-flagged, decision-ending.

Required sections ONLY: Company snapshot, Investment hypotheses, SWOT,
Problem & product, Traction & KPIs. Every factual sentence cites a claim_id
via an inline `[claim:uuid]` marker (the UI turns these into popovers).
Missing data becomes explicit gap_flags, never a confident guess. CONTRADICTED
claims must appear in the body WITH the contradiction stated. Ends with a
recommendation and a "what would change my mind" line.
"""
from __future__ import annotations

from typing import List

from llm import structured
from models import AxisScores, Claim, Memo, MemoSections
from pydantic import BaseModel

MEMO_SYSTEM = (
    "You are writing a pre-seed investment memo. HARD RULES:\n"
    "- Use ONLY these sections: company_snapshot, investment_hypotheses, swot, "
    "problem_product, traction_kpis.\n"
    "- Every factual sentence MUST cite the claim it rests on with an inline "
    "marker [claim:<claim_id>]. If you can't cite a claim, don't assert it.\n"
    "- Any claim whose trust status is 'contradicted' MUST appear in the memo "
    "body with the contradiction explicitly stated (e.g. 'deck asserts X "
    "[claim:..], but external evidence contradicts this').\n"
    "- Do NOT fabricate financials, cap tables, metrics, or dates. Missing "
    "material facts go in gap_flags as short strings, e.g. 'Cap table: not "
    "disclosed', 'Financials: pre-revenue, none'.\n"
    "- claim_refs must list every claim_id you cited.\n"
    "- End with a recommendation (invest|pass|needs_call) and a one-line "
    "what_would_change_my_mind."
)


class _MemoInner(BaseModel):
    sections: MemoSections
    gap_flags: List[str]
    claim_refs: List[str]
    recommendation: str  # invest|pass|needs_call
    what_would_change_my_mind: str


def _claims_block(claims: List[Claim]) -> str:
    lines = []
    for c in claims:
        ev = "; ".join(e.snippet[:120] for e in c.trust.evidence) or "none"
        lines.append(
            f"- claim_id={c.claim_id} [{c.type}] trust={c.trust.status}"
            f"({c.trust.confidence:.2f}) \"{c.text}\" | evidence: {ev} | note: {c.trust.note}"
        )
    return "\n".join(lines)


def _axes_block(axes: AxisScores) -> str:
    a = axes.axes
    return (
        f"founder={a.founder.score}/100 trend={a.founder.trend} :: {a.founder.rationale}\n"
        f"market={a.market.rating} :: {a.market.rationale}\n"
        f"idea_vs_market={a.idea_vs_market.verdict} :: {a.idea_vs_market.rationale}"
    )


def write_memo(opportunity_id: str, claims: List[Claim], axes: AxisScores) -> Memo:
    user = (
        f"Opportunity {opportunity_id}.\n\nCLAIMS:\n{_claims_block(claims)}\n\n"
        f"AXIS SCORES:\n{_axes_block(axes)}\n\n"
        "Write the memo. Cite claim_ids inline. Flag every missing material fact."
    )
    inner: _MemoInner = structured(_MemoInner, MEMO_SYSTEM, user)
    rec = inner.recommendation if inner.recommendation in {"invest", "pass", "needs_call"} else "needs_call"
    return Memo(
        opportunity_id=opportunity_id,
        sections=inner.sections,
        gap_flags=inner.gap_flags,
        claim_refs=inner.claim_refs,
        recommendation=rec,
        what_would_change_my_mind=inner.what_would_change_my_mind,
    )
