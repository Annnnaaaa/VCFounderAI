"""Tavily wrapper — the only place we turn web results into evidence.

Hard rule enforced here: an evidence item is built *only* from fields Tavily
actually returned (result url + content). We never synthesize a URL or a
snippet. If Tavily returns nothing, callers get an empty list and must record
`unverified` — which is an honest outcome, not a failure.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import contract as C

_client = None


def client():
    global _client
    if _client is None:
        from tavily import TavilyClient
        key = os.getenv("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY not set (check repo-root .env)")
        _client = TavilyClient(api_key=key)
    return _client


def search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Run one Tavily search. Returns [] on any failure — never raises."""
    try:
        resp = client().search(query=query, max_results=max_results,
                               search_depth="basic")
        return resp.get("results", []) or []
    except Exception as e:  # noqa: BLE001 — a dead search must not kill the pass
        print(f"[tavily] search failed for {query!r}: {e}")
        return []


def to_evidence(results: List[Dict[str, Any]], limit: int = 3,
                snippet_chars: int = 300) -> List[Dict[str, str]]:
    """Convert real Tavily results into contract evidence items."""
    items: List[Dict[str, str]] = []
    for r in results[:limit]:
        url = (r.get("url") or "").strip()
        snippet = (r.get("content") or r.get("title") or "").strip()
        if not url or not snippet:
            continue  # no URL => not usable as evidence
        items.append(C.evidence(url, snippet[:snippet_chars], "tavily"))
    return items


def extract(urls: List[str]) -> Dict[str, str]:
    """Full-text extract for the top hits. Returns {url: text}; [] on failure."""
    if not urls:
        return {}
    try:
        resp = client().extract(urls=urls[:3])
        return {r["url"]: (r.get("raw_content") or "")[:1500]
                for r in resp.get("results", []) or []}
    except Exception as e:  # noqa: BLE001
        print(f"[tavily] extract failed: {e}")
        return {}
