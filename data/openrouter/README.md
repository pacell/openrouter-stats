# OpenRouter effective token prices

Historical **effective** input/output token prices for every model on
OpenRouter — the average $/M tokens customers actually paid, not the price
providers post.

Rebuild with:

```bash
python3 scripts/openrouter_prices.py            # effective, full history
python3 scripts/openrouter_prices.py --listed   # + the listed-price change log
```

## Effective vs listed

OpenRouter publishes both, and they routinely disagree:

| | listed | effective |
|---|---|---|
| source | `/api/v1/models`, `/api/v1/models/:slug/endpoints` | `/api/frontend/v1/stats/effective-pricing` |
| meaning | the provider's posted rate | what traffic on that endpoint actually cost, per day |
| moves when | a provider repriced | caching, tiered/long-context overrides, discounts or the routing mix shifted |

Claude Sonnet 4 is the clean example: listed $3.00 / $15.00 per M tokens,
effective **$1.78 / $15.00** on 2026-08-28 — input is ~41% below list because
~48% of prompt tokens are cache hits, while output, which nothing discounts,
sits exactly on the listed rate.

## Files

All prices are **USD per million tokens**.

| file | grain | rows |
|---|---|---|
| `effective_prices_daily_by_endpoint.csv` | model × provider endpoint × day | ~125k |
| `effective_prices_daily_by_model.csv` | model × day (token-weighted across endpoints) | ~54k |
| `effective_prices_summary.csv` | model × provider endpoint, whole window | ~1.1k |

`effective_prices_summary.csv` also carries `cache_hit_rate` and `total_tokens`,
which explain most of the gap between the two prices.

## Coverage and caveats

Snapshot of 2026-08-28: **360 of 387 models**, daily from **2026-01-23** —
`range=all` is what the API returns, roughly a 7-month retention window, not
each model's full life.

- **26 models return no history** — too new, or no billable traffic.
- **`:free` variants report $0.** Correct: they are free.
- **`:batch` variants also report $0, and that is not a price.** OpenRouter does
  not attribute batch spend to this stat, so treat those 24 series as missing.
  Naively differencing them against list produces a bogus −100%.
- **The model-level daily price is a weighted mean, and the weights are
  approximate.** The API reports token volume per endpoint over the whole
  window, not per day, so `effective_prices_daily_by_model.csv` weights each
  endpoint by its window-wide `total_tokens`, renormalised over the endpoints
  live that day. Per-endpoint figures in the other two files are exact; use
  them if the weighting matters.
- **`listed_*_current` columns are a snapshot, not history.** They repeat
  today's headline price from `/api/v1/models` on every row as a reference
  line. For real listed-price history run with `--listed`, which writes
  `listed_price_changes.csv` — a change log (`changed_at`, `field`, `value`),
  sparse by design, covering input, output, cache read/write and discount.
- **Effective can exceed the model's listed price.** The listed figure is the
  default/cheapest route; effective is weighted over all endpoints actually
  served, and for multimodal models mixes in audio and image tokens priced well
  above the text rate. `openai/gpt-audio` and `mistralai/voxtral-small-24b-2507`
  are the extreme cases.

## API notes

`effective-pricing` and `listed-pricing` are undocumented front-end endpoints —
no key needed, but they can change without notice. Both take
`permaslug` (the model's `canonical_slug`, *not* its id), `variant`
(`standard` | `free` | `batch`, from the `:suffix` on the id), `range`
(`3d` `1w` `1m` `3m` `1y` `all`) and a `shape` version pinned in the script
(`v7` effective, `v4` listed) that must move with the parsing code.
