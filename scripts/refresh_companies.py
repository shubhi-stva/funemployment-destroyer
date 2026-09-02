#!/usr/bin/env python3
"""Refresh data/companies.json from the upstream board list.

The list of company -> ATS slug mappings is maintained by
zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships (MIT).
We vendor a copy so a collection run never depends on that repo being up,
and refresh it on a slower cadence than the job poll itself.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fd import config, http  # noqa: E402

SOURCE = (
    "https://raw.githubusercontent.com/zshah101/"
    "Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships/"
    "main/data/companies.json"
)

log = logging.getLogger("fd.companies")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    payload = http.get_json(SOURCE)
    if not isinstance(payload, list) or len(payload) < 100:
        log.error("refusing to overwrite companies.json with %r", type(payload))
        return 1

    cleaned = [
        {"name": e["name"], "slug": e["slug"], "ats": e["ats"].lower()}
        for e in payload
        if isinstance(e, dict) and e.get("name") and e.get("slug") and e.get("ats")
    ]

    config.COMPANIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.COMPANIES_FILE.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=1) + "\n"
    )

    by_ats: dict[str, int] = {}
    for entry in cleaned:
        by_ats[entry["ats"]] = by_ats.get(entry["ats"], 0) + 1
    log.info("Wrote %d companies: %s", len(cleaned),
             ", ".join(f"{k}={v}" for k, v in sorted(by_ats.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
