"""Build and vet a single job record in the docs/data/jobs.json schema."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import classify, config

# Ids rejected by full-text analysis. The upstream internship feed ships no
# description, so its postings can only be screened by title -- but we poll
# the same boards ourselves and *do* read their bodies. Recording rejections
# here lets build.py drop an upstream posting that our own full-text pass
# already threw out, instead of the weaker check silently reinstating it.
REJECTED_IDS: set[str] = set()


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

    # A date-only source ("2026-09-01") carries no time of day. Keep it
    # date-only so the card shows a date rather than a fabricated midnight.
    if "T" not in text and " " not in text:
        return parsed.date().isoformat()

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def content_key(company: str, title: str, location: str) -> str:
    """A stable identity for a posting, independent of its requisition id.

    ATS ids are not dependable: an employer re-posting a role gets a new
    requisition number, and Workday paths shift. Personal state (favorite,
    applied, hidden) is keyed on this instead, so marking a job applied
    survives the job being re-listed.
    """
    raw = "|".join(part.strip().lower() for part in (company, title, location))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def resolve_company(name: str, description: str, job_id: str) -> str:
    """Employer name: board name, else the posting text, else the board slug."""
    resolved = classify.clean_company_name(name, description)
    if resolved and not classify.is_generic_company(resolved):
        return resolved

    parts = job_id.split(":")
    if len(parts) >= 2:
        from_slug = classify.company_from_slug(parts[1])
        if from_slug:
            return from_slug
    return resolved or "Unknown company"


def careers_url(job_url: str) -> str:
    """The board page a posting lives on -- the employer's live job listing.

    Derived by trimming the job-specific tail off the posting URL, so it
    works for any board without a per-platform table.
    """
    if not job_url:
        return ""
    try:
        parsed = urlparse(job_url)
    except ValueError:
        return ""

    parts = [p for p in parsed.path.split("/") if p]
    origin = f"{parsed.scheme}://{parsed.netloc}"

    # greenhouse: /{slug}/jobs/{id}   lever & ashby: /{slug}/{uuid}
    if "jobs" in parts:
        parts = parts[:parts.index("jobs")]
    elif "job" in parts:               # workday: /{site}/job/{loc}/{title}
        parts = parts[:parts.index("job")]
    elif len(parts) > 1:
        parts = parts[:1]

    return origin + ("/" + "/".join(parts) if parts else "")


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

    def reject() -> None:
        REJECTED_IDS.add(job_id)
        return None

    category = classify.classify_category(title, department)
    if category is None:
        return reject()  # not a tech role

    body = classify.clean_text(description)
    text_lower = body.lower()
    haystack = f"{title.lower()} {text_lower}"

    internship = classify.is_internship_role(title, commitment)

    # Undergraduate only: drop anything that needs a master's, PhD or MBA.
    if classify.is_graduate_only(title, haystack):
        return reject()

    degree = classify.classify_degree(haystack, internship)
    experience = classify.classify_experience(title, text_lower, internship)

    if internship and degree != classify.DEGREE_NO:
        # An internship posting that lists "Bachelor's degree in X" means the
        # degree is in progress, not finished -- that is what being an intern
        # is. Collapse everything except an explicit no-degree-needed to
        # "Currently enrolled" rather than reporting a completed degree.
        degree = classify.DEGREE_ENROLLED

    if not internship:
        # --- full-time gate -------------------------------------------------
        # Three independent conditions, all required: no degree gate, no GPA
        # floor, and genuinely open to someone with no track record.
        if degree not in config.FULLTIME_ALLOWED_DEGREE:
            return reject()
        if classify.has_gpa_requirement(haystack):
            return reject()
        if classify.LEVEL_RANK.get(experience, 9) > config.FULLTIME_MAX_LEVEL:
            return reject()
        if classify.requires_prior_experience(haystack):
            return reject()

    posted_iso = iso(posted_at)
    location = classify.clean_text(location) or "Not specified"

    if config.US_ONLY and classify.is_us_location(location) is False:
        return reject()

    job = {
        "id": job_id,
        "company": resolve_company(company, description, job_id),
        "title": title,
        "type": "Internship" if internship else "Full Time",
        "category": category,
        "season": classify.extract_season(title, body) if internship else None,
        "seasons": classify.extract_seasons(title, body) if internship else [],
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
        "companyDomain": "",   # filled in by fd.logos.attach()
        "companyUrl": careers_url(url),
        "key": "",   # filled in below, once company/title/location are final
        "notes": summarise(body, degree, internship),
    }
    job["key"] = content_key(job["company"], job["title"], job["location"])
    return job


def summarise(body: str, degree: str, internship: bool) -> str:
    """A one-line note for the card. Kept short so jobs.json stays small."""
    bits = []
    if degree == classify.DEGREE_NO:
        bits.append("No degree gate")
    if not internship:
        low = body.lower()
        if classify._NO_EXPERIENCE_RE.search(low):
            bits.append("No experience required")
        else:
            years = classify.min_years_required(low)
            if years:
                bits.append(f"{years}+ yrs experience asked")
    if not bits:
        return ""
    return " · ".join(bits)
