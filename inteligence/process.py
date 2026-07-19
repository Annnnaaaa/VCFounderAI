"""VC Brain — reasoning pipeline orchestrator.

    python process.py <opportunity_id>

Runs the full chain on one opportunity, posting a trace_log entry for EVERY
step and writing every artifact via the Spine client (live API or local mock
fallback). The order encodes the reasoning:

    deck_extract -> screen -> (verify -> axis_score -> [cold_start] ->
    validate -> memo)

Non-viable rows short-circuit after screen with status=passed.

The opportunity bundle (from Spine or mocks/<id>.json) may provide:
  - deck_path:      render + vision-extract claims, OR
  - claims[]:       pre-attached claims (each may carry Lane 4 evidence)
  - one_liner/sector/stage, founder_ctx, is_cold_start
"""
from __future__ import annotations

import sys
from typing import Dict, List

import spine
from models import AxisScores, Claim, Memo
from trace import trace


def _resolve_claims(oid: str, bundle: Dict) -> List[Claim]:
    import deck

    if bundle.get("deck_path"):
        ex, claims = deck.extract_from_deck(oid, bundle["deck_path"])
        trace(oid, "deck_extract",
              f"Vision-extracted {len(claims)} claims from deck; "
              f"one-liner: {ex.company_one_liner}",
              [c.claim_id for c in claims])
        # let downstream reuse the model's read of the company
        bundle.setdefault("one_liner", ex.company_one_liner)
        bundle.setdefault("sector", ex.sector)
        bundle.setdefault("stage", ex.stage)
        return claims
    claims = deck.claims_from_bundle(oid, bundle)
    trace(oid, "deck_extract",
          f"Loaded {len(claims)} pre-attached claims from bundle (no deck vision needed)",
          [c.claim_id for c in claims])
    return claims


def process(opportunity_id: str) -> None:
    print(f"\n=== Processing {opportunity_id} "
          f"({'LIVE Spine' if spine.is_live() else 'MOCK/local'}) ===")
    bundle = spine.get_opportunity(opportunity_id)
    oid = bundle.get("opportunity_id", opportunity_id)

    # 1) claims (deck vision OR pre-attached)
    claims = _resolve_claims(oid, bundle)

    # 2) fast-pass screen — cheap in-thesis filter
    import screen as screen_mod

    sr = screen_mod.screen(
        bundle.get("one_liner", ""), bundle.get("sector", ""), bundle.get("stage", "")
    )
    trace(oid, "screen", f"viable={sr.viable}: {sr.reason}")
    if not sr.viable:
        spine.set_status(oid, "passed")
        spine.save_claims(oid, [c.model_dump() for c in claims])
        print(f"--- {oid}: screened OUT (passed). {sr.reason}")
        return

    # 3) verify — per-claim Trust Score against attached evidence
    import scorers

    claims = scorers.verify_all(claims)
    counts = _status_counts(claims)
    trace(oid, "verify",
          f"Trust verdicts: {counts['corroborated']} corroborated, "
          f"{counts['unverified']} unverified, {counts['contradicted']} contradicted",
          [c.claim_id for c in claims if c.trust.status == "contradicted"])
    spine.save_claims(oid, [c.model_dump() for c in claims])

    # 4) axis_score — 3 independent axes (NEVER averaged)
    axes: AxisScores = scorers.score_axes(oid, claims, bundle.get("founder_ctx", ""))
    trace(oid, "axis_score",
          f"founder={axes.axes.founder.score}/100 ({axes.axes.founder.trend}), "
          f"market={axes.axes.market.rating}, "
          f"idea_vs_market={axes.axes.idea_vs_market.verdict}",
          axes.axes.founder.evidence_refs + axes.axes.market.evidence_refs)
    spine.save_axis_scores(axes.model_dump())

    # 5) cold_start — only for thin-track-record founders; honest interval
    if bundle.get("is_cold_start"):
        import cold_start

        cs = cold_start.score_cold_start(oid, bundle.get("founder_ctx", ""))
        trace(oid, "cold_start",
              f"band={cs.founder_quality.band}, "
              f"interval={cs.founder_quality.interval}, "
              f"signals_used={cs.founder_quality.signals_used} — {cs.caveat}",
              [s.evidence_ref for s in cs.signals])
        spine.save_cold_start(cs.model_dump())

    # 6) memo — cited, gap-flagged, decision-ending
    import memo as memo_mod

    memo_out: Memo = memo_mod.write_memo(oid, claims, axes)
    trace(oid, "memo",
          f"recommendation={memo_out.recommendation}; "
          f"{len(memo_out.claim_refs)} citations, {len(memo_out.gap_flags)} gap flags",
          memo_out.claim_refs)

    # 7) validate — hallucination guard over axes + memo
    import validator

    unbacked = validator.validate(claims, axes, memo_out, bundle.get("founder_ctx", ""))
    if unbacked:
        for f in unbacked:
            trace(oid, "validate",
                  f"hallucination_flag @ {f.location}: \"{f.statement}\" — {f.reason}")
    else:
        trace(oid, "validate", "No unbacked factual statements found (clean).")

    spine.save_memo(memo_out.model_dump())
    spine.set_status(oid, "memo_ready")
    print(f"--- {oid}: memo_ready. recommendation={memo_out.recommendation}")


def _status_counts(claims: List[Claim]) -> Dict[str, int]:
    out = {"corroborated": 0, "unverified": 0, "contradicted": 0}
    for c in claims:
        out[c.trust.status] += 1
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python process.py <opportunity_id> [<opportunity_id> ...]")
        sys.exit(1)
    for oid in sys.argv[1:]:
        try:
            process(oid)
        except Exception as e:  # noqa: BLE001 — one bad row shouldn't kill a batch
            print(f"!!! {oid} failed: {e}")
