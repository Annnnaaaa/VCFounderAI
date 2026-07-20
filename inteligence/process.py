"""VC Brain — reasoning pipeline orchestrator.

    python process.py <opportunity_id> [<opportunity_id> ...]
    python process.py --all          # every non-passed opportunity on the Spine

Runs the full chain on one opportunity, posting a trace_log entry for EVERY
step and writing every artifact through the Spine client (live API, with local
mirroring to out/<id>/).

    deck_extract -> screen -> [persist claims] -> verify -> axis_score
                 -> [cold_start] -> memo -> validate

Ordering note: claims are PERSISTED before scoring because Lane 1 assigns
claim_ids. Everything downstream then cites ids that really exist in the DB,
which is what makes the memo's [claim:uuid] popovers resolve in the UI.

Non-viable rows short-circuit after screen with status=passed.
"""
from __future__ import annotations

import sys
from typing import Dict, List

import spine
from models import AxisScores, Claim, Memo
from trace import trace


def _resolve_claims(oid: str, bundle: Dict) -> List[Claim]:
    """Claims come from one of three places, in priority order:
    already-attached (Lane 4 enrichment / re-run) > remote deck > local deck."""
    import deck

    existing = bundle.get("claims") or []
    if existing:
        claims = deck.claims_from_bundle(oid, bundle)
        bundle["_claims_already_persisted"] = True
        trace(oid, "deck_extract",
              f"Reused {len(claims)} claims already attached to the opportunity "
              "(no deck vision needed)",
              [c.claim_id for c in claims])
        return claims

    deck_url, deck_path = bundle.get("deck_url"), bundle.get("deck_path")
    if deck_url or deck_path:
        try:
            ex, claims = deck.extract_from_deck(oid, deck_path=deck_path, deck_url=deck_url)
        except deck.UnreadableDeck as e:
            # Record it. An unreadable deck must never become an evidence-free
            # memo — downstream sees zero claims and stops.
            trace(oid, "deck_extract", f"Deck present but unreadable — {e}. No claims extracted.")
            return []
        trace(oid, "deck_extract",
              f"Vision-extracted {len(claims)} claims from deck; "
              f"one-liner: {ex.company_one_liner}",
              [c.claim_id for c in claims])
        # The deck is often richer than the application form — fill the blanks.
        for field, val in [("one_liner", ex.company_one_liner),
                           ("sector", ex.sector), ("stage", ex.stage)]:
            if not bundle.get(field):
                bundle[field] = val
        return claims

    trace(oid, "deck_extract", "No deck and no attached claims — nothing to extract.")
    return []


def process(opportunity_id: str) -> None:
    print(f"\n=== {opportunity_id} ({'LIVE Spine' if spine.is_live() else 'MOCK/local'}) ===")
    bundle = spine.get_opportunity(opportunity_id)
    oid = bundle.get("opportunity_id") or opportunity_id
    raw_opp = bundle.get("_raw_opportunity")

    # 1) claims — attached, or vision-extracted from the deck
    claims = _resolve_claims(oid, bundle)

    # 2) fast-pass screen against the LIVE fund thesis
    import screen as screen_mod

    thesis = spine.get_thesis()
    sr = screen_mod.screen(
        bundle.get("one_liner", ""), bundle.get("sector", ""), bundle.get("stage", ""), thesis
    )
    trace(oid, "screen", f"viable={sr.viable}: {sr.reason}")
    if not sr.viable:
        spine.set_status(oid, "passed", raw_opp)
        print(f"--- {oid}: screened OUT (passed). {sr.reason}")
        return

    if not claims:
        # Distinct from "new": this row HAS been screened and is in-thesis, it
        # just has nothing to reason over. Leaving it at "new" makes it look
        # unprocessed forever, with no hint that a deck is what's missing.
        trace(oid, "screen", "In-thesis but no claims available to verify — "
                             "stopping before scoring rather than inventing evidence.")
        spine.set_status(oid, "needs_evidence", raw_opp)
        print(f"--- {oid}: in-thesis but no claims/deck; nothing to score.")
        return

    # 3) persist claims first so Lane 1 assigns the claim_ids we cite downstream.
    # Claims that came back from the bundle are already in the DB — pushing them
    # again would duplicate every row, so we keep their ids.
    persisted = spine.push_claims(
        oid, [c.model_dump() for c in claims],
        already_persisted=bundle.get("_claims_already_persisted", False),
    )
    claims = [Claim.model_validate(c) for c in persisted]

    # 4) verify — per-claim Trust Score against attached evidence
    import scorers

    claims = scorers.verify_all(claims)
    for c in claims:
        spine.patch_trust(c.claim_id, c.trust.model_dump(), oid)
    spine.save_claims_local(oid, [c.model_dump() for c in claims])
    counts = _status_counts(claims)
    trace(oid, "verify",
          f"Trust verdicts: {counts['corroborated']} corroborated, "
          f"{counts['unverified']} unverified, {counts['contradicted']} contradicted",
          [c.claim_id for c in claims if c.trust.status == "contradicted"])

    # 5) axis_score — 3 independent axes (NEVER averaged)
    axes: AxisScores = scorers.score_axes(oid, claims, bundle.get("founder_ctx", ""))
    trace(oid, "axis_score",
          f"founder={axes.axes.founder.score}/100 ({axes.axes.founder.trend}), "
          f"market={axes.axes.market.rating}, "
          f"idea_vs_market={axes.axes.idea_vs_market.verdict}",
          axes.axes.founder.evidence_refs + axes.axes.market.evidence_refs)
    spine.save_axis_scores(axes.model_dump())

    # Feed the founder axis into the persistent founder score (sparkline memory).
    spine.push_founder_score(
        bundle.get("founder_identity"), axes.axes.founder.score,
        confidence=0.6, reason=axes.axes.founder.rationale[:200], opportunity_id=oid,
    )

    # 6) cold_start — thin-track-record founders get an interval, never a point
    if _is_cold_start(bundle, claims):
        import cold_start

        cs = cold_start.score_cold_start(oid, bundle.get("founder_ctx", ""))
        trace(oid, "cold_start",
              f"band={cs.founder_quality.band}, interval={cs.founder_quality.interval}, "
              f"signals_used={cs.founder_quality.signals_used} - {cs.caveat}",
              [s.evidence_ref for s in cs.signals])
        spine.save_cold_start(cs.model_dump())

    # 7) memo — cited, gap-flagged, decision-ending (auto-sets status=memo_ready)
    import memo as memo_mod

    memo_out: Memo = memo_mod.write_memo(oid, claims, axes)
    trace(oid, "memo",
          f"recommendation={memo_out.recommendation}; "
          f"{len(memo_out.claim_refs)} citations, {len(memo_out.gap_flags)} gap flags",
          memo_out.claim_refs)
    spine.save_memo(memo_out.model_dump())

    # 8) validate — hallucination guard over axes + memo
    import validator

    unbacked = validator.validate(claims, axes, memo_out, bundle.get("founder_ctx", ""))
    if unbacked:
        for f in unbacked:
            trace(oid, "validate",
                  f"hallucination_flag @ {f.location}: \"{f.statement}\" - {f.reason}")
    else:
        trace(oid, "validate", "No unbacked factual statements found (clean).")

    print(f"--- {oid}: memo_ready. recommendation={memo_out.recommendation}")


def _is_cold_start(bundle: Dict, claims: List[Claim]) -> bool:
    """Per the brief: cold start when the founder has <3 STRONG signals.

    A strong signal is an externally CORROBORATED claim about the team or the
    company's traction/revenue, or a real public handle. Deliberately NOT based
    on founder_score history — that would include scores this pipeline itself
    wrote, so a re-run would quietly promote a cold-start founder to
    'established' on the strength of our own guess.

    An explicit `is_cold_start` in the bundle (mock fixtures) always wins.
    """
    if "is_cold_start" in bundle:
        return bool(bundle["is_cold_start"])
    strong = sum(
        1 for c in claims
        if c.trust.status == "corroborated" and c.type in {"team", "traction", "revenue"}
    )
    strong += len(bundle.get("founder_handles", {}))
    return strong < 3


def _status_counts(claims: List[Claim]) -> Dict[str, int]:
    out = {"corroborated": 0, "unverified": 0, "contradicted": 0}
    for c in claims:
        out[c.trust.status] += 1
    return out


def _all_ids(force: bool = False) -> List[str]:
    """Rows still awaiting analysis. Already-decided rows (passed / memo_ready)
    are skipped unless --force. --force re-runs EVERYTHING, including passed
    rows — otherwise a loosened thesis could never resurface a company that was
    screened out under the old one."""
    done = set() if force else {"passed", "memo_ready"}
    return [r["id"] for r in spine.list_opportunities() if r.get("status") not in done]


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("usage: python process.py <opportunity_id> [...] | --all [--force]")
        sys.exit(1)
    force = "--force" in args
    ids = _all_ids(force) if args[0] == "--all" else [a for a in args if not a.startswith("--")]
    print(f"Processing {len(ids)} opportunity/ies...")
    for oid in ids:
        try:
            process(oid)
        except Exception as e:  # noqa: BLE001 — one bad row shouldn't kill a batch
            print(f"!!! {oid} failed: {e}")
