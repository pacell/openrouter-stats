# OpenRouter effective token prices

Historical **effective** input/output token prices for every model on
OpenRouter — the average $/M tokens customers actually paid, not the price
providers post.

Rebuild with:

```bash
python3 scripts/openrouter_prices.py             # effective, full history
python3 scripts/openrouter_prices.py --activity  # + token mix and blended price
python3 scripts/openrouter_prices.py --listed    # + the listed-price change log
python3 scripts/openrouter_checks.py             # validate the result
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
| `token_mix_daily_by_model.csv` | model × day, last ~31 days | ~10k |
| `blended_price_daily_by_model.csv` | model × day, last ~31 days | ~10k |

`effective_prices_summary.csv` also carries `cache_hit_rate` and `total_tokens`,
which explain most of the gap between the two prices.

## Blended price and sequence lengths

The pricing API never blends — input and output are separate series, and a
single headline $/M number only exists once you weight them by the actual
prompt:completion split. That split comes from a different endpoint,
`/api/frontend/v1/stats/model-activity`, which reports daily
`total_prompt_tokens`, `total_completion_tokens`, `total_native_tokens_cached`,
`total_native_tokens_reasoning` and request `count` per model.

`token_mix_daily_by_model.csv` turns those into per-request sequence lengths
(`avg_prompt_tokens_per_request`, `avg_completion_tokens_per_request`,
`completion_to_prompt_ratio`, `cache_hit_share_of_prompt`), and
`blended_price_daily_by_model.csv` joins them to the effective prices for a
true `blended_effective_usd_per_mtok`, its listed counterpart, and
`effective_usd_per_request`.

Traffic on OpenRouter is overwhelmingly prompt-heavy — the week to 2026-08-27,
weighted by requests:

| model | in tok/req | out tok/req | in:out | cache | blended eff. | blended list |
|---|---|---|---|---|---|---|
| `deepseek/deepseek-v4-flash` | 10,322 | 533 | 19:1 | 70% | $0.06 | $0.09 |
| `openai/gpt-5.6-luna` | 16,493 | 398 | 41:1 | 82% | $0.10 | $0.23 |
| `google/gemini-2.5-flash-lite` | 2,630 | 239 | 11:1 | 15% | $0.11 | $0.12 |
| `xiaomi/mimo-v2.5` | 83,241 | 569 | 146:1 | 95% | $0.01 | $0.14 |
| `google/gemini-3.7-flash` | 45,446 | 775 | 59:1 | 77% | $0.19 | $0.40 |

Sequence length is what makes the blended price sit so close to the input
price: at 20:1 the output rate barely registers, and the models with the
longest prompts are the ones caching hardest.

## Validation

`scripts/openrouter_checks.py` re-derives these numbers three ways. There is no
public per-model spend figure from OpenRouter, so none of them is an external
ground truth — they are consistency checks, and the blended $/M has no
independent source to be checked against.

| check | result |
|---|---|
| our token-weighted mean vs the API's own `weightedInputPrice`/`weightedOutputPrice` | 0.01% / 0.02% median error (n=55) |
| `effective_input` vs `listed x (1 - hit) + cache_read x hit` | exact — 0.0% median error (n=153 endpoints) |
| cache share (activity endpoint) + listed prices (models API) vs the charted effective input | 3.6% median error, 65% within 10% (n=5,274 model-days) |

The middle row is the load-bearing one. It holds exactly, which establishes two
things the blend depends on: caching is a pure **input**-side effect, and
`effective_input` is a cost per **total** prompt token with cached tokens in the
denominator — the same denominator the blend uses, so the cache discount is not
counted twice. The 3.6% residual in the third row is cache *writes* (priced
*above* list: $3.75/M on Sonnet 4 against a $3.00 list) and long-context tier
overrides ($6.00/M above 200k), neither of which the simple identity models.

Worked example — Claude Sonnet 4, 2026-08-27: a 52.3% cache share against
$3.00/M list and $0.30/M cache reads predicts $1.588/M; the chart says
$1.637/M, 3.0% apart.

## Caching applies to input only — but output still moves

Caching never touches output tokens, and yet effective output matches listed
output for only **23 of 55** sampled models. Two other things move it:

- **Routing mix.** The listed figure is the default/cheapest endpoint; effective
  spans every endpoint actually served. `deepseek/deepseek-v4-flash-0731` lists
  $0.14/M and bills $0.43/M across 29 endpoints.
- **Non-text output.** Image and audio output tokens are priced far above the
  text rate that gets listed. `google/gemini-3.1-flash-image` lists $3.00/M and
  bills $50.67/M.

So for image and audio models the blended figure is not a text-token price at
all, and shouldn't be read as one.

## Coverage and caveats

Snapshot of 2026-08-28: **360 of 387 models**, daily from **2026-01-23** —
`range=all` is what the API returns, roughly a 7-month retention window, not
each model's full life.

- **26 models return no history** — too new, or no billable traffic.
- **`:free` variants report $0.** Correct: they are free.
- **`:batch` variants also report $0, and that is not a price.** OpenRouter does
  not attribute batch spend to this stat, so treat those 24 series as missing.
  Naively differencing them against list produces a bogus −100%.
- **The daily weighting is the weakest link.** The validation above confirms the
  whole-window aggregate, not the day-by-day split, so a model whose routing mix
  moved during the window will drift on individual days.
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
- **The token mix only goes back ~31 days.** `model-activity` takes no range
  parameter, so `token_mix_daily_by_model.csv` and the blend cover the last
  month even though the price history runs to 7 months. The most recent day is
  partial — request counts are cut off mid-day.
- **`reasoning_tokens` is a native count and is not additive with
  `completion_tokens`.** Prompt and completion totals are normalised across
  tokenizers, reasoning is not, so on a few percent of rows reasoning exceeds
  completion. Read it as indicative, and don't subtract it.
- **Effective can exceed the model's listed price.** The listed figure is the
  default/cheapest route; effective is weighted over all endpoints actually
  served, and for multimodal models mixes in audio and image tokens priced well
  above the text rate. `openai/gpt-audio` and `mistralai/voxtral-small-24b-2507`
  are the extreme cases.

## API notes

`effective-pricing`, `listed-pricing` and `model-activity` are undocumented
front-end endpoints — no key needed, but they can change without notice.
`model-activity` takes only `permaslug` and `variant`. The two pricing ones take
`permaslug` (the model's `canonical_slug`, *not* its id), `variant`
(`standard` | `free` | `batch`, from the `:suffix` on the id), `range`
(`3d` `1w` `1m` `3m` `1y` `all`) and a `shape` version pinned in the script
(`v7` effective, `v4` listed) that must move with the parsing code.
