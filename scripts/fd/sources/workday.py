"""Workday board API.

    POST https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

Workday is the single biggest ATS in the company list (about 1,750 of 4,579
employers, including NVIDIA, Salesforce, Intel and Snap), and until now it was
never polled directly -- those companies could only ever reach the site via
the upstream internship feed, so their full-time roles were invisible.

The catch is that a board is addressed by three values -- tenant, data centre
and site path -- and the company list supplies only the tenant. Verified
coordinates therefore live in data/workday_sites.json, seeded from real URLs
in the upstream feed and extended by scripts/discover_workday.py.

Listing responses carry only a title and a path, so descriptions are fetched
per job. To keep that affordable the title is screened first, and only
plausible matches are fetched in full.
"""

from __future__ import annotations

import json
import logging

from .. import classify, config, http, record

log = logging.getLogger("fd.workday")

JOBS_API = "https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
BASE = "https://{tenant}.{dc}.myworkdayjobs.com"

# Server-side queries, so we page through a fraction of each board rather
# than all of it.
SEARCHES = ("intern", "new grad", "university graduate", "entry level")

PAGE = 20
MAX_PAGES = 5          # per search term, per board


def load_sites() -> dict:
    if not config.WORKDAY_SITES.exists():
        return {}
    try:
        return json.loads(config.WORKDAY_SITES.read_text())
    except (json.JSONDecodeError, OSError) as err:
        log.warning("could not read workday_sites.json (%s)", err)
        return {}


def _search(tenant: str, dc: str, site: str, text: str) -> list[dict]:
    """All postings a board returns for one search term."""
    url = JOBS_API.format(tenant=tenant, dc=dc, site=site)
    found: list[dict] = []

    for page in range(MAX_PAGES):
        payload = http.post_json(url, {
            "appliedFacets": {},
            "limit": PAGE,
            "offset": page * PAGE,
            "searchText": text,
        })
        if not isinstance(payload, dict):
            break
        postings = payload.get("jobPostings") or []
        found.extend(postings)
        if len(postings) < PAGE:
            break
    return found


def poll(company: dict) -> list[dict]:
    tenant = company["slug"]
    coords = company["coords"]
    dc, site = coords["dc"], coords["site"]
    name = coords.get("name") or company.get("name") or tenant
    base = BASE.format(tenant=tenant, dc=dc)

    # Collect candidates across the search terms, de-duplicated by path.
    candidates: dict[str, dict] = {}
    for term in SEARCHES:
        for posting in _search(tenant, dc, site, term):
            path = posting.get("externalPath")
            title = posting.get("title") or ""
            if not path or path in candidates:
                continue
            # Screen on the title before paying for a description.
            if classify.is_non_tech_title(title):
                continue
            if classify.classify_category(title) is None:
                continue
            candidates[path] = posting

    jobs = []
    for path, posting in candidates.items():
        detail = http.get_json(f"{base}/wday/cxs/{tenant}/{site}{path}")
        info = (detail or {}).get("jobPostingInfo") or {}
        description = info.get("jobDescription") or ""

        built = record.build(
            job_id=f"workday:{tenant}:{path}",
            company=name,
            title=info.get("title") or posting.get("title") or "",
            location=info.get("location") or posting.get("locationsText") or "",
            url=info.get("externalUrl") or f"{base}/{site}{path}",
            posted_at=info.get("startDate") or posting.get("postedOn") or "",
            source="Workday",
            description=description,
        )
        if built:
            jobs.append(built)
    return jobs


def collect(companies: list[dict]) -> list[dict]:
    """Poll every company whose Workday coordinates are known."""
    sites = load_sites()
    targets = []
    for company in companies:
        coords = sites.get(company["slug"])
        if coords and coords.get("dc") and coords.get("site"):
            targets.append({**company, "coords": coords})

    if not targets:
        log.info("  workday: no known board coordinates; skipping")
        return []

    log.info("Polling %d workday boards (of %d workday companies; the rest "
             "have no known board path)...", len(targets), len(companies))
    return http.fan_out(poll, targets, "workday")
