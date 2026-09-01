#!/usr/bin/env python3
"""Rebuild the consolidated CSVs in data/openrouter/ from data/history/.

The daily job commits only the partitioned history, because rewriting whole
tables every day would add ~16 MB of git history per commit. This turns those
partitions back into one CSV per table for reading or loading elsewhere.

    python3 scripts/openrouter_consolidate.py            # all tables
    python3 scripts/openrouter_consolidate.py --tables performance_daily_by_endpoint

Partitions overlap for the last few days, because a day is still settling when
it is first fetched. The newest partition's version of a row wins.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openrouter_stats import history, storage  # noqa: E402
from openrouter_stats.storage import TABLE_KEYS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", default=os.path.join(ROOT, "data", "history"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "openrouter"))
    ap.add_argument("--tables", nargs="*", default=None)
    args = ap.parse_args()

    stems = args.tables or history.tables(args.history_dir)
    if not stems:
        sys.exit(f"no partitions under {args.history_dir} — run the fetcher with --history")

    for stem in stems:
        if stem not in TABLE_KEYS:
            print(f"  ! unknown table {stem}", file=sys.stderr)
            continue
        rows = history.load(args.history_dir, stem)
        time_column, keys = TABLE_KEYS[stem]
        rows.sort(key=lambda r: tuple(str(r.get(k, "")) for k in keys))
        storage.write(args.out, stem, rows)


if __name__ == "__main__":
    main()
