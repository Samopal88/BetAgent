#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — clv_tracker.py

Считает CLV по уже сохранённым ставкам и odds_history.

v1:
- поддержка только рынков 1X2: home / draw / away
- источник closing line: odds_history
- работает поверх bets + matches + odds_history

Запуск:
  python clv_tracker.py
  python clv_tracker.py --days 30
  python clv_tracker.py --bet-id 123
  python clv_tracker.py --rebuild
"""

from __future__ import annotations
import os
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def ensure_clv_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS clv_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bet_id INTEGER,
        match_id INTEGER NOT NULL,
        sport TEXT,
        league TEXT,
        home_team TEXT,
        away_team TEXT,
        match_date TEXT,
        market TEXT NOT NULL,

        open_odds REAL,
        bet_odds REAL NOT NULL,
        closing_odds REAL,

        open_implied_prob REAL,
        bet_implied_prob REAL,
        closing_implied_prob REAL,

        clv_odds REAL,
        clv_pct REAL,
        clv_prob REAL,
        clv_prob_pct REAL,

        status TEXT DEFAULT 'pending',
        result TEXT,
        profit REAL,

        source_table TEXT DEFAULT 'bets',
        source_id TEXT,
        calculated_at TEXT NOT NULL,
        notes TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_clv_history_bet_id
        ON clv_history(bet_id);
    CREATE INDEX IF NOT EXISTS idx_clv_history_match_id
        ON clv_history(match_id);
    CREATE INDEX IF NOT EXISTS idx_clv_history_calculated_at
        ON clv_history(calculated_at);
    CREATE INDEX IF NOT EXISTS idx_clv_history_sport
        ON clv_history(sport);
    """)
    conn.commit()


def market_to_col(market: str) -> str | None:
    mapping = {
        "home": "odds_home",
        "draw": "odds_draw",
        "away": "odds_away",
    }
    return mapping.get((market or "").strip().lower())


def implied_prob(odds: float | None) -> float | None:
    if odds is None or odds <= 0:
        return None
    return 1.0 / odds


def safe_pct(numer: float | None, denom: float | None) -> float | None:
    if numer is None or denom is None or denom == 0:
        return None
    return (numer / denom) - 1.0


def safe_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a - b


def get_market_odds_from_row(row: sqlite3.Row, market: str) -> float | None:
    col = market_to_col(market)
    if not col:
        return None
    try:
        return float(row[col]) if row[col] is not None else None
    except Exception:
        return None


def get_open_and_closing_odds(conn: sqlite3.Connection, match_id: int, market: str, match_date: str):
    col = market_to_col(market)
    if not col:
        return None, None, "unsupported market"

    # open odds = earliest available odds
    open_row = conn.execute(f"""
        SELECT {col} AS odds
        FROM odds_history
        WHERE match_id = ?
          AND {col} IS NOT NULL
        ORDER BY datetime(captured_at) ASC, id ASC
        LIMIT 1
    """, (match_id,)).fetchone()

    # closing odds = latest odds before match start
    close_row = conn.execute(f"""
        SELECT {col} AS odds
        FROM odds_history
        WHERE match_id = ?
          AND {col} IS NOT NULL
          AND datetime(captured_at) <= datetime(?)
        ORDER BY datetime(captured_at) DESC, id DESC
        LIMIT 1
    """, (match_id, match_date)).fetchone()

    open_odds = float(open_row["odds"]) if open_row and open_row["odds"] is not None else None
    closing_odds = float(close_row["odds"]) if close_row and close_row["odds"] is not None else None

    notes = []
    if open_odds is None:
        notes.append("open_odds_missing")
    if closing_odds is None:
        notes.append("closing_odds_missing")

    return open_odds, closing_odds, ",".join(notes)


def fetch_candidate_bets(conn: sqlite3.Connection, days: int | None = None, bet_id: int | None = None):
    q = """
        SELECT
            b.id AS bet_id,
            b.match_id,
            b.market,
            b.odds AS bet_odds,
            b.result,
            b.profit,
            b.created_at,
            m.sport,
            m.league,
            m.home_team,
            m.away_team,
            m.match_date,
            m.status
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE b.market IN ('home', 'draw', 'away')
    """
    params = []

    if bet_id is not None:
        q += " AND b.id = ?"
        params.append(bet_id)

    if days is not None:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        q += " AND b.created_at >= ?"
        params.append(since)

    q += " ORDER BY b.id ASC"
    return conn.execute(q, params).fetchall()


def clv_row_exists(conn: sqlite3.Connection, bet_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM clv_history WHERE bet_id=? LIMIT 1",
        (bet_id,),
    ).fetchone()
    return row is not None


def delete_existing(conn: sqlite3.Connection, bet_id: int) -> None:
    conn.execute("DELETE FROM clv_history WHERE bet_id=?", (bet_id,))


def save_clv(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    open_odds: float | None,
    closing_odds: float | None,
    extra_notes: str = "",
) -> None:
    bet_odds = float(row["bet_odds"]) if row["bet_odds"] is not None else None

    open_ip = implied_prob(open_odds)
    bet_ip = implied_prob(bet_odds)
    close_ip = implied_prob(closing_odds)

    clv_odds = safe_diff(bet_odds, closing_odds)
    clv_pct = safe_pct(bet_odds, closing_odds)
    clv_prob = safe_diff(close_ip, bet_ip)
    clv_prob_pct = safe_pct(close_ip, bet_ip)

    calculated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO clv_history (
            bet_id, match_id, sport, league, home_team, away_team, match_date,
            market,
            open_odds, bet_odds, closing_odds,
            open_implied_prob, bet_implied_prob, closing_implied_prob,
            clv_odds, clv_pct, clv_prob, clv_prob_pct,
            status, result, profit,
            source_table, source_id, calculated_at, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        row["bet_id"],
        row["match_id"],
        row["sport"],
        row["league"],
        row["home_team"],
        row["away_team"],
        row["match_date"],
        row["market"],
        open_odds,
        bet_odds,
        closing_odds,
        open_ip,
        bet_ip,
        close_ip,
        clv_odds,
        clv_pct,
        clv_prob,
        clv_prob_pct,
        row["status"],
        row["result"],
        row["profit"],
        "bets",
        str(row["bet_id"]),
        calculated_at,
        extra_notes or "",
    ))


def print_summary(conn: sqlite3.Connection, days: int | None = None) -> None:
    q = """
        SELECT
            COUNT(*) AS total,
            AVG(clv_odds) AS avg_clv_odds,
            AVG(clv_pct) AS avg_clv_pct,
            AVG(clv_prob) AS avg_clv_prob,
            AVG(clv_prob_pct) AS avg_clv_prob_pct,
            SUM(CASE WHEN clv_odds > 0 THEN 1 ELSE 0 END) AS positive_count
        FROM clv_history
    """
    params = []
    if days is not None:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        q += " WHERE calculated_at >= ?"
        params.append(since)

    row = conn.execute(q, params).fetchone()
    total = row["total"] or 0
    pos = row["positive_count"] or 0
    positive_share = (pos / total * 100.0) if total else 0.0

    print("=" * 90)
    print("CLV TRACKER SUMMARY")
    print("=" * 90)
    print(f"Total rows                : {total}")
    print(f"Avg CLV odds              : {row['avg_clv_odds'] if row['avg_clv_odds'] is not None else 'n/a'}")
    print(f"Avg CLV pct               : {row['avg_clv_pct'] if row['avg_clv_pct'] is not None else 'n/a'}")
    print(f"Avg CLV prob              : {row['avg_clv_prob'] if row['avg_clv_prob'] is not None else 'n/a'}")
    print(f"Avg CLV prob pct          : {row['avg_clv_prob_pct'] if row['avg_clv_prob_pct'] is not None else 'n/a'}")
    print(f"Positive CLV share        : {positive_share:.2f}%")
    print("=" * 90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="обработать ставки только за N дней")
    ap.add_argument("--bet-id", type=int, default=None, help="обработать только одну ставку")
    ap.add_argument("--rebuild", action="store_true", help="пересчитать записи даже если уже были")
    args = ap.parse_args()

    conn = get_conn()

    required_tables = ["bets", "matches", "odds_history"]
    missing = [t for t in required_tables if not table_exists(conn, t)]
    if missing:
        print(f"❌ Missing required tables: {', '.join(missing)}")
        return

    ensure_clv_table(conn)
    rows = fetch_candidate_bets(conn, days=args.days, bet_id=args.bet_id)

    inserted = skipped = 0

    for row in rows:
        bet_id = row["bet_id"]

        if clv_row_exists(conn, bet_id):
            if args.rebuild:
                delete_existing(conn, bet_id)
            else:
                skipped += 1
                continue

        open_odds, closing_odds, notes = get_open_and_closing_odds(
            conn=conn,
            match_id=row["match_id"],
            market=row["market"],
            match_date=row["match_date"],
        )

        save_clv(
            conn=conn,
            row=row,
            open_odds=open_odds,
            closing_odds=closing_odds,
            extra_notes=notes,
        )
        inserted += 1

    conn.commit()

    print(f"Inserted: {inserted}")
    print(f"Skipped : {skipped}")
    print_summary(conn, days=args.days)

    conn.close()


if __name__ == "__main__":
    main()
