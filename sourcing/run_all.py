"""Run the whole Lane 4 pipeline in dependency order.

    py run_all.py            # seed -> outbound -> enrich -> verify -> check
    py run_all.py --no-seed  # skip seeding (it is idempotent, but slower)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

STEPS = [
    ("seed.py", "Seed the demo dataset (scripted profiles + fillers)"),
    ("outbound_github.py", "Outbound sourcing from GitHub"),
    ("outbound_hn.py", "Outbound sourcing from Hacker News"),
    ("enrich.py", "Tavily enrichment of inbound decks"),
    ("verify.py", "Verification pass over pending claims"),
    ("resync.py", "Reconcile the local store with the live DB"),
    ("check.py", "Acceptance criteria"),
]


def main() -> None:
    skip = set()
    if "--no-seed" in sys.argv:
        skip.add("seed.py")

    for script, label in STEPS:
        if script in skip:
            print(f"\n=== SKIP {script} ===")
            continue
        print(f"\n=== {script} — {label} ===", flush=True)
        r = subprocess.run([sys.executable, str(HERE / script)], cwd=HERE)
        if r.returncode != 0:
            print(f"[run_all] {script} exited {r.returncode}; continuing")


if __name__ == "__main__":
    main()
