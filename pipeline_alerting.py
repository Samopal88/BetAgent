# -*- coding: utf-8 -*-
"""
BETAGENT — pipeline_alerting.py

Minimal failure alerting for run_pipeline.py critical task failures.

Sends a single deduplicated Telegram message to the admin chat when
a critical pipeline step fails (parse, enrich, bet, settle, normalize).

Design constraints:
- Must not crash the pipeline if alerting itself fails (try/except wrapper)
- Must not spam on success runs (only sends when there are failures)
- One alert per run (deduplicated — all failures in one message)
- Includes: runner name, failed tasks, error text, timestamp, skipped steps
- Uses direct Telegram Bot API (no dependency on tg_bot.py notify flow)

Usage:
    from pipeline_alerting import send_pipeline_alert
    send_pipeline_alert(summary)  # fire-and-forget, safe to call unconditionally
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline_stability import RunSummary

log = logging.getLogger("pipeline.alerts")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Tasks whose failure is CRITICAL — pipeline core value is lost
CRITICAL_TASKS = {"parse", "enrich_football", "enrich_hockey", "bet_football", "bet_hockey", "bet_tennis", "settle", "normalize"}

# Tasks whose failure is WARNING — nice to have but not blocking
WARNING_TASKS = {"archive_snapshot", "tennis_results", "tennis_settle", "notify_unified", "notify_client", "notify_results", "notify_report", "notify_client_bets", "notify_client_results", "notify_tennis_results", "parse_football_stats"}

# ---------------------------------------------------------------------------
# Alert builder
# ---------------------------------------------------------------------------

def _classify_task(name: str) -> str:
    """Return severity for a task name."""
    if name in CRITICAL_TASKS:
        return "CRITICAL"
    if name in WARNING_TASKS:
        return "WARNING"
    return "WARNING"  # default: non-critical


def _build_alert_text(summary: "RunSummary") -> str | None:
    """Build Telegram alert text from RunSummary. Returns None if no failures."""
    failed = [t for t in summary.tasks if not t.success]
    if not failed:
        return None

    # Separate critical vs warning
    critical = [t for t in failed if _classify_task(t.name) == "CRITICAL"]
    warnings = [t for t in failed if _classify_task(t.name) == "WARNING"]

    # If only non-critical tasks failed and fail_fast wasn't triggered, skip
    if not critical and not summary.fail_fast_triggered:
        return None

    severity = "🔴 CRITICAL" if critical else "🟡 WARNING"

    lines = [
        f"{severity} Pipeline Failure",
        f"Runner: {summary.runner}",
        f"Time: {summary.started_at}",
        f"Mode: {'DRY-RUN' if summary.dry_run else 'LIVE'}",
        "",
    ]

    # Failed tasks
    if critical:
        lines.append("Failed tasks:")
        for t in critical:
            err = t.error or "unknown error"
            dur = f"{t.duration_sec:.1f}s"
            lines.append(f"  🔴 {t.name} ({dur})")
            lines.append(f"     {err}")

    if warnings:
        lines.append("Warnings:")
        for t in warnings:
            err = t.error or "unknown error"
            dur = f"{t.duration_sec:.1f}s"
            lines.append(f"  🟡 {t.name} ({dur})")
            lines.append(f"     {err}")

    # Skipped tasks
    skipped = [t for t in summary.tasks if not t.started_at]
    if skipped:
        lines.append("")
        lines.append(f"Skipped ({len(skipped)}):")
        for t in skipped:
            lines.append(f"  ⏭ {t.name}")

    # Fail-fast info
    if summary.fail_fast_triggered:
        lines.append("")
        lines.append(f"FAIL-FAST: {summary.fail_fast_reason}")

    # Summary counters
    lines.append("")
    lines.append(
        f"Tasks: {summary.succeeded_tasks}/{summary.total_tasks} ok, "
        f"{summary.failed_tasks} failed, {summary.skipped_tasks} skipped"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def _send_telegram(text: str) -> bool:
    """Send text to admin Telegram chat via Bot API. Returns success."""
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping alert")
        return False

    import requests

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": int(CHAT_ID),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            log.error(f"Telegram API error: {resp.status_code} {resp.text[:200]}")
            return False
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_pipeline_alert(summary: "RunSummary") -> None:
    """Check RunSummary for failures and send Telegram alert if needed.

    This function is fire-and-forget — it catches all exceptions internally
    so that alerting failures never crash the pipeline.

    Call this after summary.save() in each runner.
    """
    try:
        text = _build_alert_text(summary)
        if text is None:
            return  # No failures worth alerting

        ok = _send_telegram(text)
        if ok:
            log.info("Pipeline alert sent to Telegram")
        else:
            log.warning("Pipeline alert could not be delivered to Telegram")
    except Exception as e:
        # Never let alerting crash the pipeline
        log.error(f"send_pipeline_alert error (non-fatal): {e}")
