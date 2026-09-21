#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("BETAGENT_DB", str(BASE_DIR / "betagent.db")))

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None

def get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

def pick_col(columns: Iterable[str], candidates: list[str]) -> Optional[str]:
    cols = set(columns)
    for c in candidates:
        if c in cols:
            return c
    return None

def as_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}

def json_dumps(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))

def fingerprint_for(data: Dict[str, Any]) -> str:
    return hashlib.sha256(json_dumps(data).encode("utf-8")).hexdigest()

def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS odds_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            match_id INTEGER,
            fonbet_match_id TEXT,
            sport TEXT,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            match_date TEXT,
            odds_home REAL,
            odds_draw REAL,
            odds_away REAL,
            odds_over_2_5 REAL,
            odds_under_2_5 REAL,
            odds_over_3_5 REAL,
            odds_under_3_5 REAL,
            fingerprint TEXT,
            row_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_odds_history_match_id ON odds_history(match_id);
        CREATE INDEX IF NOT EXISTS idx_odds_history_captured_at ON odds_history(captured_at);
        CREATE INDEX IF NOT EXISTS idx_odds_history_fonbet ON odds_history(fonbet_match_id);

        CREATE TABLE IF NOT EXISTS match_feature_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            match_id INTEGER,
            fonbet_match_id TEXT,
            sport TEXT,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            match_date TEXT,
            fingerprint TEXT,
            row_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_match_feature_snapshots_match_id ON match_feature_snapshots(match_id);
        CREATE INDEX IF NOT EXISTS idx_match_feature_snapshots_captured_at ON match_feature_snapshots(captured_at);

        CREATE TABLE IF NOT EXISTS recommendation_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            source_table TEXT NOT NULL,
            source_id TEXT,
            match_id INTEGER,
            sport TEXT,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            match_date TEXT,
            market TEXT,
            odds REAL,
            stake REAL,
            ev REAL,
            result TEXT,
            profit REAL,
            fingerprint TEXT,
            row_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_recommendation_snapshots_source ON recommendation_snapshots(source_table, source_id);
        CREATE INDEX IF NOT EXISTS idx_recommendation_snapshots_match_id ON recommendation_snapshots(match_id);
        CREATE INDEX IF NOT EXISTS idx_recommendation_snapshots_captured_at ON recommendation_snapshots(captured_at);
        """
    )
    conn.commit()

def row_exists_recent(conn: sqlite3.Connection, table: str, fingerprint: str, minutes: int = 15) -> bool:
    row = conn.execute(
        f"""SELECT 1
            FROM {table}
            WHERE fingerprint = ?
              AND captured_at >= DATETIME('now', ?)
            LIMIT 1""",
        (fingerprint, f"-{minutes} minutes"),
    ).fetchone()
    return row is not None

def snapshot_matches(conn: sqlite3.Connection, verbose: bool = False) -> tuple[int, int]:
    if not table_exists(conn, "matches"):
        return 0, 0

    # Ensure the odds_history table has the totals columns
    if table_exists(conn, "odds_history"):
        cols = get_columns(conn, "odds_history")
        required_cols = {
            "odds_over_2_5": "REAL", 
            "odds_under_2_5": "REAL",
            "odds_over_3_5": "REAL", 
            "odds_under_3_5": "REAL"
        }
        for col, col_type in required_cols.items():
            if col not in cols:
                try:
                    conn.execute(f"ALTER TABLE odds_history ADD COLUMN {col} {col_type}")
                    if verbose:
                        print(f"Added column {col} to odds_history table")
                except sqlite3.OperationalError:
                    pass  # Column might have been added by another process
        conn.commit()

    cols = get_columns(conn, "matches")
    id_col = pick_col(cols, ["id"])
    sport_col = pick_col(cols, ["sport"])
    league_col = pick_col(cols, ["league", "competition", "tournament"])
    home_col = pick_col(cols, ["home_team", "home", "team_home"])
    away_col = pick_col(cols, ["away_team", "away", "team_away"])
    date_col = pick_col(cols, ["match_date", "date", "kickoff", "start_time"])
    fonbet_col = pick_col(cols, ["fonbet_match_id", "fonbet_id", "event_id", "external_id"])
    status_col = pick_col(cols, ["status"])
    home_odds_col = pick_col(cols, ["odds_home", "home_odds", "p1_odds", "odds1", "home_price"])
    draw_odds_col = pick_col(cols, ["odds_draw", "draw_odds", "x_odds", "oddsx", "draw_price"])
    away_odds_col = pick_col(cols, ["odds_away", "away_odds", "p2_odds", "odds2", "away_price"])
    over_2_5_col = pick_col(cols, ["odds_over_2_5", "over_2_5_odds", "over2.5"])
    under_2_5_col = pick_col(cols, ["odds_under_2_5", "under_2_5_odds", "under2.5"])
    over_3_5_col = pick_col(cols, ["odds_over_3_5", "over_3_5_odds", "over3.5"])
    under_3_5_col = pick_col(cols, ["odds_under_3_5", "under_3_5_odds", "under3.5"])

    query = "SELECT * FROM matches"
    if status_col:
        query += f" WHERE {status_col} IN ('upcoming','pending','scheduled','not_started','open')"

    rows = conn.execute(query).fetchall()
    odds_inserted = 0
    feature_inserted = 0
    captured_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    for row in rows:
        data = as_dict(row)
        match_id = data.get(id_col) if id_col else None
        base = {
            "match_id": match_id,
            "fonbet_match_id": data.get(fonbet_col) if fonbet_col else None,
            "sport": data.get(sport_col) if sport_col else None,
            "league": data.get(league_col) if league_col else None,
            "home_team": data.get(home_col) if home_col else None,
            "away_team": data.get(away_col) if away_col else None,
            "match_date": data.get(date_col) if date_col else None,
            "row_json": json_dumps(data),
        }

        odds_payload = {
            **base,
            "odds_home": data.get(home_odds_col) if home_odds_col else None,
            "odds_draw": data.get(draw_odds_col) if draw_odds_col else None,
            "odds_away": data.get(away_odds_col) if away_odds_col else None,
            "odds_over_2_5": data.get(over_2_5_col) if over_2_5_col else None,
            "odds_under_2_5": data.get(under_2_5_col) if under_2_5_col else None,
            "odds_over_3_5": data.get(over_3_5_col) if over_3_5_col else None,
            "odds_under_3_5": data.get(under_3_5_col) if under_3_5_col else None,
        }
        odds_fp = fingerprint_for(odds_payload)
        if not row_exists_recent(conn, "odds_history", odds_fp, minutes=15):
            conn.execute(
                """INSERT INTO odds_history (
                       captured_at, match_id, fonbet_match_id, sport, league,
                       home_team, away_team, match_date,
                       odds_home, odds_draw, odds_away,
                       odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5,
                       fingerprint, row_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    captured_at,
                    odds_payload["match_id"],
                    odds_payload["fonbet_match_id"],
                    odds_payload["sport"],
                    odds_payload["league"],
                    odds_payload["home_team"],
                    odds_payload["away_team"],
                    odds_payload["match_date"],
                    odds_payload["odds_home"],
                    odds_payload["odds_draw"],
                    odds_payload["odds_away"],
                    odds_payload["odds_over_2_5"],
                    odds_payload["odds_under_2_5"],
                    odds_payload["odds_over_3_5"],
                    odds_payload["odds_under_3_5"],
                    odds_fp,
                    odds_payload["row_json"],
                ),
            )
            odds_inserted += 1

        feat_fp = fingerprint_for(base)
        if not row_exists_recent(conn, "match_feature_snapshots", feat_fp, minutes=15):
            conn.execute(
                """INSERT INTO match_feature_snapshots (
                       captured_at, match_id, fonbet_match_id, sport, league,
                       home_team, away_team, match_date, fingerprint, row_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    captured_at,
                    base["match_id"],
                    base["fonbet_match_id"],
                    base["sport"],
                    base["league"],
                    base["home_team"],
                    base["away_team"],
                    base["match_date"],
                    feat_fp,
                    base["row_json"],
                ),
            )
            feature_inserted += 1

    conn.commit()
    if verbose:
        print(f"[matches] odds_history inserted: {odds_inserted}")
        print(f"[matches] feature_snapshots inserted: {feature_inserted}")
    return odds_inserted, feature_inserted

def enrich_with_match_meta(conn: sqlite3.Connection, match_id: Any) -> Dict[str, Any]:
    meta = {"sport": None, "league": None, "home_team": None, "away_team": None, "match_date": None}
    if not match_id or not table_exists(conn, "matches"):
        return meta
    cols = get_columns(conn, "matches")
    id_col = pick_col(cols, ["id"])
    sport_col = pick_col(cols, ["sport"])
    league_col = pick_col(cols, ["league", "competition", "tournament"])
    home_col = pick_col(cols, ["home_team", "home", "team_home"])
    away_col = pick_col(cols, ["away_team", "away", "team_away"])
    date_col = pick_col(cols, ["match_date", "date", "kickoff", "start_time"])
    if not id_col:
        return meta
    row = conn.execute(f"SELECT * FROM matches WHERE {id_col} = ? LIMIT 1", (match_id,)).fetchone()
    if not row:
        return meta
    data = as_dict(row)
    meta["sport"] = data.get(sport_col) if sport_col else None
    meta["league"] = data.get(league_col) if league_col else None
    meta["home_team"] = data.get(home_col) if home_col else None
    meta["away_team"] = data.get(away_col) if away_col else None
    meta["match_date"] = data.get(date_col) if date_col else None
    return meta

def snapshot_table_recommendations(conn: sqlite3.Connection, source_table: str, verbose: bool = False) -> int:
    if not table_exists(conn, source_table):
        return 0
    cols = get_columns(conn, source_table)
    source_id_col = pick_col(cols, ["id", "rowid"])
    match_id_col = pick_col(cols, ["match_id"])
    market_col = pick_col(cols, ["market", "pick", "selection", "final_market", "new_market"])
    odds_col = pick_col(cols, ["odds", "price"])
    stake_col = pick_col(cols, ["stake", "recommended_stake", "amount"])
    ev_col = pick_col(cols, ["ev", "edge", "expected_value"])
    result_col = pick_col(cols, ["result", "status", "final_result"])
    profit_col = pick_col(cols, ["profit", "pnl"])

    rows = conn.execute(f"SELECT * FROM {source_table} ORDER BY ROWID DESC LIMIT 500").fetchall()
    inserted = 0
    now_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    for row in rows:
        data = as_dict(row)
        match_id = data.get(match_id_col) if match_id_col else None
        meta = enrich_with_match_meta(conn, match_id)
        payload = {
            "source_table": source_table,
            "source_id": str(data.get(source_id_col)) if source_id_col else None,
            "match_id": match_id,
            "sport": meta["sport"],
            "league": meta["league"],
            "home_team": meta["home_team"],
            "away_team": meta["away_team"],
            "match_date": meta["match_date"],
            "market": data.get(market_col) if market_col else None,
            "odds": data.get(odds_col) if odds_col else None,
            "stake": data.get(stake_col) if stake_col else None,
            "ev": data.get(ev_col) if ev_col else None,
            "result": data.get(result_col) if result_col else None,
            "profit": data.get(profit_col) if profit_col else None,
            "row_json": json_dumps(data),
        }
        fp = fingerprint_for(payload)
        if row_exists_recent(conn, "recommendation_snapshots", fp, minutes=15):
            continue
        conn.execute(
            """INSERT INTO recommendation_snapshots (
                   captured_at, source_table, source_id, match_id, sport, league,
                   home_team, away_team, match_date,
                   market, odds, stake, ev, result, profit,
                   fingerprint, row_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_ts,
                payload["source_table"],
                payload["source_id"],
                payload["match_id"],
                payload["sport"],
                payload["league"],
                payload["home_team"],
                payload["away_team"],
                payload["match_date"],
                payload["market"],
                payload["odds"],
                payload["stake"],
                payload["ev"],
                payload["result"],
                payload["profit"],
                fp,
                payload["row_json"],
            ),
        )
        inserted += 1

    conn.commit()
    if verbose:
        print(f"[{source_table}] recommendation_snapshots inserted: {inserted}")
    return inserted

def main() -> int:
    parser = argparse.ArgumentParser(description="BETAGENT historical archive")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--snapshot", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return 1

    conn = get_conn()

    if args.init or not (args.init or args.snapshot):
        create_tables(conn)
        print("OK: historical tables ready")
        
        # Ensure matches table has totals columns if it exists
        if table_exists(conn, "matches"):
            cols = get_columns(conn, "matches")
            required_cols = {
                "odds_over_2_5": "REAL", 
                "odds_under_2_5": "REAL",
                "odds_over_3_5": "REAL", 
                "odds_under_3_5": "REAL"
            }
            for col, col_type in required_cols.items():
                if col not in cols:
                    try:
                        conn.execute(f"ALTER TABLE matches ADD COLUMN {col} {col_type}")
                        if args.verbose:
                            print(f"Added column {col} to matches table")
                    except sqlite3.OperationalError:
                        pass  # Column might have been added by another process
            conn.commit()

    if args.snapshot or not (args.init or args.snapshot):
        odds_n, features_n = snapshot_matches(conn, verbose=args.verbose)
        rec_n = 0
        for table in ("bets", "shadow_recommendations", "agent_recommendations", "recommendations"):
            rec_n += snapshot_table_recommendations(conn, table, verbose=args.verbose)
        print("SNAPSHOT DONE")
        print(f"  odds_history inserted: {odds_n}")
        print(f"  feature_snapshots inserted: {features_n}")
        print(f"  recommendation_snapshots inserted: {rec_n}")

    conn.close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
