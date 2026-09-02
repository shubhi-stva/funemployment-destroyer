# Funemployment Destroyer

My personal job board. It goes out every 30 minutes, checks a few thousand
company career pages, throws out everything I'm not eligible for, and puts
what's left on a page I actually want to look at.

Live at https://shubhi-stva.github.io/funemployment-destroyer/

It's a static site. Vanilla HTML, CSS and JS, no framework, no backend, no
database. The whole thing is a Python script that writes a JSON file and a
page that reads it.

## What makes the cut

Two things, and everything else gets dropped before it ever reaches the site.

Undergraduate internships, any season. Summer, Fall, Spring, Winter, co-ops.
If a posting wants a master's, a PhD or an MBA it's gone. That includes the
"Graduate Intern" and "Graduate Co-op" wording Intel and Altera use for grad
students, which reads like a normal internship title until you look it up.

Entry level full time roles where a degree isn't mandatory. A posting
survives unless it makes a bachelor's a hard requirement. "Preferred" is
fine. "Degree or equivalent experience" is fine. Never mentioning education
at all is fine. The only thing that kills it is a real requirement, either
spelled out or sitting there as a bare bullet under Qualifications.

On top of that: no GPA floors, no years of experience asked for, US only,
and it has to be a tech role.

## How the degree filter works

This decides whether something wastes my time, so it's fussier than the
rest of the pipeline.

Real postings almost never say "a degree is required." What they do is put a
line under Qualifications that reads:

> Bachelor's degree in Computer Science, Engineering, or related field.

So instead of scanning the whole posting for keywords, the collector finds
every mention of a degree and reads the text right next to it. Whichever
qualifier sits closest wins:

| What's next to the degree | Verdict |
| --- | --- |
| "no degree required", "self-taught", "bootcamp welcome" | No degree required |
| "or equivalent experience", "in lieu of" | Degree or equivalent |
| "preferred", "a plus", "nice to have" | Degree preferred |
| "currently enrolled", "pursuing", "rising senior" | Currently enrolled |
| nothing at all, just the bullet | Degree required, dropped |

Proximity matters more than it sounds. A posting once listed:

```
Bachelor's degree in computer science (required)
Master's degree in computer science (preferred)
```

A naive keyword scan sees "preferred" and lets it through. Reading the
closest qualifier gets it right.

Two other things this had to learn:

Equal opportunity boilerplate and pay text get skipped. "Final compensation
will be determined based on degree level" is a salary note, not a
requirement, and reading it as one was mislabelling dozens of internships.

Internships are never reported as needing a finished degree. A bachelor's
listed on an internship is in progress. That's what an internship is.

## Why "or equivalent experience" is its own category

"Bachelor's degree or equivalent practical experience" is not the open door
it looks like. The alternative to the degree is years of professional work,
which is exactly what someone starting out doesn't have. Both branches are
shut.

But this is different:

> a degree in CS, or equivalent experience (projects, bootcamp, open source,
> we care about what you can build)

That one spells out what equivalent means, and it's portfolio work. So the
collector checks whether the posting defines it. If it does and the answer is
projects rather than years on the job, it counts as open.

## Where the jobs come from

| Source | What it gives |
| --- | --- |
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`, full description in one request |
| Lever | `api.lever.co/v0/postings/{slug}?mode=json`, plain text description plus work mode |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{slug}` |
| Workday | `POST {tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs`, roughly 1,750 employers |
| Internship feed | [zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships](https://github.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships), MIT licensed |

All public, unauthenticated, read only. The company to board mapping in
`data/companies.json` comes from that same MIT project.

### Workday is annoying and worth it

Workday is by far the biggest ATS in the list, about 1,750 of the 4,600 or so
employers in the list, including NVIDIA, Salesforce, Intel, Accenture and Snap. It nearly
got skipped, because a Workday board is addressed by three values (tenant,
data centre, site path) and the company list only gives me the tenant.

So `data/workday_sites.json` holds the coordinates I've confirmed, seeded
from real URLs in the internship feed.
`scripts/discover_workday.py` probes the plausible combinations for the ones
I haven't resolved yet and caches both hits and misses, so dead ends aren't
retried forever. It runs 40 tenants per collection, so coverage keeps
climbing on its own and no single run gets expensive.

### What I can't get

Some companies block automated access outright:

| Company | What it returns |
| --- | --- |
| Tesla | 403 on every careers API path |
| TikTok | 302 redirect away from the jobs API |
| Apple | 301 to a not found page |
| Meta | 400 |
| LinkedIn | responds, but robots.txt says `Disallow: /` |

These are deliberate blocks, not endpoints I failed to find. Getting past
them means pretending to be a browser to defeat anti bot measures, and with
LinkedIn also ignoring an explicit directive and their terms. This repo is
public and runs on a schedule under my name, so no thanks. Email alerts on
those five sites take ten minutes to set up once.

## Whose job is it anyway

A board's registered name isn't always the employer. Some are aggregators.
The `internshiplist2000` board carries 29 Geotab roles under the name
"Internship List", which is how I ended up clicking Apply on a card that said
one company and landed on another.

So the employer gets worked out in three steps, each one only used if the
last fails:

1. The board name, with board wording trimmed off. "IntegraFEC
   Internships" becomes IntegraFEC.
2. The posting text, which nearly always names the company in the first
   couple of lines. "Who we are: Geotab is..." gives me Geotab.
3. The board slug, which often carries it when nothing else does.
   `axontalentcommunity` gives me Axon.

Getting the name right also fixes the logo, since icons are looked up by
company.

## Running it

```bash
pip install -r scripts/requirements.txt

python scripts/collect.py                        # full run
python scripts/collect.py --limit 25 --dry-run   # quick check, writes nothing
python scripts/collect.py --ats lever            # one platform
python scripts/discover_workday.py --limit 100   # find more Workday boards
python scripts/audit.py --type "Full Time" -v    # re-check what's published
```

Knobs: `FD_MAX_WORKERS`, `FD_MAX_JOBS`, `FD_MAX_AGE_DAYS`, `FD_BOARD_LIMIT`,
`FD_US_ONLY`. To loosen the full time filter, edit `FULLTIME_MAX_LEVEL` and
`FULLTIME_MAX_YEARS` in `scripts/fd/config.py`.

The collector won't write an empty `jobs.json`, so a bad network run leaves
the last good data alone.

## Looking at it locally

Just open `docs/index.html`. It works from disk: the page tries
`data/jobs.json` and falls back to `data/jobs.js`, which is the same payload
as a script tag, for when the browser blocks fetch on `file://`.

For something closer to production:

```bash
cd docs && python3 -m http.server 8000
```

## Layout

```
docs/                     the published site
  index.html
  styles.css
  app.js
  data/jobs.json          generated, don't hand edit
  data/jobs.js            same payload, for opening the file directly
scripts/
  collect.py              main entry point
  audit.py                re-checks published listings against live postings
  discover_workday.py     finds Workday board coordinates
  stamp_assets.py         cache busting for css and js
  fd/
    config.py             every knob
    classify.py           degree, GPA, category, location, seniority, season
    record.py             builds and vets one job
    enrich.py             fetches descriptions the feed didn't include
    logos.py              company name to domain
    http.py               pooled sessions, retries, thread fan out
    build.py              dedupe, prune, write
    sources/              greenhouse, lever, ashby, workday, upstream
data/
  companies.json          company to ATS mapping
  workday_sites.json      confirmed Workday board coordinates
  logos.json              company to domain cache
  seen.json               when each posting was first spotted
.github/workflows/
  collect.yml             the every 30 minutes job
```

## The data file

`docs/data/jobs.json` is `{ generatedAt, schemaVersion, stats, seasons, jobs }`.

| Field | Notes |
| --- | --- |
| `id` | ATS requisition id. Not stable, see below. |
| `key` | Hash of company, title and location. This is the real identity. |
| `company`, `title`, `location`, `url` | |
| `companyUrl` | The board page. The company name on each card links here. |
| `companyDomain` | Used for the icon. Empty means the card falls back to a monogram. |
| `type` | Internship or Full Time |
| `category` | One of eight buckets |
| `season` / `seasons` | "Spring/Summer/Fall 2027" becomes three entries so it shows under each. Empty list means no season named, treated as open to any. |
| `workMode` | On site, Hybrid, Remote, Not specified |
| `postedAt` | Kept date only when the source gave no time, so cards never invent a midnight |
| `firstSeen` | Internal. Not shown, not used for sorting. |
| `degreeRequirement` | No degree required, Degree or equivalent, Degree preferred, Currently enrolled, Degree required, Not specified |
| `experienceLevel` | Intern or Entry Level (nothing else survives) |
| `priority` | 0 to 5, drives the priority sort |
| `notes` | Short line shown on the card |

Missing fields get sensible defaults, so a partly populated feed still
renders. Filter options are built from the data at runtime, so adding a new
category or location needs no frontend change.

## Recency

Everything the page calls recent is measured from `postedAt`, the date the
company published the role. Not from when I found it. It used to do that and the sort
order looked wrong because of it.

The New badge means posted in the last 24 hours.

Worth knowing: ATS publish dates can be reset. If an employer re-lists an old
requisition, it jumps to the top even though it isn't new.

## My clicks stay in my browser

Favorites, applied and hidden live in `localStorage` under `fd.state.v1`.
This repo is public, so none of that belongs in it.

They're keyed on `key`, not on the ATS id, and that matters. Requisition ids
aren't stable. An employer re-listing a role gets a new number, Workday paths
shift, and a dedupe tie can flip which id survives a run. Three postings
changed id between two consecutive runs while being the same job, which under
id based storage would have quietly cleared them out of Applied.

Anything saved before that change still works.

Marking something applied takes it out of All, Internships, Full Time and
New, and it lives in Applied from then on. Favorites is left alone on
purpose, since that's a list I curated by hand and applying to something
shouldn't empty it.

## Checking my own work

`scripts/audit.py` re-fetches the live postings behind everything on the site
and works out the verdicts again from the raw text, instead of trusting what
the collector stored. It runs on every collection, report only, so a
classifier bug shows up in the run log rather than on the page.

It has already caught things I missed by eye, including a full time role
published as "No degree required" whose posting said the opposite.

Currently around 880 of 1,000 listings get verified against their full text.
The rest are on platforms with no reachable description (Oracle,
SmartRecruiters), so those can only be checked by title.

## Cache busting

GitHub Pages serves everything with `cache-control: max-age=600` and no
version in the URL, so after a deploy the browser keeps using the CSS and JS
it already has. The page looks unchanged and only a hard refresh fixes it,
which is a stupid thing to have to know.

`scripts/stamp_assets.py` appends a content hash to the asset links, so every
deploy is a URL the browser has genuinely never seen. The hash only changes
when the file does, so nothing loses its cache for no reason.

## Setup

Pages: Settings, then Pages, source "Deploy from a branch", branch `main`,
folder `/docs`.

The workflow needs no permission changes, it declares `contents: write`
itself.

GitHub disables scheduled workflows after 60 days of no repo activity, so it
will pause if I stop touching this entirely.

## Things that are true and slightly annoying

Every 30 minutes is the floor. GitHub's cron queue isn't punctual and a
static site has nothing to push to, so expect 30 to 60 minutes in practice.
The Run workflow button is instant.

Work mode is often "Not specified" because Greenhouse doesn't expose it and
plenty of postings never say.

Classification is heuristic. It errs toward dropping a borderline job rather
than showing one that turns out to want a degree. Check the actual posting
before spending an application on it.

Output is capped at 3,000 jobs, newest first, and anything first seen more
than 45 days ago gets pruned.

## Credits

The internship feed and the company to board mapping both come from
[zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships](https://github.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships),
used under the MIT License. Saved me building a company list from scratch.

The UI uses San Francisco through the system font stack rather than bundling
it, since Apple's licence covers app UI on Apple platforms and not
redistribution.
