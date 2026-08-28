#!/usr/bin/env python3
"""Fetch OpenRouter's historical **effective** token prices for every model.

OpenRouter publishes two different prices per model endpoint:

* the **listed** price — what the provider posts on the model page, and
* the **effective** price — the average $/M tokens customers *actually* pay,
  once prompt caching, tiered/long-context overrides and provider discounts
  are taken into account.  It is usually well below the listed price.

The effective series is the one behind the "Pricing" chart on a model page and
is served by ``/api/frontend/v1/stats/effective-pricing`` as a daily, per
provider-endpoint time series.  This script walks every model in
``/api/v1/models`` and flattens that series into CSV/JSON.

Standard library only (Python 3.10+), in keeping with the rest of the repo.

Usage
-----
    python3 scripts/openrouter_prices.py                 # effective, range=all
    python3 scripts/openrouter_prices.py --range 3m
    python3 scripts/openrouter_prices.py --listed        # also pull listed prices
    python3 scripts/openrouter_prices.py --models anthropic/claude-sonnet-4
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import csv
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE = "https://openrouter.ai"
MODELS_URL = f"{BASE}/api/v1/models"
EFFECTIVE_URL = f"{BASE}/api/frontend/v1/stats/effective-pricing"
LISTED_URL = f"{BASE}/api/frontend/v1/stats/listed-pricing"
ACTIVITY_URL = f"{BASE}/api/frontend/v1/stats/model-activity"

# Shape versions the OpenRouter front-end currently requests. They pin the
# response schema, so bump them only alongside the parsing code below.
EFFECTIVE_SHAPE = "v7"
LISTED_SHAPE = "v4"
RANGES = ("3d", "1w", "1m", "3m", "1y", "all")

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "openrouter")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 60
MAX_RETRIES = 4


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def get_json(url: str, params: Optional[Dict[str, str]] = None) -> Optional[Any]:
    """GET a JSON document, retrying transient failures with backoff."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    delay = 2.0
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (400, 403, 404, 410):  # won't fix itself on a retry
                return None
        except Exception as e:  # noqa: BLE001 - network errors of many kinds
            last_err = e
        if attempt < MAX_RETRIES:
            time.sleep(delay)
            delay *= 2
    print(f"  ! giving up on {url}: {last_err}", file=sys.stderr)
    return None


# --------------------------------------------------------------------------- #
# Model catalogue
# --------------------------------------------------------------------------- #

def list_models() -> List[Dict[str, Any]]:
    """Return every model with the (permaslug, variant) pair the stats API wants.

    ``canonical_slug`` is the permaslug; the variant is the ``:suffix`` on the
    model id (``:free``, ``:batch``), defaulting to ``standard``.
    """
    payload = get_json(MODELS_URL)
    if not payload:
        raise SystemExit("could not fetch the OpenRouter model list")
    out = []
    for m in payload["data"]:
        model_id = m["id"]
        variant = model_id.split(":", 1)[1] if ":" in model_id else "standard"
        out.append({
            "model_id": model_id,
            "permaslug": m["canonical_slug"],
            "variant": variant,
            "name": m.get("name") or model_id,
            "listed_prompt_usd_per_mtok": _per_mtok(m.get("pricing", {}).get("prompt")),
            "listed_completion_usd_per_mtok": _per_mtok(m.get("pricing", {}).get("completion")),
        })
    return out


def _per_mtok(price: Any) -> Optional[float]:
    """/api/v1/models quotes $/token; the stats API quotes $/M tokens."""
    if price is None or price == "":
        return None
    try:
        return float(price) * 1_000_000
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Effective prices
# --------------------------------------------------------------------------- #

def fetch_effective(model: Dict[str, Any], rng: str) -> Optional[Dict[str, Any]]:
    payload = get_json(EFFECTIVE_URL, {
        "permaslug": model["permaslug"],
        "variant": model["variant"],
        "shape": EFFECTIVE_SHAPE,
        "range": rng,
    })
    return payload.get("data") if isinstance(payload, dict) else None


def flatten_effective(model: Dict[str, Any], data: Dict[str, Any]
                      ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split one model's response into (daily rows, per-provider summary rows).

    ``inputChartData``/``outputChartData`` are parallel daily series keyed by
    endpoint id, so they are joined on (date, endpoint id) — an endpoint that
    served no traffic on a day is simply absent from that day's bucket.
    """
    summaries = {s["endpointId"]: s for s in data.get("providerSummaries", [])}
    names = data.get("endpointNames", {}) or {}
    slugs = data.get("endpointProviderSlugs", {}) or {}

    outputs: Dict[str, Dict[str, float]] = {}
    for point in data.get("outputChartData", []):
        outputs[point["x"]] = point.get("y") or {}

    daily: List[Dict[str, Any]] = []
    for point in data.get("inputChartData", []):
        date = str(point["x"])[:10]
        out_bucket = outputs.get(point["x"], {})
        for endpoint_id, in_price in (point.get("y") or {}).items():
            summary = summaries.get(endpoint_id, {})
            daily.append({
                "date": date,
                "model_id": model["model_id"],
                "permaslug": model["permaslug"],
                "variant": model["variant"],
                "endpoint_id": endpoint_id,
                "provider_name": summary.get("providerName") or names.get(endpoint_id, ""),
                "provider_slug": summary.get("providerSlug") or slugs.get(endpoint_id, ""),
                "effective_input_usd_per_mtok": in_price,
                "effective_output_usd_per_mtok": out_bucket.get(endpoint_id),
            })

    summary_rows = [{
        "model_id": model["model_id"],
        "permaslug": model["permaslug"],
        "variant": model["variant"],
        "endpoint_id": s.get("endpointId"),
        "provider_name": s.get("providerName"),
        "provider_slug": s.get("providerSlug"),
        "effective_input_usd_per_mtok": s.get("effectiveInputPrice"),
        "effective_output_usd_per_mtok": s.get("effectiveOutputPrice"),
        "cache_hit_rate": s.get("cacheHitRate"),
        "total_tokens": s.get("totalTokens"),
    } for s in data.get("providerSummaries", [])]

    return daily, summary_rows


def model_level_daily(model: Dict[str, Any], data: Dict[str, Any],
                      daily: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse the per-endpoint daily series to one price per model per day.

    The API only reports token volumes per endpoint over the whole window, not
    per day, so endpoints are weighted by their window-wide ``totalTokens``
    (renormalised over whichever endpoints were live that day). Where no volume
    is known the endpoints are weighted equally.

    The two ``*_current`` listed columns are today's headline price from
    ``/api/v1/models``, repeated on every row as a reference line — they are a
    snapshot, not history. Use ``--listed`` for the real listed-price change log.
    """
    weights = {s["endpointId"]: float(s.get("totalTokens") or 0)
               for s in data.get("providerSummaries", [])}

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in daily:
        by_date.setdefault(row["date"], []).append(row)

    rows = []
    for date in sorted(by_date):
        entries = by_date[date]
        rows.append({
            "date": date,
            "model_id": model["model_id"],
            "permaslug": model["permaslug"],
            "variant": model["variant"],
            "n_endpoints": len(entries),
            "effective_input_usd_per_mtok": _weighted(
                entries, "effective_input_usd_per_mtok", weights),
            "effective_output_usd_per_mtok": _weighted(
                entries, "effective_output_usd_per_mtok", weights),
            "listed_input_usd_per_mtok_current": model["listed_prompt_usd_per_mtok"],
            "listed_output_usd_per_mtok_current": model["listed_completion_usd_per_mtok"],
        })
    return rows


def _weighted(entries: List[Dict[str, Any]], field: str,
              weights: Dict[str, float]) -> Optional[float]:
    pairs = [(e[field], weights.get(e["endpoint_id"], 0.0))
             for e in entries if e.get(field) is not None]
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    if total <= 0:  # no volume reported — fall back to an unweighted mean
        return round(sum(v for v, _ in pairs) / len(pairs), 6)
    return round(sum(v * w for v, w in pairs) / total, 6)


# --------------------------------------------------------------------------- #
# Listed prices (optional companion series)
# --------------------------------------------------------------------------- #

def fetch_listed(model: Dict[str, Any], rng: str) -> List[Dict[str, Any]]:
    payload = get_json(LISTED_URL, {
        "permaslug": model["permaslug"],
        "variant": model["variant"],
        "shape": LISTED_SHAPE,
        "range": rng,
    })
    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        return []
    rows = []
    for series in data.get("series", []):
        # Each field is a sparse list of change points, not a dense daily series.
        for field, column in (("input", "listed_input_usd_per_mtok"),
                              ("output", "listed_output_usd_per_mtok"),
                              ("cacheRead", "listed_cache_read_usd_per_mtok"),
                              ("cacheWrite", "listed_cache_write_usd_per_mtok"),
                              ("discount", "discount_fraction")):
            for point in series.get(field) or []:
                rows.append({
                    "changed_at": point.get("at"),
                    "model_id": model["model_id"],
                    "permaslug": model["permaslug"],
                    "variant": model["variant"],
                    "endpoint_id": series.get("endpointId"),
                    "provider_name": series.get("providerName"),
                    "provider_slug": series.get("providerSlug"),
                    "field": column,
                    "value": point.get("value"),
                })
    return rows


# --------------------------------------------------------------------------- #
# Token mix (prompt/completion sequence lengths)
# --------------------------------------------------------------------------- #

def fetch_activity(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Daily token volumes for one model, split prompt vs completion.

    ``model-activity`` takes no range and always returns the last ~31 days —
    much shorter than the price history, so the blend below is only defined
    over that window.
    """
    payload = get_json(ACTIVITY_URL, {
        "permaslug": model["permaslug"],
        "variant": model["variant"],
    })
    data = payload.get("data") if isinstance(payload, dict) else None
    if not data:
        return []

    rows = []
    for a in data.get("analytics", []):
        requests = a.get("count") or 0
        prompt = a.get("total_prompt_tokens") or 0
        completion = a.get("total_completion_tokens") or 0
        cached = a.get("total_native_tokens_cached") or 0
        reasoning = a.get("total_native_tokens_reasoning") or 0
        rows.append({
            "date": str(a["date"])[:10],
            "model_id": model["model_id"],
            "permaslug": model["permaslug"],
            "variant": model["variant"],
            "requests": requests,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "cached_prompt_tokens": cached,
            "reasoning_tokens": reasoning,
            "avg_prompt_tokens_per_request": _div(prompt, requests, 1),
            "avg_completion_tokens_per_request": _div(completion, requests, 1),
            "avg_reasoning_tokens_per_request": _div(reasoning, requests, 1),
            "completion_to_prompt_ratio": _div(completion, prompt, 4),
            "cache_hit_share_of_prompt": _div(cached, prompt, 4),
            "tool_calls": a.get("total_tool_calls") or 0,
            "media_prompt_requests": a.get("num_media_prompt") or 0,
        })
    return rows


def _div(num: float, den: float, places: int) -> Optional[float]:
    return round(num / den, places) if den else None


def blend(model_rows: List[Dict[str, Any]], activity_rows: List[Dict[str, Any]]
          ) -> List[Dict[str, Any]]:
    """Join effective prices to the token mix to get a real blended price.

    The stats API never blends: input and output are separate series, so a
    single headline $/M figure only exists once you weight them by the actual
    prompt:completion split, which is what this does.
    """
    prices = {(r["model_id"], r["date"]): r for r in model_rows}
    out = []
    for a in activity_rows:
        p = prices.get((a["model_id"], a["date"]))
        if not p:
            continue
        ein = p["effective_input_usd_per_mtok"]
        eout = p["effective_output_usd_per_mtok"]
        if ein is None or eout is None:
            continue
        prompt, completion = a["prompt_tokens"], a["completion_tokens"]
        total = prompt + completion
        if not total:
            continue
        cost = (prompt * ein + completion * eout) / 1_000_000
        lin = p["listed_input_usd_per_mtok_current"]
        lout = p["listed_output_usd_per_mtok_current"]
        listed_cost = ((prompt * lin + completion * lout) / 1_000_000
                       if lin is not None and lout is not None else None)
        out.append({
            "date": a["date"],
            "model_id": a["model_id"],
            "variant": a["variant"],
            "requests": a["requests"],
            "avg_prompt_tokens_per_request": a["avg_prompt_tokens_per_request"],
            "avg_completion_tokens_per_request": a["avg_completion_tokens_per_request"],
            "completion_to_prompt_ratio": a["completion_to_prompt_ratio"],
            "cache_hit_share_of_prompt": a["cache_hit_share_of_prompt"],
            "effective_input_usd_per_mtok": ein,
            "effective_output_usd_per_mtok": eout,
            "blended_effective_usd_per_mtok": round(cost / total * 1_000_000, 6),
            "blended_listed_usd_per_mtok": (round(listed_cost / total * 1_000_000, 6)
                                            if listed_cost is not None else None),
            "effective_usd_per_request": round(cost / a["requests"], 8) if a["requests"] else None,
        })
    return out


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def write_csv(path: str, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  wrote {len(rows):>7,} rows -> {os.path.relpath(path)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--range", default="all", choices=RANGES,
                    help="history window to request (default: all)")
    ap.add_argument("--models", nargs="*", default=None,
                    help="limit to these model ids (default: every model)")
    ap.add_argument("--activity", action="store_true",
                    help="also pull daily prompt/completion token volumes (last ~31 "
                         "days) and derive per-request sequence lengths and a "
                         "blended price")
    ap.add_argument("--listed", action="store_true",
                    help="also pull the listed-price change log for comparison")
    ap.add_argument("--workers", type=int, default=8, help="parallel requests")
    ap.add_argument("--out", default=OUT_DIR, help="output directory")
    ap.add_argument("--raw", action="store_true",
                    help="also dump the raw API responses to raw_effective.json")
    args = ap.parse_args()

    models = list_models()
    if args.models:
        wanted = set(args.models)
        models = [m for m in models if m["model_id"] in wanted]
        missing = wanted - {m["model_id"] for m in models}
        if missing:
            print(f"! unknown model ids: {', '.join(sorted(missing))}", file=sys.stderr)
    print(f"fetching effective prices (range={args.range}) for {len(models)} models")

    daily_rows: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []
    model_rows: List[Dict[str, Any]] = []
    listed_rows: List[Dict[str, Any]] = []
    activity_rows: List[Dict[str, Any]] = []
    raw: Dict[str, Any] = {}
    no_data: List[str] = []

    def work(model: Dict[str, Any]):
        data = fetch_effective(model, args.range)
        listed = fetch_listed(model, args.range) if args.listed else []
        activity = fetch_activity(model) if args.activity else []
        return model, data, listed, activity

    done = 0
    with futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for model, data, listed, activity in pool.map(work, models):
            done += 1
            if done % 25 == 0 or done == len(models):
                print(f"  {done}/{len(models)}")
            listed_rows.extend(listed)
            activity_rows.extend(activity)
            if not data or not data.get("inputChartData"):
                no_data.append(model["model_id"])
                continue
            if args.raw:
                raw[model["model_id"]] = data
            daily, summaries = flatten_effective(model, data)
            daily_rows.extend(daily)
            summary_rows.extend(summaries)
            model_rows.extend(model_level_daily(model, data, daily))

    daily_rows.sort(key=lambda r: (r["model_id"], r["date"], r["provider_name"] or ""))
    model_rows.sort(key=lambda r: (r["model_id"], r["date"]))
    summary_rows.sort(key=lambda r: (r["model_id"], -(r["total_tokens"] or 0)))

    write_csv(os.path.join(args.out, "effective_prices_daily_by_endpoint.csv"), daily_rows,
              ["date", "model_id", "permaslug", "variant", "endpoint_id", "provider_name",
               "provider_slug", "effective_input_usd_per_mtok",
               "effective_output_usd_per_mtok"])
    write_csv(os.path.join(args.out, "effective_prices_daily_by_model.csv"), model_rows,
              ["date", "model_id", "permaslug", "variant", "n_endpoints",
               "effective_input_usd_per_mtok", "effective_output_usd_per_mtok",
               "listed_input_usd_per_mtok_current",
               "listed_output_usd_per_mtok_current"])
    write_csv(os.path.join(args.out, "effective_prices_summary.csv"), summary_rows,
              ["model_id", "permaslug", "variant", "endpoint_id", "provider_name",
               "provider_slug", "effective_input_usd_per_mtok",
               "effective_output_usd_per_mtok", "cache_hit_rate", "total_tokens"])
    if args.activity:
        activity_rows.sort(key=lambda r: (r["model_id"], r["date"]))
        write_csv(os.path.join(args.out, "token_mix_daily_by_model.csv"), activity_rows,
                  ["date", "model_id", "permaslug", "variant", "requests",
                   "prompt_tokens", "completion_tokens", "cached_prompt_tokens",
                   "reasoning_tokens", "avg_prompt_tokens_per_request",
                   "avg_completion_tokens_per_request",
                   "avg_reasoning_tokens_per_request", "completion_to_prompt_ratio",
                   "cache_hit_share_of_prompt", "tool_calls", "media_prompt_requests"])
        blended = blend(model_rows, activity_rows)
        blended.sort(key=lambda r: (r["model_id"], r["date"]))
        write_csv(os.path.join(args.out, "blended_price_daily_by_model.csv"), blended,
                  ["date", "model_id", "variant", "requests",
                   "avg_prompt_tokens_per_request", "avg_completion_tokens_per_request",
                   "completion_to_prompt_ratio", "cache_hit_share_of_prompt",
                   "effective_input_usd_per_mtok", "effective_output_usd_per_mtok",
                   "blended_effective_usd_per_mtok", "blended_listed_usd_per_mtok",
                   "effective_usd_per_request"])
    if args.listed:
        write_csv(os.path.join(args.out, "listed_price_changes.csv"), listed_rows,
                  ["changed_at", "model_id", "permaslug", "variant", "endpoint_id",
                   "provider_name", "provider_slug", "field", "value"])
    if args.raw:
        raw_path = os.path.join(args.out, "raw_effective.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=1)
        print(f"  wrote raw responses -> {os.path.relpath(raw_path)}")

    nonzero = {r["model_id"] for r in model_rows
               if (r["effective_input_usd_per_mtok"] or 0)
               or (r["effective_output_usd_per_mtok"] or 0)}
    covered = len({r["model_id"] for r in daily_rows})
    dates = sorted({r["date"] for r in daily_rows})
    print(f"\n{covered}/{len(models)} models have an effective-price history"
          f"{' (' + dates[0] + ' .. ' + dates[-1] + ')' if dates else ''}")
    zeroed = sorted({r["model_id"] for r in model_rows} - nonzero)
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
