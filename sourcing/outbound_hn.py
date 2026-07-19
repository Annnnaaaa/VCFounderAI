"""T+1:30 — Outbound sourcing from Hacker News Show HN launches.

Uses the public Algolia HN API (no auth). Every claim is backed by the real HN
item URL and the real point/comment counts from the response.

HN gives us a username, not a real name, and no github handle, so dedupe here
is best-effort: we match on the HN handle appearing as a known github handle,
then fall back to normalized name. Anything unmatched becomes a new
opportunity.

    py outbound_hn.py
"""
from __future__ import annotations

from typing import Any, Dict, List

import requests

import contract as C
import spine

API = "https://hn.algolia.com/api/v1/search"
QUERY = "Show HN llm OR agent OR inference"
MIN_POINTS = 20
MAX_OPPORTUNITIES = 6

SECTOR_HINTS = [
    ("eval", "eval & observability"), ("observab", "eval & observability"),
    ("vector", "vector/data tooling"), ("rag", "vector/data tooling"),
    ("embed", "vector/data tooling"), ("agent", "agent frameworks"),
    ("inference", "inference"), ("serving", "inference"), ("gpu", "inference"),
]


def _sector(text: str) -> str:
    low = text.lower()
    for token, sector in SECTOR_HINTS:
        if token in low:
            return sector
    return "inference"


# A Show HN title only counts as thesis-relevant if it mentions the space.
THESIS_TOKENS = ("llm", "agent", "inference", "rag", "embedding", "vector",
                 "gpu", "model", "ai ", " ai", "prompt", "eval", "openai",
                 "gpt", "claude", "llama", "transformer", "fine-tun", "serving")


def _title(hit: Dict[str, Any]) -> str:
    """Strip the 'Show HN: ' prefix to get the product pitch."""
    t = (hit.get("title") or "").strip()
    for prefix in ("Show HN: ", "Show HN – ", "Show HN - ", "Show HN, "):
        if t.startswith(prefix):
            return t[len(prefix):]
    return t


# On a code host the domain identifies nothing — the owner/repo path does.
CODE_HOSTS = {"github.com", "gitlab.com", "codeberg.org", "bitbucket.org"}


def _domain(url: str) -> str:
    """Human-readable label for the submitted product link.

    'https://cactuscompute.com/x' -> 'cactuscompute.com'
    'https://github.com/a/b/tree' -> 'github.com/a/b'
    """
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host in CODE_HOSTS:
            parts = [p for p in (parsed.path or "").split("/") if p][:2]
            if parts:
                return f"{host}/{'/'.join(parts)}"
        return host
    except Exception:  # noqa: BLE001
        return ""


def _relevant(hit: Dict[str, Any]) -> bool:
    """Algolia ORs the query loosely, so re-filter against the fund thesis."""
    blob = f"{hit.get('title') or ''} {hit.get('url') or ''}".lower()
    return any(tok in blob for tok in THESIS_TOKENS)


def _name_and_pitch(pitch: str) -> tuple[str, str]:
    """Split 'Cactus - Ollama for Smartphones' into ('Cactus', 'Ollama for...').

    Show HN titles usually lead with the product name and then a dash or colon.
    When there's no separator the whole title is the pitch and we have no
    product name to report, so we leave the name empty rather than invent one.
    """
    for sep in (" — ", " – ", " - ", ": ", ", "):
        if sep in pitch:
            head, tail = pitch.split(sep, 1)
            head = head.strip()
            # A short leading fragment reads as a product name; a long one is
            # just the first clause of a sentence.
            if 0 < len(head) <= 30 and len(head.split()) <= 4:
                return head, tail.strip()
            break
    return "", pitch


def fetch() -> List[Dict[str, Any]]:
    try:
        r = requests.get(API, params={
            "query": QUERY,
            "tags": "show_hn",
            "numericFilters": f"points>{MIN_POINTS}",
            "hitsPerPage": 30,
        }, timeout=15)
        r.raise_for_status()
        return r.json().get("hits", []) or []
    except Exception as e:  # noqa: BLE001
        print(f"[hn] search failed: {e}")
        return []


def build(hit: Dict[str, Any], existing: Dict[str, Dict[str, Any]]):
    author = hit.get("author") or ""
    pitch = _title(hit)
    points = hit.get("points") or 0
    comments = hit.get("num_comments") or 0
    item_url = f"https://news.ycombinator.com/item?id={hit['objectID']}"

    # Best-effort dedupe: HN handle often matches the founder's github handle.
    prior = (existing.get(f"github:{author.lower()}")
             or existing.get(C.founder_identity({"founder": {"name": author}})))
    if prior:
        opp, is_new = prior, False
    else:
        # HN exposes a handle, not a legal name — record the handle as the name
        # rather than inventing one.
        name, tagline = _name_and_pitch(pitch)
        blurb = tagline or pitch
        # When HN gave us no product name we leave company.name empty rather
        # than inventing one — but the submitted link is real, so surface its
        # domain in the one-liner where a human scanning the list will see it.
        if not name:
            domain = _domain(hit.get("url") or "")
            if domain:
                blurb = f"{blurb} ({domain})"
        opp = C.opportunity(
            "outbound_hn", author, name,
            one_liner=blurb[:280],
            sector=_sector(pitch),
            github="", location="",
            deck_present=False,
        )
        is_new = True

    oid = opp["id"]
    ev = C.evidence(
        item_url,
        f"Show HN: {pitch} — {points} points, {comments} comments, by {author}.",
        "hn")
    claims = [
        C.claim(oid, f"Show HN launch reached {points} points "
                     f"with {comments} comments", "traction", "hn",
                trust_obj=C.trust("corroborated", 0.95, [ev],
                                  "Hacker News is the primary source for its own "
                                  "post score; read live from the Algolia API.")),
    ]
    if hit.get("url"):
        claims.append(
            C.claim(oid, f"Shipped a public product at {hit['url']}", "tech", "hn",
                    trust_obj=C.trust("corroborated", 0.85, [
                        C.evidence(hit["url"],
                                   f"Product link submitted with the Show HN post: {pitch}",
                                   "hn"),
                    ], "Live product URL taken from the HN submission.")))
    return opp, claims, is_new


def main() -> None:
    existing = spine.existing_by_identity()
    known_claims = {c["claim_id"] for c in spine.load_claims()}

    new_opps: List[Dict[str, Any]] = []
    all_claims: List[Dict[str, Any]] = []
    seen_authors: set = set()
    dedup_hits = 0

    for hit in fetch():
        author = hit.get("author") or ""
        if not author or author in seen_authors or not _relevant(hit):
            continue
        seen_authors.add(author)
        opp, claims, is_new = build(hit, existing)
        if is_new:
            if len(new_opps) >= MAX_OPPORTUNITIES:
                continue
            new_opps.append(opp)
            print(f"[hn] NEW  {author:<18} {opp['company']['name']}")
        else:
            dedup_hits += 1
            print(f"[hn] DEDUP {author:<17} -> existing {opp['id'][:8]}")
        all_claims.extend(c for c in claims if c["claim_id"] not in known_claims)

    spine.save_opportunities(new_opps)
    spine.save_claims(all_claims)

    for o in new_opps:
        spine.trace(o["id"], "enrich",
                    f"Sourced outbound from Hacker News Show HN: {o['founder']['name']}",
                    [c["trust"]["evidence"][0]["url"]
                     for c in all_claims
                     if c["opportunity_id"] == o["id"] and c["trust"]["evidence"]][:2])

    print(f"\n[hn] {len(new_opps)} new opportunities, {dedup_hits} deduped, "
          f"{len(all_claims)} claims. live={spine.is_live()}")


if __name__ == "__main__":
    main()
