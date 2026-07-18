"""Seed 2 placeholder opportunities so Lanes 2/3/4 are never blocked.

Run: python seed.py   (idempotent — re-running replaces the same two rows)
"""
import uuid

from main import now_iso, sb, write_trace

PLACEHOLDERS = [
    {
        "id": "11111111-1111-1111-1111-111111111111",
        "source": "outbound_github",
        "founder": {
            "name": "Ada Okonkwo",
            "handles": {"github": "adaokonkwo", "twitter": "", "linkedin": ""},
            "location": "Lagos, NG",
            "identity": "github:adaokonkwo",
        },
        "company": {
            "name": "Tensorwake",
            "one_liner": "Cold-start-free serverless inference for open-weight models.",
            "sector": "inference",
            "stage": "pre-seed",
        },
        "deck_present": False,
        "status": "new",
        "created_at": now_iso(),
        "founder_score": {"value": 0, "confidence": 0.0, "trend": "flat", "history": []},
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "source": "outbound_hn",
        "founder": {
            "name": "Mira Halvorsen",
            "handles": {"github": "mirahalv", "twitter": "", "linkedin": ""},
            "location": "Oslo, NO",
            "identity": "github:mirahalv",
        },
        "company": {
            "name": "Groundtruth",
            "one_liner": "Continuous eval harness that catches agent regressions in CI.",
            "sector": "eval & observability",
            "stage": "pre-seed",
        },
        "deck_present": False,
        "status": "new",
        "created_at": now_iso(),
        "founder_score": {"value": 0, "confidence": 0.0, "trend": "flat", "history": []},
    },
]


def main() -> None:
    saved = sb.table("opportunities").upsert(PLACEHOLDERS).execute().data or []
    for row in saved:
        write_trace(row["id"], "enrich", f"seeded placeholder from {row['source']}")
        print(f"  {row['id']}  {row['company']['name']}  ({row['company']['sector']})")
    print(f"seeded {len(saved)} placeholder opportunities")


if __name__ == "__main__":
    main()
