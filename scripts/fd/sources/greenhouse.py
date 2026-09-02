"""Greenhouse public job board API.

    https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

`content=true` returns the full (double-escaped) HTML description in one
request, so a board costs exactly one round trip.
"""

from __future__ import annotations

from .. import http, record

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def poll(company: dict) -> list[dict]:
    slug = company["slug"]
    payload = http.get_json(API.format(slug=slug))
    if not isinstance(payload, dict):
        return []

    jobs = []
    for raw in payload.get("jobs") or []:
        job_id = raw.get("id")
        if job_id is None:
            continue

        departments = raw.get("departments") or []
        department = " ".join(d.get("name", "") for d in departments if isinstance(d, dict))

        location = (raw.get("location") or {}).get("name", "")

        built = record.build(
            job_id=f"greenhouse:{slug}:{job_id}",
            company=raw.get("company_name") or company.get("name") or slug,
            title=raw.get("title", ""),
            location=location,
            url=raw.get("absolute_url", ""),
            posted_at=raw.get("first_published") or raw.get("updated_at"),
            source="Greenhouse",
            description=raw.get("content", ""),
            department=department,
        )
        if built:
            jobs.append(built)
    return jobs


def collect(companies: list[dict]) -> list[dict]:
    return http.fan_out(poll, companies, "greenhouse")
