#!/usr/bin/env python3
"""Fail when a public checkout contains common secrets or runtime artifacts."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".sh", ".bat", ".ps1", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".sql"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}
BANNED_NAMES = {".env", "betagent.db", "betagent.sqlite", "betagent.sqlite3"}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "OpenAI-style token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "Telegram bot token": re.compile(r"\b\d{7,}:[A-Za-z0-9_-]{25,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def main() -> int:
    problems: list[str] = []
    git_files = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
    )
    if git_files.returncode == 0 and git_files.stdout:
        paths = [ROOT / item.decode("utf-8") for item in git_files.stdout.split(b"\0") if item]
    else:
        paths = list(ROOT.rglob("*"))

    for path in paths:
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.is_dir():
            continue
        if path.name in BANNED_NAMES or path.suffix in {".db", ".sqlite", ".sqlite3", ".pem", ".p12", ".pfx"}:
            problems.append(f"runtime/secret file: {relative}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            problems.append(f"unreadable file: {relative}: {exc}")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{label}: {relative}")

    if problems:
        print("Public-release check FAILED:")
        for problem in problems:
            print(" -", problem)
        return 1
    print("Public-release check PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
