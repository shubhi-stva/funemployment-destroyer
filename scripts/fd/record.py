"""Build and vet a single job record in the docs/data/jobs.json schema."""

from __future__ import annotations

from datetime import datetime, timezone

from . import classify, config


def iso(value) -> str:
    """Coerce whatever an ATS gave us into a UTC ISO-8601 string."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        # Lever hands back epoch milliseconds.
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def build(
    *,
    job_id: str,
    company: str,
    title: str,
    location: str,
    url: str,
    posted_at,
    source: str,
    description: str = "",
    department: str = "",
    ats_workmode: str | None = None,
    commitment: str = "",
) -> dict | None:
    """Return a site-schema job, or None if it should not be collected.

    This is where the user's two standing rules are enforced:
      * internships of any season are welcome;
      * full-time roles only when the posting sets no degree or GPA gate.
    """
    title = classify.clean_text(title)
    if not job_id or not title or not url:
        return None

    category = classify.classify_category(title, department)
    if category is None:
        return None  # not a tech role

    body = classify.clean_text(description)
    text_lower = body.lower()
    haystack = f"{title.lower()} {text_lower}"

    internship = classify.is_internship_role(title, commitment)
    degree = classify.classify_degree(haystack, internship)
    experience = classify.classify_experience(title, text_lower, internship)

    if not internship:
        # --- full-time gate -------------------------------------------------
        if degree not in config.FULLTIME_ALLOWED_DEGREE:
            return None
        if classify.has_gpa_requirement(haystack):
            return None
        if classify.LEVEL_RANK.get(experience, 9) > config.FULLTIME_MAX_LEVEL:
            return None

    posted_iso = iso(posted_at)
    location = classify.clean_text(location) or "Not specified"

    job = {
        "id": job_id,
        "company": classify.clean_text(company) or "Unknown company",
        "title": title,
        "type": "Internship" if internship else "Full Time",
        "category": category,
        "season": classify.extract_season(title, body) if internship else None,
        "location": location,
        "workMode": classify.classify_workmode(ats_workmode, location, text_lower),
        "url": url,
        "postedAt": posted_iso,
        "firstSeen": posted_iso,  # replaced by the persisted value in build.py
        "degreeRequirement": degree,
        "experienceLevel": experience,
        "status": "open",
        "priority": 0,  # scored in build.py, once firstSeen is final
        "source": source,
        "notes": summarise(body, degree, internship),
    }
    return job


def summarise(body: str, degree: str, internship: bool) -> str:
    """A one-line note for the card. Kept short so jobs.json stays small."""
    bits = []
    if degree == classify.DEGREE_NO:
        bits.append("No degree gate")
    years = classify.min_years_required(body.lower())
    if years and not internship:
        bits.append(f"{years}+ yrs experience asked")
    if not bits:
        return ""
    return " · ".join(bits)
