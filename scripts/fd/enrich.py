"""Fetch descriptions for postings the upstream feed only gave us titles for.

The upstream internship CSV carries no job description, so those postings can
only be screened by title -- a much weaker test than the full-text analysis
applied to boards we poll ourselves. Most of them live on Workday, whose
per-job JSON endpoint is derivable from the posting URL, so we fetch the body
and re-run the same gates.

Without this, roughly half the board was title-screened only.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from . import classify, config, http, record

log = logging.getLogger("fd.enrich")


def workday_api(url: str) -> str | None:
    """Turn a Workday posting URL into its CXS JSON endpoint.

    https://caci.wd1.myworkdayjobs.com/external/job/Sarasota-FL-US/Title_123
        -> https://caci.wd1.myworkdayjobs.com/wday/cxs/caci/external/job/...
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if "myworkdayjobs.com" not in parsed.netloc:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None

    tenant = parsed.netloc.split(".")[0]
    site, rest = parts[0], "/".join(parts[1:])
    return f"https://{parsed.netloc}/wday/cxs/{tenant}/{site}/{rest}"


def fetch_body(job: dict) -> str:
    """Best-effort description for a posting we did not poll directly."""
    api = workday_api(job.get("url", ""))
    if not api:
        return ""
    payload = http.get_json(api)
    if not isinstance(payload, dict):
        return ""
    info = payload.get("jobPostingInfo") or {}
    return info.get("jobDescription") or ""


def _revalidate(job: dict) -> list[dict]:
    """Re-screen one posting against its real description.

    Returns [job] to keep it (with fields corrected) or [] to drop it.
    """
    body = fetch_body(job)
    if not body:
        return [job]   # nothing new learned; the title-level verdict stands

    text = classify.clean_text(body)
    low = text.lower()
    hay = f"{job['title'].lower()} {low}"
    internship = job["type"] == "Internship"

    if classify.is_graduate_only(job["title"], hay):
        return []

    degree = classify.classify_degree(hay, internship)

    if internship:
        # Same rule as record.build: a degree named on an internship is in
        # progress, not held.
        job["degreeRequirement"] = (
            degree if degree == classify.DEGREE_NO else classify.DEGREE_ENROLLED
        )
    else:
        if degree not in config.FULLTIME_ALLOWED_DEGREE:
            return []
        if classify.has_gpa_requirement(hay):
            return []
        if classify.requires_prior_experience(hay):
            return []
        level = classify.classify_experience(job["title"], low, False)
        if classify.LEVEL_RANK.get(level, 9) > config.FULLTIME_MAX_LEVEL:
            return []
        job["degreeRequirement"] = degree
        job["experienceLevel"] = level

    # The board name may describe the board rather than the employer; the
    # description usually names the real company.
    if classify.is_generic_company(job.get("company", "")):
        job["company"] = record.resolve_company(job["company"], text, job["id"])

    # Fill in details the CSV could not give us.
    if not job.get("seasons"):
        seasons = classify.extract_seasons(job["title"], text)
        if seasons:
            job["seasons"] = seasons
            job["season"] = seasons[0]
    if job.get("workMode") in ("", "Not specified"):
        job["workMode"] = classify.classify_workmode(None, job.get("location", ""), low)

    return [job]


def enrich(jobs: list[dict]) -> list[dict]:
    """Re-screen every posting that has no description yet."""
    candidates = [j for j in jobs if workday_api(j.get("url", ""))]
    if not candidates:
        return jobs

    log.info("Fetching descriptions for %d title-only postings...", len(candidates))
    kept = http.fan_out(_revalidate, candidates, "enrich")

    kept_ids = {j["id"] for j in kept}
    dropped = len(candidates) - len(kept)
    log.info("  enrich: %d screened on full text, %d dropped", len(candidates), dropped)

    return [j for j in jobs
            if j["id"] not in {c["id"] for c in candidates} or j["id"] in kept_ids]
