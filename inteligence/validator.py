"""Validator pass — hallucination guard.

Re-reads the generated axis rationales + memo body against the stored claims
and flags any factual statement not backed by a claim_id/evidence ref. Each
unbacked statement becomes a `hallucination_flag` in the trace log so the
reasoning chain records exactly what we couldn't substantiate.
"""
from __future__ import annotations

from typing import List

from llm import structured
from models import AxisScores, Claim, Memo, ValidatorFinding, ValidatorReport

VALIDATOR_SYSTEM = (
    "You audit generated VC analysis for HALLUCINATIONS. You are given the "
    "KNOWN BACKING (claim texts + their evidence + the founder context we were "
    "handed) and the GENERATED TEXT. Flag a statement ONLY when it asserts a "
    "specific FACT (metric, name, date, funding, credential) that does NOT "
    "trace to the known backing. Statements grounded in the founder context or "
    "any listed claim/evidence are backed=true even if they don't cite an id. "
    "Opinion/analysis phrasing and hedged language are fine. For each notable "
    "statement report: the statement, its location, backed=true/false, reason."
)


def _backing(claims: List[Claim], founder_ctx: str) -> str:
    lines = [f"FOUNDER CONTEXT (trusted input): {founder_ctx or '(none given)'}", "", "KNOWN CLAIMS:"]
    for c in claims:
        ev = " | ".join(e.snippet[:140] for e in c.trust.evidence) or "no evidence"
        lines.append(f"- claim_id={c.claim_id} [{c.type}/{c.trust.status}] \"{c.text}\" :: {ev}")
    return "\n".join(lines)


def validate(
    claims: List[Claim], axes: AxisScores, memo: Memo, founder_ctx: str = ""
) -> List[ValidatorFinding]:
    a = axes.axes
    text = (
        f"===== KNOWN BACKING =====\n{_backing(claims, founder_ctx)}\n\n"
        f"===== GENERATED TEXT =====\n"
        f"[axes.founder.rationale] {a.founder.rationale}\n"
        f"[axes.market.rationale] {a.market.rationale}\n"
        f"[axes.idea_vs_market.rationale] {a.idea_vs_market.rationale}\n"
        f"[memo.company_snapshot] {memo.sections.company_snapshot}\n"
        f"[memo.problem_product] {memo.sections.problem_product}\n"
        f"[memo.traction_kpis] {memo.sections.traction_kpis}\n"
        f"[memo.investment_hypotheses] {' | '.join(memo.sections.investment_hypotheses)}\n"
    )
    report: ValidatorReport = structured(ValidatorReport, VALIDATOR_SYSTEM, text)
    return [f for f in report.findings if not f.backed]
