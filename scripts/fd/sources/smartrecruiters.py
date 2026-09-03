"""SmartRecruiters public postings API.

    https://api.smartrecruiters.com/v1/companies/{slug}/postings

About 280 employers in the company list. The listing carries only a title and
location, so descriptions come from a second request per posting. Titles are
screened first so that only plausible matches are fetched in full.
"""

from __future__ import annotations

import logging

from .. import classify, http, record

log = logging.getLogger("fd.smartrecruiters")

LIST = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}"
DETAIL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job_id}"
MAX_PAGES = 3


def _description(detail: dict) -> str:
    sections = ((detail or {}).get("jobAd") or {}).get("sections") or {}
    return " ".join(
        (section or {}).get("text", "")
        for section in sections.values()
        if isinstance(section, dict)
    )


def poll(company: dict) -> list[dict]:
    slug = company["slug"]
    candidates = []

    for page in range(MAX_PAGES):
        payload = http.get_json(LIST.format(slug=slug, offset=page * 100))
        if not isinstance(payload, dict):
            break
        postings = payload.get("content") or []
        for posting in postings:
            title = posting.get("name") or ""
            if classify.is_non_tech_title(title):
                continue
            if classify.classify_category(title) is None:
                continue
            candidates.append(posting)
        if len(postings) < 100:
            break

    jobs = []
    for posting in candidates:
        job_id = posting.get("id")
        if not job_id:
            continue
        detail = http.get_json(DETAIL.format(slug=slug, job_id=job_id))

        loc = posting.get("location") or {}
        location = ", ".join(
            part for part in (loc.get("city"), loc.get("region"), loc.get("country"))
            if part
        )

        built = record.build(
            job_id=f"smartrecruiters:{slug}:{job_id}",
            company=(posting.get("company") or {}).get("name") or company.get("name") or slug,
            title=posting.get("name") or "",
            location=location,
            url=f"https://jobs.smartrecruiters.com/{slug}/{job_id}",
            posted_at=posting.get("releasedDate") or "",
            source="SmartRecruiters",
            description=_description(detail),
            department=(posting.get("department") or {}).get("label", ""),
        )
        if built:
            jobs.append(built)
    return jobs


def collect(companies: list[dict]) -> list[dict]:
    return http.fan_out(poll, companies, "smartrecruiters")
