# openrouter-stats

What every model on OpenRouter **actually costs**, and how fast and reliably each
provider serves it.

OpenRouter publishes two prices per model. The **listed** price is what providers
post. The **effective** price is what customers actually paid once prompt caching,
long-context tiers and provider discounts are applied — routinely less than half
the listed rate, and available per day, per provider, going back ~7 months.

```
Claude Sonnet 4, 2026-08-28    listed  $3.00 in / $15.00 out per M tokens
                            effective  $1.78 in / $15.00 out
```

Input is 41% below list because ~48% of prompt tokens are cache hits. Output is
exactly on list, because caching only applies to input.

## What this pulls

Twenty CSVs from ten API surfaces, no API key, ~5,400 requests in ~4 minutes:

- **Prices** — daily effective input/output per model per provider endpoint, the
  listed-price change log, and a blended $/M weighted by real traffic
- **Catalogue** — every model, provider and endpoint, with listed pricing
  (including cache writes, discounts and long-context tiers), rate limits, data
  policies and capacity
- **Volumes** — daily prompt/completion tokens, per-request sequence lengths,
  cache hit rates, and 90 days of tokens served per provider
- **Performance** — p50 (or p90/p95/p99) throughput, time-to-first-token and
  time-to-last-token per provider endpoint
- **Reliability & quality** — uptime, tool-call and structured-output error
  rates, benchmark scores

```bash
python3 scripts/openrouter_prices.py --all     # everything
python3 scripts/openrouter_prices.py           # prices only
python3 scripts/openrouter_checks.py           # validate the result
```

Standard library only, Python 3.10+. No `pip install`.

## Pulled vs calculated

Almost everything is pulled. Only four things are computed, and the split is
enforced by the code, not just documented:

| module | rule |
|---|---|
| `openrouter_stats/pull.py` | every API call. Renames and unnests; converts $/token to $/M tokens. **No arithmetic.** |
| `openrouter_stats/derive.py` | every calculation. **No API calls.** |

**[`data/openrouter/README.md`](data/openrouter/README.md)** documents every
column of all twenty files, each tagged `API` (verbatim), `API×1e6` (unit change
only) or `CALC` (with its formula), alongside the source-endpoint map, six
different retention windows, and the validation results.

## Caveats worth reading first

- **Six retention windows.** Prices 218d, provider volumes 90d, token mix 31d,
  performance and reliability 8d, uptime and `total_tokens` ~24h. Any join is
  bounded by the shortest.
- **`:batch` variants report $0, and that is not a price.** Treat as missing.
- **Caching applies to input only, but effective output still moves** — routing
  mix and non-text modalities, not caching.
- **No external ground truth.** OpenRouter publishes no per-model spend figure,
  so the validation checks are internal consistency, not verification against a
  reported number.

The `/api/frontend/v1/*` endpoints are undocumented — they back openrouter.ai's
own model pages. No key is needed, but they can change without notice, and the
response `shape` versions are pinned in `openrouter_stats/api.py`.
