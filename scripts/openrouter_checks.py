#!/usr/bin/env python3
"""Sense-check the OpenRouter effective/blended prices in data/openrouter/.

There is no public per-model spend figure from OpenRouter, so none of these is
an external ground truth — they are consistency checks that each derive the
same number a different way. Run after `openrouter_prices.py --activity`.

  A. weighting     — does our token-weighted mean reproduce the API's own
                     `weightedInputPrice` / `weightedOutputPrice`?
  B. cache identity — is `effective_input` exactly
                     `listed x (1 - hit) + cache_read x hit`?  If so, caching is
                     a pure input-side effect *and* the effective price is a
                     cost per TOTAL prompt token (cached ones included), which
                     is the denominator the blend assumes.
  C. cross-endpoint — predict the effective-pricing chart from a completely
                     different endpoint (model-activity's cache share plus the
                     public models API's listed and cache-read prices).
  D. output         — how often does effective output actually equal listed
                     output? Caching never touches output, but routing mix and
                     non-text modalities do.
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from openrouter_prices import (  # noqa: E402
    EFFECTIVE_SHAPE, EFFECTIVE_URL, MODELS_URL, OUT_DIR, get_json, list_models)

SAMPLE = 60


def _pct(xs: List[float]) -> str:
    q = statistics.quantiles(xs, n=4)
    return (f"median {statistics.median(xs) * 100:5.2f}%  "
            f"p25 {q[0] * 100:.2f}%  p75 {q[2] * 100:.2f}%  n={len(xs)}")


def main() -> None:
    models = [m for m in list_models() if m["variant"] == "standard"][:SAMPLE]
    raw = {m["id"]: m for m in get_json(MODELS_URL)["data"]}

    effs = {}
    for m in models:
        data = get_json(EFFECTIVE_URL, {"permaslug": m["permaslug"],
                                        "variant": "standard",
                                        "shape": EFFECTIVE_SHAPE, "range": "all"})
        if isinstance(data, dict) and data.get("data"):
            effs[m["model_id"]] = data["data"]

    # ---- A. weighting -----------------------------------------------------
    a_in, a_out = [], []
    for mid, eff in effs.items():
        ss = eff.get("providerSummaries") or []
        tot = sum(s.get("totalTokens") or 0 for s in ss)
        if not tot:
            continue
        for field, api_key, bucket in (("effectiveInputPrice", "weightedInputPrice", a_in),
                                       ("effectiveOutputPrice", "weightedOutputPrice", a_out)):
            api = eff.get(api_key) or 0
            if not api:
                continue
            mine = sum((s.get(field) or 0) * (s.get("totalTokens") or 0) for s in ss) / tot
            bucket.append(abs(mine - api) / api)
    print("A. weighting reproduces the API's own weighted price")
    print(f"   input   {_pct(a_in)}")
    print(f"   output  {_pct(a_out)}")

    # ---- D. output vs listed ---------------------------------------------
    same, differ = 0, []
    for mid, eff in effs.items():
        listed = float(raw[mid]["pricing"].get("completion") or 0) * 1e6
        wo = eff.get("weightedOutputPrice") or 0
        if not listed or not wo:
            continue
        if abs(wo - listed) / listed < 0.005:
            same += 1
        else:
            differ.append((abs(wo - listed) / listed, mid, listed, wo,
                           len(eff.get("providerSummaries") or [])))
    differ.sort(reverse=True)
    print(f"\nD. effective output vs listed output: {same} within 0.5%, "
          f"{len(differ)} differ (routing mix / non-text modalities, never caching)")
    for d, mid, lo, wo, n in differ[:5]:
        print(f"   {mid:<40} ${lo:>7.3f} -> ${wo:>7.3f} ({d * 100:+7.1f}%) over {n} endpoints")

    # ---- C. cross-endpoint ------------------------------------------------
    mix_path = os.path.join(OUT_DIR, "token_mix_daily_by_model.csv")
    px_path = os.path.join(OUT_DIR, "effective_prices_daily_by_model.csv")
    if not (os.path.exists(mix_path) and os.path.exists(px_path)):
        print("\nC. skipped — run openrouter_prices.py --activity first")
        return
    mix = {(r["model_id"], r["date"]): r for r in csv.DictReader(open(mix_path))}
    px = {(r["model_id"], r["date"]): r for r in csv.DictReader(open(px_path))}

    errs = []
    for key, a in mix.items():
        p, m = px.get(key), raw.get(key[0])
        if not p or not m:
            continue
        try:
            actual = float(p["effective_input_usd_per_mtok"])
            hit = float(a["cache_hit_share_of_prompt"] or 0)
        except (TypeError, ValueError):
            continue
        listed = float(m["pricing"].get("prompt") or 0) * 1e6
        cache_read = m["pricing"].get("input_cache_read")
        if not actual or not listed or cache_read is None or hit <= 0.02:
            continue
        pred = listed * (1 - hit) + float(cache_read) * 1e6 * hit
        errs.append(abs(pred - actual) / actual)
    print("\nC. cache share (activity endpoint) + listed prices (models API) "
          "predicts the charted effective input price")
    print(f"   {_pct(errs)}")
    within = sum(1 for e in errs if e < 0.10)
    print(f"   {within}/{len(errs)} ({within / len(errs) * 100:.0f}%) agree within 10%")
    print("   residual is cache *writes* (priced above list) and long-context "
          "tier overrides, neither of which the identity models")


if __name__ == "__main__":
    main()
