"""T+0:30 — Seed the demo dataset. Run this FIRST; Lanes 1 and 3 depend on it.

Emits 7 opportunities: the 4 scripted demo profiles (3 named + filler set)
plus 3-4 mediocre OpenAI-generated fillers so the ranked pipeline looks real.

Scripted profiles ship with their trust verdicts already set (the demo script
depends on them). Filler claims are deliberately left with `trust: null` so
verify.py has genuine work to do — and since the fillers are fictional,
Tavily will find nothing and mark them `unverified`, which is the honest
outcome the rubric rewards.

    py seed.py
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field

import contract as C
import seed_profiles
import spine

FILLER_COUNT = 4


class FillerClaim(BaseModel):
    text: str = Field(description="A concrete claim as it would appear on a pitch deck slide")
    type: str = Field(description="One of: traction, revenue, team, market, tech")
    slide: int = Field(description="Deck slide number, 1-6")


class FillerProfile(BaseModel):
    founder_name: str
    company_name: str
    one_liner: str
    sector: str = Field(description="One of: inference, agent frameworks, "
                                    "vector/data tooling, eval & observability")
    location: str
    github_handle: str
    claims: List[FillerClaim]


class FillerBatch(BaseModel):
    profiles: List[FillerProfile]


SYSTEM = (
    "You generate synthetic pre-seed AI-infrastructure founder profiles for a "
    "demo dataset. These are FILLER profiles: deliberately mediocre and "
    "unremarkable, so that a ranked pipeline has a realistic middle and bottom. "
    "Avoid impressive numbers, avoid famous companies, avoid real people. "
    "Modest traction (tens to low hundreds of stars, no revenue or tiny "
    "revenue), generic positioning, thin teams."
)

USER = (
    f"Generate exactly {FILLER_COUNT} mediocre synthetic profiles for a fund "
    "investing in pre-seed AI infrastructure (inference, agent frameworks, "
    "vector/data tooling, eval & observability). Each profile gets 3-4 "
    "deck-sourced claims with realistic but unimpressive numbers. Use clearly "
    "fictional company names and founder names."
)

# Used when OPENAI_API_KEY is missing or the call fails — the demo must never
# be blocked on a model call.
FALLBACK: List[Dict[str, Any]] = [
    {
        "founder_name": "Tomas Reiner", "company_name": "ChunkWise",
        "one_liner": "Document chunking service for RAG pipelines.",
        "sector": "vector/data tooling", "location": "Prague, Czechia",
        "github_handle": "treiner",
        "claims": [
            {"text": "60 GitHub stars since launch", "type": "traction", "slide": 2},
            {"text": "Two design partners in pilot, unpaid", "type": "traction", "slide": 3},
            {"text": "Chunking quality improves retrieval hit rate by 8%", "type": "tech", "slide": 4},
        ],
    },
    {
        "founder_name": "Dana Whitfield", "company_name": "PromptLedger",
        "one_liner": "Version control and diffing for production prompts.",
        "sector": "eval & observability", "location": "Manchester, UK",
        "github_handle": "danawhit",
        "claims": [
            {"text": "$400 MRR across 7 self-serve customers", "type": "revenue", "slide": 3},
            {"text": "Solo founder, previously a backend engineer at a logistics startup",
             "type": "team", "slide": 1},
            {"text": "Prompt regression is an unsolved pain for teams shipping LLM features",
             "type": "market", "slide": 2},
        ],
    },
    {
        "founder_name": "Ibrahim Kone", "company_name": "RouteLLM Labs",
        "one_liner": "Cost-aware model router across hosted LLM providers.",
        "sector": "inference", "location": "Montreal, Canada",
        "github_handle": "ikone-dev",
        "claims": [
            {"text": "Cuts inference spend 22% in internal benchmarks", "type": "tech", "slide": 3},
            {"text": "35 GitHub stars, 4 forks", "type": "traction", "slide": 2},
            {"text": "Waitlist of 90 developers", "type": "traction", "slide": 4},
        ],
    },
    {
        "founder_name": "Sofia Marchetti", "company_name": "TraceMesh",
        "one_liner": "Distributed tracing tuned for multi-agent LLM workflows.",
        "sector": "agent frameworks", "location": "Milan, Italy",
        "github_handle": "sofiamarch",
        "claims": [
            {"text": "Open-sourced 2 months ago, 80 stars", "type": "traction", "slide": 2},
            {"text": "Team of two, both first-time founders", "type": "team", "slide": 1},
            {"text": "Agent observability is a greenfield category", "type": "market", "slide": 3},
        ],
    },
]


def _generate_fillers() -> List[Dict[str, Any]]:
    """Ask OpenAI for filler profiles; fall back to fixtures on any failure.

    Cached to out/fillers.json after the first run: the model would otherwise
    invent different founders every run, which would defeat the identity-based
    dedupe and grow the pipeline on every re-seed.
    """
    cache = spine.OUT_DIR / "fillers.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        print(f"[seed] reusing {len(cached)} cached filler profiles")
        return cached
    profiles = _generate_fillers_uncached()
    spine.OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    return profiles


def _generate_fillers_uncached() -> List[Dict[str, Any]]:
    try:
        import os

        from openai import OpenAI

        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not set")
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        completion = client.beta.chat.completions.parse(
            model=os.getenv("OPENAI_CHEAP_MODEL", "gpt-4o-mini"),
            temperature=0.8,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": USER}],
            response_format=FillerBatch,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None or not parsed.profiles:
            raise RuntimeError("model returned no profiles")
        print(f"[seed] generated {len(parsed.profiles)} filler profiles via OpenAI")
        return [p.model_dump() for p in parsed.profiles]
    except Exception as e:  # noqa: BLE001 — never block the demo on a model call
        print(f"[seed] OpenAI filler generation unavailable ({e}); using fallback fixtures")
        return FALLBACK


def _to_rows(profile: Dict[str, Any]):
    opp = C.opportunity(
        "inbound_apply", profile["founder_name"], profile["company_name"],
        one_liner=profile.get("one_liner", ""),
        sector=profile.get("sector", ""),
        github=profile.get("github_handle", ""),
        location=profile.get("location", ""),
        deck_present=True,
    )
    claims = []
    for c in profile.get("claims", []):
        ctype = c.get("type", "traction")
        if ctype not in C.CLAIM_TYPES:
            ctype = "traction"
        claims.append(
            # trust=None on purpose: verify.py resolves these against live Tavily.
            C.claim(opp["id"], c["text"], ctype, f"deck_slide_{c.get('slide', 1)}")
        )
    return opp, claims


def _reconcile(opps: List[Dict[str, Any]], claims: List[Dict[str, Any]]):
    """Reuse the ids of founders already in the DB so re-seeding is idempotent.

    Returns (opportunities_to_insert, all_claims). Claims are re-keyed onto the
    surviving opportunity id and get fresh deterministic claim_ids.
    """
    existing = spine.existing_by_identity()
    remap: Dict[str, str] = {}
    fresh: List[Dict[str, Any]] = []
    for o in opps:
        prior = existing.get(C.founder_identity(o))
        if prior:
            remap[o["id"]] = prior["id"]
            o["id"] = prior["id"]  # keep trace + handoff pointing at the real row
            print(f"[seed] '{o['company']['name'] or o['founder']['name']}' already in DB "
                  f"-> reusing {prior['id'][:8]}")
        else:
            fresh.append(o)

    for c in claims:
        if c["opportunity_id"] in remap:
            c["opportunity_id"] = remap[c["opportunity_id"]]
            c["claim_id"] = C.stable_id(c["opportunity_id"], c["text"])
    return fresh, claims


def main() -> None:
    opps, claims = seed_profiles.scripted()
    for profile in _generate_fillers()[:FILLER_COUNT]:
        o, cs = _to_rows(profile)
        opps.append(o)
        claims.extend(cs)

    new_opps, claims = _reconcile(opps, claims)
    known_claim_ids = {c["claim_id"] for c in spine.load_claims()}
    new_claims = [c for c in claims if c["claim_id"] not in known_claim_ids]

    spine.save_opportunities(new_opps)
    spine.save_claims(new_claims)
    print(f"[seed] pushed {len(new_opps)} new opportunities, {len(new_claims)} new claims")

    for o in opps:
        n = sum(1 for c in claims if c["opportunity_id"] == o["id"])
        spine.trace(o["id"], "enrich",
                    f"Seeded {o['source']} opportunity "
                    f"'{o['company']['name'] or o['founder']['name']}' with {n} claims")

    verified = sum(1 for c in claims if not C.is_pending(c))
    print(f"\n[seed] {len(opps)} opportunities, {len(claims)} claims "
          f"({verified} pre-verified, {len(claims) - verified} awaiting verify.py)")
    print(f"[seed] spine live={spine.is_live()} -> wrote {spine.OPPS_FILE.parent}")

    # Handoff file for Lane 1 to bulk-import.
    handoff = spine.OUT_DIR / "seed_handoff.json"
    handoff.write_text(
        json.dumps({"opportunities": opps, "claims": claims}, indent=2, default=str),
        encoding="utf-8")
    print(f"[seed] Lane 1 handoff -> {handoff}")


if __name__ == "__main__":
    main()
