#!/usr/bin/env python3
"""Funemployment Destroyer collector.

Polls Greenhouse / Lever / Ashby job boards plus an upstream internship feed,
keeps only what matters (tech roles; internships of any season; full-time
roles with no degree or GPA gate), and rewrites docs/data/jobs.json.

Usage:
    python scripts/collect.py                 # full run
    python scripts/collect.py --limit 40      # smoke test against 40 boards
    python scripts/collect.py --ats lever     # one platform
    python scripts/collect.py --no-upstream   # skip the internship feed
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fd import build, config  # noqa: E402
from fd import enrich  # noqa: E402
from fd.sources import ashby, greenhouse, lever, upstream  # noqa: E402

POLLERS = {
    "greenhouse": greenhouse.collect,
    "lever": lever.collect,
    "ashby": ashby.collect,
}

log = logging.getLogger("fd")


def load_companies(enabled: tuple[str, ...], limit: int) -> dict[str, list[dict]]:
    """Group the vendored company list by ATS, keeping only enabled platforms."""
    if not config.COMPANIES_FILE.exists():
        log.error("missing %s -- run scripts/refresh_companies.py", config.COMPANIES_FILE)
        return {}

    raw = json.loads(config.COMPANIES_FILE.read_text())
    grouped: dict[str, list[dict]] = {name: [] for name in enabled}
    for entry in raw:
        ats = (entry.get("ats") or "").lower()
        if ats in grouped and entry.get("slug"):
            grouped[ats].append(entry)

    if limit:
        for ats in grouped:
            grouped[ats] = grouped[ats][:limit]
    return grouped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=config.BOARD_LIMIT,
                        help="max boards per ATS (0 = all)")
    parser.add_argument("--ats", action="append", choices=sorted(POLLERS),
                        help="restrict to one or more platforms (repeatable)")
    parser.add_argument("--no-upstream", action="store_true",
                        help="skip the upstream internship CSV")
    parser.add_argument("--no-ats", action="store_true",
                        help="skip direct board polling (upstream only)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be written, but write nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    started = time.time()
    collected: list[dict] = []

    if not args.no_upstream:
        log.info("Upstream internship feed...")
        collected.extend(upstream.collect())

    if not args.no_ats:
        enabled = tuple(args.ats) if args.ats else config.ENABLED_ATS
        companies = load_companies(enabled, args.limit)
        for ats in enabled:
            boards = companies.get(ats, [])
            if not boards:
                continue
            log.info("Polling %d %s boards...", len(boards), ats)
            collected.extend(POLLERS[ats](boards))

    log.info("Collected %d raw postings in %.0fs", len(collected), time.time() - started)

    # Upstream postings arrive title-only; fetch their descriptions so they
    # face the same full-text gates as everything else.
    collected = enrich.enrich(collected)

    jobs = build.drop_rejected(collected)
    jobs = build.dedupe(jobs)
    log.info("Deduped to %d", len(jobs))

    seen = build.load_seen()
    seen = build.apply_first_seen(jobs, seen)
    jobs = build.prune(jobs)

    if args.dry_run:
        log.info("Dry run -- nothing written. Would write %d jobs.", len(jobs))
        log.info(json.dumps(build.summarise(jobs), indent=2))
        return 0

    if not jobs:
        # Never blow away a good jobs.json because one run failed upstream.
        log.error("No jobs collected; refusing to overwrite %s", config.OUTPUT_FILE)
        return 1

    stats = build.write(jobs)
    # Only remember ids we actually kept, so seen.json cannot grow forever.
    build.save_seen({j["id"]: seen[j["id"]] for j in jobs if j["id"] in seen})

    log.info("Wrote %s", config.OUTPUT_FILE)
    log.info(json.dumps(stats, indent=2))
    log.info("Done in %.0fs", time.time() - started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
