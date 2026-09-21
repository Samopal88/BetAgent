#!/usr/bin/env python3
"""
save_backtest_equity.py — строит точную equity кривую по реальным матчам.
Запускать вручную при добавлении новых стратегий.
"""
import sqlite3, os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("BETAGENT_DB", str(BASE_DIR / "betagent.db"))

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_equity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sport TEXT,
            strategy TEXT,
            match_date TEXT,
            home_team TEXT,
            away_team TEXT,
            market TEXT,
            odds REAL,
            stake REAL,
            profit REAL,
            result TEXT,
            hit INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_beq_run ON backtest_equity(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_beq_strategy ON backtest_equity(strategy, match_date)")
    conn.commit()

# ══════════════════════════════════════════════
# Определения стратегий — SQL WHERE + параметры
# ══════════════════════════════════════════════
FOOTBALL_STRATEGIES = [
    {
        "name": "SA_AWAY_DRAW",
        "sport": "football",
        "market": "draw",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_draw AS odds,
                   CASE WHEN home_score = away_score THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score = away_score THEN odds_draw - 1 ELSE -1.0 END AS profit_units
            FROM backtest_matches
            WHERE league = 'SA'
              AND home_score IS NOT NULL
              AND away_team IN ('Empoli','Genoa','Cremonese','Salernitana','Venezia')
              AND (odds_draw BETWEEN 3.0 AND 3.15 OR odds_draw BETWEEN 3.45 AND 4.6)
              AND odds_under_2_5 <= 2.0
            ORDER BY match_date
        """,
    },
    {
        "name": "DRAW_SA",
        "sport": "football",
        "market": "draw",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_draw AS odds,
                   CASE WHEN home_score = away_score THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score = away_score THEN odds_draw - 1 ELSE -1.0 END AS profit_units
            FROM backtest_matches
            WHERE league = 'SA'
              AND home_score IS NOT NULL
              AND odds_draw BETWEEN 3.0 AND 3.85
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
            ORDER BY match_date
        """,
    },
    {
        "name": "BTTS_YES_CORE_EPL",
        "sport": "football",
        "market": "btts_yes",
        "stake": 750,
        "sql": """
            SELECT match_date, home_team, away_team, odds_btts_yes AS odds,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN odds_btts_yes - 1 ELSE -1.0 END AS profit_units
            FROM backtest_matches
            WHERE league = 'EPL'
              AND home_score IS NOT NULL
              AND odds_btts_yes BETWEEN 1.85 AND 2.15
            ORDER BY match_date
        """,
    },
    {
        "name": "BTTS_YES_CORE_BL1",
        "sport": "football",
        "market": "btts_yes",
        "stake": 750,
        "sql": """
            SELECT match_date, home_team, away_team, odds_btts_yes AS odds,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN odds_btts_yes - 1 ELSE -1.0 END AS profit_units
            FROM backtest_matches
            WHERE league = 'BL1'
              AND home_score IS NOT NULL
              AND odds_btts_yes BETWEEN 1.85 AND 2.15
            ORDER BY match_date
        """,
    },
    {
        "name": "FL1_BTTS_DOUBLE",
        "sport": "football",
        "market": "btts_yes",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_btts_yes AS odds,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN odds_btts_yes - 1 ELSE -1.0 END AS profit_units
            FROM backtest_matches
            WHERE league = 'LIGUE_1'
              AND home_score IS NOT NULL
              AND odds_btts_yes BETWEEN 2.0 AND 2.1
              AND odds_over_2_5 BETWEEN 1.6 AND 1.9
            ORDER BY match_date
        """,
    },
    {
        "name": "PD_BTTS_DOUBLE",
        "sport": "football",
        "market": "btts_yes",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_btts_yes AS odds,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN odds_btts_yes - 1 ELSE -1.0 END AS profit_units
            FROM backtest_matches
            WHERE league = 'PD'
              AND home_score IS NOT NULL
              AND odds_btts_yes BETWEEN 1.75 AND 2.0
              AND odds_over_2_5 BETWEEN 1.55 AND 1.85
            ORDER BY match_date
        """,
    },
    {
        "name": "RPL_OVER25_BTTS",
        "sport": "football",
        "market": "btts_yes",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_btts_yes AS odds,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score > 0 AND away_score > 0 THEN odds_btts_yes - 1 ELSE -1.0 END AS profit_units
            FROM backtest_matches
            WHERE league = 'RPL'
              AND home_score IS NOT NULL
              AND odds_btts_yes BETWEEN 1.85 AND 2.1
              AND odds_over_2_5 BETWEEN 1.75 AND 2.05
            ORDER BY match_date
        """,
    },
    {
        "name": "DRAW_BALANCED_LINE_SA",
        "sport": "football",
        "market": "draw",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_draw AS odds,
                   CASE WHEN home_score = away_score THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score = away_score THEN odds_draw - 1 ELSE -1.0 END AS profit_units
            FROM backtest_matches
            WHERE league = 'SA'
              AND home_score IS NOT NULL
              AND odds_draw BETWEEN 3.05 AND 3.65
              AND ABS(odds_home - odds_away) <= 0.95
              AND MIN(odds_home, odds_away) >= 2.0
            ORDER BY match_date
        """,
    },
]

HOCKEY_STRATEGIES = [
    {
        "name": "NHL_DRAW_TIGHT",
        "sport": "hockey",
        "market": "draw",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_draw AS odds,
                   CASE WHEN went_ot_or_so = 1 THEN 1 ELSE 0 END AS hit,
                   CASE WHEN went_ot_or_so = 1 THEN odds_draw - 1 ELSE -1.0 END AS profit_units
            FROM backtest_hockey_matches
            WHERE league LIKE '%НХЛ%' OR league LIKE '%NHL%'
              AND home_score IS NOT NULL
              AND odds_draw BETWEEN 3.8 AND 4.8
            ORDER BY match_date
        """,
    },
    {
        "name": "NLA_BERN_AWAY_DRAW",
        "sport": "hockey",
        "market": "draw",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_draw AS odds,
                   CASE WHEN went_ot_or_so = 1 THEN 1 ELSE 0 END AS hit,
                   CASE WHEN went_ot_or_so = 1 THEN odds_draw - 1 ELSE -1.0 END AS profit_units
            FROM backtest_hockey_matches
            WHERE league = 'Хоккей. Швейцария. National League.'
              AND away_team = 'Берн'
              AND home_score IS NOT NULL
              AND odds_draw BETWEEN 4.0 AND 5.2
              AND (league NOT LIKE '%плей%' AND league NOT LIKE '%финал%')
            ORDER BY match_date
        """,
    },
    {
        "name": "KHL_UNDERDOG_DEF",
        "sport": "hockey",
        "market": "away",
        "stake": 1250,
        "sql": """
            SELECT match_date, home_team, away_team, odds_away AS odds,
                   CASE WHEN away_score > home_score THEN 1 ELSE 0 END AS hit,
                   CASE WHEN away_score > home_score THEN odds_away - 1 ELSE -1.0 END AS profit_units
            FROM backtest_hockey_matches
            WHERE (league LIKE '%КХЛ%' OR league LIKE '%KHL%')
              AND league NOT LIKE '%плей%'
              AND home_score IS NOT NULL
              AND went_ot_or_so = 0
              AND odds_away BETWEEN 2.5 AND 4.0
            ORDER BY match_date
            LIMIT 92
        """,
    },
    {
        "name": "CZECH_HOME_FAV",
        "sport": "hockey",
        "market": "home",
        "stake": 1000,
        "sql": """
            SELECT match_date, home_team, away_team, odds_home AS odds,
                   CASE WHEN home_score > away_score THEN 1 ELSE 0 END AS hit,
                   CASE WHEN home_score > away_score THEN odds_home - 1 ELSE -1.0 END AS profit_units
            FROM backtest_hockey_matches
            WHERE (league LIKE '%Чехия%' OR league LIKE '%Czech%' OR league LIKE '%Extraliga%')
              AND league NOT LIKE '%плей%'
              AND home_score IS NOT NULL
              AND went_ot_or_so = 0
              AND odds_home BETWEEN 1.4 AND 2.0
            ORDER BY match_date
            LIMIT 82
        """,
    },
]

def process_strategy(conn, strategy, run_id, created_at):
    rows = conn.execute(strategy["sql"]).fetchall()
    stake = strategy["stake"]
    result_rows = []
    for r in rows:
        profit = round(r["profit_units"] * stake, 2)
        result_rows.append({
            "run_id": run_id,
            "created_at": created_at,
            "sport": strategy["sport"],
            "strategy": strategy["name"],
            "match_date": str(r["match_date"])[:10],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "market": strategy["market"],
            "odds": float(r["odds"]) if r["odds"] else 0,
            "stake": stake,
            "profit": profit,
            "result": "won" if r["hit"] == 1 else "lost",
            "hit": r["hit"],
        })
    return result_rows

def main():
    conn = get_conn()
    ensure_schema(conn)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{created_at}] run_id={run_id}\n")

    # Удаляем старый прогон
    old = conn.execute("SELECT DISTINCT run_id FROM backtest_equity ORDER BY created_at DESC LIMIT 1").fetchone()
    if old:
        conn.execute("DELETE FROM backtest_equity WHERE run_id=?", (old["run_id"],))
        conn.commit()
        print(f"  Удалён старый прогон: {old['run_id']}")

    all_rows = []
    for strategy in FOOTBALL_STRATEGIES + HOCKEY_STRATEGIES:
        try:
            rows = process_strategy(conn, strategy, run_id, created_at)
            wins = sum(1 for r in rows if r["result"] == "won")
            losses = len(rows) - wins
            profit = sum(r["profit"] for r in rows)
            roi = profit / (len(rows) * strategy["stake"]) * 100 if rows else 0
            print(f"  {strategy['name']:35} n={len(rows):4} W={wins:4} L={losses:4} ROI={roi:+6.2f}% profit={profit:+9.0f}")
            all_rows.extend(rows)
        except Exception as e:
            print(f"  {strategy['name']:35} ОШИБКА: {e}")

    conn.executemany("""
        INSERT INTO backtest_equity
        (run_id, created_at, sport, strategy, match_date, home_team, away_team,
         market, odds, stake, profit, result, hit)
        VALUES
        (:run_id, :created_at, :sport, :strategy, :match_date, :home_team, :away_team,
         :market, :odds, :stake, :profit, :result, :hit)
    """, all_rows)
    conn.commit()
    conn.close()

    print(f"\n✅ Сохранено: {len(all_rows)} строк, {len(FOOTBALL_STRATEGIES)+len(HOCKEY_STRATEGIES)} стратегий")
    print(f"   run_id: {run_id}")

if __name__ == "__main__":
    main()
