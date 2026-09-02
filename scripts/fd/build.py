"""Merge every source into the single jobs.json the frontend reads."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from . import classify, config, logos, record

log = logging.getLogger("fd.build")

# Prefer records from richer sources when the same id shows up twice.
SOURCE_RANK = {"Lever": 3, "Ashby": 3, "Greenhouse": 3}


def load_seen() -> dict[str, str]:
    """id -> the ISO timestamp we first observed it, persisted across runs."""
    if not config.SEEN_FILE.exists():
        return {}
    try:
        data = json.loads(config.SEEN_FILE.read_text())
        return data.get("firstSeen", {}) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as err:
        log.warning("could not read seen.json (%s); starting fresh", err)
        return {}


def save_seen(seen: dict[str, str]) -> None:
    config.SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.SEEN_FILE.write_text(
        json.dumps({"firstSeen": dict(sorted(seen.items()))}, indent=0) + "\n"
    )


def drop_rejected(jobs: list[dict]) -> list[dict]:
    """Remove postings our own full-text pass rejected.

    The upstream feed screens by title only. When we polled the same board
    directly and read the full description, that verdict is strictly better
    informed and wins.
    """
    rejected = record.REJECTED_IDS
    if not rejected:
        return jobs
    kept = [j for j in jobs if j["id"] not in rejected]
    dropped = len(jobs) - len(kept)
    if dropped:
        log.info("  dropped %d upstream postings rejected by full-text analysis", dropped)
    return kept


def dedupe(jobs: list[dict]) -> list[dict]:
    """Collapse by id, then by (company, title, location).

    The second pass matters because the upstream internship feed and our own
    ATS polling can reach the same posting by different routes.
    """
    by_id: dict[str, dict] = {}
    for job in jobs:
        existing = by_id.get(job["id"])
        if existing is None or _rank(job) > _rank(existing):
            by_id[job["id"]] = job

    by_key: dict[str, dict] = {}
    for job in by_id.values():
        key = job.get("key") or job["id"]
        existing = by_key.get(key)
        if existing is None or _rank(job) > _rank(existing):
            by_key[key] = job
        elif _rank(job) == _rank(existing) and job["id"] < existing["id"]:
            # Deterministic tie-break. Without one, which id survives can
            # flip between runs, and any state keyed on it would be lost.
            by_key[key] = job
    return list(by_key.values())


def _rank(job: dict) -> int:
    """Richer records win a tie: known degree status beats 'Not specified'."""
    score = SOURCE_RANK.get(job.get("source", ""), 1)
    if job.get("degreeRequirement") != classify.DEGREE_UNKNOWN:
        score += 2
    if job.get("notes"):
        score += 1
    return score


def apply_first_seen(jobs: list[dict], seen: dict[str, str]) -> dict[str, str]:
    """Stamp each job with the first time we ever saw it.

    This is what drives the "New" badge and the Newest sort, so it must be
    the moment *we* discovered the posting -- not the moment the ATS says it
    was published, which can be backdated.
    """
    now = datetime.now(timezone.utc).isoformat()
    updated = dict(seen)

    for job in jobs:
        job_id = job["id"]
        if job_id in updated:
            job["firstSeen"] = updated[job_id]
        else:
            # First run ever sees the whole backlog at once. Fall back to the
            # posting date so a cold start does not flag 1,500 jobs as "New".
            first = job.get("firstSeen") or job.get("postedAt") or now
            updated[job_id] = first
            job["firstSeen"] = first
    return updated


def _sort_stamp(job: dict) -> datetime | None:
    """Ordering key: when the company posted it, not when we found it."""
    return _parse(job.get("postedAt")) or _parse(job.get("firstSeen"))


def prune(jobs: list[dict]) -> list[dict]:
    """Drop stale postings, sort newest-posted first, and cap the payload."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.MAX_AGE_DAYS)

    fresh = []
    for job in jobs:
        stamp = _sort_stamp(job)
        if stamp is None or stamp >= cutoff:
            fresh.append(job)

    fresh.sort(key=lambda j: _sort_stamp(j) or datetime.min.replace(tzinfo=timezone.utc),
               reverse=True)

    if config.MAX_JOBS and len(fresh) > config.MAX_JOBS:
        log.info("  capping output at %d (from %d)", config.MAX_JOBS, len(fresh))
        fresh = fresh[:config.MAX_JOBS]
    return fresh


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def summarise(jobs: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    window = timedelta(hours=config.NEW_WINDOW_HOURS)

    def count(pred) -> int:
        return sum(1 for j in jobs if pred(j))

    return {
        "total": len(jobs),
        "internships": count(lambda j: j["type"] == "Internship"),
        "fullTime": count(lambda j: j["type"] == "Full Time"),
        "newWindowHours": config.NEW_WINDOW_HOURS,
        "newRecently": count(
            lambda j: (_sort_stamp(j) or datetime.min.replace(tzinfo=timezone.utc))
            >= now - window
        ),
        "noDegreeRequired": count(
            lambda j: j["degreeRequirement"] == classify.DEGREE_NO
        ),
    }


def _current_season_index(month: int) -> int:
    """Which season we are in now: Winter 1, Spring 2, Summer 3, Fall 4."""
    if month <= 2:
        return 1
    if month <= 5:
        return 2
    if month <= 8:
        return 3
    return 4


def write(jobs: list[dict]) -> dict:
    """Score, shape, and write docs/data/jobs.json."""
    logos.attach(jobs)

    for job in jobs:
        job["priority"] = classify.score_priority(job)

    stats = summarise(jobs)
    # Offer only terms that have not already passed -- a "Summer 2025" option
    # is noise. New seasons join the list automatically as postings appear.
    now = datetime.now(timezone.utc)
    current_key = now.year + _current_season_index(now.month) / 10
    seasons = sorted(
        {
            s
            for job in jobs
            for s in (job.get("seasons") or [])
            if classify.season_sort_key(s) >= current_key
        },
        key=classify.season_sort_key,
    )
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "schemaVersion": 1,
        "stats": stats,
        "seasons": seasons,
        "jobs": jobs,
    }

    config.OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    config.OUTPUT_FILE.write_text(body + "\n")

    # Same payload as a plain script assignment. fetch() is blocked by CORS
    # when index.html is opened from disk (file://), but a <script> tag is
    # not -- so the page can fall back to this and still work when the file
    # is simply double-clicked. Only loaded if the fetch actually fails.
    config.FALLBACK_FILE.write_text("window.FD_JOBS = " + body + ";\n")
    return stats
