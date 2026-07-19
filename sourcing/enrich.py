"""T+1:00 — Tavily enrichment. Attach real web evidence to existing claims.

For each opportunity we search the founder + company across funding / revenue /
launch angles, plus a site-specific pass when we know their handles. Real hits
become evidence attached to the claims they support, and a genuinely notable
find that no existing claim covers becomes a new web-sourced claim.

Enrichment never *downgrades* a verdict — it only adds evidence and new
claims. Deciding corroborated/contradicted is verify.py's job.

    py enrich.py            # all opportunities
    py enrich.py <opp_id>   # just one
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List

import contract as C
import research
import spine

MAX_EVIDENCE_PER_CLAIM = 3


def _queries(opp: Dict[str, Any]) -> List[str]:
    founder = opp["founder"]["name"]
    company = opp["company"]["name"]
    subject = f"{founder} {company}".strip()
    qs = [f"{subject} funding OR revenue OR launch"]
    gh = opp["founder"]["handles"].get("github")
    if gh:
        qs.append(f"site:github.com {gh}")
    if company:
        qs.append(f'"{company}" AI infrastructure startup')
    return qs


def _relevant_to(claim: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """Cheap lexical overlap test between a claim and a search result.

    Deliberately conservative: we would rather attach no evidence than attach
    something unrelated and let it read as support.
    """
    stop = {"the", "and", "for", "with", "our", "are", "from", "that", "this",
            "has", "have", "was", "were", "over", "into", "per", "its"}
    words = {w.strip(".,%$()").lower() for w in claim["text"].split()
             if len(w) > 3 and w.lower() not in stop}
    blob = f"{result.get('title', '')} {result.get('content', '')}".lower()
    if not words:
        return False
    hits = sum(1 for w in words if w in blob)
    return hits >= max(2, len(words) // 4)


def enrich(opp: Dict[str, Any], claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach Tavily evidence to this opportunity's claims. Returns changed claims."""
    oid = opp["id"]
    label = opp["company"]["name"] or opp["founder"]["name"]

    results: List[Dict[str, Any]] = []
    for q in _queries(opp):
        results.extend(research.search(q, max_results=5))

    # De-dup by URL, keep order.
    seen: set = set()
    unique = []
    for r in results:
        u = (r.get("url") or "").strip()
        if u and u not in seen:
            seen.add(u)
            unique.append(r)

    if not unique:
        spine.trace(oid, "enrich", f"Tavily returned no results for {label}; "
                                   f"no evidence attached")
        print(f"[enrich] {label:<28} no results")
        return [], []

    mine = [c for c in claims if c["opportunity_id"] == oid]
    changed: List[Dict[str, Any]] = []
    attached = 0

    for claim in mine:
        matches = [r for r in unique if _relevant_to(claim, r)]
        new_ev = research.to_evidence(matches, limit=MAX_EVIDENCE_PER_CLAIM)
        if not new_ev:
            continue
        trust = claim.get("trust") or C.pending_trust()
        have = {e["url"] for e in trust.get("evidence", [])}
        add = [e for e in new_ev if e["url"] not in have]
        if not add:
            continue
        trust["evidence"] = (trust.get("evidence") or []) + add
        claim["trust"] = trust
        changed.append(claim)
        attached += len(add)

    # A strong hit that no existing claim covers becomes its own claim — but
    # only when the result actually names this company or founder. Without that
    # check every opportunity picks up a meaningless "web presence" claim from
    # whatever the search engine happened to return first.
    created: List[Dict[str, Any]] = []
    cited = {e["url"] for c in mine for e in (c.get("trust") or {}).get("evidence", [])}
    subject_terms = [t.lower() for t in (opp["company"]["name"], opp["founder"]["name"]) if t]

    # Pre-company solo builders are cold-start cases: their signal COUNT is the
    # measurement (Lane 2 sizes the confidence interval from it), so synthesizing
    # an extra claim would silently change their score. Enrich their existing
    # claims, never add to them.
    if not opp["company"]["name"]:
        subject_terms = []
    for top in unique[:3]:
        blob = f"{top.get('title', '')} {top.get('content', '')}".lower()
        if top.get("url") in cited or not subject_terms:
            continue
        if not any(term in blob for term in subject_terms):
            continue
        ev = research.to_evidence([top], limit=1)
        if ev:
            created.append(C.claim(
                oid, f"Public web presence: {(top.get('title') or top['url'])[:120]}",
                "market", "tavily",
                trust_obj=C.trust("corroborated", 0.6, ev,
                                  "Web result naming this company/founder, found during "
                                  "enrichment; corroborates a public footprint.")))
            break

    spine.trace(oid, "enrich",
                f"Tavily enrichment for {label}: {len(unique)} unique results, "
                f"{attached} evidence items attached to {len(changed)} claims, "
                f"{len(created)} new claims",
                [r["url"] for r in unique[:3]])
    print(f"[enrich] {label:<28} {len(unique)} results -> {attached} evidence on "
          f"{len(changed)} claims, {len(created)} new")
    return changed, created


def main() -> None:
    opps = spine.load_opportunities()
    claims = spine.load_claims()
    args = sys.argv[1:]
    if args and args[0] not in {"--all"}:
        opps = [o for o in opps if o["id"] == args[0]]
        if not opps:
            print(f"[enrich] no opportunity with id {args[0]}")
            return
    elif "--all" not in args:
        # Default: only inbound decks. Outbound rows already carry primary-source
        # GitHub/HN evidence, so enriching them spends Tavily budget for little
        # gain. Pass --all to override.
        opps = [o for o in opps if o["source"] == "inbound_apply"]
        print(f"[enrich] targeting {len(opps)} inbound opportunities "
              f"(pass --all to enrich outbound rows too)")

    changed: List[Dict[str, Any]] = []
    created: List[Dict[str, Any]] = []
    for opp in opps:
        ch, cr = enrich(opp, claims)
        changed.extend(ch)
        created.extend(cr)

    # Existing claims are UPDATED (evidence lives inside `trust`, so the trust
    # PATCH is the right endpoint); only brand-new claims are POSTed.
    for c in changed:
        spine.patch_claim_trust(c["claim_id"], c["trust"], claim=c)
    spine.save_claims(created)

    print(f"\n[enrich] {len(changed)} claims enriched, {len(created)} new claims "
          f"across {len(opps)} opportunities. live={spine.is_live()}")


if __name__ == "__main__":
    main()
