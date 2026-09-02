"""Ashby public posting API.

    https://api.ashbyhq.com/posting-api/job-board/{slug}

The REST board endpoint returns descriptionHtml, workplaceType and
employmentType, so there is no need for the GraphQL endpoint.
"""

from __future__ import annotations

from .. import http, record

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def poll(company: dict) -> list[dict]:
    slug = company["slug"]
    payload = http.get_json(API.format(slug=slug))
    if not isinstance(payload, dict):
        return []

    jobs = []
    for raw in payload.get("jobs") or []:
        job_id = raw.get("id")
        if not job_id or raw.get("isListed") is False:
            continue

        built = record.build(
            job_id=f"ashby:{slug}:{job_id}",
            company=company.get("name") or slug,
            title=raw.get("title", ""),
            location=raw.get("location") or "",
            url=raw.get("jobUrl") or raw.get("applyUrl") or "",
            posted_at=raw.get("publishedAt") or raw.get("updatedAt"),
            source="Ashby",
            description=raw.get("descriptionHtml") or raw.get("descriptionPlain") or "",
            department=" ".join(filter(None, [
                raw.get("department") or "",
                raw.get("team") or "",
            ])),
            ats_workmode=raw.get("workplaceType"),
            commitment=raw.get("employmentType") or "",
        )
        if built:
            jobs.append(built)
    return jobs


def collect(companies: list[dict]) -> list[dict]:
    return http.fan_out(poll, companies, "ashby")
