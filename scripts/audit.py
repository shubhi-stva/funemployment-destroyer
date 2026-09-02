#!/usr/bin/env python3
"""Re-verify published listings against their live posting text.

The collector classifies each posting once, at collection time. This script
independently re-fetches the postings behind docs/data/jobs.json and checks
the published fields against what the employer actually wrote -- so a
classifier bug shows up as a report rather than as a bad listing on the site.

It deliberately re-derives the verdicts from raw text instead of trusting the
stored fields, and it reports coverage honestly: postings from ATS platforms
the collector does not poll directly (Workday, Oracle, SmartRecruiters via the
upstream feed) have no fetchable body, so only their titles can be checked.

Usage:
    python scripts/audit.py                # audit everything fetchable
    python scripts/audit.py --type "Full Time"
    python scripts/audit.py --limit 50
    python scripts/audit.py --verbose      # show each violation's evidence
"""

from __future__ import annotations

import argparse
import collections
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fd import classify, config, enrich, http  # noqa: E402

log = logging.getLogger("fd.audit")

FETCHERS = {
    "greenhouse": lambda slug: (
        "https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % slug),
    "lever": lambda slug: "https://api.lever.co/v0/postings/%s?mode=json" % slug,
    "ashby": lambda slug: "https://api.ashbyhq.com/posting-api/job-board/%s" % slug,
}


def fetch_board(key: tuple[str, str]) -> list[tuple[str, str]]:
    """Return (job_id, body_text) for one board."""
    ats, slug = key
    payload = http.get_json(FETCHERS[ats](slug))
    out: list[tuple[str, str]] = []

    if ats == "greenhouse" and isinstance(payload, dict):
        for p in payload.get("jobs") or []:
            out.append((f"greenhouse:{slug}:{p.get('id')}", p.get("content") or ""))
    elif ats == "lever" and isinstance(payload, list):
        for p in payload:
            body = " ".join(filter(None, [
                p.get("descriptionPlain") or p.get("description") or "",
                p.get("additionalPlain") or p.get("additional") or "",
            ]))
            out.append((f"lever:{slug}:{p.get('id')}", body))
    elif ats == "ashby" and isinstance(payload, dict):
        for p in payload.get("jobs") or []:
            out.append((f"ashby:{slug}:{p.get('id')}",
                        p.get("descriptionHtml") or p.get("descriptionPlain") or ""))
    return out


def check(job: dict, body: str) -> list[str]:
    """Re-derive every gate from raw text. Returns a list of violations."""
    text = classify.clean_text(body)
    low = text.lower()
    hay = f"{job['title'].lower()} {low}"
    problems = []

    internship = job["type"] == "Internship"

    # --- undergraduate only ---
    if classify.is_graduate_only(job["title"], hay):
        problems.append("requires a graduate degree")

    # --- degree, re-derived ---
    degree = classify.classify_degree(hay, internship)

    # Mirror the collector's rule: an internship listing a degree means the
    # degree is in progress, so anything short of an explicit no-degree
    # becomes "Currently enrolled". Comparing against the raw verdict here
    # would report ~100 mismatches that are all working as designed.
    expected = degree
    if internship and degree != classify.DEGREE_NO:
        expected = classify.DEGREE_ENROLLED

    if expected != job["degreeRequirement"]:
        problems.append(
            f"degree mismatch: published '{job['degreeRequirement']}', "
            f"text implies '{expected}'")

    if not internship:
        if degree not in config.FULLTIME_ALLOWED_DEGREE:
            problems.append(f"full-time with a degree gate ({degree})")
        if classify.has_gpa_requirement(hay):
            problems.append("full-time with a GPA floor")
        # Use title+body, exactly as the collector does. Checking the body
        # alone flagged "Build & Release Engineer - New Grad" because the
        # explicit new-grad signal lives in its title.
        years = classify.min_years_required(low)
        if years > config.FULLTIME_MAX_YEARS and not classify._NO_EXPERIENCE_RE.search(hay):
            problems.append(f"full-time asking {years}+ years of experience")
        level = classify.classify_experience(job["title"], low, False)
        if classify.LEVEL_RANK.get(level, 9) > config.FULLTIME_MAX_LEVEL:
            problems.append(f"full-time above entry level ({level})")

    # --- scope ---
    if classify.is_non_tech_title(job["title"]):
        problems.append("title is not a tech role")
    if classify.is_us_location(job["location"]) is False:
        problems.append(f"location is outside the US ({job['location']})")

    return problems


def evidence(body: str, patterns=("(required)", "bachelor", "master", "phd",
                                  "years of", "gpa", "degree")) -> str:
    low = classify.clean_text(body).lower()
    for p in patterns:
        i = low.find(p)
        if i != -1:
            return "..." + low[max(0, i - 90):i + 130].strip() + "..."
    return "(no matching text)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", choices=["Full Time", "Internship"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    jobs = json.loads(config.OUTPUT_FILE.read_text())["jobs"]
    if args.type:
        jobs = [j for j in jobs if j["type"] == args.type]
    if args.limit:
        jobs = jobs[:args.limit]

    # Group by board so each is fetched once.
    boards: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    unfetchable = []
    for job in jobs:
        parts = job["id"].split(":")
        if len(parts) >= 3 and parts[0] in FETCHERS:
            boards[(parts[0], parts[1])].append(job)
        else:
            unfetchable.append(job)

    log.info("Auditing %d jobs across %d boards (%d not directly fetchable)...",
             len(jobs) - len(unfetchable), len(boards), len(unfetchable))

    bodies: dict[str, str] = {}
    for pairs in http.fan_out(fetch_board, list(boards), "audit"):
        bodies[pairs[0]] = pairs[1]

    violations, checked, missing = [], 0, 0
    for job_list in boards.values():
        for job in job_list:
            body = bodies.get(job["id"])
            if body is None:
                missing += 1
                continue
            checked += 1
            problems = check(job, body)
            if problems:
                violations.append((job, problems, body))

    # Postings we did not poll directly. Most are Workday, whose per-job
    # endpoint is derivable from the URL, so most can still be verified in
    # full rather than by title alone.
    if unfetchable:
        log.info("Fetching %d individual postings (Workday etc.)...", len(unfetchable))
        fetched = http.fan_out(
            lambda j: [(j["id"], enrich.fetch_body(j))], unfetchable, "audit-direct")
        extra = dict(fetched)
    else:
        extra = {}

    title_only = 0
    for job in unfetchable:
        body = extra.get(job["id"]) or ""
        if body:
            checked += 1
            problems = check(job, body)
        else:
            title_only += 1
            problems = []
            if classify.is_graduate_only(job["title"], ""):
                problems.append("title implies a graduate degree")
            if classify.is_non_tech_title(job["title"]):
                problems.append("title is not a tech role")
            if classify.is_us_location(job["location"]) is False:
                problems.append("location outside the US")
        if problems:
            violations.append((job, problems, body))

    log.info("")
    log.info("=" * 70)
    log.info("Full-text verified : %d", checked)
    log.info("Title-only         : %d (no body available anywhere)", title_only)
    log.info("Gone from board    : %d (posting closed since collection)", missing)
    log.info("VIOLATIONS         : %d", len(violations))
    log.info("=" * 70)

    for job, problems, body in violations:
        log.info("")
        log.info("%s | %s", job["company"][:32], job["title"][:56])
        log.info("  %s", job["url"])
        for p in problems:
            log.info("  - %s", p)
        if args.verbose and body:
            log.info("  evidence: %s", evidence(body)[:260])

    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
