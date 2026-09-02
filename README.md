# Funemployment Destroyer

A personal tech internship and full-time job discovery dashboard.
Static site, vanilla HTML/CSS/JS, hosted on GitHub Pages at:

https://shubhi-stva.github.io/funemployment-destroyer/

This is deliberately **not** a generic job board. It surfaces and organises a
curated set of opportunities, with filters shaped around what actually matters
to me (degree requirements, work mode, category, experience level).

## What it collects

Two standing rules drive every filter in the collector:

1. **Undergraduate internships — all seasons.** Summer, Fall, Spring, Winter,
   co-ops. Roles requiring a master's, PhD or MBA are dropped, including the
   "Graduate Intern" / "Graduate Co-op" labels that Intel and Altera use for
   grad students. A posting offering both routes ("Bachelor's/Master's") is
   kept.
2. **Entry-level full-time tech roles with no degree, GPA, or experience gate.**
   A full-time posting is kept only when *all four* hold: no hard education
   requirement, no numeric GPA floor, entry-level seniority, and no meaningful
   prior-experience ask (`FULLTIME_MAX_YEARS`, default 1).

3. **United States only.** Postings positively identified as abroad are
   dropped.

Everything else — non-tech roles, degree-gated roles, GPA floors, and anything
mid-level or above — is dropped at collection time.

### Location filtering

`classify.is_us_location()` returns True / False / None. Only a positive
*False* is dropped, so a location too vague to place either way (a bare
"Remote", an unlabelled office name) is kept — these boards are overwhelmingly
US-based, and dropping the ambiguous cases would lose real US roles. Set
`FD_US_ONLY=0` to disable the filter.

A multi-site posting counts as US when *any* of its sites is —
"London, England, New York, New York" is still open to someone in New York.

Two traps worth knowing, both of which bit during implementation:

- **Canadian provinces look like US states.** "Sparwood, BC" is British
  Columbia. Provinces are checked before the US test.
- **Substring matching is not enough.** "columbia" (Columbia, MD) matches
  inside "British Columbia", which let a Vancouver posting through as US.
  Matching is word-boundary aware, and accents are folded for comparison so
  "München" is recognised despite NFKD splitting the umlaut.

Seniority that cannot be positively established is treated as mid-level and
dropped. An unstated level is not evidence of an open door, so the board stays
smaller and more trustworthy rather than larger and more speculative.

## How it works

```
GitHub Actions (every 30 min)
  └─ scripts/collect.py
       ├─ upstream internship CSV   (zshah101/...-Tech-Internships, MIT)
       ├─ Greenhouse board API      ~1,034 companies
       ├─ Lever postings API        ~375 companies
       └─ Ashby posting API         ~687 companies
            ↓  classify · filter · dedupe · rank
       docs/data/jobs.json  →  committed  →  GitHub Pages
```

The frontend is unchanged by any of this: it still just reads `jobs.json`.

### Sources

| Source | Endpoint | Gives us |
| --- | --- | --- |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | Full description, departments, first-published date |
| Lever | `api.lever.co/v0/postings/{slug}?mode=json` | Plain-text description, `workplaceType`, `commitment` |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{slug}` | `descriptionHtml`, `workplaceType`, `employmentType` |
| Internship feed | [`zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships`](https://github.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships) | ~460 internships, already deduped, refreshed every 30 min |

All four are public, unauthenticated, read-only endpoints. The company →
board-slug list (`data/companies.json`, 4,579 entries) also comes from that
MIT-licensed repo; `scripts/refresh_companies.py` re-pulls it.

### How the degree filter works

This is the part that decides whether a job is worth your time, so it is
deliberately careful. Real postings almost never say *"a degree is required"* —
they put a bare bullet under Qualifications:

> Bachelor's degree in Computer Science, Engineering, or related field.

So rather than pattern-matching the whole posting, `fd/classify.py` finds every
degree mention and reads the ~240-character window around it:

| Window contains | Verdict |
| --- | --- |
| "or equivalent experience", "in lieu of", "no degree" | **No degree required** |
| "preferred", "a plus", "nice to have", "bonus" | **Degree preferred** |
| "currently enrolled", "pursuing", "rising senior" | **Currently enrolled** |
| nothing qualifying it (a bare bullet) | **Degree required** → dropped |

Windows inside pay or benefits text are skipped too. "Final compensation will
be determined based on degree level" is a salary note, not a requirement —
reading it as one previously mislabelled 68 internships as "Degree required".

Internships are never reported as requiring a completed degree: a posting
listing "Bachelor's degree in X" means the degree is *in progress*, which is
what being an intern is, so anything short of an explicit no-degree-needed
becomes **Currently enrolled**.

### The degree badge on cards

The chip is shown only where it tells you something actionable:

| Card | Chip |
| --- | --- |
| Internship | never shown — enrolment is implied by the role |
| Full time, no degree required | **shown** |
| Full time, degree preferred | hidden — a preference is not a gate |

Equal-opportunity boilerplate is skipped, and bare `master` is ignored so
*"learn and master complex systems"* is not read as a master's degree.

GPA is separate: a numeric floor anywhere in the posting (`3.0 GPA`,
`minimum GPA of 3.5`) drops a full-time role outright, unless the posting
explicitly waives it.

Postings that never mention education at all are classified `Not specified` and
**excluded from full-time results by default** — silence is not evidence of an
open door. Run the workflow manually with *"Also keep full-time roles that never
mention a degree"* checked, or set `FD_INCLUDE_UNSPECIFIED=1`, to widen the net.

## Running the collector yourself

```bash
pip install -r scripts/requirements.txt

python scripts/collect.py                    # full run (~5 min, ~2,100 boards)
python scripts/collect.py --limit 25 --dry-run   # smoke test, writes nothing
python scripts/collect.py --ats lever            # one platform
python scripts/collect.py --no-upstream          # skip the internship feed
```

Env knobs: `FD_MAX_WORKERS`, `FD_MAX_JOBS`, `FD_MAX_AGE_DAYS`,
`FD_BOARD_LIMIT`, `FD_INCLUDE_UNSPECIFIED`.

To widen the full-time net, raise `FULLTIME_MAX_LEVEL` / `FULLTIME_MAX_YEARS` in
`scripts/fd/config.py`.

The collector refuses to write an empty `jobs.json`, so a bad network run
leaves the last good data in place.

## Project structure

```
docs/                     the published site (GitHub Pages root)
  index.html
  styles.css
  app.js
  data/jobs.json          generated -- do not hand-edit
  data/jobs.js            same payload, for opening index.html from disk
  .nojekyll
scripts/
  collect.py              collector entry point
  refresh_companies.py    re-pull the board list
  requirements.txt
  fd/
    config.py             every tunable knob
    classify.py           degree / GPA / category / work mode / seniority
    record.py             build + vet one job record
    http.py               pooled session, retries, thread fan-out
    build.py              dedupe, firstSeen persistence, prune, write
    sources/              greenhouse.py lever.py ashby.py upstream.py
data/
  companies.json          4,579 company -> ATS slug mappings
  seen.json               id -> when we first saw it (NOT personal state)
  logos.json              company -> domain cache for company icons
.github/workflows/
  collect.yml             the every-30-minutes job
```

All asset paths are relative (`./styles.css`, `./app.js`, `./data/jobs.json`),
so the site works under the `/funemployment-destroyer/` project path without a
`<base>` tag and without hardcoding a domain.

## Previewing locally

**Just double-click `docs/index.html`.** It works from disk: the page tries
`data/jobs.json` first and falls back to `data/jobs.js` (the same payload as a
`<script>` assignment) when the browser blocks `fetch()` on `file://`.

For a preview that matches production exactly, serve it over HTTP:

```bash
cd docs
python3 -m http.server 8000
```

Then open http://localhost:8000 — note this only works while that command is
still running; closing the terminal stops the server.

Any static server works — e.g. `npx serve docs` or `php -S localhost:8000 -t docs`.

## Turning it on

**Pages:** Settings → Pages → Source: *Deploy from a branch*, branch `main`,
folder `/docs`.

**Collection:** Settings → Actions → General → Workflow permissions:
*Read and write permissions*. The workflow needs this to commit refreshed
listings back to the repo.

Then run **Actions → Collect jobs → Run workflow** once to seed it; after that
the every-30-minutes schedule takes over. GitHub disables scheduled workflows on
repos with no activity for 60 days, so it will pause if you stop touching the
repo entirely.

## Data model

`docs/data/jobs.json` is either a bare array of jobs, or an object:

```json
{ "generatedAt": "ISO-8601", "schemaVersion": 1, "jobs": [ ... ] }
```

Each job:

| Field | Notes |
| --- | --- |
| `id` | Stable unique string. Used as the localStorage key — must not change between runs. |
| `company` | |
| `title` | |
| `type` | `Internship` or `Full Time` |
| `category` | Software Engineering, AI / Machine Learning, Data, Cybersecurity, Cloud / Infrastructure, Developer Productivity, Product Engineering, Robotics |
| `season` | Earliest term named, e.g. `Summer 2027`; `null` for full-time |
| `seasons` | Every term the posting names. "Spring/Summer/Fall 2027" becomes three entries, so the role appears under each. An empty list means the posting named no term and is treated as open to any. |
| `companyDomain` | Resolved company website, used to fetch a company icon. Empty when unresolved — the card falls back to a monogram. |
| `location` | Free text, e.g. `New York, NY` |
| `workMode` | `On site`, `Hybrid`, `Remote` |
| `url` | Original posting; opens in a new tab |
| `postedAt` | ISO datetime the company posted it. Kept date-only when the source gave no time of day, so the card never invents a "12:00 AM". |
| `firstSeen` | ISO datetime this system first saw it. Internal only — not displayed, and no longer used for sorting. |
| `degreeRequirement` | `No degree required`, `Degree preferred`, `Currently enrolled`, `Degree required`, `Not specified` |
| `experienceLevel` | e.g. `Intern`, `Entry Level`, `Mid Level` |
| `status` | `open` / `closed` |
| `priority` | Number, 0–5. Drives "Highest priority" sort. |
| `source` | ATS or site the job came from |
| `notes` | Short free-text note shown on the card |

Missing fields are normalised to sensible defaults in `normaliseJob()`, so a
partially-populated feed still renders.

Filter dropdown options are derived from the data at runtime — adding a new
category or location to `jobs.json` requires no frontend change.

### Recency

Everything the UI calls recent is measured from **`postedAt`** — when the
company published the role — not from when this collector noticed it:

- **Newest / Oldest** sort by `postedAt`
- The **New** badge means posted within the last 72 hours
  (`CONFIG.newWindowHours` in `app.js`, `NEW_WINDOW_HOURS` in `config.py`)
- The priority score's freshness bonus uses `postedAt`

`firstSeen` still exists in the data and in `data/seen.json`, because it is the
stable anchor that keeps a posting's identity across runs, but it is no longer
shown on cards and no longer affects ordering.

Caveat worth knowing: a handful of sources publish a date with no time of day,
which sorts as midnight UTC, and an employer that re-publishes an old req can
reset its `postedAt`. Both are the ATS's data, not a bug here.

## Personal state stays out of git

**Favorites, Applied, and Hidden are never written to `jobs.json`.** They live
in `localStorage` under the key `fd.state.v1`:

```json
{ "favorites": ["job-id"], "applied": ["job-id"], "hidden": ["job-id"] }
```

This repo and site are public; application activity is not. Hidden jobs drop
out of every list and can be restored from the collapsed drawer below the
results.

## Typography

The UI uses **San Francisco**, Apple's system typeface, referenced through the
system font stack (`-apple-system`, `BlinkMacSystemFont`, `system-ui`) rather
than bundled. Apple's licence covers SF for app UI on Apple platforms, not
redistribution, so shipping the font files in a public repo would violate it —
and referencing the installed system copy is both legal and free of any
download.

On Apple devices this renders in real SF. Elsewhere it falls through to Segoe
UI Variable (Windows), Roboto (Android), then Inter if installed. Numerals use
SF Mono via `ui-monospace`.

## Company icons

Job URLs point at ATS hosts, never the employer, so the domain is looked up
from the company name via Clearbit's autocomplete endpoint and cached in
`data/logos.json` — later runs only query companies not already cached. The
card then loads `icons.duckduckgo.com/ip3/{domain}.ico` (DuckDuckGo rather
than Google, so icon requests are not tied to a Google profile).

About 70% of companies resolve. The rest — and any icon that 404s — fall back
to a monogram tinted by a hash of the company name, so every card shows an
identity and none shows a broken image.

## Known limits

- **"As soon as posted" means ~30 minutes.** GitHub's cron queue is not
  punctual enough for a tighter schedule, and a static site has nothing to push
  to. Trigger a run by hand from the Actions tab when you want it now.
- **Output is capped at 3,000 jobs** (`FD_MAX_JOBS`), newest first, and anything
  first seen more than 45 days ago is pruned. Both keep the page fast.
- **Work mode is often `Not specified`** — Greenhouse simply does not expose it,
  and many postings never say. Lever and Ashby do.
- **Classification is heuristic.** It errs toward dropping a borderline job
  rather than showing one that turns out to want a degree. Always confirm on the
  posting itself before spending an application.

## Attribution

The internship feed and the company board list come from
[`zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships`](https://github.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships),
used under the MIT License.
