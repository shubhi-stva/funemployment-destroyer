"""Lever public postings API.

    https://api.lever.co/v0/postings/{slug}?mode=json

Lever is the richest of the three: it hands back a plain-text description
plus an explicit `workplaceType` and a `commitment` (Full-time / Intern).
"""

from __future__ import annotations

from .. import http, record

API = "https://api.lever.co/v0/postings/{slug}?mode=json"


def poll(company: dict) -> list[dict]:
    slug = company["slug"]
    payload = http.get_json(API.format(slug=slug))
    if not isinstance(payload, list):
        return []

    jobs = []
    for raw in payload:
        job_id = raw.get("id")
        if not job_id:
            continue

        categories = raw.get("categories") or {}
        description = " ".join(filter(None, [
            raw.get("descriptionPlain") or raw.get("description") or "",
            raw.get("additionalPlain") or raw.get("additional") or "",
        ]))

        built = record.build(
            job_id=f"lever:{slug}:{job_id}",
            company=company.get("name") or slug,
            title=raw.get("text", ""),
            location=categories.get("location") or "",
            url=raw.get("hostedUrl") or raw.get("applyUrl") or "",
            posted_at=raw.get("createdAt"),
            source="Lever",
            description=description,
            department=" ".join(filter(None, [
                categories.get("department") or "",
                categories.get("team") or "",
            ])),
            ats_workmode=raw.get("workplaceType"),
            commitment=categories.get("commitment") or "",
        )
        if built:
            jobs.append(built)
    return jobs


def collect(companies: list[dict]) -> list[dict]:
    return http.fan_out(poll, companies, "lever")
