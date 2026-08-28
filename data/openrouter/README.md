# OpenRouter model, price and performance data

Historical **effective** token prices for every model on OpenRouter — the $/M
tokens customers actually paid, not the rate providers post — plus the endpoint
catalogue, token volumes, throughput/latency, reliability and benchmark scores
that explain them.

```bash
python3 scripts/openrouter_prices.py --all     # everything below
python3 scripts/openrouter_prices.py           # prices only
python3 scripts/openrouter_prices.py --activity --performance
python3 scripts/openrouter_checks.py           # validate the result
```

A full `--all` run is ~5,400 requests over ~4.5 minutes and needs no API key.

---

## Pulled vs calculated

**Almost everything here is pulled.** Four things are ours, and the split is
structural, not just documented:

| module | role |
|---|---|
| `openrouter_stats/pull.py` | every API call. Renames keys and unnests; converts $/token to $/M tokens. **No arithmetic.** |
| `openrouter_stats/derive.py` | every calculation. **Makes no API calls.** |

So: if a column is not listed in the four blocks below, it came off the API
verbatim. In the data dictionary each column is tagged:

- **`API`** — the response value, unchanged
- **`API×1e6`** — the response value, converted from $/token to $/M tokens
- **`CALC`** — computed by us; the formula is given

### The four things we calculate

1. **Model-level daily price** — endpoint prices weighted by traffic
   (`derive.model_daily_prices`)
2. **Sequence lengths and cache share** — token counts divided by request counts
   (`derive.token_mix`)
3. **Blended price** — input weighted against output by the real prompt:completion
   split (`derive.blended_prices`)
4. **Provider ranking** — medians of the daily performance series, ranked
   (`derive.provider_ranking`)
5. **Provider rollup** — per-model-endpoint rows aggregated to one row per
   provider (`derive.provider_summary`)

### Source endpoints

| API | endpoint | feeds |
|---|---|---|
| public | `/api/v1/models` | `model_catalogue` |
| public | `/api/v1/providers` | `provider_catalogue` |
| front-end | `/stats/endpoint` | `endpoint_catalogue` |
| front-end | `/stats/effective-pricing` | the three `effective_prices_*` files |
| front-end | `/stats/listed-pricing` | `listed_price_changes` |
| front-end | `/stats/model-activity` | `token_mix_daily_by_model` |
| front-end | `/stats/throughput-comparison`, `/stats/latency-comparison`, `/stats/latency-e2e-comparison` | `performance_daily_by_endpoint` |
| front-end | `/stats/cache-hit-rate-comparison` | `cache_hit_rate_daily_by_endpoint` |
| front-end | `/stats/tool-call-error-rate`, `/stats/structured-output-error-rate` | the two `*_error_rate_*` files |
| front-end | `/stats/model-uptime-recent` | `model_uptime_recent` |
| front-end | `/stats/benchmark-scores` | `benchmark_scores` |
| front-end | `/stats/top-apps-for-model`, `/stats/top-colos-for-model` | `top_apps_by_model`, `top_colos_by_model` |
| front-end | `/stats/provider-token-chart` | `provider_token_daily` |

The `/api/frontend/v1/*` endpoints are undocumented — they back openrouter.ai's
own model pages. No key is needed, but they can change without notice.

---

## Files

Snapshot of 2026-08-28. All prices are **USD per million tokens** unless the
column name says otherwise. `endpoint_id` is the join key across every file; it
appears only in `endpoint_catalogue`, which is therefore the join table.

| file | grain | rows | coverage |
|---|---|---|---|
| `model_catalogue.csv` | model | 388 | current |
| `provider_catalogue.csv` | provider | 103 | current |
| `endpoint_catalogue.csv` | model × endpoint | 1,212 | current |
| `effective_prices_daily_by_endpoint.csv` | model × endpoint × day | 125,466 | 218d, 360 models |
| `effective_prices_daily_by_model.csv` | model × day | 53,920 | 218d |
| `effective_prices_summary.csv` | model × endpoint | 1,098 | prices whole window, volumes **~24h** |
| `listed_price_changes.csv` | change point | 20,249 | 370 models |
| `token_mix_daily_by_model.csv` | model × day | 10,174 | **31d**, 359 models |
| `blended_price_daily_by_model.csv` | model × day | 10,120 | **31d** |
| `performance_daily_by_endpoint.csv` | model × endpoint × colo × day | 9,269 | **8d**, 344 models |
| `provider_performance_summary.csv` | model × endpoint × colo | 1,258 | **8d** |
| `cache_hit_rate_daily_by_endpoint.csv` | model × endpoint × day | 11,323 | **8d**, 376 models |
| `tool_call_error_rate_daily.csv` | model × endpoint × day | 9,307 | **8d**, 311 models |
| `structured_output_error_rate_daily.csv` | model × endpoint × day | 7,403 | **8d**, 295 models |
| `model_uptime_recent.csv` | model × 10-min bucket | 56,260 | **~24h** |
| `benchmark_scores.csv` | model × endpoint × benchmark | 2,431 | 162 models |
| `top_apps_by_model.csv` | model × app | 1,665 | current |
| `top_colos_by_model.csv` | model × colo | 6,180 | current |
| `provider_summary.csv` | provider | 74 | volumes **~24h** |
| `provider_token_daily.csv` | provider × model × day | 37,655 | **90d** |

**Six different retention windows.** Anything joining them is bounded by the
shortest — see Caveats.

---

## Data dictionary

Shared identifier columns, `API` throughout: `model_id` (e.g.
`anthropic/claude-sonnet-4`), `permaslug` (the model's `canonical_slug`, which
is what the stats API keys on — *not* the id), `variant` (`standard` | `free` |
`batch`, taken from the `:suffix` on the id), `endpoint_id`, `provider_name`,
`provider_slug`, `date`.

### model_catalogue.csv

| column | src | meaning |
|---|---|---|
| `name`, `created`, `context_length`, `modality`, `tokenizer` | `API` | catalogue metadata |
| `listed_input_usd_per_mtok`, `listed_output_usd_per_mtok`, `listed_cache_read_usd_per_mtok` | `API×1e6` | headline price — the default/cheapest route, already net of any variant discount |

### provider_catalogue.csv

| column | src | meaning |
|---|---|---|
| `headquarters`, `datacenters` | `API` | jurisdiction; `datacenters` is pipe-delimited |
| `privacy_policy_url`, `terms_of_service_url`, `status_page_url` | `API` | provider links |

### endpoint_catalogue.csv

The join table, and the richest single call in the dataset.

| column | src | meaning |
|---|---|---|
| `provider_region`, `quantization` | `API` | e.g. `global`, `fp8` |
| `context_length`, `max_completion_tokens`, `max_prompt_tokens` | `API` | per-endpoint limits, which differ from the model's |
| `capacity_tpm`, `limit_rpm`, `limit_rpd` | `API` | throughput capacity and rate limits |
| `status`, `is_disabled`, `is_deranked`, `is_free`, `is_byok`, `is_hidden`, `moderation_required` | `API` | routing eligibility flags |
| `supports_reasoning`, `supports_implicit_caching` | `API` | capability flags |
| `listed_input_usd_per_mtok`, `listed_output_usd_per_mtok`, `listed_cache_read_usd_per_mtok`, `listed_cache_write_usd_per_mtok`, `listed_cache_write_1h_usd_per_mtok` | `API×1e6` | this endpoint's posted rates. **Already net of `discount`.** Note cache *writes* often cost **more** than the base input rate |
| `listed_web_search_usd_per_call` | `API` | $ per call, not per token |
| `discount` | `API` | fraction already taken off the upstream list price (0.5 = the price shown is half list) |
| `n_price_tiers`, `tier_min_prompt_tokens`, `tier_input_usd_per_mtok`, `tier_output_usd_per_mtok` | `API`/`API×1e6` | long-context tier. 119 endpoints have one — e.g. Sonnet 4 doubles above 200k prompt tokens |
| `policy_trains_on_prompts`, `policy_retains_prompts`, `policy_can_publish`, `policy_requires_user_ids` | `API` | data policy. 16 endpoints train on prompts |
| `p50_throughput_tok_s`, `p90_throughput_tok_s`, `p99_throughput_tok_s`, `p50_latency_ms`, `p90_latency_ms`, `p99_latency_ms` | `API` | OpenRouter's own percentiles over a rolling **30-minute** window — distinct from the daily series in `performance_daily_by_endpoint` |
| `stats_request_count`, `stats_window_minutes` | `API` | sample size behind those percentiles |
| `created_at` | `API` | when the endpoint was added to OpenRouter |

### effective_prices_daily_by_endpoint.csv

| column | src | meaning |
|---|---|---|
| `effective_input_usd_per_mtok` | `API` | what a prompt token actually cost that day on that endpoint. **Cost per *total* prompt token, cached ones included in the denominator** |
| `effective_output_usd_per_mtok` | `API` | same for completion tokens |

Exact, per endpoint. Prefer this file when a specific day or provider matters.

### effective_prices_daily_by_model.csv

| column | src | meaning |
|---|---|---|
| `n_endpoints` | `CALC` | endpoints live that day |
| `effective_input_usd_per_mtok`, `effective_output_usd_per_mtok` | `CALC` | `SUM(price_e × tokens_e) / SUM(tokens_e)` over the endpoints live that day |
| `listed_input_usd_per_mtok_current`, `listed_output_usd_per_mtok_current` | `API×1e6` | today's headline price, repeated on every row as a reference line. **A snapshot, not history** — use `listed_price_changes.csv` for that |

### effective_prices_summary.csv

| column | src | meaning |
|---|---|---|
| `effective_input_usd_per_mtok`, `effective_output_usd_per_mtok` | `API` | whole-window average for that endpoint |
| `cache_hit_rate` | `API` | fraction of prompt tokens served from cache (0–1) |
| `total_tokens` | `API` | **a rolling ~24-hour volume, not the window** — see the caveat below. These are the weights behind the model-level collapse |

### listed_price_changes.csv

A sparse change log, not a dense series: one row per price change.

| column | src | meaning |
|---|---|---|
| `changed_at` | `API` | ISO timestamp of the change |
| `field` | `API` | which price moved: input, output, cache read/write, or discount |
| `value` | `API` | new value ($/M tokens, or a fraction for discount) |

### token_mix_daily_by_model.csv

| column | src | meaning |
|---|---|---|
| `requests`, `prompt_tokens`, `completion_tokens`, `cached_prompt_tokens`, `reasoning_tokens` | `API` | daily totals |
| `tool_calls`, `requests_with_tool_call_errors`, `media_prompt_requests`, `audio_prompt_requests`, `image_output_requests` | `API` | daily counts |
| `avg_prompt_tokens_per_request` | `CALC` | `prompt_tokens / requests` |
| `avg_completion_tokens_per_request` | `CALC` | `completion_tokens / requests` |
| `avg_reasoning_tokens_per_request` | `CALC` | `reasoning_tokens / requests` |
| `completion_to_prompt_ratio` | `CALC` | `completion_tokens / prompt_tokens` |
| `cache_hit_share_of_prompt` | `CALC` | `cached_prompt_tokens / prompt_tokens` |

### blended_price_daily_by_model.csv

| column | src | meaning |
|---|---|---|
| `blended_effective_usd_per_mtok` | `CALC` | `(prompt × eff_in + completion × eff_out) / (prompt + completion)` |
| `blended_listed_usd_per_mtok` | `CALC` | same weights, listed prices |
| `effective_usd_per_request` | `CALC` | `(prompt × eff_in + completion × eff_out) / 1e6 / requests` |

### performance_daily_by_endpoint.csv

Keyed by `endpoint_id::colo` upstream, so `colo` is a real dimension here.

| column | src | meaning |
|---|---|---|
| `percentile` | — | which percentile was requested; p50 is the API default |
| `throughput_tok_s` | `API` | output tokens per second — how fast the model writes |
| `ttft_ms` | `API` | Time to First Token, from when the request is sent |
| `e2e_ms` | `API` | Time to Last Token — full round trip |

### provider_performance_summary.csv

| column | src | meaning |
|---|---|---|
| `days_observed` | `CALC` | daily points behind the medians |
| `throughput_tok_s`, `ttft_ms`, `e2e_ms` | `CALC` | median of the daily series |
| `throughput_rank`, `ttft_rank` | `CALC` | rank within the model, 1 = best. They disagree constantly |
| `effective_input_usd_per_mtok`, `effective_output_usd_per_mtok`, `total_tokens` | `API` | joined from `effective_prices_summary` so speed can be read against cost |

### cache_hit_rate_daily_by_endpoint.csv

| column | src | meaning |
|---|---|---|
| `cache_hit_rate_pct` | `API` | percent (0–100), not a fraction — unlike `cache_hit_rate` in the summary file |

### tool_call_error_rate_daily.csv / structured_output_error_rate_daily.csv

| column | src | meaning |
|---|---|---|
| `tool_call_error_rate_pct` / `structured_output_error_rate_pct` | `API` | percent of calls that errored |
| `tool_call_volume` / `structured_output_volume` | `API` | calls behind the rate — a high rate on tiny volume means little |

### model_uptime_recent.csv

| column | src | meaning |
|---|---|---|
| `timestamp` | `API` | 10-minute bucket |
| `availability_pct` | `API` | success rate **including** OpenRouter's fallback routing |
| `availability_without_routing_pct` | `API` | what a caller pinned to one provider would have seen. The gap is the value routing adds |

### benchmark_scores.csv

| column | src | meaning |
|---|---|---|
| `benchmark_type` | `API` | `gpqa_diamond` or `tau_bench_verified_airline` |
| `score` | `API` | 0–1 |
| `run_count` | `API` | runs behind the score — often 1, so treat as indicative |
| `endpoint_id` | `API` | **null for the `auto-routing` row**, which scores OpenRouter's own routing rather than a provider |

### top_apps_by_model.csv / top_colos_by_model.csv

| column | src | meaning |
|---|---|---|
| `rank`, `app_id`, `app_title`, `app_slug`, `app_origin_url`, `app_categories` | `API` | the public apps sending most tokens; categories pipe-delimited |
| `total_tokens`, `total_requests` | `API` | that app's volume on this model |
| `colo` | `API` | datacenter code (`IAD`, `FRA`, …) in OpenRouter's own order |

### provider_summary.csv

One row per provider, across every model it serves. Ranked by volume.

| column | src | meaning |
|---|---|---|
| `token_rank` | `CALC` | rank by `tokens_last_24h`, 1 = largest |
| `headquarters` | `API` | joined from `provider_catalogue` |
| `n_models`, `n_endpoints` | `CALC` | distinct counts |
| `tokens_last_24h` | `CALC` | `SUM(total_tokens)` — inherits the ~24h window |
| `share_of_tokens_pct` | `CALC` | that sum over all providers' |
| `effective_input_usd_per_mtok`, `effective_output_usd_per_mtok`, `cache_hit_rate` | `CALC` | token-weighted across the provider's endpoints |
| `median_listed_input_usd_per_mtok`, `median_listed_output_usd_per_mtok` | `CALC` | median over its endpoints in `endpoint_catalogue` |
| `median_p50_throughput_tok_s`, `median_p50_latency_ms` | `CALC` | median of the per-endpoint p50s, which come off the API over its own 30-min window |
| `n_endpoints_training_on_prompts` | `CALC` | count where `policy_trains_on_prompts` is true |

These averages **mix models**. A provider serving mostly small models will show
a low effective price for that reason alone, so read a provider's price against
its `n_models`, or go to `effective_prices_summary.csv` for like-for-like.

### provider_token_daily.csv

The only provider-level **history** in the dataset: 90 days of tokens served.

| column | src | meaning |
|---|---|---|
| `model_permaslug` | `API` | a permaslug — join to `model_catalogue.permaslug`, not to `model_id`. The literal value `Others` is a bucket, not a model |
| `tokens` | `API` | tokens that provider served for that model that day |

Each day lists the provider's **top 9 models plus `Others`**, so a daily total
per provider is complete, but the per-model breakdown is not — a specific model
missing from a day means it was outside that provider's top 9, not that it was
unserved.

---

## Providers

Volumes are heavily concentrated. Top of `provider_summary.csv`:

| # | provider | models | tokens 24h | share | eff. in | eff. out | cache |
|---|---|---|---|---|---|---|---|
| 1 | OpenAI | 49 | 1,493B | 14.9% | $0.163 | $3.225 | 88% |
| 2 | Xiaomi | 2 | 1,259B | 12.6% | $0.011 | $0.293 | 95% |
| 3 | Z.ai | 13 | 1,037B | 10.3% | $0.071 | $0.915 | 89% |
| 4 | Tencent Cloud | 5 | 838B | 8.4% | $0.047 | $0.604 | 91% |
| 5 | GMICloud | 22 | 590B | 5.9% | $0.028 | $0.362 | 84% |
| 7 | Google Vertex | 52 | 470B | 4.7% | $0.463 | $5.586 | 44% |
| 8 | DeepInfra | 74 | 411B | 4.1% | $0.058 | $0.396 | 65% |

The top four are 46% of all tokens, and two of them (Xiaomi, Tencent Cloud) reach
that on five models or fewer. The price columns are not comparable across rows —
Google Vertex looks expensive because it serves frontier models, not because it
marks them up.

---

## Effective vs listed

| | listed | effective |
|---|---|---|
| source | `/api/v1/models`, `/stats/endpoint` | `/stats/effective-pricing` |
| meaning | the posted rate | what traffic actually cost, per day |
| moves when | a provider repriced | caching, tier overrides, discounts or the routing mix shifted |

Claude Sonnet 4 is the clean example: listed $3.00 / $15.00, effective
**$1.78 / $15.00** on 2026-08-28 — input ~41% below list because ~48% of prompt
tokens are cache hits, output exactly on the listed rate.

### Caching applies to input only — but output still moves

Caching never touches output tokens, and yet effective output matches listed
output for only **23 of 55** sampled models. Two other things move it:

- **Routing mix.** Listed is the default/cheapest endpoint; effective spans every
  endpoint served. `deepseek/deepseek-v4-flash-0731` lists $0.14/M, bills $0.43/M
  across 29 endpoints.
- **Non-text output.** Image and audio tokens are priced far above the listed
  text rate. `google/gemini-3.1-flash-image` lists $3.00/M, bills $50.67/M.

For image and audio models the blended figure is not a text-token price.

## Blended price and sequence lengths

The pricing API never blends — input and output are separate series, and one
headline $/M number only exists once weighted by the real prompt:completion
split, which comes from `/stats/model-activity`.

Traffic is overwhelmingly prompt-heavy. Week to 2026-08-27, request-weighted:

| model | in tok/req | out tok/req | in:out | cache | blended eff. | blended list |
|---|---|---|---|---|---|---|
| `deepseek/deepseek-v4-flash` | 10,322 | 533 | 19:1 | 70% | $0.06 | $0.09 |
| `openai/gpt-5.6-luna` | 16,493 | 398 | 41:1 | 82% | $0.10 | $0.23 |
| `google/gemini-2.5-flash-lite` | 2,630 | 239 | 11:1 | 15% | $0.11 | $0.12 |
| `xiaomi/mimo-v2.5` | 83,241 | 569 | 146:1 | 95% | $0.01 | $0.14 |
| `google/gemini-3.7-flash` | 45,446 | 775 | 59:1 | 77% | $0.19 | $0.40 |

At 20:1 the output rate barely registers, and the longest-prompt models are the
ones caching hardest. Assuming a 3:1 mix instead of measuring it overstates GLM
5.3 flash's blended price by 99%.

## Throughput and latency

`--percentile p90|p95|p99` switches all three series; p50 is the default. "Best
provider" is usually three different providers:

| model | | provider | tok/s | TTFT ms | eff. in $/M |
|---|---|---|---|---|---|
| `z-ai/glm-5.3-flash` | fastest | Baseten | 112 | 768 | 0.0618 |
| | cheapest | Z.ai | 33 | 4,290 | 0.0227 |
| | lowest TTFT | Together | 46 | 475 | 0.0757 |
| `openai/gpt-oss-120b` | fastest | Cerebras | 785 | 231 | 0.3499 |
| | cheapest | CoreWeave | 34 | 460 | 0.0299 |
| | lowest TTFT | Baseten | 222 | 228 | 0.0999 |

On `gpt-oss-120b` that is a 23× throughput spread against a 12× price spread,
pointing opposite ways.

---

## Validation

`scripts/openrouter_checks.py` re-derives the numbers three ways. There is no
public per-model spend figure from OpenRouter, so **none is an external ground
truth** — the blended price has no independent source to be checked against.

| check | result |
|---|---|
| our token-weighted mean vs the API's own `weightedInputPrice`/`weightedOutputPrice` | 0.01% / 0.02% median error (n=55) |
| `effective_input` vs `listed × (1 − hit) + cache_read × hit` | exact — 0.0% median error (n=153 endpoints) |
| cache share (activity endpoint) + listed prices (models API) vs the charted effective input | 3.6% median error, 65% within 10% (n=5,274 model-days) |

The middle row is load-bearing. Holding exactly establishes both that caching is
a pure **input**-side effect and that `effective_input` is a cost per **total**
prompt token — the same denominator the blend uses, so the cache discount is not
counted twice. The 3.6% residual in the third row is cache *writes* (priced
*above* list: $3.75/M on Sonnet 4 against a $3.00 list) and long-context tier
overrides, neither of which the simple identity models.

Worked example — Claude Sonnet 4, 2026-08-27: a 52.3% cache share against
$3.00/M list and $0.30/M cache reads predicts $1.588/M; the chart says $1.637/M,
3.0% apart.

## Caveats

- **`total_tokens` is a rolling ~24 hours, not the window.** Measured across 355
  models, it sits at 1.12x the current partial day and 0.02x the 31-day window.
  Two consequences: it is *today's* traffic, so `provider_summary.csv` is a
  snapshot rather than a history; and the model-level daily price weights every
  historical day by today's routing mix. The further back the day, the weaker
  that assumption — per-endpoint prices are exact, so prefer them for a specific
  day. For provider volume history use `provider_token_daily.csv`.
- **Six retention windows.** Prices 218d, token mix 31d, performance and the
  three reliability series 8d, provider token history 90d, uptime and
  `total_tokens` ~24h. Any join is bounded by the shortest.
  The `timeRange` parameter on the performance endpoints is accepted but
  **ignored** — `1w` and `all` return the same 8 points — so there is no way to
  get more. Historical trends beyond these windows require running the fetcher
  on a schedule and accumulating your own history.
- **`range=all` is ~7 months, not each model's full life.** The price history
  starts 2026-01-23 for every model, however old.
- **27 models return no history** — too new, or no billable traffic.
- **`:free` variants report $0.** Correct: they are free.
- **`:batch` variants also report $0, and that is not a price.** OpenRouter does
  not attribute batch spend to this stat, so treat those 24 series as missing.
  Naively differencing them against list produces a bogus −100%.
- **The daily model-level weighting is the weakest link.** The validation
  confirms the whole-window aggregate, not the day-by-day split, and the API
  publishes no daily per-endpoint volumes. A model whose routing mix moved will
  drift on individual days; per-endpoint figures are exact.
- **The most recent day is partial** and grows during the day, so re-running
  mid-day changes the last row.
- **A new model's first days are unreliable.** While volumes ramp, the price and
  cache-hit series are computed over slightly different windows — on GLM 5.3
  flash's launch day two endpoints were 26% and 31% off the identity, then within
  0.2% by day three.
- **`reasoning_tokens` is a native count and is not additive with
  `completion_tokens`.** Prompt and completion are normalised across tokenizers,
  reasoning is not, so on a few percent of rows reasoning exceeds completion.
- **Mind the units.** `cache_hit_rate` (summary) is a fraction;
  `cache_hit_rate_pct` (daily) is 0–100.

## API notes

Both pricing endpoints take `permaslug`, `variant`, `range`
(`3d` `1w` `1m` `3m` `1y` `all`) and a `shape` version pinned in
`openrouter_stats/api.py` (`v7` effective, `v4` listed) that must move with the
parsing code. `model-activity`, `top-apps-for-model` and `model-uptime-recent`
take only `permaslug` and `variant`. `benchmark-scores` takes only `permaslug`.
The comparison endpoints take `timeRange` and, for throughput, `percentile`.
