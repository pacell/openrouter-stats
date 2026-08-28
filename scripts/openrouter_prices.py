#!/usr/bin/env python3
"""Fetch OpenRouter's model, pricing, performance and reliability data.

The headline series is the **effective** token price — the average $/M tokens
customers actually pay once prompt caching, tiered overrides and provider
discounts are applied, which is usually well below the posted rate.

Everything written here is either pulled verbatim from the API
(``openrouter_stats/pull.py``) or computed by us (``openrouter_stats/derive.py``).
The split is enforced by that module boundary and documented column by column in
``data/openrouter/README.md``.

Standard library only (Python 3.10+), in keeping with the rest of the repo.

Usage
-----
    python3 scripts/openrouter_prices.py --all         # everything
    python3 scripts/openrouter_prices.py               # prices only
    python3 scripts/openrouter_prices.py --activity --performance
    python3 scripts/openrouter_prices.py --models anthropic/claude-sonnet-4 --all
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openrouter_stats import derive, pull, storage  # noqa: E402
from openrouter_stats.api import PERCENTILES, RANGES  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "openrouter")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--range", default="all", choices=RANGES,
                    help="history window to request (default: all)")
    ap.add_argument("--models", nargs="*", default=None,
                    help="limit to these model ids (default: every model)")
    ap.add_argument("--all", action="store_true", help="enable every section below")
    ap.add_argument("--catalogue", action="store_true",
                    help="per-endpoint listed pricing, limits, data policy, p50-p99")
    ap.add_argument("--activity", action="store_true",
                    help="daily token volumes, sequence lengths and blended price")
    ap.add_argument("--performance", action="store_true",
                    help="daily throughput / TTFT / time-to-last-token, ranked")
    ap.add_argument("--reliability", action="store_true",
                    help="uptime, cache hit rate, tool-call and structured-output errors")
    ap.add_argument("--quality", action="store_true", help="benchmark scores")
    ap.add_argument("--apps", action="store_true", help="top apps and datacenters")
    ap.add_argument("--listed", action="store_true", help="listed-price change log")
    ap.add_argument("--percentile", default="p50", choices=PERCENTILES,
                    help="percentile for the performance series (default: p50)")
    ap.add_argument("--workers", type=int, default=8, help="parallel requests")
    ap.add_argument("--out", default=OUT_DIR, help="output directory")
    args = ap.parse_args()

    if args.all:
        for flag in ("catalogue", "activity", "performance", "reliability",
                     "quality", "apps", "listed"):
            setattr(args, flag, True)

    models = pull.models()
    if args.models:
        wanted = set(args.models)
        models = [m for m in models if m["model_id"] in wanted]
        missing = wanted - {m["model_id"] for m in models}
        if missing:
            print(f"! unknown model ids: {', '.join(sorted(missing))}", file=sys.stderr)
    print(f"fetching {len(models)} models (range={args.range})")

    bins = {k: [] for k in (
        "eff_daily", "eff_summary", "model_daily", "listed", "activity", "mix",
        "perf", "cache", "tool_err", "struct_err", "uptime", "bench", "apps",
        "colos", "endpoints")}
    no_data = []

    def work(model):
        eff = pull.effective(model, args.range)
        got = {"model": model, "eff": eff}
        names = (eff or {}).get("endpointNames", {}) or {}
        slugs = (eff or {}).get("endpointProviderSlugs", {}) or {}
        if args.catalogue:
            got["endpoints"] = pull.endpoints(model)
        if args.listed:
            got["listed"] = pull.listed(model, args.range)
        if args.activity:
            got["activity"] = pull.activity(model)
        if args.performance:
            got["perf"] = pull.performance(model, args.range, args.percentile,
                                           names, slugs)
        if args.reliability:
            got["cache"] = pull.cache_hit_rate(model, args.range)
            got["tool_err"] = pull.tool_call_errors(model, args.range)
            got["struct_err"] = pull.structured_output_errors(model, args.range)
            got["uptime"] = pull.uptime(model)
        if args.quality:
            got["bench"] = pull.benchmarks(model)
        if args.apps:
            got["apps"] = pull.top_apps(model)
            got["colos"] = pull.top_colos(model)
        return got

    done = 0
    with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for got in pool.map(work, models):
            done += 1
            if done % 50 == 0 or done == len(models):
                print(f"  {done}/{len(models)}")
            model, eff = got["model"], got["eff"]
            for key in ("listed", "endpoints", "perf", "cache", "tool_err",
                        "struct_err", "uptime", "bench", "apps", "colos"):
                bins[key].extend(got.get(key) or [])
            if got.get("activity"):
                bins["activity"].extend(got["activity"])
                bins["mix"].extend(derive.token_mix(got["activity"]))
            if not eff or not eff.get("inputChartData"):
                no_data.append(model["model_id"])
                continue
            daily, summary = pull.effective_rows(model, eff)
            bins["eff_daily"].extend(daily)
            bins["eff_summary"].extend(summary)
            bins["model_daily"].extend(derive.model_daily_prices(model, eff, daily))

    print("\nwriting to", os.path.relpath(args.out))
    storage.write(args.out, "model_catalogue", models)
    bins["eff_daily"].sort(key=lambda r: (r["model_id"], r["date"], r["provider_name"] or ""))
    bins["model_daily"].sort(key=lambda r: (r["model_id"], r["date"]))
    bins["eff_summary"].sort(key=lambda r: (r["model_id"], -(r["total_tokens"] or 0)))
    storage.write(args.out, "effective_prices_daily_by_endpoint", bins["eff_daily"])
    storage.write(args.out, "effective_prices_daily_by_model", bins["model_daily"])
    storage.write(args.out, "effective_prices_summary", bins["eff_summary"])

    if args.catalogue:
        storage.write(args.out, "provider_catalogue", pull.providers())
        bins["endpoints"].sort(key=lambda r: (r["model_id"], r["provider_name"] or ""))
        storage.write(args.out, "endpoint_catalogue", bins["endpoints"])
    if args.activity:
        bins["mix"].sort(key=lambda r: (r["model_id"], r["date"]))
        storage.write(args.out, "token_mix_daily_by_model", bins["mix"])
        blended = derive.blended_prices(bins["model_daily"], bins["mix"])
        blended.sort(key=lambda r: (r["model_id"], r["date"]))
        storage.write(args.out, "blended_price_daily_by_model", blended)
    if args.performance:
        bins["perf"].sort(key=lambda r: (r["model_id"], r["date"], r["provider_name"]))
        storage.write(args.out, "performance_daily_by_endpoint", bins["perf"])
        best = derive.provider_ranking(bins["perf"], bins["eff_summary"])
        best.sort(key=lambda r: (r["model_id"], r["throughput_rank"]))
        storage.write(args.out, "provider_performance_summary", best)
    if args.reliability:
        for stem, key in (("cache_hit_rate_daily_by_endpoint", "cache"),
                          ("tool_call_error_rate_daily", "tool_err"),
                          ("structured_output_error_rate_daily", "struct_err")):
            bins[key].sort(key=lambda r: (r["model_id"], r["date"]))
            storage.write(args.out, stem, bins[key])
        bins["uptime"].sort(key=lambda r: (r["model_id"], r["timestamp"] or ""))
        storage.write(args.out, "model_uptime_recent", bins["uptime"])
    if args.quality:
        bins["bench"].sort(key=lambda r: (r["model_id"], r["benchmark_type"] or "",
                                          -(r["score"] or 0)))
        storage.write(args.out, "benchmark_scores", bins["bench"])
    if args.apps:
        storage.write(args.out, "top_apps_by_model", bins["apps"])
        storage.write(args.out, "top_colos_by_model", bins["colos"])
    if args.listed:
        storage.write(args.out, "listed_price_changes", bins["listed"])

    covered = len({r["model_id"] for r in bins["eff_daily"]})
    dates = sorted({r["date"] for r in bins["eff_daily"]})
    nonzero = {r["model_id"] for r in bins["model_daily"]
               if (r["effective_input_usd_per_mtok"] or 0)
               or (r["effective_output_usd_per_mtok"] or 0)}
    zeroed = sorted({r["model_id"] for r in bins["model_daily"]} - nonzero)
    print(f"\n{covered}/{len(models)} models have an effective-price history"
          f"{' (' + dates[0] + ' .. ' + dates[-1] + ')' if dates else ''}")
    if zeroed:
        batch = [m for m in zeroed if m.endswith(":batch")]
        free = [m for m in zeroed if m.endswith(":free")]
        print(f"{len(zeroed)} models report an all-zero effective price "
              f"({len(free)} :free — genuinely $0; {len(batch)} :batch — OpenRouter "
              f"does not attribute batch spend to this stat, so treat as missing, "
              f"not as free)")
    if no_data:
        print(f"{len(no_data)} models returned no history (too new, or no traffic)")


if __name__ == "__main__":
    main()
