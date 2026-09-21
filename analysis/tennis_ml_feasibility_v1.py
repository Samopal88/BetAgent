#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TENNIS ML FEASIBILITY — DATA SURVEY SCRIPT

This is a sandbox exploration tool.
Does NOT modify any production files, rules, or backtest configs.

Usage:
  python analysis/tennis_ml_feasibility_v1.py
"""
import sqlite3, json, os
from pathlib import Path
from datetime import datetime

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def survey():
    conn = get_conn()
    report = []

    def section(title):
        report.append(f"\n{'='*60}")
        report.append(f"  {title}")
        report.append(f"{'='*60}")

    def tbl(title, query):
        report.append(f"\n--- {title} ---")
        rows = conn.execute(query).fetchall()
        for r in rows:
            report.append("  " + " | ".join(str(v) for v in r))

    # ============================================================
    section("1. DATABASE TABLES")
    # ============================================================
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%tennis%' ORDER BY name"
    ).fetchall()
    for t in tables:
        name = t[0]
        cnt = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        report.append(f"  {name}: {cnt} rows")

    # ============================================================
    section("2. backtest_tennis_matches — MAIN DATASET")
    # ============================================================
    tbl("Schema", "SELECT sql FROM sqlite_master WHERE name='backtest_tennis_matches'")

    tbl("Total / Date Range", """
        SELECT COUNT(*), MIN(match_date), MAX(match_date)
        FROM backtest_tennis_matches
    """)

    tbl("By Year", """
        SELECT substr(match_date,1,4) as yr, COUNT(*)
        FROM backtest_tennis_matches GROUP BY yr ORDER BY yr
    """)

    tbl("By Tour / Level / Surface", """
        SELECT tour, level, surface, COUNT(*)
        FROM backtest_tennis_matches
        GROUP BY tour, level, surface ORDER BY tour, level, surface
    """)

    tbl("NULL counts per column", """
        SELECT
            COUNT(*) as total,
            COUNT(*) - COUNT(odds_p1) as p1_nulls,
            COUNT(*) - COUNT(odds_p2) as p2_nulls,
            COUNT(*) - COUNT(odds_total_over) as total_nulls,
            COUNT(*) - COUNT(odds_handicap_p1) as hcp_nulls,
            COUNT(*) - COUNT(surface) as surf_nulls,
            COUNT(*) - COUNT(total_line) as tline_nulls
        FROM backtest_tennis_matches
    """)

    tbl("Odds distribution (match winner)", """
        SELECT MIN(odds_p1), MAX(odds_p1), ROUND(AVG(odds_p1),2),
               MIN(odds_p2), MAX(odds_p2), ROUND(AVG(odds_p2),2)
        FROM backtest_tennis_matches
        WHERE odds_p1 IS NOT NULL
    """)

    tbl("Total games lines", """
        SELECT total_line, COUNT(*) as cnt
        FROM backtest_tennis_matches WHERE total_line IS NOT NULL
        GROUP BY total_line ORDER BY cnt DESC LIMIT 10
    """)

    tbl("Handicap lines", """
        SELECT handicap_line, COUNT(*) as cnt
        FROM backtest_tennis_matches WHERE handicap_line IS NOT NULL
        GROUP BY handicap_line ORDER BY cnt DESC LIMIT 10
    """)

    tbl("Score outcomes", """
        SELECT sets_winner, sets_loser, COUNT(*)
        FROM backtest_tennis_matches
        GROUP BY sets_winner, sets_loser ORDER BY sets_winner, sets_loser
    """)

    tbl("Tiebreak flag", """
        SELECT tiebreak, COUNT(*) FROM backtest_tennis_matches GROUP BY tiebreak
    """)

    tbl("Unique players", """
        SELECT COUNT(DISTINCT player1) as p1_unique,
               COUNT(DISTINCT player2) as p2_unique
        FROM backtest_tennis_matches
    """)

    # ============================================================
    section("3. backtest_tennis_players — PLAYER STATS")
    # ============================================================
    tbl("Schema", "SELECT sql FROM sqlite_master WHERE name='backtest_tennis_players'")

    tbl("Coverage", """
        SELECT COUNT(*),
               COUNT(w_ace) as ace_filled,
               COUNT(w_1stIn) as serve_filled,
               COUNT(winner_rank) as rank_filled,
               COUNT(minutes) as minutes_filled
        FROM backtest_tennis_players
    """)

    tbl("By Year", """
        SELECT year, COUNT(*) FROM backtest_tennis_players GROUP BY year ORDER BY year
    """)

    tbl("By Surface", """
        SELECT surface, COUNT(*) FROM backtest_tennis_players GROUP BY surface
    """)

    tbl("By Level", """
        SELECT tourney_level, COUNT(*) FROM backtest_tennis_players GROUP BY tourney_level
    """)

    # ============================================================
    section("4. tennis_data_odds — SECONDARY ODDS SOURCE")
    # ============================================================
    tbl("Schema", "SELECT sql FROM sqlite_master WHERE name='tennis_data_odds'")
    tbl("Count / Years", """
        SELECT year, COUNT(*) FROM tennis_data_odds GROUP BY year ORDER BY year
    """)
    tbl("Surfaces", """
        SELECT surface, COUNT(*) FROM tennis_data_odds GROUP BY surface
    """)

    # ============================================================
    section("5. NAME MAPPING")
    # ============================================================
    tbl("tennis_name_lookup", """
        SELECT COUNT(*) FROM tennis_name_lookup
    """)
    tbl("tennis_player_mapping", """
        SELECT COUNT(*), ROUND(AVG(confidence),1) as avg_conf
        FROM tennis_player_mapping
    """)
    tbl("tennis_player_mapping_review", """
        SELECT COUNT(*) FROM tennis_player_mapping_review
    """)

    # ============================================================
    section("6. MARKET FEASIBILITY SUMMARY")
    # ============================================================
    mw = conn.execute(
        "SELECT COUNT(*) FROM backtest_tennis_matches WHERE odds_p1 IS NOT NULL AND odds_p2 IS NOT NULL"
    ).fetchone()[0]
    tg = conn.execute(
        "SELECT COUNT(*) FROM backtest_tennis_matches WHERE odds_total_over IS NOT NULL"
    ).fetchone()[0]
    hc = conn.execute(
        "SELECT COUNT(*) FROM backtest_tennis_matches WHERE odds_handicap_p1 IS NOT NULL"
    ).fetchone()[0]
    both = conn.execute(
        "SELECT COUNT(*) FROM backtest_tennis_matches WHERE odds_total_over IS NOT NULL AND odds_handicap_p1 IS NOT NULL"
    ).fetchone()[0]

    report.append(f"  Match Winner (odds_p1/p2): {mw} matches ({mw/26686*100:.1f}%)")
    report.append(f"  Total Games (over/under):  {tg} matches ({tg/26686*100:.1f}%)")
    report.append(f"  Handicap:                  {hc} matches ({hc/26686*100:.1f}%)")
    report.append(f"  Both total+handicap:       {both} matches ({both/26686*100:.1f}%)")

    # ============================================================
    section("7. FEATURE AVAILABILITY FOR ML")
    # ============================================================
    report.append("  Features available in backtest_tennis_matches:")
    report.append("    - tour (ATP/WTA)")
    report.append("    - level (250/500/1000)")
    report.append("    - surface (hard/clay/grass/empty)")
    report.append("    - match_date")
    report.append("    - player1, player2 (Russian names)")
    report.append("    - sets_winner, sets_loser (score)")
    report.append("    - tiebreak flag")
    report.append("    - odds_p1, odds_p2 (match winner)")
    report.append("    - odds_total_over/under, total_line (total games)")
    report.append("    - odds_handicap_p1/p2, handicap_line (handicap)")
    report.append("")
    report.append("  Features available in backtest_tennis_players (joinable):")
    report.append("    - winner_rank, loser_rank")
    report.append("    - w_ace, l_ace, w_df, l_df")
    report.append("    - w_1stIn, w_1stWon, w_2ndWon (serve stats)")
    report.append("    - w_bpSaved, w_bpFaced (break points)")
    report.append("    - minutes (match duration)")
    report.append("    - best_of (3 or 5 sets)")
    report.append("    - tourney_level (A/M/G etc.)")
    report.append("")
    report.append("  Features NOT available:")
    report.append("    - Player ranking history / rolling form")
    report.append("    - H2H history between players")
    report.append("    - Recent match results for each player")
    report.append("    - Weather / indoor-outdoor")
    report.append("    - Rest days between matches")
    report.append("    - Injury / retirement flags")
    report.append("    - Set-by-set scores (only final score_detail)")

    conn.close()

    # Print to console
    for line in report:
        print(line)

    # Save as JSON for the report generator
    with open("analysis/tennis_ml_feasibility_data.json", "w") as f:
        json.dump({"survey_lines": report}, f, ensure_ascii=False, indent=2)

    print(f"\nSurvey saved to analysis/tennis_ml_feasibility_data.json")


if __name__ == "__main__":
    survey()
