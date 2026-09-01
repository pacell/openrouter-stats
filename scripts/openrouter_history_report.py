#!/usr/bin/env python3
"""Summarise what the partitioned history currently holds.

Used by the daily workflow for its commit body, and by hand to see how far the
accumulated record now reaches past the API's own retention.

    python3 scripts/openrouter_history_report.py
    python3 scripts/openrouter_history_report.py --oneline
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openrouter_stats import history  # noqa: E402
from openrouter_stats.storage import TABLE_KEYS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", default=os.path.join(ROOT, "data", "history"))
    ap.add_argument("--oneline", action="store_true")
    args = ap.parse_args()

    stats = list(history.summarise(args.history_dir))
    if not stats:
        print("no history yet")
        return

    if args.oneline:
        rows = sum(r for _, _, r, _ in stats)
        parts = sum(p for _, p, _, _ in stats)
        span = min(s.split(" .. ")[0] for _, _, _, s in stats if s)
        print(f"{len(stats)} tables, {parts:,} partitions, {rows:,} rows, "
              f"earliest {span}")
        return

    width = max(len(s[0]) for s in stats)
    print(f"{'table':<{width}} {'parts':>6} {'rows':>10}  span")
    for stem, parts, rows, span in sorted(stats):
        kind = "" if TABLE_KEYS.get(stem, (None,))[0] else "  (static snapshots)"
        print(f"{stem:<{width}} {parts:>6} {rows:>10,}  {span}{kind}")


if __name__ == "__main__":
    main()
