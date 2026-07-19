"""Deck extraction: PDF/PPTX/images -> page images -> ONE vision call.

Output is `claims[]` (each tagged source="deck_slide_N") plus the company
one-liner / sector / stage. We render pages with PyMuPDF (no poppler/system
deps needed on Windows) and hand every page image to the vision model in a
single strict structured-output call.

If the opportunity bundle already carries deck claims (mock rows, or a re-run),
we skip the vision call and use those — extraction is idempotent.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

from models import Claim, DeckExtraction, ExtractedClaim, Trust

SCREEN_SYSTEM = (
    "You are a diligence analyst extracting verifiable CLAIMS from a startup "
    "pitch deck. A claim is any factual assertion an investor would want to "
    "verify: traction, revenue, team credentials, market size, or tech. "
    "Quote or tightly paraphrase the deck's own words. Tag each claim with the "
    "1-based slide number it appears on and its type "
    "(traction|revenue|team|market|tech). Do NOT invent numbers the deck does "
    "not state. Also give a one-line company description, its sector, and stage."
)


def _render_pdf(path: Path) -> List[bytes]:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    images: List[bytes] = []
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def _render_images(paths: List[Path]) -> List[bytes]:
    return [p.read_bytes() for p in paths]


def render_deck(deck_path: str) -> List[bytes]:
    """Return one PNG per slide/page. Supports .pdf and image files.
    (PPTX: convert to PDF first — LibreOffice/soffice not assumed here.)"""
    p = Path(deck_path)
    if not p.exists():
        raise FileNotFoundError(f"Deck not found: {deck_path}")
    if p.suffix.lower() == ".pdf":
        return _render_pdf(p)
    if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        return _render_images([p])
    raise ValueError(
        f"Unsupported deck format {p.suffix}. Convert PPTX->PDF first."
    )


def extract_from_deck(
    opportunity_id: str, deck_path: str
) -> Tuple[DeckExtraction, List[Claim]]:
    """Vision extraction from an actual deck file."""
    from llm import structured  # lazy import so mock paths need no OpenAI key

    images = render_deck(deck_path)
    ex = structured(
        DeckExtraction,
        SCREEN_SYSTEM,
        f"This deck has {len(images)} slides (in order). Extract the claims, "
        "one-liner, sector, and stage.",
        images=images,
    )
    claims = [_to_claim(opportunity_id, c) for c in ex.claims]
    return ex, claims


def _to_claim(opportunity_id: str, ec: ExtractedClaim) -> Claim:
    """Stamp our own ids + a pristine (unverified) Trust — trust is decided
    later by the verifier, never by the extractor."""
    return Claim(
        claim_id=str(uuid.uuid4()),
        opportunity_id=opportunity_id,
        text=ec.text,
        type=ec.type,
        source=f"deck_slide_{ec.slide}",
        trust=Trust(status="unverified", confidence=0.0, evidence=[], note="not yet verified"),
    )


def claims_from_bundle(opportunity_id: str, bundle: Dict) -> List[Claim]:
    """Build Claim objects from a Spine/mock bundle that already lists claims
    (with any evidence Lane 4 attached). Preserves supplied claim_ids."""
    out: List[Claim] = []
    for raw in bundle.get("claims", []):
        raw = dict(raw)
        raw.setdefault("claim_id", str(uuid.uuid4()))
        raw.setdefault("opportunity_id", opportunity_id)
        raw.setdefault(
            "trust",
            {"status": "unverified", "confidence": 0.0, "evidence": [], "note": "not yet verified"},
        )
        out.append(Claim.model_validate(raw))
    return out
