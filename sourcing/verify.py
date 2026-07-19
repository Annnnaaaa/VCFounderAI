"""T+1:55 — Verification pass. Give every unverified claim a trust verdict.

For each claim still pending, we search Tavily and hand the claim plus the
*real* returned snippets to a judge model, which returns one of:

  corroborated  external evidence supports the claim
  contradicted  external evidence conflicts with the claim
  unverified    nothing found, or nothing decisive

`unverified` is the honest default and is explicitly not a failure — a fund
that says "we could not confirm this" beats one that guesses. The judge may
only cite evidence we actually retrieved; if Tavily returned nothing we skip
the model entirely and record `unverified` with an empty evidence list.

Claims that already carry a real verdict (the scripted demo profiles, and the
corroborated GitHub/HN claims where the platform is the primary source) are
left untouched.

    py verify.py
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from pydantic import BaseModel, Field

import contract as C
import research
import spine


class Verdict(BaseModel):
    status: str = Field(description="corroborated, contradicted, or unverified")
    confidence: float = Field(description="0.0-1.0 confidence in the status")
    note: str = Field(description="One sentence explaining the verdict, "
                                  "referencing the evidence")
    cited_urls: List[str] = Field(description="URLs from the supplied evidence "
                                              "that justify the verdict; empty if none")


SYSTEM = (
    "You are a diligence analyst verifying a claim made by a startup founder "
    "against web evidence. You are given the claim and a numbered list of real "
    "search results. Rules:\n"
    "- 'corroborated' only if a result substantively supports the specific "
    "claim (matching numbers, named facts). Vague topical overlap is NOT "
    "corroboration.\n"
    "- 'contradicted' only if a result directly conflicts with the claim.\n"
    "- 'unverified' if the results are irrelevant, generic, or merely absent. "
    "This is the correct, expected answer most of the time and is not a "
    "failure.\n"
    "- Only cite URLs from the supplied list. Never invent a URL.\n"
    "- Be conservative: when in doubt, answer 'unverified'."
)


def _judge(claim_text: str, results: List[Dict[str, Any]]) -> Verdict:
    from openai import OpenAI

    listing = "\n".join(
        f"[{i + 1}] {r.get('title', '')}\nURL: {r.get('url', '')}\n"
        f"{(r.get('content') or '')[:500]}"
        for i, r in enumerate(results[:5]))
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    completion = client.beta.chat.completions.parse(
        model=os.getenv("OPENAI_CHEAP_MODEL", "gpt-4o-mini"),
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"CLAIM: {claim_text}\n\nSEARCH RESULTS:\n{listing}"},
        ],
        response_format=Verdict,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("judge returned nothing")
    return parsed


def verify_claim(claim: Dict[str, Any], opp: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve one pending claim into a trust object built from real evidence."""
    founder = opp["founder"]["name"]
    company = opp["company"]["name"]
    query = f"{company} {founder} {claim['text']}".strip()
    results = research.search(query, max_results=5)

    if not results:
        return C.trust("unverified", 0.2, [],
                       "No external sources found for this claim; recorded as "
                       "unverified rather than assumed true.")

    try:
        v = _judge(claim["text"], results)
    except Exception as e:  # noqa: BLE001 — a judge failure must not fake a verdict
        print(f"[verify] judge unavailable ({e}); defaulting to unverified")
        return C.trust("unverified", 0.2, research.to_evidence(results, limit=2),
                       "Search returned results but automated comparison was "
                       "unavailable; needs analyst review.")

    status = v.status if v.status in C.TRUST_STATUSES else "unverified"
    # Keep only evidence the judge actually cited, and only from real results.
    by_url = {r.get("url"): r for r in results if r.get("url")}
    cited = [by_url[u] for u in v.cited_urls if u in by_url]
    evidence = research.to_evidence(cited or (results if status != "unverified" else []),
                                    limit=3)
    if status != "unverified" and not evidence:
        # A verdict with no citable evidence cannot stand.
        status = "unverified"
    confidence = min(max(float(v.confidence), 0.0), 1.0)
    if status == "unverified":
        # `confidence` sits inside `trust`, so the UI reads it as "how much do
        # we trust this claim". A judge that is *certain* it found nothing must
        # not surface as a high-trust chip — cap it into a clearly-low band.
        confidence = min(confidence, 0.25)
    return C.trust(status, confidence, evidence, v.note)


def main() -> None:
    opps = {o["id"]: o for o in spine.load_opportunities()}
    claims = spine.load_claims()
    pending = [c for c in claims if C.is_pending(c) and c["opportunity_id"] in opps]

    print(f"[verify] {len(pending)} pending claims of {len(claims)} total")
    counts: Dict[str, int] = {"corroborated": 0, "contradicted": 0, "unverified": 0}

    for claim in pending:
        opp = opps[claim["opportunity_id"]]
        trust = verify_claim(claim, opp)
        claim["trust"] = trust
        counts[trust["status"]] += 1
        spine.patch_claim_trust(claim["claim_id"], trust, claim=claim)
        spine.trace(claim["opportunity_id"], "verify",
                    f"{trust['status'].upper()} (conf {trust['confidence']}): "
                    f"{claim['text'][:90]} — {trust['note'][:160]}",
                    [e["url"] for e in trust["evidence"]])
        label = opps[claim["opportunity_id"]]["company"]["name"] or "-"
        print(f"[verify] {trust['status']:<13} {label[:18]:<20} {claim['text'][:52]}")

    still = sum(1 for c in spine.load_claims() if C.is_pending(c))
    print(f"\n[verify] {counts} | claims still pending: {still} | live={spine.is_live()}")


if __name__ == "__main__":
    main()
