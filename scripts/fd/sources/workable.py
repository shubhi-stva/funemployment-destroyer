"""Workable public widget API.

    https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true

About 145 employers. `details=true` returns the full description inline, so
one request covers a whole board and no per-posting fetch is needed.
"""

from __future__ import annotations

import logging

from .. import http, record

log = logging.getLogger("fd.workable")

API = "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"


def poll(company: dict) -> list[dict]:
    slug = company["slug"]
    payload = http.get_json(API.format(slug=slug))
    if not isinstance(payload, dict):
        return []

    jobs = []
    for posting in payload.get("jobs") or []:
        shortcode = posting.get("shortcode")
        if not shortcode:
            continue

        location = ", ".join(
            part for part in (posting.get("city"), posting.get("state"),
                              posting.get("country"))
            if part
        )

        built = record.build(
            job_id=f"workable:{slug}:{shortcode}",
            company=company.get("name") or slug,
            title=posting.get("title") or "",
            location=location,
            url=posting.get("url") or posting.get("shortlink") or "",
            posted_at=posting.get("published_on") or posting.get("created_at") or "",
            source="Workable",
            description=posting.get("description") or "",
            department=posting.get("department") or "",
            commitment=posting.get("employment_type") or "",
        )
        if built:
            jobs.append(built)
    return jobs


def collect(companies: list[dict]) -> list[dict]:
    return http.fan_out(poll, companies, "workable")
