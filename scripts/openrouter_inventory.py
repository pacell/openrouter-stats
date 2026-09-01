#!/usr/bin/env python3
"""Print the table inventory: grain, time span and coverage of every CSV.

Generated from the files themselves rather than maintained by hand, so it
cannot drift from the data. The Markdown output is pasted into the "Table
inventory" section of data/openrouter/README.md.

    python3 scripts/openrouter_inventory.py            # aligned text
    python3 scripts/openrouter_inventory.py --markdown # README table
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "openrouter")
TIME_COLUMNS = ("date", "timestamp", "hour", "changed_at")


def inspect(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        rows = list(reader)

    time_column = next((c for c in TIME_COLUMNS if c in columns), None)
    span, periods = "", 0
    if time_column and rows:
        stamps = sorted({r[time_column][:10] for r in rows if r[time_column]})
        span, periods = f"{stamps[0]} .. {stamps[-1]}", len(stamps)

    def distinct(column: str) -> int:
        return len({r[column] for r in rows if r.get(column)}) if column in columns else 0

    has_model = "model_id" in columns
    has_endpoint = "endpoint_id" in columns
    has_provider = "provider_slug" in columns or "provider_name" in columns

    if has_model and has_endpoint:
        grain = "model x provider"
    elif has_endpoint or (has_provider and not has_model):
        grain = "provider"
    elif has_model:
        grain = "model"
    else:
        grain = "-"
    if "colo" in columns:
        grain += " x colo"
    if "percentile" in columns:
        grain += " x pctile"

    return {
        "file": os.path.basename(path)[:-4],
        "rows": len(rows),
        "kind": "time series" if time_column else "static",
        "grain": grain,
        "span": span,
        "periods": periods,
        "models": distinct("model_id"),
        "endpoints": distinct("endpoint_id"),
        "providers": distinct("provider_slug") or distinct("provider_name"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--dir", default=DATA_DIR)
    args = ap.parse_args()

    files = sorted(f for f in os.listdir(args.dir) if f.endswith(".csv"))
    if not files:
        sys.exit(f"no CSVs in {args.dir}")
    stats = [inspect(os.path.join(args.dir, f)) for f in files]
    series = [s for s in stats if s["kind"] == "time series"]
    static = [s for s in stats if s["kind"] == "static"]

    if args.markdown:
        for label, group in (("Time series", series), ("Static (current snapshot)", static)):
            print(f"\n**{label}**\n")
            print("| table | grain | rows | span | periods | models | endpoints |")
            print("|---|---|---|---|---|---|---|")
            for s in sorted(group, key=lambda x: -x["periods"] or 0):
                print(f"| `{s['file']}` | {s['grain']} | {s['rows']:,} | {s['span'] or '—'} "
                      f"| {s['periods'] or '—'} | {s['models'] or '—'} | {s['endpoints'] or '—'} |")
        return

    width = max(len(s["file"]) for s in stats)
    for label, group in (("TIME SERIES", series), ("STATIC", static)):
        print(f"\n== {label} ==")
        for s in sorted(group, key=lambda x: -x["periods"] or 0):
            print(f"  {s['file']:<{width}} {s['rows']:>8,}  {s['grain']:<26} "
                  f"{s['span']:<24} {s['periods'] or '':>4}p "
                  f"{s['models'] or '':>4}m {s['endpoints'] or '':>5}e")


if __name__ == "__main__":
    main()
