"""The four scripted demo profiles, hardcoded.

These drive the demo script, so they are deterministic fixtures rather than
LLM output — the exact numbers matter (AgentStack must come out
`contradicted`; Priya must expose exactly 2 signals so Lane 2 lands band
`medium` / interval ~[0.45, 0.72]).

HONESTY MARKER: these companies are fictional, so their evidence is
necessarily synthetic. Every seeded trust note therefore starts with
"[seed fixture]" so that scripted demo evidence is never mistaken in the DB
or the UI for something Tavily/GitHub actually returned. Real verification
output (enrich.py, verify.py, the outbound connectors) never carries that
marker and only ever uses URLs and snippets from live API responses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import contract as C

FIXTURE = "[seed fixture] "


def _bundle(opp: Dict[str, Any], claims: List[Dict[str, Any]]):
    return opp, claims


def vectorforge() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Strong inbound — deck claims corroborate."""
    opp = C.opportunity(
        "inbound_apply", "Lena Vogt", "VectorForge",
        one_liner="Low-latency inference runtime for quantized open-weight models.",
        sector="inference", github="lenavogt", twitter="lenavogt_dev",
        linkedin="lena-vogt-infra", location="Berlin, Germany",
        deck_present=True,
    )
    oid = opp["id"]
    claims = [
        C.claim(oid, "800 GitHub stars on the VectorForge inference runtime",
                "traction", "deck_slide_2",
                trust_obj=C.trust("corroborated", 0.92, [
                    C.evidence("https://github.com/lenavogt/vectorforge",
                               "vectorforge — low-latency inference runtime. 812 stars, "
                               "47 forks, last commit 2 days ago.", "github"),
                ], FIXTURE + "Repo star count (812) matches the deck's ~800 claim.")),
        C.claim(oid, "Show HN launch reached the front page",
                "traction", "deck_slide_2",
                trust_obj=C.trust("corroborated", 0.88, [
                    C.evidence("https://news.ycombinator.com/item?id=40218877",
                               "Show HN: VectorForge – 3x faster quantized inference on "
                               "commodity GPUs (287 points, 94 comments)", "hn"),
                ], FIXTURE + "Show HN post at 287 points is consistent with a front-page run.")),
        C.claim(oid, "Founder spent 4 years as an inference engineer on a production "
                     "ML serving team", "team", "deck_slide_1",
                trust_obj=C.trust("corroborated", 0.80, [
                    C.evidence("https://github.com/lenavogt",
                               "Lena Vogt — Berlin. 1.4k followers. Repos: vectorforge, "
                               "kv-cache-bench, triton-kernels-notes.", "github"),
                ], FIXTURE + "Public repo history is consistent with a deep inference background.")),
        # Deliberately left thin: honest `unverified` beats a guessed corroboration.
        C.claim(oid, "Sub-50ms p99 cold start for 7B quantized models",
                "tech", "deck_slide_3",
                trust_obj=C.trust("unverified", 0.35, [],
                                  FIXTURE + "Benchmark is self-reported; no independent "
                                            "third-party reproduction found.")),
        C.claim(oid, "Inference tooling spend is growing as open-weight models displace "
                     "hosted APIs", "market", "deck_slide_4",
                trust_obj=C.trust("unverified", 0.30, [],
                                  FIXTURE + "Directionally plausible but no cited source "
                                            "in the deck.")),
    ]
    return _bundle(opp, claims)


def agentstack() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Seeded contradiction — the trust wow moment."""
    opp = C.opportunity(
        "inbound_apply", "Marcus Feld", "AgentStack",
        one_liner="Orchestration framework for multi-step LLM agents.",
        sector="agent frameworks", github="marcusfeld", twitter="marcusfeld",
        linkedin="marcus-feld", location="Austin, TX, USA",
        deck_present=True,
    )
    oid = opp["id"]
    repo_ev = C.evidence(
        "https://github.com/marcusfeld/agentstack",
        "agentstack — created 21 days ago. 40 stars, 3 forks, 2 contributors.",
        "github")
    site_ev = C.evidence(
        "https://agentstack.dev",
        "AgentStack — Docs, GitHub, Discord. No pricing or billing page present; "
        "no paid tier advertised.",
        "tavily")
    claims = [
        C.claim(oid, "2,000 paying developers on the platform",
                "traction", "deck_slide_3",
                trust_obj=C.trust("contradicted", 0.90, [repo_ev, site_ev],
                                  FIXTURE + "Repo is 3 weeks old with 40 stars and 2 "
                                            "contributors, and the site has no paid tier — "
                                            "inconsistent with 2,000 paying developers.")),
        C.claim(oid, "$30K MRR and growing 40% month over month",
                "revenue", "deck_slide_3",
                trust_obj=C.trust("contradicted", 0.88, [site_ev, repo_ev],
                                  FIXTURE + "No pricing page, no billing flow, and no paid "
                                            "tier on the product site — no mechanism to "
                                            "collect $30K MRR.")),
        C.claim(oid, "Used in production by 12 companies",
                "traction", "deck_slide_4",
                trust_obj=C.trust("contradicted", 0.72, [repo_ev],
                                  FIXTURE + "No public adopters, case studies or dependent "
                                            "repos; 2 contributors on a 3-week-old project.")),
        C.claim(oid, "Team of 4 ex-FAANG infrastructure engineers",
                "team", "deck_slide_1",
                trust_obj=C.trust("unverified", 0.30, [],
                                  FIXTURE + "No public profiles found for the claimed team "
                                            "members; not disproven, just unevidenced.")),
    ]
    return _bundle(opp, claims)


def priya_nair() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Cold-start solo builder — exactly 2 signals, nothing else.

    No company, no funding, no LinkedIn. The two claims below ARE the two
    signals Lane 2 reads (oss + public_writing) to produce band `medium`
    with interval ~[0.45, 0.72]. Do not add a third.
    """
    opp = C.opportunity(
        "inbound_apply", "Priya Nair", "",
        one_liner="Solo builder working on LLM evaluation methodology; no company formed yet.",
        sector="eval & observability", github="priyanair-ml", twitter="", linkedin="",
        location="Bengaluru, India",
        deck_present=False,
    )
    oid = opp["id"]
    claims = [
        # signal 1 — oss
        C.claim(oid, "Author of a 120-star open-source LLM evaluation harness",
                "tech", "github",
                trust_obj=C.trust("corroborated", 0.85, [
                    C.evidence("https://github.com/priyanair-ml/evalharness",
                               "evalharness — task-agnostic evaluation harness for LLMs. "
                               "120 stars, 14 forks, 61 commits.", "github"),
                ], FIXTURE + "Repo is the primary source for its own star count.")),
        # signal 2 — public_writing
        C.claim(oid, "Published a detailed methodology post on avoiding contamination "
                     "in LLM eval sets", "tech", "tavily",
                trust_obj=C.trust("corroborated", 0.70, [
                    C.evidence("https://priyanair.dev/posts/eval-contamination",
                               "On contamination in LLM eval sets — why held-out splits "
                               "leak, and a cheap detection recipe.", "tavily"),
                ], FIXTURE + "Single substantive public post; demonstrates domain insight "
                             "but is a thin track record on its own.")),
    ]
    return _bundle(opp, claims)


def scripted() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """All scripted demo profiles as (opportunities, claims)."""
    opps: List[Dict[str, Any]] = []
    claims: List[Dict[str, Any]] = []
    for builder in (vectorforge, agentstack, priya_nair):
        o, cs = builder()
        opps.append(o)
        claims.extend(cs)
    return opps, claims
