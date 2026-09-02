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

# A genuine escape hatch: the posting says outright that no degree is needed.
#
# "Bachelor's degree OR equivalent practical experience" is deliberately NOT
# here. It is not an open door -- it is a degree gate whose only alternative
# is years of professional experience. Someone with neither fails both
# branches, so treating it as "no degree required" surfaced exactly the roles
# this board exists to filter out.
_ESCAPE_RE = re.compile(
    r"no degree"
    r"|degree (?:is )?not (?:required|necessary|needed)"
    r"|not required"
    r"|we do not require"
    r"|do(?:es)? not require a (?:college |university )?degree"
    r"|regardless of (?:degree|education|background)"
    r"|self[- ]taught"
    r"|bootcamp"
    r"|no formal education"
    r"|degree[- ]?free"
)

# When a posting spells out what "equivalent" means and the answer is
# portfolio work rather than years on the job, the door really is open to an
# early-career candidate:
#
#   "a degree in CS, or equivalent experience (projects, bootcamp, open
#    source - we care about what you can build)"
#
# That is a different promise from a bare "or equivalent practical
# experience", which in practice means professional years.
_EQUIVALENT_IS_PORTFOLIO_RE = re.compile(
    r"(?:project|bootcamp|open[- ]source|portfolio|self[- ]taught|"
    r"personal work|side project|what you can build|hobby)"
)

# "Degree or equivalent experience" -- a gate with an experience-shaped
# alternative. Treated as a requirement, because the alternative is exactly
# the thing an early-career candidate does not have.
_DEGREE_OR_EXPERIENCE_RE = re.compile(
    r"or equivalent"
    r"|equivalent (?:practical |work |industry |professional |relevant )?experience"
    r"|in lieu of"
    r"|or (?:relevant|practical|comparable) experience"
)

_PREFERRED_RE = re.compile(
    r"preferred|a plus|nice to have|desirable|advantageous|bonus|ideally|"
    r"we'd love|would be great|helpful|beneficial"
)

_HARD_REQUIRED_RE = re.compile(
    r"\(required\)|required|must have|must possess|must hold|must be|"
    r"mandatory|essential|minimum of"
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
    # Equal-opportunity / legal boilerplate
    r"equal opportunity|without regard to|discriminat|protected (?:class|veteran)"
    r"|affirmative action|e-verify|reasonable accommodation"
    # Compensation and benefits. "Final compensation will be determined based
    # on degree level" is a pay note, not an education requirement -- reading
    # it as one mislabels a large share of internships.
    r"|compensation|salary|pay (?:range|rate|band)|hourly rate|stipend"
    r"|benefits|perks|401\(?k\)?|insurance|equity|bonus|relocation"
    r"|paid time off|pto\b|vacation"
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
# "Bachelor's degree or equivalent experience" -- the degree is one route, not
# the only one. Kept distinct from both "required" and "preferred" so the card
# says exactly what the posting says.
DEGREE_OR_EQUIV = "Degree or equivalent"
DEGREE_PREFERRED = "Degree preferred"
DEGREE_ENROLLED = "Currently enrolled"
DEGREE_REQUIRED = "Degree required"
DEGREE_UNKNOWN = "Not specified"


# --- undergraduate vs graduate --------------------------------------------

# "Master's", "PhD", "MBA" -- note the possessive is required on master so the
# verb ("master new technologies") does not match.
_GRAD_RE = re.compile(
    r"\b(?:master'?s|masters|m\.s\.|m\.eng|msc|mba|phd|ph\.d\.|doctoral|doctorate"
    r"|graduate degree|graduate program|graduate student|post[- ]?doc)\b"
    r"|\bms\b(?=\s*(?:in|or|/|,|degree)\b)"
)

# Degree-level undergraduate signals ONLY. Used by the graduate-only test,
# where loose words like "junior" (which appears in plenty of job titles and
# body copy) were wrongly cancelling a real "graduate degree" requirement.
_UNDERGRAD_DEGREE_RE = re.compile(
    r"\b(?:bachelor'?s|bachelors|b\.s\.|b\.a\.|bsc|ba/bs|bs/ms|undergrad(?:uate)?"
    r"|associate'?s)\b"
    r"|\b(?:bs|ba)\b(?=\s*(?:in|or|/|,|degree)\b)"
)

# Undergraduate alternatives. "New grad"/"recent graduate" describe someone
# finishing a bachelor's, so they must NOT count as graduate-level signals.
_UNDERGRAD_RE = re.compile(
    r"\b(?:bachelor'?s|bachelors|b\.s\.|b\.a\.|bsc|ba/bs|bs/ms|undergrad(?:uate)?"
    r"|associate'?s|sophomore|junior|senior year|freshman"
    r"|new ?grad(?:uate)?|recent graduate|college student|university student)\b"
    r"|\b(?:bs|ba)\b(?=\s*(?:in|or|/|,|degree)\b)"
)

# Undergraduate routes as named in a *title*. Deliberately excludes the
# "new grad" family, which says nothing about which degree is being finished.
_UNDERGRAD_TITLE_RE = re.compile(
    r"\b(?:bachelor'?s|bachelors|b\.s\.|b\.a\.|ba/bs|undergrad(?:uate)?"
    r"|associate'?s)\b"
    r"|\b(?:bs|ba)\b(?=\s*(?:in|or|/|,|degree|\'s)\b)"
)

# Titles that are graduate-only on their face.
_GRAD_TITLE_RE = re.compile(
    r"\b(?:phd|ph\.d\.|doctoral|mba|masters?'?s?|graduate)\b(?![- ]?grad\b)"
)


def is_graduate_only(title: str, text_lower: str) -> bool:
    """True when the role is open only to master's/PhD candidates.

    The test is comparative, not absolute: a posting saying "Bachelor's or
    Master's degree" is open to undergraduates and must be kept. Only when
    graduate credentials are named and no undergraduate path is offered
    anywhere is the role genuinely closed to an undergrad.
    """
    t = norm(title)

    # An explicit graduate credential in the title is checked FIRST. "Applied
    # Scientist, PhD New Grad" is a new graduate *of a PhD* -- the "new grad"
    # wording does not make it open to undergraduates.
    # "Graduate Intern" / "Graduate Co-op" is the standard industry label for
    # an intern pursuing a master's or PhD -- Intel and Altera pair it with
    # "Undergraduate Intern" for bachelor's students. The word only counts
    # when attached to the role, so "New Graduate" is unaffected.
    if re.search(r"\b(?:phd|ph\.d\.|mba|doctoral|masters?'?s?)\b", t) or \
       re.search(r"\bgraduate\s+(?:intern|co-?op|student|program|research)", t):
        # ...unless the title also names an undergraduate route, as in
        # "(2028 Bachelor's/Master's graduates)". "New grad" deliberately does
        # not count here, for the reason above.
        return not _UNDERGRAD_TITLE_RE.search(t)

    # No graduate credential named: new-grad framing is undergraduate-friendly.
    if re.search(r"new ?grad|recent graduate", t):
        return False

    if not text_lower:
        return False
    if not _GRAD_RE.search(text_lower):
        return False
    # Graduate credentials mentioned -- keep it only if an undergraduate
    # *degree* route is offered too. Weak words like "junior" do not count.
    return not _UNDERGRAD_DEGREE_RE.search(text_lower)


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


# Ordered only for tie-breaks; selection is by distance, not by this order.
_QUALIFIERS = (
    ("escape", _ESCAPE_RE),
    ("required", _HARD_REQUIRED_RE),
    ("degree_or_experience", _DEGREE_OR_EXPERIENCE_RE),
    ("preferred", _PREFERRED_RE),
)


def _qualifier_for(text_lower: str, m_start: int, m_end: int) -> str | None:
    """Classify ONE degree mention by the qualifier nearest to it.

    Scanning the whole window for "preferred" is wrong when two requirements
    sit next to each other:

        Bachelor's degree in computer science (required)
        Master's degree in computer science (preferred)

    A window around "bachelor's" contains both words. The bachelor's line is
    a hard requirement, so the qualifier that counts is the closest one --
    "(required)" here -- not whichever pattern happens to be tested first.
    Text after the mention is preferred, since qualifiers usually follow.
    """
    after = text_lower[m_end:m_end + _WINDOW_AFTER]
    best = None
    for kind, pattern in _QUALIFIERS:
        found = pattern.search(after)
        if found and (best is None or found.start() < best[0]):
            best = (found.start(), kind)

    if best and best[1] == "degree_or_experience":
        # Check whether the posting defines "equivalent" as portfolio work
        # rather than professional years. Only the text immediately following
        # the clause counts, so an unrelated later mention cannot soften it.
        tail = after[best[0]:best[0] + 110]
        if _EQUIVALENT_IS_PORTFOLIO_RE.search(tail):
            return "escape"

    if best:
        return best[1]

    before = text_lower[max(0, m_start - _WINDOW_BEFORE):m_start]
    best = None
    for kind, pattern in _QUALIFIERS:
        for found in pattern.finditer(before):
            distance = len(before) - found.end()
            if best is None or distance < best[0]:
                best = (distance, kind)
    return best[1] if best else None


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

    escape = preferred = required = enrolled = or_equivalent = False

    for match in _DEGREE_MENTION.finditer(text_lower):
        start = max(0, match.start() - _WINDOW_BEFORE)
        window = text_lower[start:match.end() + _WINDOW_AFTER]
        if _BOILERPLATE_RE.search(window):
            continue

        if _ENROLLED_RE.search(window):
            enrolled = True

        kind = _qualifier_for(text_lower, match.start(), match.end())
        if kind == "escape":
            escape = True
        elif kind == "preferred":
            preferred = True
        elif kind == "degree_or_experience":
            or_equivalent = True
        else:
            # "required", or a bare bullet with no qualifier at all: both
            # gate on actually holding the degree.
            required = True

    if is_internship and enrolled:
        return DEGREE_ENROLLED
    # A hard requirement anywhere outranks a preference elsewhere: one line
    # saying a master's is "preferred" does not soften a bachelor's being
    # "(required)" on the line above.
    if required:
        return DEGREE_REQUIRED
    if preferred:
        return DEGREE_PREFERRED
    if or_equivalent:
        return DEGREE_OR_EQUIV
    if escape:
        return DEGREE_NO
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
    # Physical security and facilities work. The Cybersecurity keywords were
    # sweeping these in -- "Security Associate - 1st Shift" is a guard post.
    "security associate", "security officer", "protective services",
    "loss prevention", "1st shift", "2nd shift", "3rd shift", "night shift",
    "icqa", "footwear", "apparel", "merchandis", "financial analyst",
    "survey operations", "operations center", "dispatcher",
    "support specialist", "support associate", "help desk", "helpdesk",
    "service desk", "desktop support", "project assistant",
    "project coordinator", "administrative assistant", "executive assistant",
    "implementation specialist", "sales specialist", "marketing specialist",
    "product specialist", "operations specialist", "payroll specialist",
    "hr specialist", "recruiting coordinator", "content strategist",
    "designer", "ux research", "ui/ux", "product design",
    # Engineering disciplines that are not software. The generic "engineer"
    # keyword below was sweeping these in as Software Engineering -- 9% of
    # the board was civil and structural work. Bare "mechanical" and
    # "electrical" are deliberately NOT listed: those are frequently robotics
    # roles, which is a category the board does want.
    "civil engineer", "civil engineering", "structural engineer",
    "structural engineering", "bridge", "water resources", "wastewater",
    "environmental engineer", "environmental engineering", "chemical engineer",
    "chemical engineering", "petroleum", "geotechnical", "hvac", "mep ",
    "nuclear engineer", "mining engineer", "metallurg", "biomedical",
    "industrial engineer", "industrial engineering", "industrial environmental",
    "manufacturing engineer", "process engineer", "packaging engineer",
    "acoustic", "welding", "piping", "surveying", "land development",
    "site design", "architectural", "construction",
    # Operations / physical
    "operations manager", "supervisor", "fulfillment", "inventory",
    "shipping", "logistics", "warehouse", "supply chain", "manufacturing",
    "technician", "field service", "driver", "janitor", "security guard",
    "nurse", "physician", "therapist", "teacher", "barista",
)



def is_non_tech_title(title: str) -> bool:
    """True when the title itself rules the role out of scope.

    This is a *positive rejection*, distinct from "no category matched", and
    callers must not paper over it with a fallback category.
    """
    title_hay = f" {norm(title)} "
    return any(hint in title_hay for hint in NON_TECH_HINTS)


def classify_category(title: str, department: str = "") -> str | None:
    """Return one of the eight categories, or None if it is not a tech role."""
    hay = f" {norm(title)} {norm(department)} "

    # A hard non-tech signal in the *title* disqualifies immediately, so
    # "Sales Engineer" and "Civil Engineering Intern" cannot slip through.
    if is_non_tech_title(title):
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
# Allows words between the count and "experience": the earlier version
# required them to be adjacent and so missed "2+ years of professional
# software engineering experience", letting a mid-level role through.
_YEARS_RE = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-|to|\u2013|\u2014)?\s*(?:\d{1,2})?\s*\+?\s*"
    r"years?\b[^.\n;]{0,70}?\bexperience\b"
)


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


_SEASON_WORDS = "winter|spring|summer|fall|autumn"

# "Spring/Summer/Fall 2027" -- a run of seasons sharing one year.
_SEASON_RUN_RE = re.compile(
    rf"\b((?:{_SEASON_WORDS})(?:\s*(?:/|,|&|\+|-|\bor\b|\band\b)\s*(?:{_SEASON_WORDS}))*)"
    rf"\s*(?:of\s+)?\b(20\d{{2}})\b"
)
# "2027 Summer Analyst" -- year first.
_SEASON_REV_RE = re.compile(rf"\b(20\d{{2}})\s+((?:{_SEASON_WORDS}))\b")

_SEASON_ORDER = {"Winter": 1, "Spring": 2, "Summer": 3, "Fall": 4}


def _canon_season(word: str) -> str:
    word = word.strip().lower()
    return "Fall" if word in ("fall", "autumn") else word.capitalize()


def season_sort_key(season: str) -> float:
    """Chronological ordering: Fall 2026 < Winter 2027 < Spring 2027 < ..."""
    try:
        name, year = season.rsplit(" ", 1)
        return int(year) + _SEASON_ORDER.get(name, 9) / 10
    except (ValueError, AttributeError):
        return 9999.0


def extract_seasons(title: str, text: str = "") -> list[str]:
    """Every season a posting names, e.g. ['Spring 2027', 'Summer 2027'].

    A posting covering multiple terms genuinely belongs under each of them, so
    the field is a list. An empty list means the posting named no season --
    treated downstream as open to any.
    """
    found: list[str] = []

    for source in (title, text[:3000]):
        low = norm(source)
        if not low:
            continue

        for run, year in _SEASON_RUN_RE.findall(low):
            for word in re.split(r"\s*(?:/|,|&|\+|-|\bor\b|\band\b)\s*", run):
                if word.strip():
                    label = f"{_canon_season(word)} {year}"
                    if label not in found:
                        found.append(label)

        for year, word in _SEASON_REV_RE.findall(low):
            label = f"{_canon_season(word)} {year}"
            if label not in found:
                found.append(label)

        # The title is authoritative -- do not dilute it with body mentions.
        if found:
            break

    return sorted(found, key=season_sort_key)


def extract_season(title: str, text: str = "") -> str | None:
    """The single earliest season, kept for the card's summary chip."""
    seasons = extract_seasons(title, text)
    return seasons[0] if seasons else None


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

    # Freshness, measured from the posting date.
    stamp = job.get("postedAt") or job.get("firstSeen")
    if stamp:
        try:
            posted = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=timezone.utc)
            age_h = (datetime.now(timezone.utc) - posted).total_seconds() / 3600
            if age_h <= 24:
                score += 1
        except ValueError:
            pass

    return max(0, min(5, score))

# ------------------------------------------------------------------ country

US_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "district of columbia": "dc", "puerto rico": "pr",
}

# Abbreviations only count with a comma or boundary in front, so "IN" in
# "Built IN Public" or "OR" in "Remote OR Hybrid" is not read as a state.
_STATE_ABBR_RE = re.compile(
    r"(?:,\s*|\(\s*)(" + "|".join(sorted(set(US_STATES.values()))) + r")\b\.?",
    re.I,
)
_STATE_NAME_RE = re.compile(
    r"\b(" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")\b", re.I
)
# "Thornton CO 80023" -- state abbreviation followed by a ZIP code.
_US_ZIP_RE = re.compile(
    r"\b(" + "|".join(sorted(set(US_STATES.values()))) + r")\s+\d{5}\b", re.I
)
# A leading "TX, Coppell".
_US_LEADING_ABBR_RE = re.compile(
    r"^\s*(" + "|".join(sorted(set(US_STATES.values()))) + r")\s*,", re.I
)

_US_COUNTRY_RE = re.compile(
    r"\b(?:united states(?: of america)?|u\.?s\.?a\.?|usa|us)\b"
    r"|\bnationwide\b|\banywhere in the u\.?s",
    re.I,
)

# US cities distinctive enough to stand alone. Deliberately excludes names
# shared with a foreign city -- Cambridge, Birmingham, Manchester, Portland,
# Vancouver, London -- which must carry a state to count.
_US_CITIES = {
    "san francisco", "new york city", "nyc", "brooklyn", "manhattan",
    "los angeles", "san diego", "san jose", "silicon valley", "palo alto",
    "mountain view", "sunnyvale", "santa clara", "menlo park", "cupertino",
    "redwood city", "berkeley", "oakland", "pasadena", "santa monica",
    "culver city", "el segundo", "torrance", "irvine", "long beach",
    "sacramento", "fremont", "seattle", "bellevue", "redmond", "kirkland",
    "austin", "dallas", "houston", "plano", "richardson", "frisco",
    "san antonio", "fort worth", "denver", "boulder", "colorado springs",
    "chicago", "evanston", "atlanta", "miami", "orlando", "tampa",
    "jacksonville", "philadelphia", "pittsburgh", "phoenix", "tempe",
    "scottsdale", "chandler", "tucson", "detroit", "ann arbor",
    "minneapolis", "st. paul", "saint paul", "nashville", "memphis",
    "charlotte", "raleigh", "durham", "chapel hill", "columbus",
    "indianapolis", "kansas city", "st. louis", "saint louis", "milwaukee",
    "cincinnati", "cleveland", "salt lake city", "provo",
    "las vegas", "reno", "boise", "portland, or", "baltimore",
    "washington dc", "washington, d.c.", "arlington", "alexandria",
    "reston", "mclean", "herndon", "bethesda", "rockville", "new orleans",
    "birmingham, al", "huntsville", "omaha", "des moines", "madison",
    "hoboken", "jersey city", "newark", "princeton", "stamford",
    "new haven", "providence", "hartford", "buffalo", "rochester",
    "syracuse", "albany", "pittsford", "spacex site", "boston", "alameda",
    "scotts valley", "burbank", "thornton", "coppell", "redwood shores",
}

# Canadian provinces, which look exactly like US state abbreviations.
_CA_PROVINCES = (
    "british columbia", "ontario", "quebec", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick", "newfoundland",
    "prince edward island", "yukon", "nunavut", "northwest territories",
)
_CA_ABBR_RE = re.compile(
    r"(?:,\s*|\(\s*)(bc|on|qc|ab|mb|sk|ns|nb|nl|pe|yt|nt|nu)\b\.?", re.I
)

# Region labels that are inherently not a US location.
_NON_US_REGIONS = (
    "latin america", "latam", "emea", "apac", "asia pacific", "middle east",
    "europe", "eu remote", "worldwide", "global remote",
)

_NON_US_COUNTRIES = (
    "united kingdom", "england", "scotland", "wales", "northern ireland",
    "ireland", "canada", "mexico", "brazil", "argentina", "chile", "colombia",
    "peru", "uruguay", "costa rica", "panama", "india", "china", "japan",
    "south korea", "korea", "taiwan", "hong kong", "singapore", "malaysia",
    "indonesia", "thailand", "vietnam", "philippines", "australia",
    "new zealand", "germany", "france", "spain", "portugal", "italy",
    "netherlands", "belgium", "luxembourg", "switzerland", "austria",
    "sweden", "norway", "denmark", "finland", "iceland", "poland",
    "czech republic", "czechia", "slovakia", "hungary", "romania",
    "bulgaria", "greece", "turkey", "ukraine", "russia", "estonia",
    "latvia", "lithuania", "croatia", "serbia", "slovenia", "israel",
    "united arab emirates", "uae", "saudi arabia", "qatar", "egypt",
    "nigeria", "kenya", "south africa", "ghana", "morocco", "pakistan",
    "bangladesh", "sri lanka", "nepal",
)

_NON_US_CITIES = (
    "london", "manchester", "birmingham, uk", "edinburgh", "glasgow",
    "bristol", "leeds", "cambridge, uk", "oxford, uk", "belfast", "cardiff",
    "dublin", "cork", "toronto", "vancouver, bc", "montreal", "ottawa",
    "calgary", "waterloo, on", "bangalore", "bengaluru", "hyderabad",
    "mumbai", "new delhi", "gurgaon", "gurugram", "noida", "pune",
    "chennai", "kolkata", "ahmedabad", "berlin", "munich", "munchen",
    "hamburg", "frankfurt", "cologne", "stuttgart", "dusseldorf", "paris",
    "lyon", "toulouse", "marseille", "amsterdam", "rotterdam", "eindhoven",
    "utrecht", "the hague", "brussels", "antwerp", "ghent", "zurich",
    "geneva", "basel", "bern", "lausanne", "zug", "vienna",
    "stockholm", "gothenburg", "oslo", "copenhagen", "helsinki",
    "reykjavik", "warsaw", "krakow", "wroclaw", "gdansk",
    "prague", "brno", "bratislava", "budapest", "bucharest", "cluj",
    "sofia", "athens", "istanbul", "ankara", "kyiv", "kiev", "moscow",
    "tallinn", "riga", "vilnius", "zagreb", "belgrade", "ljubljana",
    "madrid", "barcelona", "valencia", "lisbon", "porto", "rome", "milan",
    "turin", "sydney", "melbourne", "brisbane", "perth", "adelaide",
    "canberra", "auckland", "wellington", "christchurch", "tokyo", "osaka",
    "kyoto", "seoul", "busan", "beijing", "shanghai", "shenzhen",
    "guangzhou", "hangzhou", "taipei", "tel aviv", "jerusalem", "haifa",
    "herzliya", "dubai", "abu dhabi", "doha", "riyadh", "cairo", "lagos",
    "nairobi", "cape town", "johannesburg", "manila", "cebu", "jakarta",
    "bangkok", "ho chi minh", "hanoi", "kuala lumpur", "sao paulo",
    "rio de janeiro", "buenos aires", "santiago", "bogota",
    "lima", "mexico city", "monterrey", "guadalajara",
    # Engineering and outsourcing hubs that were classified "unknown" and so
    # kept: Craiova (Romania) and Kaunas (Lithuania) both reached the site.
    "craiova", "iasi", "timisoara", "brasov", "constanta", "sibiu",
    "poznan", "lodz", "katowice", "gdynia", "szczecin", "lublin",
    "kaunas", "klaipeda", "tartu", "kosice", "plzen", "ostrava",
    "debrecen", "szeged", "varna", "plovdiv", "skopje", "tirana",
    "sarajevo", "podgorica", "chisinau", "minsk", "lviv", "kharkiv",
    "odesa", "dnipro", "yerevan", "tbilisi", "baku", "almaty", "tashkent",
    "sheffield", "nottingham", "newcastle", "liverpool", "southampton",
    "aberdeen", "galway", "limerick", "bilbao", "seville", "malaga",
    "zaragoza", "bologna", "florence", "naples", "genoa", "lucerne",
    "graz", "linz", "salzburg", "malmo", "uppsala", "bergen", "trondheim",
    "aarhus", "espoo", "tampere", "turku", "nuremberg", "leipzig",
    "dresden", "bonn", "essen", "dortmund", "bordeaux", "nantes", "lille",
    "grenoble", "rennes",
    "hsinchu", "kaohsiung", "nagoya", "fukuoka", "sapporo", "yokohama",
    "incheon", "daegu", "chengdu", "wuhan", "nanjing", "suzhou", "tianjin",
    "qingdao", "dalian", "xiamen", "jaipur", "indore", "coimbatore",
    "kochi", "nagpur", "vadodara", "chandigarh", "thiruvananthapuram",
    "colombo", "dhaka", "karachi", "lahore", "islamabad", "kathmandu",
    "da nang", "chiang mai", "surabaya", "bandung", "penang", "johor",
    "davao", "queenstown",
)


def _fold(text: str) -> str:
    """Strip combining marks so accented place names compare as plain ASCII."""
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _mentions(haystack: str, needles) -> bool:
    """Word-boundary containment.

    Plain substring matching is wrong here: "columbia" (Columbia, MD) matches
    inside "British Columbia", which let a Vancouver posting through as US.
    """
    for needle in needles:
        start = 0
        while True:
            i = haystack.find(needle, start)
            if i == -1:
                break
            before = haystack[i - 1] if i > 0 else " "
            after_i = i + len(needle)
            after = haystack[after_i] if after_i < len(haystack) else " "
            if not before.isalpha() and not after.isalpha():
                return True
            start = i + 1
    return False


def is_us_location(location: str) -> bool | None:
    """True if the location is in the US, False if abroad, None if unclear.

    A posting listing several sites counts as US when *any* of them is in the
    US -- "London, England, New York, New York" is still open to someone
    based in New York.
    """
    # clean_text applies NFKD, which splits "u" from its umlaut, so a needle
    # like "munchen" cannot match "Mu<combining diaeresis>nchen". Drop the
    # combining marks for matching only -- display text is untouched.
    text = _fold(norm(location))
    if not text:
        return None

    # A Canadian province abbreviation is checked before the US test, because
    # "BC" and "ON" are shaped exactly like US state abbreviations.
    canadian = _CA_ABBR_RE.search(text) or _mentions(text, _CA_PROVINCES)

    us = bool(
        _US_COUNTRY_RE.search(text)
        or _STATE_ABBR_RE.search(text)
        or _STATE_NAME_RE.search(text)
        or _US_ZIP_RE.search(text)
        or _US_LEADING_ABBR_RE.search(text)
        or _mentions(text, _US_CITIES)
    )

    if canadian and not us:
        return False
    if us:
        return True

    if (_mentions(text, _NON_US_COUNTRIES)
            or _mentions(text, _NON_US_CITIES)
            or _mentions(text, _NON_US_REGIONS)):
        return False

    return None
