"""HTTP client with on-disk caching, retries and per-host rate limiting.

The federal geospatial services this tool depends on are slow, occasionally
flaky, and unhappy about bursts of traffic. Caching also means a re-run on the
same day costs nothing, which matters because parcel physical attributes do not
change between runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(".cache/http")
USER_AGENT = "ncscout/0.1 (land natural-capital screening; contact: repo owner)"


class RateLimiter:
    """Enforces a minimum interval between requests to the same host."""

    def __init__(self, min_interval_s: float = 0.34) -> None:
        self.min_interval_s = min_interval_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            delay = self.min_interval_s - (now - last)
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._last[host] = now


class CachedClient:
    """A small requests-style wrapper used by every enricher."""

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        timeout: float = 45.0,
        max_retries: int = 3,
        min_interval_s: float = 0.34,
        use_cache: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.use_cache = use_cache
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self._limiter = RateLimiter(min_interval_s)
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        self.stats = {"hits": 0, "misses": 0, "errors": 0}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CachedClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _cache_key(self, method: str, url: str, params: Any, body: Any) -> Path:
        payload = json.dumps(
            {"m": method, "u": url, "p": params, "b": body},
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
        host = (urlparse(url).hostname or "unknown").replace(".", "_")
        return self.cache_dir / f"{host}__{digest}.json"

    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        cache: bool = True,
    ) -> Any | None:
        """Return parsed JSON, or None when the call fails after retries.

        Enrichers are expected to tolerate None and mark the measurement as
        missing rather than aborting the whole scan.
        """
        cache_path = self._cache_key(method, url, params, json_body)
        if cache and self.use_cache and cache_path.exists():
            try:
                self.stats["hits"] += 1
                return json.loads(cache_path.read_text())
            except (OSError, json.JSONDecodeError):
                cache_path.unlink(missing_ok=True)
                self.stats["hits"] -= 1

        self.stats["misses"] += 1
        host = urlparse(url).hostname or "unknown"
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            self._limiter.wait(host)
            try:
                response = self._client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
                # 4xx other than 429 will not improve on retry.
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                data = response.json()
            except Exception as exc:  # noqa: BLE001 - deliberately broad
                last_error = exc
                if attempt < self.max_retries - 1:
                    backoff = (2**attempt) + random.uniform(0, 0.4)
                    log.debug(
                        "%s %s failed (%s); retrying in %.1fs",
                        method,
                        url,
                        exc.__class__.__name__,
                        backoff,
                    )
                    time.sleep(backoff)
                continue

            if cache and self.use_cache:
                try:
                    cache_path.write_text(json.dumps(data))
                except OSError:
                    pass
            return data

        self.stats["errors"] += 1
        log.warning("giving up on %s %s: %s", method, url, last_error)
        return None

    def get_json(self, url: str, **kwargs: Any) -> Any | None:
        return self.request_json("GET", url, **kwargs)

    def post_json(self, url: str, **kwargs: Any) -> Any | None:
        return self.request_json("POST", url, **kwargs)
