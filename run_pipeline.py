#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — run_pipeline.py

Автоматический запуск pipeline по расписанию.

Что добавлено:
- shadow-сравнение двух агентов после боевого анализа
- repair_pending_bets_v2.py:
  * запускается после parser_v2.py
  * запускается перед settle
  * чинит связь bets.match_id -> matches.id по fonbet_id

Важно:
- football shadow в режиме PLUS
- hockey shadow в режиме safe
"""

import os
import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    os.environ["PYTHONIOENCODING"] = "utf-8"

import time
import argparse
import subprocess
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

from pipeline_stability import (
    RunSummary,
    run_task,
    check_parse_sanity,
    check_enrich_sanity,
)
from pipeline_alerting import send_pipeline_alert

PIPELINE_DIR = Path(__file__).parent
LOG_FILE = PIPELINE_DIR / "pipeline.log"
load_dotenv(PIPELINE_DIR / ".env")

SCHEDULE = {
    (2, 0):  "tennis_settle",
    (8, 0):  "morning",
    (14, 0): "afternoon",
    (20, 0): "tennis_settle",
    (21, 0): "evening",
    (23, 30): "night",
}

ENV_VARS = {
    "LLM_API_URL":            os.getenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions"),
    "LLM_API_KEY":            os.getenv("LLM_API_KEY", ""),
    "LLM_MODEL":              os.getenv("LLM_MODEL", "anthropic/claude-haiku-4-5"),
    "FOOTBALL_DATA_API_KEY":  os.getenv("FOOTBALL_DATA_API_KEY", ""),
    "BETAGENT_DB":            os.getenv("BETAGENT_DB", "betagent.db"),
    "BETAGENT_BANK":          os.getenv("BETAGENT_BANK", "100000"),
}

from logging.handlers import RotatingFileHandler

LOG_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
LOG_BACKUP_COUNT = 3

rotating_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
)
rotating_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        rotating_handler,
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("pipeline")


def _log_skip_summary(summary: RunSummary, task_name: str):
    """Record a skipped task in the summary (for fail-fast scenarios)."""
    from pipeline_stability import TaskResult
    result = TaskResult(
        name=task_name,
        started_at="",
        ended_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        success=False,
        error="Skipped due to upstream failure",
    )
    summary.add_task(result)
    log.warning(f"  ⏭️ Пропуск: {task_name} (зависит от предыдущего шага)")


def run(script: str, args: list | None = None, timeout: int = 300) -> bool:
    cmd = [sys.executable, str(PIPELINE_DIR / script)] + (args or [])
    log.info(f"→ {script} {' '.join(args or [])}")

    env = os.environ.copy()
    env.update(ENV_VARS)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(PIPELINE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            for line in lines[-10:]:
                if line.strip():
                    log.info(f"   {line}")
            return True
        else:
            log.error(f"   ❌ returncode={result.returncode}")
            if result.stdout:
                for line in result.stdout.strip().split("\n")[-10:]:
                    if line.strip():
                        log.error(f"   {line}")
            if result.stderr:
                log.error(f"   {result.stderr[:600]}")
            return False
    except subprocess.TimeoutExpired:
        log.error(f"   ⏱️ Timeout ({timeout}s)")
        return False
    except Exception as e:
        log.error(f"   ❌ {e}")
        return False


def task_repair_pending():
    script = PIPELINE_DIR / "repair_pending_bets_v2.py"
    if script.exists():
        run("repair_pending_bets_v2.py", timeout=240)


def task_parse(dry_run: bool = False):
    """Parse football + hockey odds. Returns metadata for summary."""
    log.info("📡 Парсинг линии Фонбет...")
    ok_fb = run("parser_v2.py", ["--sport", "football", "--replace-sport"])
    ok_hk = run("parser_v2.py", ["--sport", "hockey", "--replace-sport"])
    task_repair_pending()

    # Sanity checks
    db_path = str(PIPELINE_DIR / "betagent.db")
    fb_sanity = check_parse_sanity("football", db_path)
    hk_sanity = check_parse_sanity("hockey", db_path)

    matches_parsed = fb_sanity.get("matches_today", 0) + hk_sanity.get("matches_today", 0)
    warnings = fb_sanity.get("warnings", []) + hk_sanity.get("warnings", [])
    for w in warnings:
        log.warning(f"  ⚠️ {w}")

    return {
        "matches_parsed": matches_parsed,
        "football_ok": ok_fb,
        "hockey_ok": ok_hk,
        "warnings": warnings,
    }


def task_enrich_football(dry_run: bool = False):
    """Enrich football data. Returns metadata for summary."""
    log.info("⚽ Обогащение футбол...")
    ok1 = run("enricher_football.py", timeout=600)
    ok2 = run("enricher_football_rpl_v3.py", timeout=180)
    ok3 = run("fetch_team_history.py", ["--matches", "15"], timeout=600)
    ok4 = run("injuries_fetcher.py", timeout=240)

    db_path = str(PIPELINE_DIR / "betagent.db")
    sanity = check_enrich_sanity("football", db_path)

    return {
        "enrich_ok": all([ok1, ok2, ok3, ok4]),
        "warnings": sanity.get("warnings", []),
    }


def task_enrich_hockey(dry_run: bool = False):
    """Enrich hockey data. Returns metadata for summary."""
    log.info("🏒 Обогащение хоккей...")
    ok1 = run("the_sports_khl_parser.py", timeout=60)
    ok2 = run("the_sports_nhl_parser.py", timeout=60)
    ok3 = run("enricher_from_the_sports.py", timeout=120)
    ok4 = run("enricher_from_the_sports_nhl.py", timeout=120)
    ok5 = run("sync_match_facts_v3.py", timeout=180)

    return {
        "enrich_ok": all([ok1, ok2, ok3, ok4, ok5]),
    }


def task_parse_football_stats(dry_run: bool = False):
    """Parse corners/YC/shots stats for last 5 days for all target leagues."""
    from datetime import datetime, timedelta
    date_from = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    date_to = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    run("betz_football_stats_parser.py", [
        "--date-from", date_from,
        "--date-to", date_to,
        "--delay", "0.3"
    ], timeout=300)


def get_current_bankroll() -> float:
    """Читает текущий банк из БД."""
    import sqlite3, os
    db = os.path.join(os.path.dirname(__file__), "betagent.db")
    try:
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT COALESCE(SUM(profit),0) FROM bets WHERE result IN ('won','lost')").fetchone()
        conn.close()
        initial = float(os.getenv("BETAGENT_BANK", "100000"))
        return round(initial + float(row[0] or 0), 2)
    except:
        return float(os.getenv("BETAGENT_BANK", "100000"))

def task_expire_subscriptions():
    """Деактивируем истёкшие подписки."""
    try:
        import psycopg2
        from datetime import datetime
        from dotenv import load_dotenv
        load_dotenv(str(PIPELINE_DIR / ".env"))
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        cur = conn.cursor()
        cur.execute("""
            UPDATE subscriptions SET status='expired'
            WHERE end_date < NOW() AND status='active'
            RETURNING user_id
        """)
        expired = cur.fetchall()
        conn.commit()
        conn.close()
        if expired:
            log.info(f"⏰ Деактивировано подписок: {len(expired)} | users: {[r[0] for r in expired]}")
    except Exception as e:
        log.warning(f"⚠️ Ошибка деактивации подписок: {e}")

def task_bet_football(dry_run: bool = False):
    """Analyze football matches. Returns metadata for summary."""
    log.info("⚽ Анализ футбол...")
    bankroll = get_current_bankroll()
    log.info(f"🏦 Текущий банк: {bankroll:.0f} руб")
    args = ["--sport", "football", "--bankroll", str(bankroll)]
    if dry_run:
        args.append("--dry-run")
    ok = run("agent_handoff_v7.py", args, timeout=1200)

    # Count signals/bets from this run
    signals_created = 0
    bets_created = 0
    try:
        import sqlite3
        db = str(PIPELINE_DIR / "betagent.db")
        conn = sqlite3.connect(db)
        today = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) FROM handoff_decisions WHERE sport='football' "
            "AND created_at LIKE ? AND decision != 'PASS'",
            (today + "%",),
        ).fetchone()
        signals_created = row[0] if row else 0
        row = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE created_at LIKE ? "
            "AND match_id IN (SELECT id FROM matches WHERE sport='football')",
            (today + "%",),
        ).fetchone()
        bets_created = row[0] if row else 0
        conn.close()
    except Exception:
        pass

    return {
        "analysis_ok": ok,
        "signals_created": signals_created,
        "bets_created": bets_created,
    }


def task_bet_hockey(dry_run: bool = False):
    """Analyze hockey matches. Returns metadata for summary."""
    log.info("🏒 Анализ хоккей...")
    bankroll = get_current_bankroll()
    log.info(f"🏦 Текущий банк: {bankroll:.0f} руб")
    args = ["--sport", "hockey", "--bankroll", str(bankroll)]
    if dry_run:
        args.append("--dry-run")
    ok = run("agent_handoff_v7.py", args, timeout=600)

    signals_created = 0
    bets_created = 0
    try:
        import sqlite3
        db = str(PIPELINE_DIR / "betagent.db")
        conn = sqlite3.connect(db)
        today = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) FROM handoff_decisions WHERE sport='hockey' "
            "AND created_at LIKE ? AND decision != 'PASS'",
            (today + "%",),
        ).fetchone()
        signals_created = row[0] if row else 0
        row = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE created_at LIKE ? "
            "AND match_id IN (SELECT id FROM matches WHERE sport='hockey')",
            (today + "%",),
        ).fetchone()
        bets_created = row[0] if row else 0
        conn.close()
    except Exception:
        pass

    return {
        "analysis_ok": ok,
        "signals_created": signals_created,
        "bets_created": bets_created,
    }


# def task_shadow_football(dry_run: bool = False, mode: str = "plus"):
#     log.info("🕵️ Shadow football...")
#     args = ["--sport", "football", "--limit", "20", "--mode", mode]
#     run("dual_agent_shadow_runner_v1.py", args, timeout=1200)


# def task_shadow_hockey(dry_run: bool = False, mode: str = "safe"):
#     log.info("🕵️ Shadow hockey...")
#     args = ["--sport", "hockey", "--limit", "20", "--mode", mode]
#     run("dual_agent_shadow_runner_v1.py", args, timeout=900)


def task_tennis_results():
    """Обновить свежие результаты теннисных матчей для settlement."""
    log.info("🎾 Обновление результатов тенниса...")
    ok = run("tennis_results_updater.py", ["--days", "3"], timeout=240)
    return {"results_updated": ok}


def task_tennis_settle():
    """Settle tennis signals. Returns metadata."""
    log.info("🎾 Закрытие теннисных сигналов...")
    ok = run("tennis_live_pipeline.py", ["--settle"], timeout=240)

    bets_settled = 0
    try:
        import sqlite3
        db = str(PIPELINE_DIR / "betagent.db")
        conn = sqlite3.connect(db)
        today = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) FROM tennis_signals WHERE settled_at LIKE ?",
            (today + "%",),
        ).fetchone()
        bets_settled = row[0] if row else 0
        conn.close()
    except Exception:
        pass

    return {"settle_ok": ok, "bets_settled": bets_settled}


def task_bet_tennis(dry_run: bool = False):
    """Analyze tennis matches. Returns metadata."""
    log.info("🎾 Анализ теннис...")
    args = []
    if dry_run:
        args.append("--dry-run")
    ok = run("tennis_live_pipeline.py", args, timeout=600)

    signals_created = 0
    try:
        import sqlite3
        db = str(PIPELINE_DIR / "betagent.db")
        conn = sqlite3.connect(db)
        today = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) FROM tennis_signals WHERE created_at LIKE ? AND status='pending'",
            (today + "%",),
        ).fetchone()
        signals_created = row[0] if row else 0
        conn.close()
    except Exception:
        pass

    return {
        "analysis_ok": ok,
        "signals_created": signals_created,
    }


def task_notify(mode: str = "bets"):
    """Send admin Telegram notification. Fire-and-forget but logs outcome."""
    log.info(f"📱 Telegram уведомление '{mode}' (admin bot)...")
    try:
        subprocess.Popen(
            [sys.executable, str(PIPELINE_DIR / "tg_bot.py"), "--notify", mode],
            stdout=open(str(LOG_FILE), "a"), stderr=subprocess.STDOUT,
        )
        return {"notifications_sent": 1, "mode": mode}
    except Exception as e:
        log.error(f"  ❌ Notification failed: {e}")
        return {"notifications_sent": 0, "mode": mode, "error": str(e)}


def task_notify_client(mode: str = "bets"):
    """Отправить уведомления подписчикам через клиентский бот."""
    log.info(f"📱 Telegram уведомление '{mode}' (client bot)...")
    mode_map = {"bets": "bets", "results": "results"}
    client_mode = mode_map.get(mode)
    if client_mode:
        # Check if notifier exists before attempting
        notifier_path = PIPELINE_DIR / "bot" / "notifier.py"
        if not notifier_path.exists():
            log.warning(f"  ⚠️ bot/notifier.py not found — skipping client notification")
            return {"notifications_sent": 0, "skipped": True, "reason": "notifier not found"}
        ok = run("bot/notifier.py", ["--mode", client_mode], timeout=120)
        return {"notifications_sent": 1 if ok else 0, "mode": mode}
    return {"notifications_sent": 0, "skipped": True}


def task_notify_tennis(mode: str = "bets"):
    """Отправить теннисные уведомления подписчикам."""
    log.info(f"🎾 Теннисное уведомление '{mode}' (client bot)...")
    mode_map = {"bets": "bets", "results": "results"}
    client_mode = mode_map.get(mode)
    if client_mode:
        notifier_path = PIPELINE_DIR / "bot" / "notifier.py"
        if not notifier_path.exists():
            log.warning(f"  ⚠️ bot/notifier.py not found — skipping tennis notification")
            return {"notifications_sent": 0, "skipped": True, "reason": "notifier not found"}
        ok = run("bot/notifier.py", ["--mode", client_mode, "--tennis"], timeout=120)
        return {"notifications_sent": 1 if ok else 0, "mode": mode}
    return {"notifications_sent": 0, "skipped": True}


def task_publish_channel(mode: str = "bets"):
    """Опубликовать в канал."""
    log.info(f"📢 Публикация в канал '{mode}'...")
    mode_map = {"bets": "bets", "results": "results"}
    pub_mode = mode_map.get(mode)
    if pub_mode:
        run("content_publisher.py", ["--mode", pub_mode], timeout=60)


def task_notify_unified():
    """Unified NEW_BET notification via notification_layer.py.

    Replaces separate task_notify('bets') + task_publish_channel('bets')
    for the NEW_BET event type. Uses unified dedup (notification_log table).
    Client notifications still use separate path (per-user PG dedup).
    """
    log.info("📱 Unified NEW_BET notification (admin + channel)...")
    try:
        from notification_layer import notify_new_bet_unified
        results = notify_new_bet_unified(admin=True, channel=True)
        log.info(f"  Unified notify results: {results}")
        return {"unified_notify_ok": True, **results}
    except Exception as e:
        log.error(f"  ❌ Unified notification failed: {e}")
        return {"unified_notify_ok": False, "error": str(e)}


def task_notify_results_unified():
    """Unified SETTLED_RESULT notification via notification_layer.py.

    Replaces separate task_notify('results') + task_publish_channel('results')
    for the SETTLED_RESULT event type. Uses unified dedup.
    """
    log.info("📱 Unified SETTLED_RESULT notification (admin + channel)...")
    try:
        from notification_layer import notify_settled_results_unified
        results = notify_settled_results_unified(admin=True, channel=True)
        log.info(f"  Unified results: {results}")
        return {"unified_results_ok": True, **results}
    except Exception as e:
        log.error(f"  ❌ Unified results notification failed: {e}")
        return {"unified_results_ok": False, "error": str(e)}


def task_archive_snapshot():
    log.info("🗄️ Архивация исторических данных...")
    run("historical_archive_v1.py", ["--snapshot"], timeout=180)


def task_normalize_results():
    """Run result normalization layer — populate normalized_results from raw sources."""
    log.info("🔄 Нормализация результатов...")
    ok1 = run("result_normalization.py", ["--sport", "football", "--days", "3"], timeout=30)
    ok2 = run("result_normalization.py", ["--sport", "hockey", "--days", "3"], timeout=30)
    ok3 = run("result_normalization.py", ["--sport", "tennis", "--days", "3"], timeout=30)
    return {"normalize_ok": all([ok1, ok2, ok3])}


def task_settle():
    """Settle bets. Returns metadata for summary."""
    log.info("💰 Закрытие ставок...")
    task_repair_pending()

    pending_before = 0
    try:
        import sqlite3
        db = str(PIPELINE_DIR / "betagent.db")
        conn = sqlite3.connect(db)
        pending_before = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE result = 'pending'"
        ).fetchone()[0]
        conn.close()
    except Exception:
        pass

    # Normalize results first so settlement can use canonical data
    task_normalize_results()
    # Парсим футбольные результаты перед закрытием
    from datetime import datetime, timedelta
    today = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    ok1 = run("sportsru_football_results_parser.py", ["--date", today], timeout=60)
    ok2 = run("sportsru_football_results_parser.py", ["--date", yesterday], timeout=60)
    # MLS результаты в results_raw (settler их не видит через backtest_matches)
    run("betz_mls_parser.py", ["--days", "3", "--delay", "0.1"], timeout=120)
    # Скандинавские летние лиги (Швеция/Норвегия/Дания/Финляндия) — нужны для SUMMER_BTTS_HOME
    run("betz_scandinavia_betz_parser.py", ["--days", "3", "--delay", "0.1"], timeout=180)
    ok_tennis_results = True
    tennis_results_path = PIPELINE_DIR / "tennis_results_updater.py"
    if tennis_results_path.exists():
        ok_tennis_results = run("tennis_results_updater.py", ["--days", "3"], timeout=240)

    ok3 = run("updater_results.py", ["--settle"], timeout=240)

    ok4 = True
    settler_path = PIPELINE_DIR / "settler.py"
    if settler_path.exists():
        ok4 = run("settler.py", timeout=240)

    ok_notify = run("tg_bot.py", ["--notify", "results"], timeout=60)

    # Count settled bets
    bets_settled = 0
    tennis_pending_after = 0
    pending_after = 0
    try:
        import sqlite3
        db = str(PIPELINE_DIR / "betagent.db")
        conn = sqlite3.connect(db)
        today_str = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE settled_at LIKE ?",
            (today_str + "%",),
        ).fetchone()
        bets_settled = row[0] if row else 0
        pending_after = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE result = 'pending'"
        ).fetchone()[0]
        tennis_pending_after = conn.execute(
            "SELECT COUNT(*) FROM bets b JOIN matches m ON m.id = b.match_id "
            "WHERE b.result = 'pending' AND m.sport = 'tennis'"
        ).fetchone()[0]
        conn.close()
    except Exception:
        pass

    closed_now = max(0, pending_before - pending_after)
    log.info(
        "Settlement telemetry: pending_before=%s | pending_after=%s | tennis_pending_after=%s | closed_now=%s | settled_today=%s",
        pending_before, pending_after, tennis_pending_after, closed_now, bets_settled,
    )

    return {
        "settle_ok": all([ok1, ok2, ok_tennis_results, ok3, ok4, ok_notify]),
        "bets_settled": bets_settled,
        "closed_now": closed_now,
        "tennis_pending_after": tennis_pending_after,
    }


def task_tennis_settle_only():
    """Lightweight tennis settlement — results + settle only, no parsing.
    Runs between main pipeline cycles to catch matches that finished
    during the day (e.g. 02:00 and 20:00)."""
    log.info("🎾 Быстрое закрытие тенниса...")
    run_task("tennis_results", lambda: task_tennis_results(), summary=None)
    run_task("tennis_settle", lambda: task_tennis_settle(), summary=None)


def run_morning(dry_run: bool = False):
    summary = RunSummary(runner="morning", dry_run=dry_run)
    log.info("=" * 60)
    log.info("🌅 УТРЕННИЙ ПРОГОН")
    log.info("=" * 60)

    # Normalize results — if this fails, settle still works with raw fallback
    run_task("normalize", lambda: task_normalize_results(), summary=summary)

    # Settle — if this fails, continue (results may be stale but not critical)
    run_task("settle", lambda: task_settle(), summary=summary)

    # Parse — CRITICAL: if parse fails, skip all dependent steps
    parse_ok = run_task("parse", lambda: task_parse(dry_run), summary=summary).success
    if not parse_ok:
        summary.fail_fast("Parse failed — skipping enrich and analysis")
        _log_skip_summary(summary, "enrich_football")
        _log_skip_summary(summary, "enrich_hockey")
        _log_skip_summary(summary, "bet_football")
        _log_skip_summary(summary, "bet_hockey")
        _log_skip_summary(summary, "bet_tennis")
    else:
        # Enrich — if enrich fails, skip analysis for that sport
        enrich_fb_ok = run_task("enrich_football", lambda: task_enrich_football(dry_run), summary=summary).success
        enrich_hk_ok = run_task("enrich_hockey", lambda: task_enrich_hockey(dry_run), summary=summary).success

        if enrich_fb_ok:
            run_task("bet_football", lambda: task_bet_football(dry_run), summary=summary)
        else:
            summary.fail_fast("Enrich football failed — skipping bet_football")
            _log_skip_summary(summary, "bet_football")

        if enrich_hk_ok:
            run_task("bet_hockey", lambda: task_bet_hockey(dry_run), summary=summary)
        else:
            summary.fail_fast("Enrich hockey failed — skipping bet_hockey")
            _log_skip_summary(summary, "bet_hockey")

        # Tennis has its own pipeline, runs independently
        run_task("bet_tennis", lambda: task_bet_tennis(dry_run), summary=summary)

    # Archive and notifications (non-critical)
    run_task("archive_snapshot", lambda: task_archive_snapshot(), summary=summary)
    run_task("tennis_results", lambda: task_tennis_results(), summary=summary)
    run_task("tennis_settle", lambda: task_tennis_settle(), summary=summary)
    run_task("notify_unified", lambda: task_notify_unified(), summary=summary)
    run_task("notify_client", lambda: task_notify_client("bets"), summary=summary)

    summary.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary.save()
    log.info(summary.to_text())
    send_pipeline_alert(summary)
    log.info("✅ Утренний прогон завершён\n")


def run_afternoon(dry_run: bool = False):
    summary = RunSummary(runner="afternoon", dry_run=dry_run)
    log.info("=" * 60)
    log.info("☀️ ДНЕВНОЙ ПРОГОН")
    log.info("=" * 60)

    parse_ok = run_task("parse", lambda: task_parse(dry_run), summary=summary).success
    if not parse_ok:
        summary.fail_fast("Parse failed — skipping enrich and analysis")
        _log_skip_summary(summary, "enrich_football")
        _log_skip_summary(summary, "bet_football")
        _log_skip_summary(summary, "bet_tennis")
    else:
        enrich_fb_ok = run_task("enrich_football", lambda: task_enrich_football(dry_run), summary=summary).success
        if enrich_fb_ok:
            run_task("bet_football", lambda: task_bet_football(dry_run), summary=summary)
        else:
            summary.fail_fast("Enrich football failed — skipping bet_football")
            _log_skip_summary(summary, "bet_football")
        run_task("bet_tennis", lambda: task_bet_tennis(dry_run), summary=summary)

    run_task("archive_snapshot", lambda: task_archive_snapshot(), summary=summary)
    run_task("tennis_results", lambda: task_tennis_results(), summary=summary)
    run_task("tennis_settle", lambda: task_tennis_settle(), summary=summary)
    run_task("notify_unified", lambda: task_notify_unified(), summary=summary)
    run_task("notify_client", lambda: task_notify_client("bets"), summary=summary)

    summary.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary.save()
    log.info(summary.to_text())
    send_pipeline_alert(summary)
    log.info("✅ Дневной прогон завершён\n")


def run_evening(dry_run: bool = False):
    summary = RunSummary(runner="evening", dry_run=dry_run)
    log.info("=" * 60)
    log.info("🌆 ВЕЧЕРНИЙ ПРОГОН")
    log.info("=" * 60)

    # Normalize results first, then settle
    run_task("normalize", lambda: task_normalize_results(), summary=summary)
    run_task("settle", lambda: task_settle(), summary=summary)

    parse_ok = run_task("parse", lambda: task_parse(dry_run), summary=summary).success
    if not parse_ok:
        summary.fail_fast("Parse failed — skipping enrich and analysis")
        _log_skip_summary(summary, "enrich_football")
        _log_skip_summary(summary, "enrich_hockey")
        _log_skip_summary(summary, "bet_football")
        _log_skip_summary(summary, "bet_hockey")
        _log_skip_summary(summary, "bet_tennis")
    else:
        enrich_fb_ok = run_task("enrich_football", lambda: task_enrich_football(dry_run), summary=summary).success
        enrich_hk_ok = run_task("enrich_hockey", lambda: task_enrich_hockey(dry_run), summary=summary).success

        if enrich_fb_ok:
            run_task("bet_football", lambda: task_bet_football(dry_run), summary=summary)
        else:
            summary.fail_fast("Enrich football failed — skipping bet_football")
            _log_skip_summary(summary, "bet_football")

        if enrich_hk_ok:
            run_task("bet_hockey", lambda: task_bet_hockey(dry_run), summary=summary)
        else:
            summary.fail_fast("Enrich hockey failed — skipping bet_hockey")
            _log_skip_summary(summary, "bet_hockey")

        run_task("bet_tennis", lambda: task_bet_tennis(dry_run), summary=summary)

    run_task("archive_snapshot", lambda: task_archive_snapshot(), summary=summary)
    run_task("tennis_results", lambda: task_tennis_results(), summary=summary)
    run_task("tennis_settle", lambda: task_tennis_settle(), summary=summary)
    run_task("notify_unified", lambda: task_notify_unified(), summary=summary)
    run_task("notify_results", lambda: task_notify_results_unified(), summary=summary)
    run_task("notify_report", lambda: task_notify("report"), summary=summary)
    run_task("notify_client_bets", lambda: task_notify_client("bets"), summary=summary)
    run_task("notify_client_results", lambda: task_notify_client("results"), summary=summary)
    summary.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary.save()
    log.info(summary.to_text())
    send_pipeline_alert(summary)
    log.info("✅ Вечерний прогон завершён\n")


def run_night(dry_run: bool = False):
    summary = RunSummary(runner="night", dry_run=dry_run)
    log.info("=" * 60)
    log.info("🌙 НОЧНОЙ ПРОГОН")
    log.info("=" * 60)

    parse_ok = run_task("parse", lambda: task_parse(dry_run), summary=summary).success
    if not parse_ok:
        summary.fail_fast("Parse failed — skipping enrich and analysis")
        _log_skip_summary(summary, "enrich_hockey")
        _log_skip_summary(summary, "bet_hockey")
        _log_skip_summary(summary, "bet_tennis")
    else:
        enrich_hk_ok = run_task("enrich_hockey", lambda: task_enrich_hockey(dry_run), summary=summary).success
        if enrich_hk_ok:
            run_task("bet_hockey", lambda: task_bet_hockey(dry_run), summary=summary)
        else:
            summary.fail_fast("Enrich hockey failed — skipping bet_hockey")
            _log_skip_summary(summary, "bet_hockey")
        run_task("bet_tennis", lambda: task_bet_tennis(dry_run), summary=summary)

    run_task("archive_snapshot", lambda: task_archive_snapshot(), summary=summary)
    run_task("tennis_results", lambda: task_tennis_results(), summary=summary)
    run_task("tennis_settle", lambda: task_tennis_settle(), summary=summary)
    run_task("notify_unified", lambda: task_notify_unified(), summary=summary)
    run_task("notify_client", lambda: task_notify_client("bets"), summary=summary)

    summary.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary.save()
    log.info(summary.to_text())
    send_pipeline_alert(summary)
    log.info("✅ Ночной прогон завершён\n")


def run_full(dry_run: bool = False):
    summary = RunSummary(runner="full", dry_run=dry_run)
    log.info("=" * 60)
    log.info("🚀 ПОЛНЫЙ ПРОГОН")
    log.info("=" * 60)

    run_task("settle", lambda: task_settle(), summary=summary)

    parse_ok = run_task("parse", lambda: task_parse(dry_run), summary=summary).success
    if not parse_ok:
        summary.fail_fast("Parse failed — skipping enrich and analysis")
        _log_skip_summary(summary, "enrich_football")
        _log_skip_summary(summary, "parse_football_stats")
        _log_skip_summary(summary, "enrich_hockey")
        _log_skip_summary(summary, "bet_football")
        _log_skip_summary(summary, "bet_hockey")
        _log_skip_summary(summary, "bet_tennis")
    else:
        run_task("enrich_football", lambda: task_enrich_football(dry_run), summary=summary)
        run_task("parse_football_stats", lambda: task_parse_football_stats(dry_run), summary=summary)
        run_task("enrich_hockey", lambda: task_enrich_hockey(dry_run), summary=summary)
        run_task("bet_football", lambda: task_bet_football(dry_run), summary=summary)
        run_task("bet_hockey", lambda: task_bet_hockey(dry_run), summary=summary)
        run_task("bet_tennis", lambda: task_bet_tennis(dry_run), summary=summary)

    run_task("archive_snapshot", lambda: task_archive_snapshot(), summary=summary)
    run_task("notify_unified", lambda: task_notify_unified(), summary=summary)
    run_task("notify_client", lambda: task_notify_client("bets"), summary=summary)

    summary.ended_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary.save()
    log.info(summary.to_text())
    send_pipeline_alert(summary)
    log.info("✅ Полный прогон завершён\n")


RUNNERS = {
    "morning":       run_morning,
    "afternoon":     run_afternoon,
    "evening":       run_evening,
    "night":         run_night,
    "tennis_settle": lambda dry_run=False: task_tennis_settle_only(),
}


def get_next_run(schedule: dict) -> tuple:
    now = datetime.now()
    candidates = []
    for (h, m), name in schedule.items():
        run_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if run_time <= now:
            run_time += timedelta(days=1)
        diff = (run_time - now).total_seconds()
        candidates.append((diff, name, run_time))
    candidates.sort(key=lambda x: x[0])
    return candidates[0]


def scheduler_loop(dry_run: bool = False):
    log.info("🤖 BETAGENT Pipeline Scheduler запущен")
    log.info(f"📁 Рабочая папка: {PIPELINE_DIR}")
    log.info(f"📋 Лог: {LOG_FILE}")
    log.info(f"🏦 Банк: {ENV_VARS['BETAGENT_BANK']} руб")
    if dry_run:
        log.info("⚠️  DRY-RUN режим — ставки не записываются")

    log.info("\nРасписание:")
    for (h, m), name in sorted(SCHEDULE.items()):
        log.info(f"  {h:02d}:{m:02d} — {name}")
    log.info("")

    while True:
        wait_sec, run_name, run_time = get_next_run(SCHEDULE)
        wait_min = int(wait_sec / 60)
        wait_hr = wait_min // 60
        wait_min_rem = wait_min % 60
        log.info(f"⏰ Следующий прогон: {run_name} в {run_time.strftime('%H:%M')} (через {wait_hr}ч {wait_min_rem}мин)")

        elapsed = 0
        while elapsed < wait_sec:
            time.sleep(30)
            elapsed += 30
            now = datetime.now()
            for (h, m), name in SCHEDULE.items():
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                diff = abs((now - target).total_seconds())
                if diff < 35:
                    runner = RUNNERS.get(name)
                    if runner:
                        try:
                            runner(dry_run=dry_run)
                        except Exception as e:
                            log.error(f"❌ Ошибка прогона {name}: {e}")
                    break


def main():
    ap = argparse.ArgumentParser(description="BETAGENT Pipeline Scheduler")
    ap.add_argument("--now", action="store_true", help="Запустить полный прогон сейчас")
    ap.add_argument("--settle", action="store_true", help="Только закрыть ставки")
    ap.add_argument("--dry-run", action="store_true", help="Без реальных ставок")
    ap.add_argument("--run", choices=list(RUNNERS.keys()), help="Запустить конкретный прогон")
    args = ap.parse_args()

    if not ENV_VARS["LLM_API_KEY"]:
        log.warning("⚠️  LLM_API_KEY не задан! Проверь .env")

    if args.settle:
        task_settle()
        return
    if args.now:
        run_full(dry_run=args.dry_run)
        return
    if args.run:
        RUNNERS[args.run](dry_run=args.dry_run)
        return

    try:
        scheduler_loop(dry_run=args.dry_run)
    except KeyboardInterrupt:
        log.info("\n👋 Pipeline остановлен")


if __name__ == "__main__":
    main()
