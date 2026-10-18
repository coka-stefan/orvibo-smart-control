#!/usr/bin/env python3
"""Reject Chinese text except reviewed, exact compatibility-fixture lines."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(
    r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\uff01-\uff60\uffe0-\uffe6\U00020000-\U000323af]"
)
MANIFEST = ROOT / "english-language-exceptions.json"


def main() -> int:
    exceptions = json.loads(MANIFEST.read_text(encoding="utf-8"))["exceptions"]
    allowed = {}
    for item in exceptions:
        key = (item["path"], item["line_sha256"])
        if key in allowed or not item["reason"].strip():
            raise ValueError("Every exception must be unique and explain its compatibility purpose")
        allowed[key] = item["reason"]
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).decode().split("\0")
    failures = []
    seen = set()
    for name in sorted(set(paths) - {""}):
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if not HAN.search(line):
                continue
            key = (name, hashlib.sha256(line.encode()).hexdigest())
            if key in allowed:
                seen.add(key)
            else:
                failures.append(f"{name}:{number}: unreviewed Chinese text")
    for name, digest in allowed.keys() - seen:
        failures.append(f"{name}: stale compatibility exception {digest[:12]}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"English-only check passed ({len(seen)} exact compatibility exceptions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
