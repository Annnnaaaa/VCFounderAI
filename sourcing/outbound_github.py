"""T+1:30 — Outbound sourcing from GitHub. Founders who never applied.

Authenticated repo search across the fund's thesis topics, filtered to recent,
individually-owned projects. Every claim here is `corroborated` at high
confidence because GitHub IS the primary source for its own star counts — the
evidence URL is the repo itself, and every snippet comes from the API response.

Dedupe: keyed on github handle, so a founder already in the DB (seeded or from
a previous outbound run) gets new claims attached to their existing
opportunity rather than a duplicate row.

    py outbound_github.py
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

import contract as C
import spine

TOPICS = ["llm", "rag", "agents", "inference", "llm-eval", "vector-database"]
MIN_STARS = 30
PUSHED_SINCE = "2026-05-01"
# One search request per topic, no pagination — the budget stays at 6 search
# calls regardless of page size, so we take a wide page and filter locally.
PER_TOPIC = 25
MAX_OPPORTUNITIES = 8

# Curated lists, tutorials and course repos rack up stars but are not startups.
NON_PRODUCT = ("awesome", "tutorial", "course", "handbook", "cookbook", "roadmap",
               "examples", "learn-", "-guide", "guide-", "book", "papers",
               "paper-list", "cheatsheet", "interview", "resources", "collection",
               "demo", "starter", "boilerplate", "template",
               # educational "build X yourself" repos: high stars, not companies
               "from scratch", "from-scratch", "step by step", "step-by-step",
               "教程", "study", "notes", "curriculum", "bootcamp", "exercises",
               # prompt-leak / jailbreak archives: viral star counts, no product
               "leaked", "jailbreak", "system prompt", "prompt collection",
               "prompt library", "you can actually run")

# Well-known orgs/accounts that are not pre-seed founders.
BIG_CO = {
    "openai", "google", "google-research", "googleapis", "meta", "facebook",
    "facebookresearch", "microsoft", "azure", "aws", "amazon", "awslabs",
    "nvidia", "huggingface", "langchain-ai", "run-llama", "anthropics",
    "deepmind", "apple", "netflix", "uber", "airbnb", "vercel", "cloudflare",
    "elastic", "mongodb", "redis", "databricks", "snowflake", "ibm", "intel",
    "alibaba", "bytedance", "tencent", "baidu", "salesforce", "oracle",
    "qdrant", "weaviate", "milvus-io", "chroma-core", "pinecone-io", "vllm-project",
}

SECTOR_BY_TOPIC = {
    "llm": "inference",
    "inference": "inference",
    "agents": "agent frameworks",
    "rag": "vector/data tooling",
    "vector-database": "vector/data tooling",
    "llm-eval": "eval & observability",
}

API = "https://api.github.com"


def _session() -> requests.Session:
    """Authenticated session when GITHUB_PAT is present.

    The PAT is strongly preferred (30 search req/min vs 10, 5000/hr core vs
    60). We degrade to unauthenticated rather than hard-failing so the
    connector still produces live results; with our small request budget the
    anonymous limits are usually enough.
    """
    s = requests.Session()
    s.headers.update({
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "vcbrain-sourcing",
    })
    pat = os.getenv("GITHUB_PAT")
    if pat:
        s.headers["Authorization"] = f"Bearer {pat}"
    else:
        print("[github] WARNING: GITHUB_PAT empty — running UNAUTHENTICATED "
              "(10 search req/min, 60/hr core). Set it in the repo-root .env.")
    return s


def search_repos(s: requests.Session, topic: str) -> List[Dict[str, Any]]:
    q = f"topic:{topic} stars:>{MIN_STARS} pushed:>{PUSHED_SINCE}"
    try:
        r = s.get(f"{API}/search/repositories",
                  params={"q": q, "sort": "stars", "order": "desc",
                          "per_page": PER_TOPIC},
                  timeout=15)
        r.raise_for_status()
        return r.json().get("items", []) or []
    except Exception as e:  # noqa: BLE001
        print(f"[github] search failed for topic={topic}: {e}")
        return []


def get_user(s: requests.Session, login: str) -> Dict[str, Any]:
    try:
        r = s.get(f"{API}/users/{login}", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[github] user fetch failed for {login}: {e}")
        return {}


def _days_since(iso: str) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def _is_individual(repo: Dict[str, Any]) -> bool:
    owner = repo.get("owner") or {}
    login = (owner.get("login") or "").lower()
    if owner.get("type") != "User":       # excludes Organization-owned repos
        return False
    if login in BIG_CO:
        return False
    if repo.get("fork"):
        return False
    haystack = f"{repo.get('name', '')} {repo.get('description') or ''}".lower()
    if any(token in haystack for token in NON_PRODUCT):
        return False
    return True


def collect() -> Dict[str, Dict[str, Any]]:
    """Search every topic and return {login: {user, repos[]}} for individuals."""
    s = _session()
    found: Dict[str, Dict[str, Any]] = {}
    for topic in TOPICS:
        for repo in search_repos(s, topic):
            if not _is_individual(repo):
                continue
            login = repo["owner"]["login"]
            entry = found.setdefault(login, {"user": None, "repos": []})
            if repo["id"] not in {r["id"] for r in entry["repos"]}:
                repo["_topic"] = topic
                entry["repos"].append(repo)
    # Rank by best repo's stars, keep the top N, then fetch profiles.
    ranked = sorted(found.items(),
                    key=lambda kv: max(r["stargazers_count"] for r in kv[1]["repos"]),
                    reverse=True)[:MAX_OPPORTUNITIES]
    out: Dict[str, Dict[str, Any]] = {}
    for login, entry in ranked:
        entry["user"] = get_user(s, login)
        out[login] = entry
    return out


def build(login: str, entry: Dict[str, Any], existing: Dict[str, Dict[str, Any]]):
    """Map one GitHub builder to (opportunity, claims, is_new)."""
    user = entry["user"] or {}
    repos = sorted(entry["repos"], key=lambda r: r["stargazers_count"], reverse=True)
    top = repos[0]

    identity = f"github:{login.lower()}"
    prior = existing.get(identity)
    if prior:
        opp, is_new = prior, False
    else:
        opp = C.opportunity(
            "outbound_github",
            user.get("name") or login,
            top["name"],
            one_liner=(top.get("description") or "")[:280],
            sector=SECTOR_BY_TOPIC.get(top.get("_topic", ""), "inference"),
            github=login,
            twitter=user.get("twitter_username") or "",
            location=user.get("location") or "",
            deck_present=False,
        )
        is_new = True

    oid = opp["id"]
    stars = top["stargazers_count"]
    pushed_days = _days_since(top.get("pushed_at", ""))
    repo_ev = C.evidence(
        top["html_url"],
        f"{top['full_name']} — {(top.get('description') or 'no description')}. "
        f"{stars} stars, {top.get('forks_count', 0)} forks, "
        f"last push {top.get('pushed_at', 'unknown')}.",
        "github")

    claims = [
        C.claim(oid, f"{stars} GitHub stars on {top['name']}", "traction", "github",
                trust_obj=C.trust("corroborated", 0.95, [repo_ev],
                                  "GitHub is the primary source for this repo's own "
                                  "star count; read live from the API.")),
    ]

    if pushed_days is not None and pushed_days <= 30:
        claims.append(
            C.claim(oid, f"Actively maintained — last commit {pushed_days} days ago",
                    "tech", "github",
                    trust_obj=C.trust("corroborated", 0.95, [repo_ev],
                                      "pushed_at read live from the GitHub API.")))

    followers = user.get("followers")
    if followers:
        claims.append(
            C.claim(oid, f"{followers} GitHub followers across "
                         f"{user.get('public_repos', 0)} public repos",
                    "team", "github",
                    trust_obj=C.trust("corroborated", 0.9, [
                        C.evidence(user.get("html_url", top["owner"]["html_url"]),
                                   f"{login} — {user.get('name') or login}. "
                                   f"{followers} followers, "
                                   f"{user.get('public_repos', 0)} public repos. "
                                   f"{user.get('bio') or ''}".strip(),
                                   "github"),
                    ], "Owner profile read live from the GitHub API.")))

    if len(repos) > 1:
        others = ", ".join(f"{r['name']} ({r['stargazers_count']}*)" for r in repos[1:4])
        claims.append(
            C.claim(oid, f"Builder footprint across multiple thesis-relevant repos: {others}",
                    "team", "github",
                    trust_obj=C.trust("corroborated", 0.9, [
                        C.evidence(r["html_url"],
                                   f"{r['full_name']} — {r['stargazers_count']} stars.",
                                   "github") for r in repos[1:4]
                    ], "Multiple repos matched the fund's thesis topics.")))

    return opp, claims, is_new


def main() -> None:
    existing = spine.existing_by_identity()
    known_claims = {c["claim_id"] for c in spine.load_claims()}

    new_opps: List[Dict[str, Any]] = []
    all_claims: List[Dict[str, Any]] = []
    dedup_hits = 0

    for login, entry in collect().items():
        opp, claims, is_new = build(login, entry, existing)
        if is_new:
            new_opps.append(opp)
            print(f"[github] NEW  {login:<20} {opp['company']['name']} "
                  f"({len(claims)} claims)")
        else:
            dedup_hits += 1
            print(f"[github] DEDUP {login:<19} -> existing {opp['id'][:8]}, "
                  f"attaching {len(claims)} claims")
        all_claims.extend(c for c in claims if c["claim_id"] not in known_claims)

    spine.save_opportunities(new_opps)
    spine.save_claims(all_claims)

    for o in new_opps:
        spine.trace(o["id"], "enrich",
                    f"Sourced outbound from GitHub: {o['founder']['handles']['github']} "
                    f"({o['company']['name']})",
                    [c["trust"]["evidence"][0]["url"]
                     for c in all_claims
                     if c["opportunity_id"] == o["id"] and c["trust"]["evidence"]][:3])

    print(f"\n[github] {len(new_opps)} new opportunities, {dedup_hits} deduped, "
          f"{len(all_claims)} claims. live={spine.is_live()}")


if __name__ == "__main__":
    main()
