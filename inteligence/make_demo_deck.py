"""Generate real one-page demo decks for the /apply flow.

The decks seeded on the Spine are 24-byte placeholders ("%PDF-1.4 fake deck
bytes"), so they can't exercise vision extraction. This produces genuine PDFs
carrying the demo claims — including AgentStack's seeded contradiction.

    python make_demo_deck.py            # writes decks/*.pdf
"""
from __future__ import annotations

import pathlib

import fitz

DECKS = {
    "vectorforge": {
        "title": "VectorForge",
        "tagline": "GPU-native vector database for real-time RAG at inference scale",
        "slides": [
            [
                "Team",
                "CEO - ex-Staff Engineer, Pinecone query engine (3 yrs)",
                "CTO - PhD, approximate nearest-neighbour search, 400+ citations",
                "CTO maintains annlib, 6,100 GitHub stars",
            ],
            [
                "Traction & Revenue",
                "3 enterprise design partners in production",
                "220M vectors served per day",
                "3x QoQ query growth",
                "$18K MRR from two paid design partners",
                "Third pilot converting next quarter",
            ],
        ],
    },
    "agentstack": {
        "title": "AgentStack",
        "tagline": "Hosted orchestration runtime for multi-agent LLM workflows",
        "slides": [
            [
                "Team",
                "Solo founder, first-time",
                "Previously frontend engineer at a mid-size SaaS",
            ],
            [
                "Traction & Revenue",
                "2,000 paying developers",
                "$30K MRR three months after launch",
                "Fastest-growing agent runtime",
                "3x week-over-week active workflows",
            ],
        ],
    },
}


def build(name: str, spec: dict, out_dir: pathlib.Path) -> pathlib.Path:
    doc = fitz.open()
    for i, lines in enumerate(spec["slides"]):
        page = doc.new_page(width=720, height=540)
        if i == 0:
            page.insert_text((60, 90), spec["title"], fontsize=36, fontname="helv")
            page.insert_text((60, 130), spec["tagline"], fontsize=14, fontname="helv")
            y = 200
        else:
            y = 90
        page.insert_text((60, y), lines[0], fontsize=24, fontname="helv")
        y += 45
        for line in lines[1:]:
            page.insert_text((70, y), f"- {line}", fontsize=15, fontname="helv")
            y += 30
        page.insert_text((60, 510), f"Slide {i + 1}", fontsize=10, fontname="helv")
    out = out_dir / f"{name}.pdf"
    doc.save(out)
    doc.close()
    return out


if __name__ == "__main__":
    out_dir = pathlib.Path(__file__).parent / "decks"
    out_dir.mkdir(exist_ok=True)
    for name, spec in DECKS.items():
        p = build(name, spec, out_dir)
        print(f"wrote {p} ({p.stat().st_size} bytes)")
