"""Shared HTTP plumbing: one pooled session, bounded retries, thread fan-out."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable

import requests

from . import config

log = logging.getLogger("fd.http")

_local = threading.local()


def session() -> requests.Session:
    """One Session per worker thread (Session is not thread-safe)."""
    existing = getattr(_local, "session", None)
    if existing is None:
        existing = requests.Session()
        existing.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        })
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
        existing.mount("https://", adapter)
        _local.session = existing
    return existing


def get_json(url: str, **kwargs: Any) -> Any | None:
    """GET and parse JSON. Returns None on 404 or exhausted retries."""
    return _request_json("GET", url, **kwargs)


def post_json(url: str, payload: dict, **kwargs: Any) -> Any | None:
    return _request_json("POST", url, json=payload, **kwargs)


def _request_json(method: str, url: str, **kwargs: Any) -> Any | None:
    kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            response = session().request(method, url, **kwargs)
        except requests.RequestException as err:
            if attempt == config.MAX_RETRIES:
                log.debug("%s %s failed: %s", method, url, err)
                return None
            time.sleep(0.6 * (attempt + 1))
            continue

        # A missing board is the normal case for a stale slug -- not an error.
        if response.status_code in (404, 403, 410):
            return None
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == config.MAX_RETRIES:
                return None
            time.sleep(1.5 * (attempt + 1))
            continue
        try:
            return response.json()
        except ValueError:
            return None
    return None


def get_text(url: str) -> str | None:
    try:
        response = session().get(url, timeout=config.REQUEST_TIMEOUT)
    except requests.RequestException:
        return None
    return response.text if response.ok else None


def fan_out(func: Callable[[Any], list], items: Iterable[Any], label: str) -> list:
    """Run func over items across a thread pool, flattening the results.

    Exceptions in a worker are logged and skipped -- one broken board must
    never take down a whole run.
    """
    items = list(items)
    results: list = []
    done = 0
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        futures = {pool.submit(func, item): item for item in items}
        for future in as_completed(futures):
            done += 1
            try:
                results.extend(future.result() or [])
            except Exception as err:  # noqa: BLE001 - resilience is the point
                log.debug("%s worker failed for %r: %s", label, futures[future], err)
            if done % 250 == 0 or done == len(items):
                log.info("  %s: %d/%d boards polled, %d postings kept",
                         label, done, len(items), len(results))
    return results
