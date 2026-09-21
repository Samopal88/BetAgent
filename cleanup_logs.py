#!/usr/bin/env python3
"""
BETAGENT — Log cleanup utility.

Removes dated log files older than RETENTION_DAYS.
Safe to run from cron. Only touches files matching known patterns.
Does NOT touch active/current logs.

Usage:
    python3 cleanup_logs.py              # dry-run (default)
    python3 cleanup_logs.py --apply      # actually delete
    python3 cleanup_logs.py --days 14    # keep 14 days instead of 7
"""

import argparse
import os
import time
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
RETENTION_DAYS = 7

# Patterns for dated log files that should be rotated
DATED_PATTERNS = [
    "pipeline_*.log",
    "settle_*.log",
]


def cleanup(dry_run: bool = True, retention_days: int = RETENTION_DAYS) -> dict:
    """Remove dated logs older than retention_days. Returns stats dict."""
    cutoff = time.time() - (retention_days * 86400)
    stats = {"removed": 0, "kept": 0, "freed_bytes": 0}

    for pattern in DATED_PATTERNS:
        for f in sorted(LOG_DIR.glob(pattern)):
            if f.stat().st_mtime < cutoff:
                size = f.stat().st_size
                if dry_run:
                    print(f"  [DRY-RUN] Would remove: {f.name} ({size / 1024:.0f} KB, "
                          f"modified {time.strftime('%Y-%m-%d', time.localtime(f.stat().st_mtime))})")
                else:
                    f.unlink()
                    print(f"  Removed: {f.name} ({size / 1024:.0f} KB)")
                stats["removed"] += 1
                stats["freed_bytes"] += size
            else:
                stats["kept"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Clean up old BetAgent log files")
    parser.add_argument("--apply", action="store_true", help="Actually delete old files (default: dry-run)")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS, help=f"Retention days (default: {RETENTION_DAYS})")
    args = parser.parse_args()

    mode = "DRY-RUN" if args.apply is False else "APPLY"
    print(f"=== BetAgent Log Cleanup ({mode}, retention={args.days} days) ===")
    print(f"  Log directory: {LOG_DIR}")
    print()

    stats = cleanup(dry_run=not args.apply, retention_days=args.days)

    print()
    print(f"  Removed: {stats['removed']} files")
    print(f"  Kept:    {stats['kept']} files")
    print(f"  Freed:   {stats['freed_bytes'] / 1024:.0f} KB")

    if args.apply is False:
        print()
        print("  This was a dry-run. Use --apply to actually delete files.")


if __name__ == "__main__":
    main()
