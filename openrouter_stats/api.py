"""HTTP plumbing and the OpenRouter endpoint map.

Two API surfaces are used:

* ``/api/v1/*`` — the documented public API.
* ``/api/frontend/v1/*`` — the undocumented endpoints behind openrouter.ai's own
  model pages. No key is needed, but they can change without notice, and the
  ``shape`` versions below pin the response schema, so they must move together
  with the parsing code.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

BASE = "https://openrouter.ai"

# -- documented public API --------------------------------------------------
MODELS_URL = f"{BASE}/api/v1/models"
PROVIDERS_URL = f"{BASE}/api/v1/providers"

# -- undocumented front-end API ---------------------------------------------
F = f"{BASE}/api/frontend/v1/stats"
EFFECTIVE_URL = f"{F}/effective-pricing"
LISTED_URL = f"{F}/listed-pricing"
ACTIVITY_URL = f"{F}/model-activity"
ENDPOINT_URL = f"{F}/endpoint"
BENCHMARK_URL = f"{F}/benchmark-scores"
CACHE_HIT_URL = f"{F}/cache-hit-rate-comparison"
TOOL_ERROR_URL = f"{F}/tool-call-error-rate"
STRUCT_ERROR_URL = f"{F}/structured-output-error-rate"
UPTIME_URL = f"{F}/model-uptime-recent"
TOP_APPS_URL = f"{F}/top-apps-for-model"
TOP_COLOS_URL = f"{F}/top-colos-for-model"
PROVIDER_TOKENS_URL = f"{F}/provider-token-chart"
PERF_URLS = {
    "throughput_tok_s": f"{F}/throughput-comparison",
    "ttft_ms": f"{F}/latency-comparison",
    "e2e_ms": f"{F}/latency-e2e-comparison",
}

EFFECTIVE_SHAPE = "v7"
LISTED_SHAPE = "v4"
RANGES = ("3d", "1w", "1m", "3m", "1y", "all")
PERCENTILES = ("p50", "p90", "p95", "p99")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 60
MAX_RETRIES = 4


def get_json(url: str, params: Optional[Dict[str, str]] = None) -> Optional[Any]:
    """GET a JSON document, retrying transient failures with backoff."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json",
               "Accept-Encoding": "gzip"}
    delay, last_err = 2.0, None
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


def data_of(payload: Any) -> Any:
    """Unwrap the ``{"data": ...}`` envelope every endpoint uses."""
    return payload.get("data") if isinstance(payload, dict) else None
