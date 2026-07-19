"""Builders for the frozen shared contract.

Everything this lane emits goes through here so the field names can't drift
from the shapes Lane 1 owns. Two rules encoded as asserts, because both are
acceptance criteria:
  * a claim's trust status is one of the three allowed values;
  * every evidence item carries a real URL (we never emit evidence without one).
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List

from spine import new_id, now_iso

# Namespace for deterministic ids, so re-running a script upserts the same rows
# instead of creating duplicates.
_NS = uuid.UUID("6f1d2e00-0000-4000-8000-000000000001")


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(_NS, "|".join(parts)))

CLAIM_TYPES = {"traction", "revenue", "team", "market", "tech"}
TRUST_STATUSES = {"corroborated", "unverified", "contradicted"}


def opportunity(source: str, founder_name: str, company_name: str, *,
                one_liner: str = "", sector: str = "", stage: str = "pre-seed",
                github: str = "", twitter: str = "", linkedin: str = "",
                location: str = "", deck_present: bool = False,
                opportunity_id: str | None = None) -> Dict[str, Any]:
    return {
        "id": opportunity_id or new_id(),
        "source": source,
        "founder": {
            "name": founder_name,
            "handles": {"github": github, "twitter": twitter, "linkedin": linkedin},
            "location": location,
        },
        "company": {
            "name": company_name,
            "one_liner": one_liner,
            "sector": sector,
            "stage": stage,
        },
        "deck_present": deck_present,
        "created_at": now_iso(),
        "status": "new",
    }


def evidence(url: str, snippet: str, source: str) -> Dict[str, str]:
    assert url, "evidence item must carry a URL — never emit evidence without one"
    return {"url": url, "snippet": snippet, "source": source}


def trust(status: str, confidence: float, evidence_items: List[Dict[str, str]],
          note: str) -> Dict[str, Any]:
    assert status in TRUST_STATUSES, f"bad trust status: {status}"
    return {
        "status": status,
        "confidence": round(float(confidence), 2),
        "evidence": evidence_items,
        "note": note,
    }


# Sentinel note marking a claim that has not been through verification yet.
# Lane 1's `trust` column is NOT NULL, so an unprocessed claim can't be sent as
# null; it ships as `unverified` (the honest status for something unchecked)
# carrying this marker, and verify.py picks up exactly these.
PENDING_NOTE = "PENDING_VERIFICATION — not yet checked against external sources."


def pending_trust() -> Dict[str, Any]:
    return trust("unverified", 0.0, [], PENDING_NOTE)


def is_pending(claim_obj: Dict[str, Any]) -> bool:
    t = claim_obj.get("trust")
    if not t:
        return True
    return str(t.get("note", "")).startswith("PENDING_VERIFICATION")


def claim(opportunity_id: str, text: str, claim_type: str, source: str, *,
          trust_obj: Dict[str, Any] | None = None,
          claim_id: str | None = None) -> Dict[str, Any]:
    assert claim_type in CLAIM_TYPES, f"bad claim type: {claim_type}"
    return {
        # Deterministic: the same claim on the same opportunity keeps its id
        # across reruns, so re-seeding never duplicates.
        "claim_id": claim_id or stable_id(opportunity_id, text),
        "opportunity_id": opportunity_id,
        "text": text,
        "type": claim_type,
        "source": source,
        "trust": trust_obj or pending_trust(),
    }


def founder_identity(opp: Dict[str, Any]) -> str:
    """Stable dedupe key: github handle when we have one, else normalized name.

    Same key => same founder, so the outbound connectors attach claims to the
    existing opportunity instead of creating a duplicate row.
    """
    gh = (opp.get("founder", {}).get("handles", {}).get("github") or "").strip().lower()
    if gh:
        return f"github:{gh}"
    name = (opp.get("founder", {}).get("name") or "").strip().lower()
    return "name:" + re.sub(r"[^a-z0-9]+", "-", name).strip("-")
