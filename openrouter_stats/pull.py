"""Everything in this module is **pulled**, not computed.

Each function reshapes one API response into flat rows. Values are carried
across verbatim; the only liberties taken are renaming keys, unnesting, and
converting OpenRouter's $/token prices to $/M tokens (a x1e6 unit change, noted
per column in the data dictionary). No averaging, weighting or blending happens
here — that all lives in ``derive.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .api import (ACTIVITY_URL, BENCHMARK_URL, CACHE_HIT_URL, EFFECTIVE_SHAPE,
                  EFFECTIVE_URL, ENDPOINT_URL, LISTED_SHAPE, LISTED_URL,
                  MODELS_URL, PERF_URLS, PROVIDERS_URL, STRUCT_ERROR_URL,
                  PROVIDER_TOKENS_URL, TOOL_ERROR_URL, TOP_APPS_URL, TOP_COLOS_URL,
                  UPTIME_URL,
                  data_of, get_json)

MTOK = 1_000_000


def per_mtok(price: Any) -> Optional[float]:
    """OpenRouter quotes $/token; every price column here is $/M tokens."""
    if price is None or price == "":
        return None
    try:
        return float(price) * MTOK
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Catalogue
# --------------------------------------------------------------------------- #

def models() -> List[Dict[str, Any]]:
    """Every model, with the (permaslug, variant) pair the stats API keys on.

    ``canonical_slug`` is the permaslug; the variant is the ``:suffix`` on the
    model id (``:free``, ``:batch``), defaulting to ``standard``.
    """
    payload = get_json(MODELS_URL)
    if not payload:
        raise SystemExit("could not fetch the OpenRouter model list")
    out = []
    for m in payload["data"]:
        model_id = m["id"]
        pricing = m.get("pricing") or {}
        out.append({
            "model_id": model_id,
            "permaslug": m["canonical_slug"],
            "variant": model_id.split(":", 1)[1] if ":" in model_id else "standard",
            "name": m.get("name") or model_id,
            "created": m.get("created"),
            "context_length": m.get("context_length"),
            "modality": (m.get("architecture") or {}).get("modality"),
            "tokenizer": (m.get("architecture") or {}).get("tokenizer"),
            "listed_input_usd_per_mtok": per_mtok(pricing.get("prompt")),
            "listed_output_usd_per_mtok": per_mtok(pricing.get("completion")),
            "listed_cache_read_usd_per_mtok": per_mtok(pricing.get("input_cache_read")),
        })
    return out


def providers() -> List[Dict[str, Any]]:
    """The provider directory: policies, headquarters, datacenter regions."""
    rows = []
    for p in data_of(get_json(PROVIDERS_URL)) or []:
        rows.append({
            "provider_name": p.get("name"),
            "provider_slug": p.get("slug"),
            "headquarters": p.get("headquarters"),
            "datacenters": "|".join(p.get("datacenters") or []),
            "privacy_policy_url": p.get("privacy_policy_url"),
            "terms_of_service_url": p.get("terms_of_service_url"),
            "status_page_url": p.get("status_page_url"),
        })
    return rows


def endpoints(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The full per-endpoint record: listed pricing, limits, policy, p50-p99.

    This is the only source that carries the endpoint **id**, which is what
    every daily series is keyed on, so it is the join table for the whole
    dataset. ``stats`` here is a rolling 30-minute window, distinct from the
    daily performance series in ``performance()``.
    """
    rows = []
    for e in data_of(get_json(ENDPOINT_URL, {"permaslug": model["permaslug"],
                                             "variant": model["variant"]})) or []:
        pricing = e.get("pricing") or {}
        stats = e.get("stats") or {}
        policy = e.get("data_policy") or {}
        overrides = pricing.get("overrides") or []
        first = overrides[0] if overrides else {}
        rows.append({
            "model_id": model["model_id"],
            "permaslug": model["permaslug"],
            "variant": model["variant"],
            "endpoint_id": e.get("id"),
            "provider_name": e.get("provider_display_name") or e.get("provider_name"),
            "provider_slug": e.get("provider_slug"),
            "provider_region": e.get("provider_region"),
            "quantization": e.get("quantization"),
            "context_length": e.get("context_length"),
            "max_completion_tokens": e.get("max_completion_tokens"),
            "max_prompt_tokens": e.get("max_prompt_tokens"),
            "capacity_tpm": e.get("capacity_tpm"),
            "limit_rpm": e.get("limit_rpm"),
            "limit_rpd": e.get("limit_rpd"),
            "status": e.get("status"),
            "is_disabled": e.get("is_disabled"),
            "is_deranked": e.get("is_deranked"),
            "is_free": e.get("is_free"),
            "is_byok": e.get("is_byok"),
            "is_hidden": e.get("is_hidden"),
            "moderation_required": e.get("moderation_required"),
            "supports_reasoning": e.get("supports_reasoning"),
            "supports_implicit_caching": e.get("supports_implicit_caching"),
            "listed_input_usd_per_mtok": per_mtok(pricing.get("prompt")),
            "listed_output_usd_per_mtok": per_mtok(pricing.get("completion")),
            "listed_cache_read_usd_per_mtok": per_mtok(pricing.get("input_cache_read")),
            "listed_cache_write_usd_per_mtok": per_mtok(pricing.get("input_cache_write")),
            "listed_cache_write_1h_usd_per_mtok": per_mtok(pricing.get("input_cache_write_1h")),
            "listed_web_search_usd_per_call": pricing.get("web_search"),
            "discount": pricing.get("discount"),
            "n_price_tiers": len(overrides),
            "tier_min_prompt_tokens": first.get("min_prompt_tokens"),
            "tier_input_usd_per_mtok": per_mtok(first.get("prompt")),
            "tier_output_usd_per_mtok": per_mtok(first.get("completion")),
            "policy_trains_on_prompts": policy.get("training"),
            "policy_retains_prompts": policy.get("retainsPrompts"),
            "policy_can_publish": policy.get("canPublish"),
            "policy_requires_user_ids": policy.get("requiresUserIDs"),
            "p50_throughput_tok_s": stats.get("p50_throughput"),
            "p90_throughput_tok_s": stats.get("p90_throughput"),
            "p99_throughput_tok_s": stats.get("p99_throughput"),
            "p50_latency_ms": stats.get("p50_latency"),
            "p90_latency_ms": stats.get("p90_latency"),
            "p99_latency_ms": stats.get("p99_latency"),
            "stats_request_count": stats.get("request_count"),
            "stats_window_minutes": stats.get("window_minutes"),
            "created_at": e.get("created_at"),
        })
    return rows


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #

def effective(model: Dict[str, Any], rng: str) -> Optional[Dict[str, Any]]:
    """Raw effective-pricing response: daily per-endpoint series + summaries."""
    return data_of(get_json(EFFECTIVE_URL, {
        "permaslug": model["permaslug"], "variant": model["variant"],
        "shape": EFFECTIVE_SHAPE, "range": rng}))


def effective_rows(model: Dict[str, Any], data: Dict[str, Any]
                   ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split one effective-pricing response into daily rows and summary rows.

    ``inputChartData``/``outputChartData`` are parallel daily series keyed by
    endpoint id, joined here on (date, endpoint). An endpoint that served no
    traffic on a day is simply absent from that day's bucket.

    Note ``totalTokens`` on the summary rows measures a rolling ~24 hours, not
    the requested range — it is a current-traffic figure sitting alongside a
    multi-month price history.
    """
    summaries = {s["endpointId"]: s for s in data.get("providerSummaries", [])}
    names = data.get("endpointNames", {}) or {}
    slugs = data.get("endpointProviderSlugs", {}) or {}
    outputs = {p["x"]: (p.get("y") or {}) for p in data.get("outputChartData", [])}

    daily = []
    for point in data.get("inputChartData", []):
        out_bucket = outputs.get(point["x"], {})
        for endpoint_id, in_price in (point.get("y") or {}).items():
            s = summaries.get(endpoint_id, {})
            daily.append({
                "date": str(point["x"])[:10],
                "model_id": model["model_id"],
                "permaslug": model["permaslug"],
                "variant": model["variant"],
                "endpoint_id": endpoint_id,
                "provider_name": s.get("providerName") or names.get(endpoint_id, ""),
                "provider_slug": s.get("providerSlug") or slugs.get(endpoint_id, ""),
                "effective_input_usd_per_mtok": in_price,
                "effective_output_usd_per_mtok": out_bucket.get(endpoint_id),
            })

    summary = [{
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
    return daily, summary


def listed(model: Dict[str, Any], rng: str) -> List[Dict[str, Any]]:
    """Listed-price change log. Sparse by design: change points, not a series."""
    data = data_of(get_json(LISTED_URL, {
        "permaslug": model["permaslug"], "variant": model["variant"],
        "shape": LISTED_SHAPE, "range": rng}))
    if not data:
        return []
    fields = (("input", "listed_input_usd_per_mtok"),
              ("output", "listed_output_usd_per_mtok"),
              ("cacheRead", "listed_cache_read_usd_per_mtok"),
              ("cacheWrite", "listed_cache_write_usd_per_mtok"),
              ("discount", "discount_fraction"))
    rows = []
    for series in data.get("series", []):
        for key, column in fields:
            for point in series.get(key) or []:
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
# Volumes, performance, reliability, quality
# --------------------------------------------------------------------------- #

def activity(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Daily token volumes split prompt vs completion.

    Takes no range parameter and always returns the last ~31 days.
    """
    data = data_of(get_json(ACTIVITY_URL, {"permaslug": model["permaslug"],
                                           "variant": model["variant"]}))
    rows = []
    for a in (data or {}).get("analytics", []):
        rows.append({
            "date": str(a["date"])[:10],
            "model_id": model["model_id"],
            "permaslug": model["permaslug"],
            "variant": model["variant"],
            "requests": a.get("count") or 0,
            "prompt_tokens": a.get("total_prompt_tokens") or 0,
            "completion_tokens": a.get("total_completion_tokens") or 0,
            "cached_prompt_tokens": a.get("total_native_tokens_cached") or 0,
            "reasoning_tokens": a.get("total_native_tokens_reasoning") or 0,
            "tool_calls": a.get("total_tool_calls") or 0,
            "requests_with_tool_call_errors": a.get("requests_with_tool_call_errors") or 0,
            "media_prompt_requests": a.get("num_media_prompt") or 0,
            "audio_prompt_requests": a.get("num_audio_prompt") or 0,
            "image_output_requests": a.get("image_output_requests") or 0,
        })
    return rows


def performance(model: Dict[str, Any], rng: str, percentile: str,
                names: Dict[str, str], slugs: Dict[str, str]) -> List[Dict[str, Any]]:
    """Daily throughput, time-to-first-token and time-to-last-token.

    Three series joined on (date, endpoint, colo). ``percentile`` is omitted for
    p50 because that is the API's own default. Despite accepting a timeRange,
    these endpoints always return the last 8 days.
    """
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for column, url in PERF_URLS.items():
        params = {"permaslug": model["permaslug"], "variant": model["variant"],
                  "timeRange": rng}
        if percentile != "p50":
            params["percentile"] = percentile
        for point in data_of(get_json(url, params)) or []:
            date = str(point["x"])[:10]
            for key, value in (point.get("y") or {}).items():
                endpoint_id, _, colo = key.partition("::")
                row = merged.setdefault((date, key), {
                    "date": date, "model_id": model["model_id"],
                    "permaslug": model["permaslug"], "variant": model["variant"],
                    "endpoint_id": endpoint_id, "colo": colo or "default",
                    "provider_name": names.get(endpoint_id, ""),
                    "provider_slug": slugs.get(endpoint_id, ""),
                    "percentile": percentile,
                    "throughput_tok_s": None, "ttft_ms": None, "e2e_ms": None,
                })
                row[column] = value
    return list(merged.values())


def _keyed_daily(url: str, model: Dict[str, Any], rng: str, column: str,
                 volume_column: Optional[str] = None) -> List[Dict[str, Any]]:
    """Shared shape: [{x: date, y: {endpointId: value}, volume?: {...}}]."""
    rows = []
    for point in data_of(get_json(url, {"permaslug": model["permaslug"],
                                        "variant": model["variant"],
                                        "timeRange": rng})) or []:
        volumes = point.get("volume") or {}
        for endpoint_id, value in (point.get("y") or {}).items():
            row = {"date": str(point["x"])[:10], "model_id": model["model_id"],
                   "permaslug": model["permaslug"], "variant": model["variant"],
                   "endpoint_id": endpoint_id, column: value}
            if volume_column:
                row[volume_column] = volumes.get(endpoint_id)
            rows.append(row)
    return rows


def cache_hit_rate(model: Dict[str, Any], rng: str) -> List[Dict[str, Any]]:
    """Daily per-endpoint cache hit rate, as a percentage (0-100)."""
    return _keyed_daily(CACHE_HIT_URL, model, rng, "cache_hit_rate_pct")


def tool_call_errors(model: Dict[str, Any], rng: str) -> List[Dict[str, Any]]:
    """Daily per-endpoint tool-call error rate (%) and the call volume behind it."""
    return _keyed_daily(TOOL_ERROR_URL, model, rng, "tool_call_error_rate_pct",
                        "tool_call_volume")


def structured_output_errors(model: Dict[str, Any], rng: str) -> List[Dict[str, Any]]:
    """Daily per-endpoint structured-output error rate (%) and request volume."""
    return _keyed_daily(STRUCT_ERROR_URL, model, rng,
                        "structured_output_error_rate_pct", "structured_output_volume")


def uptime(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Recent availability in 10-minute buckets, model-wide.

    ``availability`` counts OpenRouter's fallback routing as a success;
    ``availability_without_routing`` is what a single-provider caller would see.
    """
    data = data_of(get_json(UPTIME_URL, {"permaslug": model["permaslug"],
                                         "variant": model["variant"]}))
    return [{
        "timestamp": b.get("timestamp"),
        "model_id": model["model_id"],
        "permaslug": model["permaslug"],
        "variant": model["variant"],
        "availability_pct": b.get("availability"),
        "availability_without_routing_pct": b.get("availabilityWithoutRouting"),
    } for b in (data or {}).get("buckets", [])]


def benchmarks(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Benchmark scores per endpoint. ``endpoint_id`` is null for auto-routing."""
    data = data_of(get_json(BENCHMARK_URL, {"permaslug": model["permaslug"]}))
    return [{
        "model_id": model["model_id"],
        "permaslug": model["permaslug"],
        "benchmark_type": s.get("benchmark_type"),
        "provider_name": s.get("display_name") or s.get("provider_name"),
        "endpoint_id": s.get("endpoint_id"),
        "score": s.get("score"),
        "run_count": s.get("run_count"),
    } for s in (data or {}).get("scores", [])]


def top_apps(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The public apps sending the most tokens to this model."""
    data = data_of(get_json(TOP_APPS_URL, {"permaslug": model["permaslug"],
                                           "variant": model["variant"]}))
    rows = []
    for a in (data or {}).get("top_apps", []):
        app = a.get("app") or {}
        rows.append({
            "model_id": model["model_id"],
            "permaslug": model["permaslug"],
            "variant": model["variant"],
            "rank": a.get("rank"),
            "app_id": a.get("app_id"),
            "app_title": app.get("title"),
            "app_slug": app.get("slug"),
            "app_origin_url": app.get("origin_url"),
            "app_categories": "|".join(app.get("categories") or []),
            "total_tokens": a.get("total_tokens"),
            "total_requests": a.get("total_requests"),
        })
    return rows


def top_colos(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Datacenter locations serving this model, in OpenRouter's own order."""
    data = data_of(get_json(TOP_COLOS_URL, {"permaslug": model["permaslug"],
                                            "variant": model["variant"]}))
    return [{
        "model_id": model["model_id"],
        "permaslug": model["permaslug"],
        "variant": model["variant"],
        "rank": i,
        "colo": colo,
    } for i, colo in enumerate((data or {}).get("colos", []), start=1)]


def provider_token_chart(provider_slug: str) -> List[Dict[str, Any]]:
    """Daily tokens served by one provider, broken out by model.

    Takes a provider slug and no model, so this is the only source of a
    provider-level volume history: 90 days, against the 24 hours behind
    ``total_tokens`` elsewhere. Each day lists the provider's top 9 models plus
    an ``Others`` bucket, so the **daily total is complete** even though the
    per-model breakdown is not. ``model_permaslug`` is a permaslug, not a model
    id — join it to ``model_catalogue.permaslug``.
    """
    data = data_of(get_json(PROVIDER_TOKENS_URL, {"provider": provider_slug}))
    rows = []
    for point in (data or {}).get("chartData", []):
        for permaslug, tokens in (point.get("ys") or {}).items():
            rows.append({
                "date": str(point["x"])[:10],
                "provider_slug": provider_slug,
                "model_permaslug": permaslug,
                "tokens": tokens,
            })
    return rows
