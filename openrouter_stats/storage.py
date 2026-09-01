"""CSV output, and the column order for every file in the dataset."""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, List

# Column order per output file. Every name here is either carried verbatim from
# the API (see pull.py) or computed (see derive.py) — the data dictionary in
# data/openrouter/README.md marks which for each one.
SCHEMAS: Dict[str, List[str]] = {
    "model_catalogue": [
        "model_id", "permaslug", "variant", "name", "created", "context_length",
        "modality", "tokenizer", "listed_input_usd_per_mtok",
        "listed_output_usd_per_mtok", "listed_cache_read_usd_per_mtok"],
    "provider_catalogue": [
        "provider_name", "provider_slug", "headquarters", "datacenters",
        "privacy_policy_url", "terms_of_service_url", "status_page_url"],
    "endpoint_catalogue": [
        "model_id", "permaslug", "variant", "endpoint_id", "provider_name",
        "provider_slug", "provider_region", "quantization", "context_length",
        "max_completion_tokens", "max_prompt_tokens", "capacity_tpm", "limit_rpm",
        "limit_rpd", "status", "is_disabled", "is_deranked", "is_free", "is_byok",
        "is_hidden", "moderation_required", "supports_reasoning",
        "supports_implicit_caching", "listed_input_usd_per_mtok",
        "listed_output_usd_per_mtok", "listed_cache_read_usd_per_mtok",
        "listed_cache_write_usd_per_mtok", "listed_cache_write_1h_usd_per_mtok",
        "listed_web_search_usd_per_call", "discount", "n_price_tiers",
        "tier_min_prompt_tokens", "tier_input_usd_per_mtok",
        "tier_output_usd_per_mtok", "policy_trains_on_prompts",
        "policy_retains_prompts", "policy_can_publish", "policy_requires_user_ids",
        "p50_throughput_tok_s", "p75_throughput_tok_s", "p90_throughput_tok_s",
        "p95_throughput_tok_s", "p99_throughput_tok_s", "p50_latency_ms",
        "p75_latency_ms", "p90_latency_ms", "p95_latency_ms", "p99_latency_ms",
        "stats_request_count", "stats_window_minutes", "created_at"],
    "endpoint_price_tiers": [
        "model_id", "permaslug", "variant", "endpoint_id", "provider_name",
        "sku_label", "tier_index", "tier_label", "price", "unit_label",
        "display_multiplier"],
    "endpoint_pricing_raw": [
        "model_id", "permaslug", "variant", "endpoint_id", "provider_name",
        "pricing_key", "value"],
    "endpoint_uptime_daily": [
        "date", "model_id", "permaslug", "variant", "endpoint_id", "uptime_pct"],
    "endpoint_uptime_hourly": [
        "hour", "endpoint_id", "uptime_pct"],
    "effective_prices_daily_by_endpoint": [
        "date", "model_id", "permaslug", "variant", "endpoint_id", "provider_name",
        "provider_slug", "effective_input_usd_per_mtok",
        "effective_output_usd_per_mtok"],
    "effective_prices_daily_by_model": [
        "date", "model_id", "permaslug", "variant", "n_endpoints",
        "effective_input_usd_per_mtok", "effective_output_usd_per_mtok",
        "listed_input_usd_per_mtok_current", "listed_output_usd_per_mtok_current"],
    "model_price_headline": [
        "model_id", "permaslug", "variant", "n_endpoints",
        "weighted_input_usd_per_mtok", "weighted_output_usd_per_mtok",
        "weighted_cache_hit_rate"],
    "effective_prices_summary": [
        "model_id", "permaslug", "variant", "endpoint_id", "provider_name",
        "provider_slug", "effective_input_usd_per_mtok",
        "effective_output_usd_per_mtok", "cache_hit_rate", "total_tokens"],
    "listed_price_changes": [
        "changed_at", "model_id", "permaslug", "variant", "endpoint_id",
        "provider_name", "provider_slug", "field", "value"],
    "token_mix_daily_by_model": [
        "date", "model_id", "permaslug", "variant", "requests", "prompt_tokens",
        "completion_tokens", "cached_prompt_tokens", "reasoning_tokens",
        "avg_prompt_tokens_per_request", "avg_completion_tokens_per_request",
        "avg_reasoning_tokens_per_request", "completion_to_prompt_ratio",
        "cache_hit_share_of_prompt", "tool_calls", "requests_with_tool_call_errors",
        "media_prompt_requests", "audio_prompt_requests", "image_output_requests"],
    "blended_price_daily_by_model": [
        "date", "model_id", "variant", "requests", "avg_prompt_tokens_per_request",
        "avg_completion_tokens_per_request", "completion_to_prompt_ratio",
        "cache_hit_share_of_prompt", "effective_input_usd_per_mtok",
        "effective_output_usd_per_mtok", "blended_effective_usd_per_mtok",
        "blended_listed_usd_per_mtok", "effective_usd_per_request"],
    "performance_daily_by_endpoint": [
        "date", "model_id", "permaslug", "variant", "endpoint_id", "colo",
        "provider_name", "provider_slug", "percentile", "throughput_tok_s",
        "ttft_ms", "e2e_ms"],
    "cache_hit_rate_daily_by_endpoint": [
        "date", "model_id", "permaslug", "variant", "endpoint_id",
        "cache_hit_rate_pct"],
    "tool_call_error_rate_daily": [
        "date", "model_id", "permaslug", "variant", "endpoint_id",
        "tool_call_error_rate_pct", "tool_call_volume"],
    "structured_output_error_rate_daily": [
        "date", "model_id", "permaslug", "variant", "endpoint_id",
        "structured_output_error_rate_pct", "structured_output_volume"],
    "model_uptime_recent": [
        "timestamp", "model_id", "permaslug", "variant", "availability_pct",
        "availability_without_routing_pct"],
    "benchmark_scores": [
        "model_id", "permaslug", "benchmark_type", "provider_name", "endpoint_id",
        "score", "run_count"],
    "top_apps_by_model": [
        "model_id", "permaslug", "variant", "rank", "app_id", "app_title",
        "app_slug", "app_origin_url", "app_categories", "total_tokens",
        "total_requests"],
    "provider_token_daily": [
        "date", "provider_slug", "model_permaslug", "tokens"],
    "provider_summary": [
        "token_rank", "provider_slug", "provider_name", "headquarters", "n_models",
        "n_endpoints", "tokens_last_24h", "share_of_tokens_pct",
        "n_endpoints_training_on_prompts"],
    "top_colos_by_model": [
        "model_id", "permaslug", "variant", "rank", "colo"],
}


def write(out_dir: str, stem: str, rows: List[Dict[str, Any]]) -> None:
    path = os.path.join(out_dir, f"{stem}.csv")
    os.makedirs(out_dir, exist_ok=True)
    fields = SCHEMAS[stem]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  {len(rows):>8,} rows -> {stem}.csv")
