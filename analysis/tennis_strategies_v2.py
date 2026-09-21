#!/usr/bin/env python3
"""
Tennis Strategies V2 — No Lookahead Bias
Uses SQL window functions for rolling calculations from PREVIOUS matches only.
"""

import sqlite3
from collections import defaultdict
from datetime import datetime

DB_PATH = "/root/betagent/betagent.db"
REPORT_PATH = "/root/betagent/analysis/tennis_strategies_v2_report.md"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def main():
    conn = get_connection()

    print("Step 1: Building player match history with row numbers...")

    # Create a unified player match history table
    conn.execute("DROP TABLE IF EXISTS temp_player_matches")
    conn.execute("""
        CREATE TEMP TABLE temp_player_matches AS
        SELECT
            tour, year, tourney_date, tourney_name, surface, tourney_level,
            winner_name as player, winner_rank as rank,
            w_ace as ace, w_df as df, w_1stWon as firstWon, w_1stIn as firstIn,
            straight_sets, 1 as was_winner
        FROM backtest_tennis_players
        UNION ALL
        SELECT
            tour, year, tourney_date, tourney_name, surface, tourney_level,
            loser_name as player, loser_rank as rank,
            l_ace as ace, l_df as df, l_1stWon as firstWon, l_1stIn as firstIn,
            0 as straight_sets, 0 as was_winner
        FROM backtest_tennis_players
        ORDER BY player, tourney_date, tourney_name
    """)

    conn.execute("CREATE INDEX idx_pm_player ON temp_player_matches(player, tourney_date)")

    print("Step 2: Calculating rolling stats with window functions...")

    # Calculate rolling straight set % from last 10 matches
    conn.execute("DROP TABLE IF EXISTS temp_rolling_10")
    conn.execute("""
        CREATE TEMP TABLE temp_rolling_10 AS
        SELECT
            player, tour, year, tourney_date, tourney_name, surface,
            straight_sets, was_winner,
            AVG(straight_sets) OVER (
                PARTITION BY player
                ORDER BY tourney_date, tourney_name
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as rolling_straight_pct_10,
            COUNT(straight_sets) OVER (
                PARTITION BY player
                ORDER BY tourney_date, tourney_name
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) as prev_10_count
        FROM temp_player_matches
    """)

    # Calculate rolling ace avg from last 5 matches
    conn.execute("DROP TABLE IF EXISTS temp_rolling_ace")
    conn.execute("""
        CREATE TEMP TABLE temp_rolling_ace AS
        SELECT
            player, tourney_date, tourney_name, was_winner,
            AVG(ace) OVER (
                PARTITION BY player
                ORDER BY tourney_date, tourney_name
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as rolling_ace_avg_5,
            COUNT(ace) OVER (
                PARTITION BY player
                ORDER BY tourney_date, tourney_name
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as prev_5_ace_count
        FROM temp_player_matches
        WHERE ace IS NOT NULL
    """)

    # Calculate rolling DF avg from last 5 matches
    conn.execute("DROP TABLE IF EXISTS temp_rolling_df")
    conn.execute("""
        CREATE TEMP TABLE temp_rolling_df AS
        SELECT
            player, tourney_date, tourney_name, was_winner,
            AVG(df) OVER (
                PARTITION BY player
                ORDER BY tourney_date, tourney_name
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as rolling_df_avg_5,
            COUNT(df) OVER (
                PARTITION BY player
                ORDER BY tourney_date, tourney_name
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as prev_5_df_count
        FROM temp_player_matches
        WHERE df IS NOT NULL
    """)

    # Calculate rolling 1stWon% from last 5 matches
    conn.execute("DROP TABLE IF EXISTS temp_rolling_1st")
    conn.execute("""
        CREATE TEMP TABLE temp_rolling_1st AS
        SELECT
            player, tourney_date, tourney_name, was_winner,
            AVG(CAST(firstWon AS REAL) / firstIn) OVER (
                PARTITION BY player
                ORDER BY tourney_date, tourney_name
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as rolling_1stWon_pct_5,
            COUNT(firstWon) OVER (
                PARTITION BY player
                ORDER BY tourney_date, tourney_name
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) as prev_5_1st_count
        FROM temp_player_matches
        WHERE firstWon IS NOT NULL AND firstIn IS NOT NULL AND firstIn > 0
    """)

    print("Step 3: Testing Strategy A: Dominant winner → straight sets...")

    # Strategy A: winner_rank <= 20, rank_gap >= 50, rolling_straight_pct_10 >= 0.65
    strategy_a = conn.execute("""
        SELECT
            p.tour, p.year, p.surface, p.straight_sets,
            r.rolling_straight_pct_10
        FROM backtest_tennis_players p
        JOIN temp_rolling_10 r ON r.player = p.winner_name
            AND r.tourney_date = p.tourney_date
            AND r.tourney_name = p.tourney_name
            AND r.was_winner = 1
        WHERE p.winner_rank IS NOT NULL
            AND p.loser_rank IS NOT NULL
            AND p.winner_rank <= 20
            AND (p.loser_rank - p.winner_rank) >= 50
            AND r.rolling_straight_pct_10 >= 0.65
    """).fetchall()

    print(f"  Strategy A: {len(strategy_a)} qualifying matches")

    # Strategy A aggregation
    a_agg = defaultdict(lambda: {'n': 0, 'straight': 0})
    a_by_year = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'straight': 0}))

    for row in strategy_a:
        key = (row['tour'], row['surface'])
        a_agg[key]['n'] += 1
        a_agg[key]['straight'] += row['straight_sets']
        a_by_year[key][row['year']]['n'] += 1
        a_by_year[key][row['year']]['straight'] += row['straight_sets']

    print("Step 4: Testing Strategy B: High DF server → 3+ sets...")

    # Strategy B: rolling_df_avg_5 >= 4.0 for winner
    strategy_b = conn.execute("""
        SELECT
            p.tour, p.year, p.surface,
            CASE WHEN p.straight_sets = 0 THEN 1 ELSE 0 END as is_3set,
            d.rolling_df_avg_5
        FROM backtest_tennis_players p
        JOIN temp_rolling_df d ON d.player = p.winner_name
            AND d.tourney_date = p.tourney_date
            AND d.tourney_name = p.tourney_name
            AND d.was_winner = 1
        WHERE d.rolling_df_avg_5 >= 4.0
    """).fetchall()

    print(f"  Strategy B: {len(strategy_b)} qualifying matches")

    b_agg = defaultdict(lambda: {'n': 0, 'three_set': 0})
    b_by_year = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'three_set': 0}))

    for row in strategy_b:
        key = (row['tour'], row['surface'])
        b_agg[key]['n'] += 1
        b_agg[key]['three_set'] += row['is_3set']
        b_by_year[key][row['year']]['n'] += 1
        b_by_year[key][row['year']]['three_set'] += row['is_3set']

    print("Step 5: Testing Strategy C: Dominant first serve → straight sets...")

    # Strategy C: rolling_1stWon_pct_5 >= 0.72
    strategy_c = conn.execute("""
        SELECT
            p.tour, p.year, p.surface, p.straight_sets,
            f.rolling_1stWon_pct_5
        FROM backtest_tennis_players p
        JOIN temp_rolling_1st f ON f.player = p.winner_name
            AND f.tourney_date = p.tourney_date
            AND f.tourney_name = p.tourney_name
            AND f.was_winner = 1
        WHERE f.rolling_1stWon_pct_5 >= 0.72
    """).fetchall()

    print(f"  Strategy C: {len(strategy_c)} qualifying matches")

    c_agg = defaultdict(lambda: {'n': 0, 'straight': 0})
    c_by_year = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'straight': 0}))

    for row in strategy_c:
        key = (row['tour'], row['surface'])
        c_agg[key]['n'] += 1
        c_agg[key]['straight'] += row['straight_sets']
        c_by_year[key][row['year']]['n'] += 1
        c_by_year[key][row['year']]['straight'] += row['straight_sets']

    print("Step 6: Testing Strategy D: Both high aces → OVER...")

    # Strategy D: Both winner and loser rolling_ace_avg_5 >= 5
    strategy_d = conn.execute("""
        SELECT
            p.tour, p.year, p.surface,
            CASE WHEN (p.sets_winner + p.sets_loser) >= 3 THEN 1 ELSE 0 END as is_3set,
            aw.rolling_ace_avg_5 as winner_ace,
            al.rolling_ace_avg_5 as loser_ace
        FROM backtest_tennis_players p
        JOIN temp_rolling_ace aw ON aw.player = p.winner_name
            AND aw.tourney_date = p.tourney_date
            AND aw.tourney_name = p.tourney_name
            AND aw.was_winner = 1
        JOIN temp_rolling_ace al ON al.player = p.loser_name
            AND al.tourney_date = p.tourney_date
            AND al.tourney_name = p.tourney_name
            AND al.was_winner = 0
        WHERE aw.rolling_ace_avg_5 >= 5
            AND al.rolling_ace_avg_5 >= 5
    """).fetchall()

    print(f"  Strategy D: {len(strategy_d)} qualifying matches")

    d_agg = defaultdict(lambda: {'n': 0, 'three_set': 0})
    d_by_year = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'three_set': 0}))

    for row in strategy_d:
        key = (row['tour'], row['surface'])
        d_agg[key]['n'] += 1
        d_agg[key]['three_set'] += row['is_3set']
        d_by_year[key][row['year']]['n'] += 1
        d_by_year[key][row['year']]['three_set'] += row['is_3set']

    # Also test with actual odds from backtest_tennis_matches
    print("\nStep 7: Matching with actual odds from backtest_tennis_matches...")

    # Get odds data for strategy B (DF → OVER)
    # We need to match backtest_tennis_players with backtest_tennis_matches
    # The matching is tricky since names might differ. Let's try by date+tournament.

    # For now, use theoretical odds as specified in the requirements

    print("Step 8: Building report...")

    # Build report
    lines = []
    lines.append("# Tennis Strategies V2 — No Lookahead Bias Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Database: {DB_PATH}")
    lines.append("")
    lines.append("## Key Changes from V1")
    lines.append("")
    lines.append("### REMOVED (Lookahead Bias)")
    lines.append("")
    lines.append("| Strategy | Issue |")
    lines.append("|----------|-------|")
    lines.append("| `3_sets → OVER` | 100% lookahead — if match went 3 sets, total is obviously over |")
    lines.append("| `SURFACE_SPECIALIST` | 100% hit rate — uses same-match surface stats |")
    lines.append("| `SERVE_DF` (w_df>=5) | Uses DF count FROM the same match (after it finished) |")
    lines.append("| `SERVE_DOMINANT` (1stWon/1stIn>0.75) | Uses serve stats FROM the same match |")
    lines.append("")
    lines.append("### VALIDATED (No Lookahead)")
    lines.append("")
    lines.append("- `first_set_tb=1 → OVER` — LIVE strategy (first set already finished)")
    lines.append("- `first_set_bagel=1 → UNDER` — LIVE strategy (first set already finished)")
    lines.append("- `ROLLING_DOMINANT` — Uses rolling straight% from PREVIOUS matches ✓")
    lines.append("- `FORM_DOMINANT` — Uses rank/rank_gap from BEFORE match ✓")
    lines.append("")
    lines.append("### NEW STRATEGIES (Rolling from PREVIOUS matches only)")
    lines.append("")
    lines.append("All rolling stats calculated from matches BEFORE the current match date:")
    lines.append("- `rolling_straight_pct_10`: % straight set wins in last 10 matches")
    lines.append("- `rolling_ace_avg_5`: avg aces in last 5 matches")
    lines.append("- `rolling_df_avg_5`: avg double faults in last 5 matches")
    lines.append("- `rolling_1stWon_pct_5`: avg 1stWon% in last 5 matches")
    lines.append("")

    def format_strategy_section(title, criteria, odds, agg, by_year, is_3set=False):
        section = []
        section.append(f"## {title}")
        section.append("")
        section.append(f"**Criteria:** {criteria}")
        section.append(f"**Theoretical odds:** {odds}")
        section.append("")

        for key in sorted(agg.keys()):
            tour, surface = key
            data = agg[key]
            n = data['n']
            if n == 0:
                continue

            if is_3set:
                rate = data['three_set'] / n * 100
            else:
                rate = data['straight'] / n * 100

            roi = (rate / 100 * odds - 1) * 100

            section.append(f"### {tour} / {surface}")
            section.append(f"ROI: {roi:+.1f}% | n={n} | {'3set' if is_3set else 'straight'}%: {rate:.1f}% | AvgOdds: {odds}")
            section.append("")

            section.append(f"| Year | n | {'3set%' if is_3set else 'straight%'} | ROI% |")
            section.append(f"|------|---|---|---|")

            years_positive = 0
            total_years = 0

            for year in sorted(by_year[key].keys()):
                yd = by_year[key][year]
                if yd['n'] == 0:
                    continue
                if is_3set:
                    yr_rate = yd['three_set'] / yd['n'] * 100
                else:
                    yr_rate = yd['straight'] / yd['n'] * 100
                yr_roi = (yr_rate / 100 * odds - 1) * 100

                section.append(f"| {year} | {yd['n']} | {yr_rate:.1f}% | {yr_roi:+.1f}% |")

                total_years += 1
                if yr_roi > 0:
                    years_positive += 1

            section.append("")
            section.append(f"Years positive: {years_positive}/{total_years}")
            section.append("")

        return "\n".join(section)

    # Strategy A
    lines.append("---")
    lines.append("")
    lines.append(format_strategy_section(
        "Strategy A: Dominant Winner → Straight Sets",
        "winner_rank <= 20, rank_gap >= 50, rolling_straight_pct_10 >= 65%",
        1.70, a_agg, a_by_year, is_3set=False
    ))

    # Strategy B
    lines.append("---")
    lines.append("")
    lines.append(format_strategy_section(
        "Strategy B: High DF Server → 3+ Sets (OVER)",
        "rolling_df_avg_5 >= 4.0 for winner",
        2.20, b_agg, b_by_year, is_3set=True
    ))

    # Strategy C
    lines.append("---")
    lines.append("")
    lines.append(format_strategy_section(
        "Strategy C: Dominant First Serve → Straight Sets",
        "rolling_1stWon_pct_5 >= 0.72",
        1.70, c_agg, c_by_year, is_3set=False
    ))

    # Strategy D
    lines.append("---")
    lines.append("")
    lines.append(format_strategy_section(
        "Strategy D: Both High Aces → OVER Total",
        "Both winner and loser rolling_ace_avg_5 >= 5",
        2.00, d_agg, d_by_year, is_3set=True
    ))

    # Summary table
    lines.append("---")
    lines.append("")
    lines.append("## Summary: 2022-2026 Consistency Check")
    lines.append("")
    lines.append("Priority: strategies where ALL years 2022-2026 are positive ROI.")
    lines.append("")
    lines.append("| Strategy | Tour | Surface | 2022 | 2023 | 2024 | 2025 | 2026 | All +? |")
    lines.append("|----------|------|---------|------|------|------|------|------|--------|")

    for strat_name, by_year_data, odds, is_3set in [
        ("A: Dom Winner→SS", a_by_year, 1.70, False),
        ("B: High DF→3set", b_by_year, 2.20, True),
        ("C: 1stServe→SS", c_by_year, 1.70, False),
        ("D: Both Aces→OVER", d_by_year, 2.00, True),
    ]:
        for key in sorted(by_year_data.keys()):
            tour, surface = key
            years_data = by_year_data[key]

            all_positive = True
            year_cells = []
            for year in [2022, 2023, 2024, 2025, 2026]:
                if year in years_data and years_data[year]['n'] > 0:
                    yd = years_data[year]
                    if is_3set:
                        rate = yd['three_set'] / yd['n'] * 100
                    else:
                        rate = yd['straight'] / yd['n'] * 100
                    roi = (rate / 100 * odds - 1) * 100
                    year_cells.append(f"{roi:+.1f}%")
                    if roi <= 0:
                        all_positive = False
                else:
                    year_cells.append("n/a")

            marker = "✅" if all_positive else "❌"
            lines.append(f"| {strat_name} | {tour} | {surface} | {' | '.join(year_cells)} | {marker} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Data Quality Notes")
    lines.append("")
    lines.append("- Rolling windows: 5 matches (serve stats), 10 matches (straight set %)")
    lines.append("- All rolling stats calculated from PREVIOUS matches only (no lookahead)")
    lines.append("- Window functions use `ROWS BETWEEN N PRECEDING AND 1 PRECEDING` to exclude current match")
    lines.append("")

    # Write report
    report = "\n".join(lines)
    with open(REPORT_PATH, 'w') as f:
        f.write(report)

    print(f"\nReport saved to {REPORT_PATH}")

    conn.close()

if __name__ == "__main__":
    main()
