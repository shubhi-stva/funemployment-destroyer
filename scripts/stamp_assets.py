#!/usr/bin/env python3
"""Stamp docs/index.html's asset links with a content hash.

GitHub Pages serves every file with `cache-control: max-age=600` and no
version in the URL, so a browser that has seen styles.css or app.js keeps
using its copy after a deploy -- the page looks unchanged until the user
hard-refreshes, which is not something anyone should have to know to do.

Appending ?v=<hash of the file> makes each deploy a new URL, so the browser
fetches it because it has genuinely never seen it. The hash only changes when
the file's bytes change, so unchanged assets still cache normally.

Idempotent: safe to run on every build.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.html"
ASSETS = ("styles.css", "app.js")


def digest(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:10]


def main() -> int:
    if not INDEX.exists():
        print(f"missing {INDEX}", file=sys.stderr)
        return 1

    html = INDEX.read_text()
    original = html

    for name in ASSETS:
        asset = INDEX.parent / name
        if not asset.exists():
            print(f"missing {asset}", file=sys.stderr)
            return 1

        version = digest(asset)
        # Matches ./name with or without an existing ?v=... stamp.
        pattern = re.compile(r"(\./" + re.escape(name) + r")(\?v=[0-9a-f]+)?")
        html, count = pattern.subn(rf"\g<1>?v={version}", html)
        if not count:
            print(f"no reference to {name} in index.html", file=sys.stderr)
            return 1
        print(f"  {name} -> ?v={version} ({count} reference{'s' if count > 1 else ''})")

    if html != original:
        INDEX.write_text(html)
        print("index.html updated")
    else:
        print("index.html already current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
