"""Turn raw ATS postings into the fields docs/data/jobs.json promises.

Every classifier here is deliberately conservative: when the posting text
does not clearly say something, we return the "unknown" value rather than
guessing. A wrong "No degree required" is worse than a "Not specified",
because it wastes an application.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timezone

from . import config

# --------------------------------------------------------------------- text

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str | None) -> str:
    """HTML (possibly double-escaped, as Greenhouse serves it) -> plain text."""
    if not raw:
        return ""
    text = html.unescape(html.unescape(raw))
    text = _TAG_RE.sub(" ", text)
    text = unicodedata.normalize("NFKD", text)
    # Normalise the several apostrophes ATSes use so "bachelor's" matches.
    text = text.replace("’", "'").replace("‘", "'")
    return _WS_RE.sub(" ", text).strip()


def norm(text: str) -> str:
    return clean_text(text).lower()


# ------------------------------------------------------------------- degree

# Real postings rarely say "a degree is required". They say, in a bullet under
# Qualifications: "Bachelor's degree in Computer Science, or related field."
# So rather than ordering global regexes, we find every degree mention and read
# the window around it -- that window is what says required / preferred / or
# equivalent. Aggregate precedence is then: escape hatch > required > preferred.

# Note the mandatory possessive on bachelor/master: bare "master" is a verb in
# the wild ("learn and master complex systems", "master relationship builder").
_DEGREE_MENTION = re.compile(
    r"\b(?:"
    r"bachelor'?s|bachelors|master'?s|masters|"
    r"ba/bs|bs/ms|b\.s\.|b\.a\.|m\.s\.|bsc|msc|"
    r"phd|ph\.d\.|doctorate|"
    r"associate'?s degree|college degree|university degree|academic degree|"
    r"undergraduate degree|graduate degree|(?:4|four)[- ]year degree|"
    r"degree in|degree or|degree,|degree\.|degrees?\b"
    r")\b"
    # Bare abbreviations, but only where they are clearly the credential:
    # "BS in CS", "MS or equivalent", "BA/BS".
    r"|\b(?:bs|ba|ms|bsc|msc)\b(?=\s*(?:in|or|/|,|degree)\b)"
)

# Window is asymmetric: qualifiers ("required", "preferred", "or equivalent")
# follow the noun far more often than they precede it.
_WINDOW_BEFORE = 90
_WINDOW_AFTER = 150

# An explicit escape hatch: the degree is one acceptable path, not the only one.
_ESCAPE_RE = re.compile(
    r"or equivalent"
    r"|equivalent (?:practical |work |industry |professional |relevant )?experience"
    r"|in lieu of"
    r"|not required"
    r"|no degree"
    r"|degree (?:is )?not"
    r"|or (?:relevant|practical|comparable) experience"
    r"|we do not require"
    r"|regardless of (?:degree|education)"
    r"|self[- ]taught"
    r"|bootcamp"
)

_PREFERRED_RE = re.compile(
    r"preferred|a plus|nice to have|desirable|advantageous|bonus|ideally|"
    r"we'd love|would be great|helpful|beneficial"
)

_HARD_REQUIRED_RE = re.compile(
    r"required|must have|must possess|must hold|minimum|mandatory|essential|"
    r"you have|requirement"
)

_ENROLLED_RE = re.compile(
    r"currently enrolled"
    r"|currently pursuing|actively pursuing|pursuing (?:a|an|your)"
    r"|working toward(?:s)? (?:a |an )?(?:bachelor|master|degree|phd)"
    r"|enrolled in (?:a |an )?(?:accredited |full[- ]time )?(?:degree|bachelor|master|program|university|college)"
    r"|rising (?:junior|senior|sophomore|freshman)"
    r"|expected graduation|graduating (?:in|between|by)"
    r"|must be a (?:current )?student"
    r"|returning to (?:school|university|your studies)"
)

# Site-wide boilerplate that mentions degrees without stating a requirement --
# most often an EEO / non-discrimination clause. Windows matching this are
# ignored entirely.
_BOILERPLATE_RE = re.compile(
    r"equal opportunity|without regard to|discriminat|protected (?:class|veteran)"
    r"|affirmative action|e-verify|reasonable accommodation"
)

# "3.0 GPA", "GPA of at least 3.5", "minimum GPA: 3.2"
_GPA_RE = re.compile(
    r"(?:\b\d\.\d{1,2}\s*(?:\+|or (?:higher|above|better))?\s*(?:cumulative\s+)?gpa\b)"
    r"|(?:\bgpa\b[^.\n]{0,40}?\d\.\d{1,2})"
)
_GPA_WAIVED_RE = re.compile(
    r"gpa[^.\n]{0,30}(?:not required|is not considered|no minimum|not a factor)"
    r"|(?:no|without a) (?:minimum )?gpa"
)

DEGREE_NO = "No degree required"
DEGREE_PREFERRED = "Degree preferred"
DEGREE_ENROLLED = "Currently enrolled"
DEGREE_REQUIRED = "Degree required"
DEGREE_UNKNOWN = "Not specified"


def has_gpa_requirement(text_lower: str) -> bool:
    """True when the posting sets a numeric GPA floor."""
    if not text_lower:
        return False
    if _GPA_WAIVED_RE.search(text_lower):
        return False
    return bool(_GPA_RE.search(text_lower))


def _windows(text_lower: str):
    """Yield the text surrounding each degree mention, skipping boilerplate."""
    for match in _DEGREE_MENTION.finditer(text_lower):
        start = max(0, match.start() - _WINDOW_BEFORE)
        window = text_lower[start:match.end() + _WINDOW_AFTER]
        if _BOILERPLATE_RE.search(window):
            continue
        yield window


def classify_degree(text_lower: str, is_internship: bool) -> str:
    """Map posting text to one of the five degreeRequirement values."""
    if not text_lower:
        return DEGREE_UNKNOWN

    # A global "no degree required" statement outranks any local window.
    if re.search(r"no degree (?:is )?required|degree (?:is )?not required|"
                 r"do(?:es)? not require a (?:college |university )?degree|"
                 r"without a (?:college )?degree|degree(?:s)? (?:are|is) not (?:necessary|required)",
                 text_lower):
        return DEGREE_NO

    escape = preferred = required = enrolled = False
    for window in _windows(text_lower):
        if _ENROLLED_RE.search(window):
            enrolled = True
        if _ESCAPE_RE.search(window):
            escape = True
        elif _PREFERRED_RE.search(window):
            preferred = True
        else:
            # A bare degree bullet in a qualifications list is a requirement,
            # whether or not the posting bothers to say the word.
            required = True

    if is_internship and enrolled:
        return DEGREE_ENROLLED
    if escape:
        return DEGREE_NO
    if required:
        return DEGREE_REQUIRED
    if preferred:
        return DEGREE_PREFERRED
    if is_internship and _ENROLLED_RE.search(text_lower):
        return DEGREE_ENROLLED
    return DEGREE_UNKNOWN


# ----------------------------------------------------------------- category

# Ordered: the first matching bucket wins, so put the specific ones first.
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("AI / Machine Learning", (
        "machine learning", "deep learning", "artificial intelligence",
        " ai ", "ai/ml", "ml engineer", "mle", "nlp", "computer vision",
        "research scientist", "applied scientist", "llm", "generative ai",
        "genai", "ml infrastructure", "ml platform", "perception research",
    )),
    ("Robotics", (
        "robot", "robotics", "autonomy", "autonomous vehicle", "motion planning",
        "slam", "controls engineer", "mechatronic", "perception engineer",
        "drone", "uav",
    )),
    ("Cybersecurity", (
        "security", "cybersecurity", "infosec", "appsec", "application security",
        "penetration test", "pentest", "red team", "blue team", "threat",
        "detection engineer", "vulnerability", "cryptograph", "trust and safety",
        "trust & safety", "iam ", "identity and access",
    )),
    ("Cloud / Infrastructure", (
        "infrastructure", "cloud", "devops", "site reliability", " sre",
        "sre ", "platform engineer", "kubernetes", "systems engineer",
        "network engineer", "distributed systems", "database engineer",
        "storage engineer", "compute", "virtualization",
    )),
    ("Developer Productivity", (
        "developer productivity", "developer experience", "devex", "devx",
        "build system", "build engineer", "release engineer", "tooling",
        "developer tools", "developer platform", "internal tools",
        "test infrastructure", "qa engineer", "quality engineer",
        "automation engineer", "sdet",
    )),
    ("Data", (
        "data engineer", "data scientist", "data science", "analytics",
        "business intelligence", "data platform", "etl", "data warehouse",
        "quantitative", "statistician", "data analyst", "decision science",
        "analytics engineer", "bi engineer", "machine learning analyst",
        "research analyst", "data architect",
    )),
    ("Product Engineering", (
        "product engineer", "full stack", "fullstack", "front end", "frontend",
        "web engineer", "mobile engineer", "ios engineer", "android engineer",
        "ui engineer", "growth engineer", "application engineer",
    )),
    ("Software Engineering", (
        "software engineer", "software developer", "swe", "backend",
        "back end", "software development", "programmer", "engineer",
        "developer", "systems programmer", "compiler", "embedded",
        "firmware", "game engineer", "graphics",
    )),
]

# If none of the above hit, the posting probably is not a tech role at all.
NON_TECH_HINTS = (
    # Go-to-market and back office
    "recruiter", "recruiting", "talent acquisition", "account executive",
    "account manager", "sales", "marketing", "customer success",
    "customer support", "customer experience", "customer trust",
    "human resources", "people operations", "paralegal", "attorney",
    "counsel", "accountant", "accounting", "payroll", "bookkeep",
    "office manager", "executive assistant", "receptionist",
    "business development", "procurement", "facilities", "real estate",
    "brand ", "content writer", "copywriter", "social media",
    "public relations", "communications", "community manager",
    "partnerships", "revenue", "finance", "controller", "auditor",
    # Non-engineering "technical" titles
    "product manager", "product owner", "program manager", "project manager",
    "engineering manager", "technical writer", "technical program",
    "technical support", "support engineer", "solutions architect",
    "solution architect", "solutions engineer", "solutions consultant",
    "sales engineer", "implementation", "onboarding", "trainer",
    "scrum master", "business analyst", "compliance", "auditor",
    "support specialist", "support associate", "help desk", "helpdesk",
    "service desk", "desktop support", "project assistant",
    "project coordinator", "administrative assistant", "executive assistant",
    "implementation specialist", "sales specialist", "marketing specialist",
    "product specialist", "operations specialist", "payroll specialist",
    "hr specialist", "recruiting coordinator", "content strategist",
    "designer", "ux research", "ui/ux", "product design",
    # Operations / physical
    "operations manager", "supervisor", "fulfillment", "inventory",
    "shipping", "logistics", "warehouse", "supply chain", "manufacturing",
    "technician", "field service", "driver", "janitor", "security guard",
    "nurse", "physician", "therapist", "teacher", "barista",
)



def classify_category(title: str, department: str = "") -> str | None:
    """Return one of the eight categories, or None if it is not a tech role."""
    hay = f" {norm(title)} {norm(department)} "

    # A hard non-tech signal in the *title* disqualifies immediately, so
    # "Sales Engineer" and "Marketing Analyst" do not slip into Data.
    title_hay = f" {norm(title)} "
    for hint in NON_TECH_HINTS:
        if hint in title_hay:
            return None

    for category, keywords in CATEGORY_RULES:
        if any(keyword in hay for keyword in keywords):
            return category
    return None


# ---------------------------------------------------------------- work mode

WORKMODE_ONSITE = "On site"
WORKMODE_HYBRID = "Hybrid"
WORKMODE_REMOTE = "Remote"
WORKMODE_UNKNOWN = "Not specified"

_ATS_WORKMODE = {
    "remote": WORKMODE_REMOTE,
    "hybrid": WORKMODE_HYBRID,
    "onsite": WORKMODE_ONSITE,
    "on-site": WORKMODE_ONSITE,
    "in office": WORKMODE_ONSITE,
    "unspecified": WORKMODE_UNKNOWN,
}


def classify_workmode(ats_value: str | None, location: str, text_lower: str) -> str:
    """Prefer the ATS's own field; fall back to the location and body text."""
    if ats_value:
        mapped = _ATS_WORKMODE.get(ats_value.strip().lower())
        if mapped:
            return mapped

    loc = norm(location)
    if "remote" in loc:
        return WORKMODE_REMOTE
    if "hybrid" in loc:
        return WORKMODE_HYBRID

    if "fully remote" in text_lower or "100% remote" in text_lower:
        return WORKMODE_REMOTE
    if "hybrid" in text_lower:
        return WORKMODE_HYBRID
    if "on-site" in text_lower or "onsite" in text_lower or "in-office" in text_lower:
        return WORKMODE_ONSITE
    return WORKMODE_UNKNOWN


# ---------------------------------------------------------- experience level

# Higher rank = more senior. config.FULLTIME_MAX_LEVEL cuts the tail.
LEVEL_RANK = {
    "Intern": 0,
    "Entry Level": 1,
    "Mid Level": 2,
    "Senior": 3,
    "Staff+": 4,
}

_SENIOR_RE = re.compile(r"\b(senior|sr\.?|lead|manager|head of)\b")
_STAFF_RE = re.compile(r"\b(staff|principal|distinguished|fellow|director|vp|vice president|chief)\b")
_ENTRY_RE = re.compile(r"\b(new ?grad|graduate|entry[- ]level|early career|junior|jr\.?|associate|apprentice|university grad|campus)\b")
_YEARS_RE = re.compile(r"(\d{1,2})\+?\s*(?:-|to|–)?\s*(?:\d{1,2})?\s*years?(?:'| of)?\s+(?:of\s+)?(?:relevant\s+|professional\s+|industry\s+)?experience")


# Postings that say outright that no background is needed.
_NO_EXPERIENCE_RE = re.compile(
    r"no (?:prior |previous |professional |work |relevant )?experience (?:is )?(?:required|necessary|needed)"
    r"|no experience necessary"
    r"|0[-\s]*(?:to|-)?\s*1\s*years?"
    r"|entry[- ]level"
    r"|new ?grad(?:uate)?"
    r"|early[- ]career"
    r"|we will train|training provided|will train you"
    r"|suitable for (?:recent )?graduates"
)


def classify_experience(title: str, text_lower: str, is_internship: bool) -> str:
    if is_internship:
        return "Intern"

    t = norm(title)
    # Seniority in the title is the strongest signal and outranks the body --
    # a "Senior Engineer" posting that mentions "entry-level" somewhere in its
    # boilerplate is still a senior role.
    if _STAFF_RE.search(t):
        return "Staff+"
    if _SENIOR_RE.search(t):
        return "Senior"
    if _ENTRY_RE.search(t):
        return "Entry Level"

    # The years-of-experience ask is the next most reliable thing.
    match = _YEARS_RE.search(text_lower)
    if match:
        years = int(match.group(1))
        if years <= 1:
            return "Entry Level"
        if years <= 4:
            return "Mid Level"
        if years <= 7:
            return "Senior"
        return "Staff+"

    # No years quoted: an explicit "no experience required" still qualifies.
    if _NO_EXPERIENCE_RE.search(text_lower):
        return "Entry Level"

    # Genuinely unstated. Guessing "Entry Level" here would flood the board
    # with mid-level roles, so stay honest and let the caller drop it.
    return "Mid Level"


def requires_prior_experience(text_lower: str) -> bool:
    """True when the posting quotes any years-of-experience minimum.

    An explicit "no experience required" wins, and "0-1 years" parses to 0,
    so genuinely open roles still pass.
    """
    if _NO_EXPERIENCE_RE.search(text_lower):
        return False
    return min_years_required(text_lower) > config.FULLTIME_MAX_YEARS


def min_years_required(text_lower: str) -> int:
    match = _YEARS_RE.search(text_lower)
    return int(match.group(1)) if match else 0


# --------------------------------------------------------------- internship

_INTERN_RE = re.compile(r"\b(intern|internship|co-?op|placement student|summer analyst|industrial placement)\b")


def is_internship_role(title: str, commitment: str = "") -> bool:
    hay = f"{norm(title)} {norm(commitment)}"
    return bool(_INTERN_RE.search(hay))


_SEASON_RE = re.compile(r"\b(summer|fall|autumn|winter|spring)\b[^.\n]{0,12}?\b(20\d{2})\b")
_SEASON_RE_REV = re.compile(r"\b(20\d{2})\b[^.\n]{0,12}?\b(summer|fall|autumn|winter|spring)\b")


def extract_season(title: str, text: str = "") -> str | None:
    """Best-effort 'Summer 2027' style label from the title, then the body."""
    for source in (title, text[:2000]):
        low = norm(source)
        match = _SEASON_RE.search(low)
        if match:
            season, year = match.group(1), match.group(2)
        else:
            match = _SEASON_RE_REV.search(low)
            if not match:
                continue
            year, season = match.group(1), match.group(2)
        season = "Fall" if season in ("fall", "autumn") else season.capitalize()
        return f"{season} {year}"
    return None


# ----------------------------------------------------------------- priority

def score_priority(job: dict) -> int:
    """0-5 ranking used by the 'Highest priority' sort.

    Weighted toward what the user actually asked for: no degree gate,
    recently posted, and junior enough to be realistic.
    """
    score = 2

    degree = job.get("degreeRequirement")
    if degree == DEGREE_NO:
        score += 2
    elif degree == DEGREE_PREFERRED:
        score += 1

    level = job.get("experienceLevel")
    if level in ("Intern", "Entry Level"):
        score += 1
    elif level == "Staff+":
        score -= 1

    if job.get("workMode") == WORKMODE_REMOTE:
        score += 1

    # Freshness: anything inside the New window gets a nudge.
    first_seen = job.get("firstSeen")
    if first_seen:
        try:
            seen = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - seen).total_seconds() / 3600
            if age_h <= 24:
                score += 1
        except ValueError:
            pass

    return max(0, min(5, score))
