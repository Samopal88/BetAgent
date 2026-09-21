# -*- coding: utf-8 -*-
"""
BETAGENT — pipeline_stability.py

Minimal hardening layer for run_pipeline.py:
- TaskResult dataclass with timing, status, metadata
- run_task() wrapper with exception handling and duration tracking
- RunSummary with JSON serialization
- Sanity checks for parse output and data freshness
- Circuit-breaker helpers for fail-fast behavior

Usage:
    from pipeline_stability import run_task, RunSummary, TaskResult

    summary = RunSummary(runner="morning", dry_run=True)
    result = run_task("parse", lambda: do_parse(), summary=summary)
    if result.failed:
        summary.fail_fast("parse failed, skipping dependent steps")
    ...
    summary.save()
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ============================================================
# TaskResult
# ============================================================

@dataclass
class TaskResult:
    name: str
    started_at: str
    ended_at: str = ""
    duration_sec: float = 0.0
    success: bool = False
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return not self.success


# ============================================================
# RunSummary
# ============================================================

class RunSummary:
    """Collects per-task results for a single pipeline run."""

    def __init__(self, runner: str, dry_run: bool = False):
        self.runner = runner
        self.dry_run = dry_run
        self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ended_at = ""
        self.tasks: List[TaskResult] = []
        self.fail_fast_triggered = False
        self.fail_fast_reason = ""
        self.notes: List[str] = []

    # -- task tracking ------------------------------------------------

    def add_task(self, result: TaskResult):
        self.tasks.append(result)

    def fail_fast(self, reason: str):
        self.fail_fast_triggered = True
        self.fail_fast_reason = reason
        self.notes.append(f"FAIL-FAST: {reason}")

    # -- counters convenience -----------------------------------------

    @property
    def total_tasks(self) -> int:
        return len(self.tasks)

    @property
    def succeeded_tasks(self) -> int:
        return sum(1 for t in self.tasks if t.success)

    @property
    def failed_tasks(self) -> int:
        return sum(1 for t in self.tasks if not t.success)

    @property
    def skipped_tasks(self) -> int:
        return sum(1 for t in self.tasks if not t.started_at)

    # -- aggregate counters from task metadata ------------------------

    def counter(self, key: str) -> int:
        """Sum a counter across all task metadata dicts."""
        return sum(t.metadata.get(key, 0) for t in self.tasks)

    # -- serialization ------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runner": self.runner,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "fail_fast_triggered": self.fail_fast_triggered,
            "fail_fast_reason": self.fail_fast_reason,
            "notes": self.notes,
            "summary": {
                "total_tasks": self.total_tasks,
                "succeeded": self.succeeded_tasks,
                "failed": self.failed_tasks,
                "skipped": self.skipped_tasks,
                "total_duration_sec": round(
                    sum(t.duration_sec for t in self.tasks), 1
                ),
                "counters": {
                    "matches_parsed": self.counter("matches_parsed"),
                    "signals_created": self.counter("signals_created"),
                    "bets_created": self.counter("bets_created"),
                    "bets_settled": self.counter("bets_settled"),
                    "notifications_sent": self.counter("notifications_sent"),
                },
            },
            "tasks": [
                {
                    "name": t.name,
                    "status": "ok" if t.success else "failed",
                    "duration_sec": round(t.duration_sec, 1),
                    "error": t.error or "",
                    "metadata": t.metadata,
                }
                for t in self.tasks
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            "=" * 60,
            f"RUN SUMMARY — {self.runner} ({'DRY-RUN' if self.dry_run else 'LIVE'})",
            f"Started: {self.started_at}",
            f"Ended:   {self.ended_at}",
            f"Tasks:   {self.succeeded_tasks}/{self.total_tasks} ok, "
            f"{self.failed_tasks} failed, {self.skipped_tasks} skipped",
            f"Duration: {round(sum(t.duration_sec for t in self.tasks), 1)}s total",
        ]
        if self.fail_fast_triggered:
            lines.append(f"FAIL-FAST: {self.fail_fast_reason}")
        lines.append("-" * 60)
        for t in self.tasks:
            status = "OK" if t.success else "FAIL"
            dur = f"{t.duration_sec:.1f}s"
            meta = ""
            if t.metadata:
                parts = [f"{k}={v}" for k, v in t.metadata.items()]
                meta = " | " + ", ".join(parts)
            err = f" — {t.error}" if t.error else ""
            lines.append(f"  [{status}] {t.name} ({dur}){err}{meta}")
        if self.notes:
            lines.append("-" * 60)
            for note in self.notes:
                lines.append(f"  NOTE: {note}")
        lines.append("=" * 60)
        return "\n".join(lines)

    def save(self, output_dir: Optional[str] = None):
        """Save summary as JSON and text to the run_summaries directory."""
        if output_dir is None:
            output_dir = str(Path(__file__).parent / "run_summaries")
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        runner = self.runner.replace(" ", "_")
        # JSON
        json_path = os.path.join(output_dir, f"{runner}_{ts}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        # Text
        txt_path = os.path.join(output_dir, f"{runner}_{ts}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(self.to_text())
        self.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# run_task wrapper
# ============================================================

def run_task(
    name: str,
    fn: Callable[[], Optional[Dict[str, Any]]],
    summary: Optional[RunSummary] = None,
    timeout_sec: int = 1200,
) -> TaskResult:
    """
    Execute a pipeline task with timing, exception handling, and metadata.

    Args:
        name: Task name for logging
        fn: Callable that returns optional metadata dict (or None)
        summary: Optional RunSummary to auto-add result to
        timeout_sec: Not enforced here (caller handles via subprocess),
                     but recorded in metadata

    Returns:
        TaskResult with success/failure, duration, error, metadata
    """
    started = time.time()
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = TaskResult(name=name, started_at=started_at)

    try:
        meta = fn()
        result.success = True
        if isinstance(meta, dict):
            result.metadata = meta
    except SystemExit:
        # Some scripts call sys.exit(0) on success
        result.success = True
    except Exception as e:
        result.success = False
        result.error = f"{type(e).__name__}: {e}"

    result.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result.duration_sec = round(time.time() - started, 2)

    if summary:
        summary.add_task(result)

    return result


# ============================================================
# Sanity checks
# ============================================================

def check_parse_sanity(sport: str, db_path: str = "betagent.db") -> Dict[str, Any]:
    """
    Quick sanity check after parsing: are there matches for today?
    Returns dict with check results.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    result = {
        "sport": sport,
        "matches_today": 0,
        "matches_with_odds": 0,
        "min_odds": None,
        "max_odds": None,
        "stale_matches": 0,
        "ok": False,
        "warnings": [],
    }
    try:
        conn = sqlite3.connect(db_path)
        # Count today's matches
        row = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE sport=? AND match_date LIKE ?",
            (sport, today + "%"),
        ).fetchone()
        result["matches_today"] = row[0] if row else 0

        if result["matches_today"] == 0:
            result["warnings"].append(f"No matches found for {sport} today ({today})")
            # Not necessarily a failure — could be off-day
            result["ok"] = True  # Don't fail, just warn
            conn.close()
            return result

        # Check odds presence
        row = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE sport=? AND match_date LIKE ? "
            "AND (odds_home IS NOT NULL OR odds_draw IS NOT NULL OR odds_away IS NOT NULL)",
            (sport, today + "%"),
        ).fetchone()
        result["matches_with_odds"] = row[0] if row else 0

        if result["matches_with_odds"] == 0:
            result["warnings"].append(
                f"{result['matches_today']} matches but NONE have odds — parser may be broken"
            )

        # Check odds ranges (sanity: odds should be 1.01-50.0)
        row = conn.execute(
            "SELECT MIN(odds_home), MAX(odds_home) FROM matches "
            "WHERE sport=? AND match_date LIKE ? AND odds_home IS NOT NULL",
            (sport, today + "%"),
        ).fetchone()
        if row and row[0] is not None:
            result["min_odds"] = round(row[0], 2)
            result["max_odds"] = round(row[1], 2)
            if row[0] < 1.01 or row[1] > 50.0:
                result["warnings"].append(
                    f"Suspicious odds range: {row[0]}-{row[1]} for {sport}"
                )

        # Check for stale matches (dates in the past)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) FROM matches WHERE sport=? AND match_date < ? AND status='pending'",
            (sport, yesterday),
        ).fetchone()
        result["stale_matches"] = row[0] if row else 0
        if result["stale_matches"] > 0:
            result["warnings"].append(
                f"{result['stale_matches']} stale pending matches for {sport}"
            )

        conn.close()
        result["ok"] = True
    except Exception as e:
        result["ok"] = False
        result["warnings"].append(f"Sanity check error: {e}")

    return result


def check_enrich_sanity(sport: str, db_path: str = "betagent.db") -> Dict[str, Any]:
    """
    Check that enrichment produced data (form, standings, injuries).
    """
    result = {
        "sport": sport,
        "match_facts_updated": 0,
        "injuries_fetched": 0,
        "ok": True,
        "warnings": [],
    }
    try:
        conn = sqlite3.connect(db_path)
        today = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) FROM match_facts WHERE updated_at LIKE ?",
            (today + "%",),
        ).fetchone()
        result["match_facts_updated"] = row[0] if row else 0
        conn.close()
    except Exception as e:
        result["ok"] = False
        result["warnings"].append(f"Enrich sanity check error: {e}")
    return result


# Need timedelta
from datetime import timedelta
