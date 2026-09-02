"""Resolve company name -> web domain, so cards can show a company icon.

The job URLs all point at ATS hosts (greenhouse.io, lever.co, ashbyhq.com),
never at the employer, so the domain has to be looked up. Results are cached
in data/logos.json and only new companies are queried on later runs -- after
the first run this costs almost nothing.

The frontend turns the domain into an icon via DuckDuckGo's icon service and
falls back to a monogram when there is no domain or the icon 404s.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

from . import config, http

log = logging.getLogger("fd.logos")

SUGGEST = "https://autocomplete.clearbit.com/v1/companies/suggest?query={q}"

# Suffixes to drop before matching, so "Nike, Inc." matches "Nike".
_SUFFIX_RE = re.compile(
    r"\b(inc|llc|ltd|limited|corp|corporation|co|company|plc|gmbh|ag|sa|nv|bv"
    r"|holdings|group|labs|technologies|technology|systems|solutions)\b\.?",
    re.I,
)
_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> str:
    name = _SUFFIX_RE.sub(" ", name.lower())
    return _PUNCT_RE.sub("", name)


def _clean_query(name: str) -> str:
    """Drop legal suffixes before querying -- 'NIKE, Inc.' finds nothing."""
    cleaned = _SUFFIX_RE.sub(" ", name)
    cleaned = re.sub(r"[,.]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip() or name


def _lookup(name: str) -> str | None:
    """Best-matching domain for a company name, or None."""
    target = _normalise(name)
    if not target:
        return None

    results = http.get_json(SUGGEST.format(q=quote(_clean_query(name))))
    if not isinstance(results, list) or not results:
        return None

    # Exact normalised match first -- the API happily returns loose matches
    # ("Databricks" also suggests "mg-alloy.com"), and a wrong logo is worse
    # than none.
    for entry in results:
        if isinstance(entry, dict) and _normalise(entry.get("name", "")) == target:
            domain = (entry.get("domain") or "").strip().lower()
            if domain:
                return domain
    return None


def load_cache() -> dict[str, str | None]:
    if not config.LOGO_CACHE.exists():
        return {}
    try:
        data = json.loads(config.LOGO_CACHE.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as err:
        log.warning("could not read logos.json (%s); starting fresh", err)
        return {}


def save_cache(cache: dict[str, str | None]) -> None:
    config.LOGO_CACHE.parent.mkdir(parents=True, exist_ok=True)
    config.LOGO_CACHE.write_text(
        json.dumps(dict(sorted(cache.items())), indent=0, ensure_ascii=False) + "\n"
    )


def attach(jobs: list[dict]) -> dict[str, str | None]:
    """Stamp every job with companyDomain, looking up only unseen companies."""
    cache = load_cache()
    companies = sorted({j["company"] for j in jobs if j.get("company")})
    unknown = [c for c in companies if c not in cache]

    if unknown:
        log.info("Resolving %d new company domains (%d cached)...",
                 len(unknown), len(companies) - len(unknown))
        resolved = http.fan_out(
            lambda name: [(name, _lookup(name))], unknown, "logos"
        )
        for name, domain in resolved:
            cache[name] = domain

        # Anything the fan-out dropped gets a negative entry, so a failed
        # lookup is not retried on every future run.
        for name in unknown:
            cache.setdefault(name, None)

    for job in jobs:
        job["companyDomain"] = cache.get(job.get("company")) or ""

    hit = sum(1 for j in jobs if j["companyDomain"])
    log.info("  logos: %d/%d jobs have a company domain", hit, len(jobs))
    save_cache(cache)
    return cache
