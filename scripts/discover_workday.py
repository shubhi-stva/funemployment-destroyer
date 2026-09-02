#!/usr/bin/env python3
"""Find Workday board coordinates for companies we cannot yet poll.

A Workday board is addressed by tenant + data centre + site path, and the
company list gives only the tenant. This probes the plausible combinations
for tenants we have not resolved, and records what answers.

Both outcomes are cached. A tenant that responds is stored with its
coordinates; one that does not is stored as a miss with an attempt count, so
later runs do not keep paying for the same dead ends. Work is capped per run
(--limit) so this can sit in the scheduled collection without dominating it,
and coverage grows a little on each pass.

Usage:
    python scripts/discover_workday.py            # default budget
    python scripts/discover_workday.py --limit 200
    python scripts/discover_workday.py --retry-misses
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fd import config, http  # noqa: E402

log = logging.getLogger("fd.discover")

DCS = ["wd1", "wd5", "wd3", "wd12", "wd2", "wd103", "wd501"]

# Site paths seen in the wild. {t} is the tenant, {T} its upper case form.
SITE_TEMPLATES = [
    "External", "external", "Careers", "careers", "{t}", "{T}",
    "{t}careers", "{t}_careers", "{t}Careers", "External_Career_Site",
    "ExternalCareerSite", "{T}ExternalCareerSite", "{T}_External_Career_Site",
    "Search", "{t}jobs", "jobs", "Global", "GlobalCareers", "professional",
    "{t}External", "{t}_External", "CareerSite", "Career", "careersite",
]

MAX_MISS_ATTEMPTS = 3      # stop retrying a tenant after this many failures


def probe(tenant: str) -> dict | None:
    """First combination that returns a populated board, or None."""
    for dc, template in itertools.product(DCS, SITE_TEMPLATES):
        site = template.replace("{t}", tenant).replace("{T}", tenant.upper())
        url = f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
        payload = http.post_json(
            url, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
        )
        if isinstance(payload, dict) and isinstance(payload.get("total"), int) \
                and payload["total"] > 0:
            return {"dc": dc, "site": site, "total": payload["total"]}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40,
                        help="tenants to probe this run (0 = all)")
    parser.add_argument("--retry-misses", action="store_true",
                        help="also retry tenants that previously failed")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    sites = json.loads(config.WORKDAY_SITES.read_text()) if config.WORKDAY_SITES.exists() else {}
    companies = json.loads(config.COMPANIES_FILE.read_text())
    workday = [c for c in companies if (c.get("ats") or "").lower() == "workday"]

    def unresolved(company):
        entry = sites.get(company["slug"])
        if entry is None:
            return True
        if entry.get("site"):
            return False
        if args.retry_misses:
            return True
        return entry.get("attempts", 0) < MAX_MISS_ATTEMPTS

    pending = [c for c in workday if unresolved(c)]
    if args.limit:
        pending = pending[:args.limit]

    resolved = sum(1 for e in sites.values() if e.get("site"))
    log.info("Workday: %d resolved, %d total, probing %d this run...",
             resolved, len(workday), len(pending))
    if not pending:
        return 0

    def work(company):
        return [(company, probe(company["slug"]))]

    found = 0
    for company, result in http.fan_out(work, pending, "discover"):
        slug = company["slug"]
        if result:
            sites[slug] = {"dc": result["dc"], "site": result["site"],
                           "name": company.get("name") or slug}
            found += 1
            log.info("  found %-22s %s / %s  (%d postings)",
                     slug, result["dc"], result["site"], result["total"])
        else:
            prior = sites.get(slug) or {}
            sites[slug] = {"dc": None, "site": None,
                           "name": company.get("name") or slug,
                           "attempts": prior.get("attempts", 0) + 1}

    config.WORKDAY_SITES.write_text(
        json.dumps(dict(sorted(sites.items())), indent=1, ensure_ascii=False) + "\n"
    )
    log.info("Resolved %d new board(s); %d known in total.",
             found, sum(1 for e in sites.values() if e.get("site")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
