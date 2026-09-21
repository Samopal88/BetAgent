import sqlite3
import os
import random
from pathlib import Path
from fastapi import APIRouter, Depends
from api.auth import require_subscription
from api.database import execute

from dotenv import load_dotenv
BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

router = APIRouter(prefix="/signals", tags=["signals"])

SQLITE_DB = os.getenv("BETAGENT_DB", str(BASE_DIR / "betagent.db"))

PLAN_DELAY_MINUTES = {"basic": 15, "pro": 0, "premium": 0}
PLAN_LIMIT = {"basic": 999, "pro": 999, "premium": 999}
PLAN_WEEKLY_LIMIT = {"basic": 5, "pro": 999, "premium": 999}

def get_sqlite_signals(plan: str, limit: int = 20):
    delay_min = PLAN_DELAY_MINUTES.get(plan, 15)
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    try:
        # Сначала смотрим какие колонки реально есть в bets
        cols = {row[1] for row in conn.execute("PRAGMA table_info(bets)").fetchall()}

        is_golden_sel = "b.is_golden" if "is_golden" in cols else "0 as is_golden"
        ev_sel = "b.ev" if "ev" in cols else "0 as ev"

        cur = conn.execute(f"""
            SELECT
                b.id,
                m.sport,
                m.league,
                m.home_team,
                m.away_team,
                m.match_date,
                b.market,
                b.odds,
                {ev_sel},
                b.result,
                b.created_at,
                {is_golden_sel}
            FROM bets b
            JOIN matches m ON b.match_id = m.id
            WHERE b.result = 'pending'
              AND datetime(b.created_at) <= datetime('now', '-{delay_min} minutes')
            ORDER BY b.created_at DESC
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    clean = []
    for r in rows:
        ev = r.get("ev") or 0
        try:
            ev = float(ev)
        except Exception:
            ev = 0

        if ev > 0:
            ev_range = f"{max(0, round(ev*100-1.5)):.0f}–{round(ev*100+1.5):.0f}%"
        else:
            ev_range = "3–7%"

        confidence = "medium"
        if ev > 0.07:
            confidence = "high"
        elif ev < 0.03:
            confidence = "low"

        is_golden = bool(r.get("is_golden"))
        if is_golden and plan == "basic":
            continue

        clean.append({
            "id": r["id"],
            "sport": r.get("sport", ""),
            "league": r.get("league", ""),
            "match": f"{r['home_team']} — {r['away_team']}",
            "match_date": r.get("match_date", ""),
            "market": r.get("market", ""),
            "odds": r.get("odds"),
            "bookmaker": "Fonbet",
            "confidence": confidence,
            "ev_range": ev_range,
            "is_golden": is_golden,
            "created_at": r.get("created_at", ""),
        })

    return clean[:PLAN_LIMIT.get(plan, 3)]

def make_watermark_stake(user_id: int, base: int = 1000) -> int:
    random.seed(user_id * 9999)
    return base + random.randint(-50, 50)

@router.get("/active")
def active_signals(user=Depends(require_subscription)):
    plan = user["subscription"]["plan"]
    signals = get_sqlite_signals(plan)
    # Для Basic — применяем недельный лимит
    if plan == "basic":
        import psycopg2, psycopg2.extras, os as _os
        from datetime import datetime, timedelta
        try:
            pg = psycopg2.connect(_os.getenv("DATABASE_URL"))
            pg.autocommit = True
            cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Считаем сигналы за текущую неделю (с понедельника)
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
            cur.execute("""
                SELECT COUNT(*) as cnt FROM user_signal_views usv
                WHERE usv.user_id = %s AND usv.shown_at >= %s
            """, (user["id"], monday))
            row = cur.fetchone()
            pg.close()
            used_this_week = row["cnt"] if row else 0
            weekly_limit = PLAN_WEEKLY_LIMIT["basic"]
            remaining = max(0, weekly_limit - used_this_week)
            signals = signals[:remaining]
        except Exception as e:
            pass
    wm_stake = make_watermark_stake(user["id"])
    for sig in signals:
        try:
            execute("""
                INSERT INTO user_signal_views (user_id, signal_id, watermark_stake)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, signal_id) DO NOTHING
            """, (user["id"], sig["id"], wm_stake))
        except Exception:
            pass
        sig["recommended_stake"] = wm_stake
    weekly_used = 0
    weekly_remaining = 999
    if plan == "basic":
        try:
            import psycopg2, os as _os
            from datetime import datetime, timedelta
            pg = psycopg2.connect(_os.getenv("DATABASE_URL"))
            cur = pg.cursor()
            today = datetime.now()
            monday = (today - timedelta(days=today.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
            cur.execute("SELECT COUNT(*) FROM user_signal_views WHERE user_id=%s AND shown_at>=%s", (user["id"], monday))
            weekly_used = cur.fetchone()[0]
            pg.close()
            weekly_remaining = max(0, 5 - weekly_used)
        except Exception:
            pass
    return {"plan": plan, "count": len(signals), "signals": signals, "weekly_used": weekly_used, "weekly_remaining": weekly_remaining}

@router.get("/top")
def top_signal(user=Depends(require_subscription)):
    plan = user["subscription"]["plan"]
    signals = get_sqlite_signals(plan, limit=50)
    golden = [s for s in signals if s["is_golden"]]
    if plan == "premium" and golden:
        return {"signal": golden[0]}
    high = [s for s in signals if s["confidence"] == "high"]
    if high:
        return {"signal": high[0]}
    return {"signal": signals[0] if signals else None}

@router.get("/history")
def history(user=Depends(require_subscription)):
    plan = user["subscription"]["plan"]
    limit = 30 if plan == "basic" else 200
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT b.id, m.sport, m.league,
                   m.home_team, m.away_team, m.match_date,
                   b.market, b.odds, b.result, b.profit, b.created_at
            FROM bets b
            JOIN matches m ON b.match_id = m.id
            WHERE b.result IN ('won','lost')
              AND COALESCE(b.excluded_from_stats, 0) = 0
            ORDER BY b.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()

    total = len(rows)
    won = sum(1 for r in rows if r["result"] == "won")
    total_profit = sum(r["profit"] or 0 for r in rows)
    return {
        "stats": {
            "total": total,
            "won": won,
            "winrate": round(won / total * 100, 1) if total else 0,
            "profit": round(total_profit, 2),
        },
        "history": [dict(r) for r in rows]
    }
