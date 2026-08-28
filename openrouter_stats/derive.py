"""Everything in this module is **computed by us**, not returned by OpenRouter.

Nothing here calls the API. Every value it produces is arithmetic over rows from
``pull.py``, and every function documents its formula and its weakness. If a
column is not produced here, it came off the API verbatim.

Three things are derived:

1. ``model_daily_prices`` — one effective price per model per day, weighting the
   per-endpoint prices by traffic.
2. ``token_mix`` — per-request sequence lengths and cache share, from raw token
   and request counts.
3. ``blended_prices`` — a single $/M figure, weighting input against output by
   the actual prompt:completion split.
4. ``provider_ranking`` — per-endpoint medians of the daily performance series,
   ranked, with prices joined on.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, Iterable, List, Optional, Tuple

MTOK = 1_000_000


def _div(num: float, den: float, places: int) -> Optional[float]:
    return round(num / den, places) if den else None


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


def model_daily_prices(model: Dict[str, Any], effective_data: Dict[str, Any],
                       daily: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse the per-endpoint daily prices to one price per model per day.

    ``effective_input  = SUM(price_e x tokens_e) / SUM(tokens_e)`` over the
    endpoints live that day, and likewise for output.

    Known weakness: the API reports token volume per endpoint over the **whole
    window**, not per day, so the weights are window-wide and merely
    renormalised over the endpoints live on each day. A model whose routing mix
    moved during the window will drift on individual days. Where no volume is
    reported at all, endpoints are weighted equally. Per-endpoint prices are
    exact; only this collapse is approximate.

    The two ``*_current`` columns are today's headline price from the models
    API, repeated on every row as a reference line. They are a snapshot, not
    history.
    """
    weights = {s["endpointId"]: float(s.get("totalTokens") or 0)
               for s in effective_data.get("providerSummaries", [])}

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for row in daily:
        by_date.setdefault(row["date"], []).append(row)

    return [{
        "date": date,
        "model_id": model["model_id"],
        "permaslug": model["permaslug"],
        "variant": model["variant"],
        "n_endpoints": len(entries),
        "effective_input_usd_per_mtok":
            _weighted(entries, "effective_input_usd_per_mtok", weights),
        "effective_output_usd_per_mtok":
            _weighted(entries, "effective_output_usd_per_mtok", weights),
        "listed_input_usd_per_mtok_current": model["listed_input_usd_per_mtok"],
        "listed_output_usd_per_mtok_current": model["listed_output_usd_per_mtok"],
    } for date, entries in sorted(by_date.items())]


def token_mix(activity_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-request sequence lengths and cache share from raw daily counts.

    ``avg_prompt_tokens_per_request  = prompt_tokens / requests``
    ``completion_to_prompt_ratio     = completion_tokens / prompt_tokens``
    ``cache_hit_share_of_prompt      = cached_prompt_tokens / prompt_tokens``

    These are per **request**, so multi-turn conversations that resend history
    inflate the input side. That is the real billing shape, not the
    per-conversation payload.
    """
    out = []
    for a in activity_rows:
        req, prompt = a["requests"], a["prompt_tokens"]
        row = dict(a)
        row.update({
            "avg_prompt_tokens_per_request": _div(prompt, req, 1),
            "avg_completion_tokens_per_request": _div(a["completion_tokens"], req, 1),
            "avg_reasoning_tokens_per_request": _div(a["reasoning_tokens"], req, 1),
            "completion_to_prompt_ratio": _div(a["completion_tokens"], prompt, 4),
            "cache_hit_share_of_prompt": _div(a["cached_prompt_tokens"], prompt, 4),
        })
        out.append(row)
    return out


def blended_prices(model_rows: List[Dict[str, Any]],
                   mix_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Join effective prices to the token mix to get a single blended price.

    The API never blends: input and output are separate series, so one headline
    $/M figure only exists once weighted by the real prompt:completion split.

        cost    = (prompt x eff_in + completion x eff_out) / 1e6
        blended = cost / (prompt + completion) x 1e6

    This is only valid because ``effective_input`` is a cost per **total**
    prompt token with cached tokens in the denominator — verified by
    ``openrouter_checks.py``, so the cache discount is not counted twice.

    For image and audio models the result is not a text-token price: non-text
    tokens are priced far above the text rate and are mixed into both series.
    """
    prices = {(r["model_id"], r["date"]): r for r in model_rows}
    out = []
    for a in mix_rows:
        p = prices.get((a["model_id"], a["date"]))
        if not p:
            continue
        ein, eout = (p["effective_input_usd_per_mtok"],
                     p["effective_output_usd_per_mtok"])
        prompt, completion = a["prompt_tokens"], a["completion_tokens"]
        total = prompt + completion
        if ein is None or eout is None or not total:
            continue
        cost = (prompt * ein + completion * eout) / MTOK
        lin, lout = (p["listed_input_usd_per_mtok_current"],
                     p["listed_output_usd_per_mtok_current"])
        listed_cost = ((prompt * lin + completion * lout) / MTOK
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
            "blended_effective_usd_per_mtok": round(cost / total * MTOK, 6),
            "blended_listed_usd_per_mtok": (round(listed_cost / total * MTOK, 6)
                                            if listed_cost is not None else None),
            "effective_usd_per_request": (round(cost / a["requests"], 8)
                                          if a["requests"] else None),
        })
    return out


def provider_ranking(perf_rows: List[Dict[str, Any]],
                     summary_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Median each endpoint's daily performance, join prices, and rank.

    A median over the daily points stops one bad day deciding the ranking. Two
    rankings are given because they disagree constantly: ``throughput_rank``
    (fastest writer first) and ``ttft_rank`` (quickest to respond first). The
    cheapest endpoint is rarely either, which is why the prices ride along.

    Only 8 days of performance data exist, so a rank is a current snapshot.
    """
    price = {(r["model_id"], r["endpoint_id"]): r for r in summary_rows}

    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for r in perf_rows:
        grouped.setdefault((r["model_id"], r["endpoint_id"], r["colo"]), []).append(r)

    out = []
    for (model_id, endpoint_id, colo), rows in grouped.items():
        p = price.get((model_id, endpoint_id), {})
        row = {
            "model_id": model_id,
            "endpoint_id": endpoint_id,
            "colo": colo,
            "provider_name": rows[0]["provider_name"] or p.get("provider_name") or "",
            "provider_slug": rows[0]["provider_slug"] or p.get("provider_slug") or "",
            "percentile": rows[0]["percentile"],
            "days_observed": len(rows),
            "effective_input_usd_per_mtok": p.get("effective_input_usd_per_mtok"),
            "effective_output_usd_per_mtok": p.get("effective_output_usd_per_mtok"),
            "total_tokens": p.get("total_tokens"),
        }
        for column in ("throughput_tok_s", "ttft_ms", "e2e_ms"):
            vals = [r[column] for r in rows if r[column] is not None]
            row[column] = round(statistics.median(vals), 2) if vals else None
        out.append(row)

    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for r in out:
        by_model.setdefault(r["model_id"], []).append(r)
    for rows in by_model.values():
        for rank, r in enumerate(sorted(
                rows, key=lambda x: -(x["throughput_tok_s"] or 0)), start=1):
            r["throughput_rank"] = rank
        for rank, r in enumerate(sorted(
                rows, key=lambda x: (x["ttft_ms"] is None, x["ttft_ms"] or 0)), start=1):
            r["ttft_rank"] = rank
    return out
