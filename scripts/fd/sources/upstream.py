"""Internship feed from zshah101/Automated-List-Of-...-Tech-Internships (MIT).

That project already polls thousands of boards for internships every 30
minutes, so we consume its CSV rather than duplicating the work. Its ids use
the same `{ats}:{slug}:{id}` scheme we generate, which makes de-duplication
against our own ATS polling free.
"""

from __future__ import annotations

import csv
import io
import logging

from .. import classify, config, http, record

log = logging.getLogger("fd.upstream")

# The feed's own coarse category, used only as a fallback hint.
CATEGORY_HINT = {
    "software": "Software Engineering",
    "ai/ml": "AI / Machine Learning",
    "ml": "AI / Machine Learning",
    "data": "Data",
    "security": "Cybersecurity",
    "hardware": "Software Engineering",
    "quant": "Data",
}


def collect() -> list[dict]:
    body = http.get_text(config.UPSTREAM_CSV)
    if not body:
        log.warning("upstream CSV unavailable; skipping")
        return []

    jobs = []
    for row in csv.DictReader(io.StringIO(body)):
        job_id = (row.get("id") or "").strip()
        title = classify.clean_text(row.get("title"))
        url = (row.get("url") or "").strip()
        if not job_id or not title or not url:
            continue

        # A title that is positively non-tech is rejected outright. The feed's
        # own coarse category must not resurrect it -- that fallback was
        # reinstating civil-engineering internships as "Software".
        if classify.is_non_tech_title(title):
            continue

        # Otherwise prefer our own bucketing, falling back to the feed's hint
        # only when our classifier simply found no match.
        category = classify.classify_category(title, row.get("category") or "")
        if category is None:
            category = CATEGORY_HINT.get((row.get("category") or "").strip().lower())
        if category is None:
            continue

        # Undergraduate only. The feed carries no description, so this is a
        # title-level test -- record.build() does the full-text version for
        # postings we poll ourselves.
        if classify.is_graduate_only(title, ""):
            continue

        seasons = classify.extract_seasons(title)
        if not seasons:
            declared = (row.get("season") or "").strip()
            if declared.lower() not in ("", "not stated", "unknown"):
                seasons = [declared]
        season = seasons[0] if seasons else None

        location = classify.clean_text(row.get("location")) or "Not specified"
        in_us = classify.is_us_location(location)
        if config.US_ONLY and (in_us is False or (config.US_STRICT and in_us is None)):
            continue
        posted = record.iso(row.get("posted_at"))
        first_seen = record.iso(row.get("first_seen_at")) or posted

        notes = []
        if (row.get("salary") or "").strip():
            notes.append(row["salary"].strip())
        skills = [s.strip() for s in (row.get("skills") or "").split(";") if s.strip()]
        if skills:
            notes.append(", ".join(skills[:5]))

        jobs.append({
            "id": job_id,
            "company": record.resolve_company(row.get("company") or "", "", job_id),
            "title": title,
            "type": "Internship",
            "category": category,
            "season": season,
            "seasons": seasons,
            "location": location,
            "workMode": classify.classify_workmode(row.get("remote"), location, ""),
            "url": url,
            "postedAt": posted,
            "firstSeen": first_seen,
            "degreeRequirement": classify.DEGREE_ENROLLED,
            "experienceLevel": "Intern",
            "status": "open",
            "priority": 0,
            "source": _source_label(job_id),
            "companyDomain": "",
            "companyUrl": record.careers_url(url),
            "notes": " · ".join(notes),
            "key": record.content_key(
                record.resolve_company(row.get("company") or "", "", job_id),
                title, location),
        })

    log.info("  upstream: %d internships parsed", len(jobs))
    return jobs


def _source_label(job_id: str) -> str:
    ats = job_id.split(":", 1)[0] if ":" in job_id else ""
    return {
        "greenhouse": "Greenhouse",
        "lever": "Lever",
        "ashby": "Ashby",
        "workday": "Workday",
        "smartrecruiters": "SmartRecruiters",
        "workable": "Workable",
        "rippling": "Rippling",
        "breezy": "Breezy",
        "recruitee": "Recruitee",
        "oracle": "Oracle",
    }.get(ats, "Internship feed")
