"""Tunable knobs for the collector.

Everything the engine's behaviour depends on lives here so the source
modules stay mechanical.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# --- Paths ---------------------------------------------------------------

COMPANIES_FILE = ROOT / "data" / "companies.json"
SEEN_FILE = ROOT / "data" / "seen.json"
# company name -> web domain, used to render a company icon
LOGO_CACHE = ROOT / "data" / "logos.json"
# verified Workday board coordinates: tenant -> {dc, site, name}
WORKDAY_SITES = ROOT / "data" / "workday_sites.json"
OUTPUT_FILE = ROOT / "docs" / "data" / "jobs.json"
# Same data as a <script> assignment, for opening index.html from disk.
FALLBACK_FILE = ROOT / "docs" / "data" / "jobs.js"

# Upstream internship feed (MIT licensed, refreshed every 30 minutes).
UPSTREAM_CSV = (
    "https://raw.githubusercontent.com/zshah101/"
    "Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships/"
    "main/data/internships.csv"
)

# --- HTTP ----------------------------------------------------------------

USER_AGENT = (
    "funemployment-destroyer/1.0 "
    "(+https://github.com/shubhi-stva/funemployment-destroyer)"
)
REQUEST_TIMEOUT = 25
MAX_WORKERS = int(os.environ.get("FD_MAX_WORKERS", "24"))
MAX_RETRIES = 2

# Boards to poll. Ordered so the cheapest/densest platforms run first.
ENABLED_ATS = ("greenhouse", "lever", "ashby", "workday")

# Cap on boards polled per run (0 = no cap). Useful for local smoke tests.
BOARD_LIMIT = int(os.environ.get("FD_BOARD_LIMIT", "0"))

# --- Output shaping ------------------------------------------------------

# Hard ceiling on jobs written to jobs.json, so the static page stays fast.
# Newest-first, so this trims the stale tail, not fresh postings.
MAX_JOBS = int(os.environ.get("FD_MAX_JOBS", "3000"))

# Drop anything first seen longer ago than this.
MAX_AGE_DAYS = int(os.environ.get("FD_MAX_AGE_DAYS", "45"))

# A posting counts as "New" in the UI within this window. Kept in sync with
# CONFIG.newWindowHours in docs/app.js.
NEW_WINDOW_HOURS = 24

# --- What we actually want -----------------------------------------------

# Full-time roles are kept unless a bachelor's degree is a STRICT
# requirement. Everything softer qualifies:
#   - the posting says no degree is needed
#   - a degree is merely preferred
#   - a degree OR equivalent experience is accepted
#   - education is never mentioned at all
# Only "Degree required" -- a bare qualifications bullet, or an explicit
# "(required)" -- is disqualifying.
FULLTIME_ALLOWED_DEGREE: tuple[str, ...] = (
    "No degree required",
    "Degree preferred",
    "Degree or equivalent",
    "Not specified",
)
# Full-time roles must be genuinely open to someone starting out: entry level,
# and asking for no meaningful prior experience. Anything that quotes a
# years-of-experience minimum above FULLTIME_MAX_YEARS is dropped, as is
# anything whose seniority could not be positively established -- an unstated
# level is not evidence of an open door.
# United States only. Postings positively identified as abroad are dropped;
# a location too vague to place either way (a bare "Remote", an unlabelled
# office name) is kept, since these boards are overwhelmingly US-based and
# dropping them would lose real US roles.
US_ONLY = os.environ.get("FD_US_ONLY", "1") == "1"

FULLTIME_MAX_LEVEL = 1  # see classify.LEVEL_RANK; 1 == Entry Level
FULLTIME_MAX_YEARS = 0  # any quoted years-of-experience ask disqualifies
