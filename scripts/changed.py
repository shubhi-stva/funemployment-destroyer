#!/usr/bin/env python3
"""Exit 0 if docs/data/jobs.json's listings differ from the committed version.

jobs.json is minified onto a single line and always carries a fresh
`generatedAt`, so `git diff` is never empty. The workflow needs to know
whether the *listings* moved, which is what this compares.

Exit codes:
    0  changed (or no previous version) -- commit it
    1  unchanged -- skip the commit
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TARGET = "docs/data/jobs.json"


def listings(text: str) -> list:
    try:
        return json.loads(text).get("jobs", [])
    except (json.JSONDecodeError, AttributeError):
        return []


def main() -> int:
    new = listings(Path(TARGET).read_text())
    if not new:
        print("jobs.json has no listings; refusing to commit")
        return 1

    try:
        previous = subprocess.run(
            ["git", "show", f"HEAD:{TARGET}"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        print("no committed version yet -> changed")
        return 0

    old = listings(previous)
    if old == new:
        print(f"listings unchanged ({len(new)} roles)")
        return 1

    added = {j["id"] for j in new} - {j["id"] for j in old}
    removed = {j["id"] for j in old} - {j["id"] for j in new}
    print(f"changed: {len(added)} added, {len(removed)} removed, {len(new)} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
