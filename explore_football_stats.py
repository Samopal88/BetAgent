#!/usr/bin/env python3
"""
Explore the backtest_football_stats table to find target league names,
then run the corners/yellow cards/cards analysis.
"""

import sqlite3
import json
from collections import defaultdict

DB = "/root/betagent/betagent.db"
conn = sqlite3.connect(DB)

# Identify target leagues in backtest_football_stats
# Based on backtest_matches, the short league keys are:
# BL1 -> Bundesliga, SA -> Serie A, PD -> La Liga, FL1 -> Ligue 1, EPL -> Premier League, RPL -> RPL
# But in backtest_football_stats the names are in Russian with "Футбол." prefix

# Let's find the main league names (with large counts, 2021-2026 range)
rows = conn.execute("""
    SELECT league, COUNT(*) as n, MIN(match_date), MAX(match_date)
    FROM backtest_football_stats
    WHERE corners_line IS NOT NULL
    GROUP BY league
    HAVING n >= 50
    ORDER BY n DESC
""").fetchall()

print("TARGET LEAGUES (corners data available):")
for r in rows:
    print(f"  {r[0]} | n={r[1]}")

conn.close()
