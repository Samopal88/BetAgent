#!/usr/bin/env python3
"""
Build football_features_ml_v1 — unified analytical layer for ML value betting.

1 row = 1 match
Joins base odds (1X2, total, handicap, BTTS) with special markets (corners, yellow_cards).
Calculates: implied probabilities, margin, overround, odds ratios.
"""

import sqlite3
import json
from pathlib import Path

DB_PATH = "/root/betagent/betagent.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ──────────────────────────────────────────────
# 1. Drop & recreate the unified table
# ──────────────────────────────────────────────
def create_unified_table(conn):
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS football_features_ml_v1")

    cur.execute("""
    CREATE TABLE football_features_ml_v1 AS
    SELECT
        -- identifiers
        m.id                          AS match_id,
        m.source                      AS source,
        m.source_match_id             AS source_match_id,
        m.league                      AS league,
        m.season                      AS season,
        m.country                     AS country,
        m.competition                 AS competition,
        m.stage                       AS stage,
        m.match_date                  AS match_date,
        m.match_time                  AS match_time,
        m.home_team                   AS home_team,
        m.away_team                   AS away_team,
        m.home_score                  AS home_score,
        m.away_score                  AS away_score,
        m.result_raw                  AS result_raw,
        m.result_type                 AS result_type,

        -- 1X2 odds (base)
        m.odds_home                   AS odds_1x2_home,
        m.odds_draw                   AS odds_1x2_draw,
        m.odds_away                   AS odds_1x2_away,

        -- Total O/U (base)
        m.odds_total_over             AS odds_total_over,
        m.odds_total_under            AS odds_total_under,
        m.total_line                  AS total_line,

        -- Handicap (base)
        m.odds_handicap_home          AS odds_hcp_home,
        m.odds_handicap_away          AS odds_hcp_away,
        m.handicap_line_home          AS hcp_line_home,
        m.handicap_line_away          AS hcp_line_away,

        -- BTTS (base)
        m.odds_btts_yes               AS odds_btts_yes,
        m.odds_btts_no                AS odds_btts_no,

        -- Corners special market
        c_odds.odds_home              AS odds_corners_home,
        c_odds.odds_draw              AS odds_corners_draw,
        c_odds.odds_away              AS odds_corners_away,
        c_odds.odds_total_over        AS odds_corners_over,
        c_odds.odds_total_under       AS odds_corners_under,
        c_odds.total_line             AS corners_total_line,
        c_odds.odds_handicap_home     AS odds_corners_hcp_home,
        c_odds.odds_handicap_away     AS odds_corners_hcp_away,
        c_odds.handicap_line_home     AS corners_hcp_line,

        -- Yellow cards special market
        y_odds.odds_home              AS odds_yc_home,
        y_odds.odds_draw              AS odds_yc_draw,
        y_odds.odds_away              AS odds_yc_away,
        y_odds.odds_total_over        AS odds_yc_over,
        y_odds.odds_total_under       AS odds_yc_under,
        y_odds.total_line             AS yc_total_line,
        y_odds.odds_handicap_home     AS odds_yc_hcp_home,
        y_odds.odds_handicap_away     AS odds_yc_hcp_away,
        y_odds.handicap_line_home     AS yc_hcp_line,

        -- flags: which markets are present
        CASE WHEN m.odds_home IS NOT NULL THEN 1 ELSE 0 END AS has_1x2,
        CASE WHEN m.odds_total_over IS NOT NULL THEN 1 ELSE 0 END AS has_total,
        CASE WHEN m.odds_handicap_home IS NOT NULL AND m.odds_handicap_home != 0 THEN 1 ELSE 0 END AS has_handicap,
        CASE WHEN m.odds_btts_yes IS NOT NULL THEN 1 ELSE 0 END AS has_btts,
        CASE WHEN c_odds.source_match_id IS NOT NULL THEN 1 ELSE 0 END AS has_corners,
        CASE WHEN y_odds.source_match_id IS NOT NULL THEN 1 ELSE 0 END AS has_yellow_cards

    FROM backtest_football_matches_betz m

    -- LEFT JOIN corners (pick first available per base_match_id)
    LEFT JOIN (
        SELECT base_match_id,
               odds_home, odds_draw, odds_away,
               odds_total_over, odds_total_under, total_line,
               odds_handicap_home, odds_handicap_away, handicap_line_home,
               source_match_id
        FROM backtest_football_special_markets_betz
        WHERE market_type = 'corners'
        GROUP BY base_match_id
    ) c_odds ON c_odds.base_match_id = CAST(m.source_match_id AS TEXT)

    -- LEFT JOIN yellow_cards (pick first available per base_match_id)
    LEFT JOIN (
        SELECT base_match_id,
               odds_home, odds_draw, odds_away,
               odds_total_over, odds_total_under, total_line,
               odds_handicap_home, odds_handicap_away, handicap_line_home,
               source_match_id
        FROM backtest_football_special_markets_betz
        WHERE market_type = 'yellow_cards'
        GROUP BY base_match_id
    ) y_odds ON y_odds.base_match_id = CAST(m.source_match_id AS TEXT)
    """)

    conn.commit()
    print("[OK] football_features_ml_v1 created")


# ──────────────────────────────────────────────
# 2. Add derived feature columns
# ──────────────────────────────────────────────
def add_derived_features(conn):
    cur = conn.cursor()

    # --- 1X2 implied probabilities & margin ---
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_1x2_home REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_1x2_draw REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_1x2_away REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN margin_1x2 REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN overround_1x2 REAL
    """)

    # --- Total implied probs & margin ---
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_total_over REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_total_under REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN margin_total REAL
    """)

    # --- BTTS implied probs & margin ---
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_btts_yes REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_btts_no REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN margin_btts REAL
    """)

    # --- Corners implied probs & margin ---
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_corners_home REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_corners_draw REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_corners_away REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN margin_corners_1x2 REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_corners_over REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_corners_under REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN margin_corners_total REAL
    """)

    # --- Yellow cards implied probs & margin ---
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_yc_home REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_yc_draw REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_yc_away REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN margin_yc_1x2 REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_yc_over REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN prob_yc_under REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN margin_yc_total REAL
    """)

    # --- Odds ratios (cross-market) ---
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN odds_ratio_home_vs_corners REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN odds_ratio_away_vs_corners REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN odds_ratio_home_vs_yc REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN odds_ratio_away_vs_yc REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN odds_ratio_total_vs_corners REAL
    """)
    cur.execute("""
    ALTER TABLE football_features_ml_v1
    ADD COLUMN odds_ratio_total_vs_yc REAL
    """)

    conn.commit()

    # --- Populate all derived values ---
    cur.execute("""
    UPDATE football_features_ml_v1
    SET
        -- 1X2 implied probabilities (fair = 1/odds)
        prob_1x2_home  = CASE WHEN odds_1x2_home  > 0 THEN ROUND(1.0 / odds_1x2_home, 6)  END,
        prob_1x2_draw  = CASE WHEN odds_1x2_draw  > 0 THEN ROUND(1.0 / odds_1x2_draw, 6)  END,
        prob_1x2_away  = CASE WHEN odds_1x2_away  > 0 THEN ROUND(1.0 / odds_1x2_away, 6)  END,

        -- 1X2 margin = sum(implied) - 1
        margin_1x2 = CASE
            WHEN odds_1x2_home > 0 AND odds_1x2_draw > 0 AND odds_1x2_away > 0
            THEN ROUND((1.0/odds_1x2_home + 1.0/odds_1x2_draw + 1.0/odds_1x2_away) - 1.0, 6)
        END,

        -- 1X2 overround = sum(implied)
        overround_1x2 = CASE
            WHEN odds_1x2_home > 0 AND odds_1x2_draw > 0 AND odds_1x2_away > 0
            THEN ROUND(1.0/odds_1x2_home + 1.0/odds_1x2_draw + 1.0/odds_1x2_away, 6)
        END,

        -- Total O/U implied probs
        prob_total_over  = CASE WHEN odds_total_over  > 0 THEN ROUND(1.0 / odds_total_over, 6)  END,
        prob_total_under = CASE WHEN odds_total_under > 0 THEN ROUND(1.0 / odds_total_under, 6) END,

        -- Total margin
        margin_total = CASE
            WHEN odds_total_over > 0 AND odds_total_under > 0
            THEN ROUND((1.0/odds_total_over + 1.0/odds_total_under) - 1.0, 6)
        END,

        -- BTTS implied probs
        prob_btts_yes = CASE WHEN odds_btts_yes > 0 THEN ROUND(1.0 / odds_btts_yes, 6) END,
        prob_btts_no  = CASE WHEN odds_btts_no  > 0 THEN ROUND(1.0 / odds_btts_no, 6)  END,

        -- BTTS margin
        margin_btts = CASE
            WHEN odds_btts_yes > 0 AND odds_btts_no > 0
            THEN ROUND((1.0/odds_btts_yes + 1.0/odds_btts_no) - 1.0, 6)
        END,

        -- Corners 1X2 implied probs
        prob_corners_home = CASE WHEN odds_corners_home > 0 THEN ROUND(1.0 / odds_corners_home, 6) END,
        prob_corners_draw = CASE WHEN odds_corners_draw > 0 THEN ROUND(1.0 / odds_corners_draw, 6) END,
        prob_corners_away = CASE WHEN odds_corners_away > 0 THEN ROUND(1.0 / odds_corners_away, 6) END,

        -- Corners 1X2 margin
        margin_corners_1x2 = CASE
            WHEN odds_corners_home > 0 AND odds_corners_draw > 0 AND odds_corners_away > 0
            THEN ROUND((1.0/odds_corners_home + 1.0/odds_corners_draw + 1.0/odds_corners_away) - 1.0, 6)
        END,

        -- Corners total implied probs
        prob_corners_over  = CASE WHEN odds_corners_over  > 0 THEN ROUND(1.0 / odds_corners_over, 6)  END,
        prob_corners_under = CASE WHEN odds_corners_under > 0 THEN ROUND(1.0 / odds_corners_under, 6) END,

        -- Corners total margin
        margin_corners_total = CASE
            WHEN odds_corners_over > 0 AND odds_corners_under > 0
            THEN ROUND((1.0/odds_corners_over + 1.0/odds_corners_under) - 1.0, 6)
        END,

        -- Yellow cards 1X2 implied probs
        prob_yc_home = CASE WHEN odds_yc_home > 0 THEN ROUND(1.0 / odds_yc_home, 6) END,
        prob_yc_draw = CASE WHEN odds_yc_draw > 0 THEN ROUND(1.0 / odds_yc_draw, 6) END,
        prob_yc_away = CASE WHEN odds_yc_away > 0 THEN ROUND(1.0 / odds_yc_away, 6) END,

        -- Yellow cards 1X2 margin
        margin_yc_1x2 = CASE
            WHEN odds_yc_home > 0 AND odds_yc_draw > 0 AND odds_yc_away > 0
            THEN ROUND((1.0/odds_yc_home + 1.0/odds_yc_draw + 1.0/odds_yc_away) - 1.0, 6)
        END,

        -- Yellow cards total implied probs
        prob_yc_over  = CASE WHEN odds_yc_over  > 0 THEN ROUND(1.0 / odds_yc_over, 6)  END,
        prob_yc_under = CASE WHEN odds_yc_under > 0 THEN ROUND(1.0 / odds_yc_under, 6) END,

        -- Yellow cards total margin
        margin_yc_total = CASE
            WHEN odds_yc_over > 0 AND odds_yc_under > 0
            THEN ROUND((1.0/odds_yc_over + 1.0/odds_yc_under) - 1.0, 6)
        END,

        -- Odds ratios: base vs corners 1X2
        odds_ratio_home_vs_corners = CASE
            WHEN odds_1x2_home > 0 AND odds_corners_home > 0
            THEN ROUND(odds_1x2_home * 1.0 / odds_corners_home, 4)
        END,
        odds_ratio_away_vs_corners = CASE
            WHEN odds_1x2_away > 0 AND odds_corners_away > 0
            THEN ROUND(odds_1x2_away * 1.0 / odds_corners_away, 4)
        END,

        -- Odds ratios: base vs yellow cards 1X2
        odds_ratio_home_vs_yc = CASE
            WHEN odds_1x2_home > 0 AND odds_yc_home > 0
            THEN ROUND(odds_1x2_home * 1.0 / odds_yc_home, 4)
        END,
        odds_ratio_away_vs_yc = CASE
            WHEN odds_1x2_away > 0 AND odds_yc_away > 0
            THEN ROUND(odds_1x2_away * 1.0 / odds_yc_away, 4)
        END,

        -- Odds ratios: total lines
        odds_ratio_total_vs_corners = CASE
            WHEN odds_total_over > 0 AND odds_corners_over > 0
            THEN ROUND(odds_total_over * 1.0 / odds_corners_over, 4)
        END,
        odds_ratio_total_vs_yc = CASE
            WHEN odds_total_over > 0 AND odds_yc_over > 0
            THEN ROUND(odds_total_over * 1.0 / odds_yc_over, 4)
        END
    """)

    conn.commit()
    print("[OK] Derived features populated")


# ──────────────────────────────────────────────
# 3. Summary report
# ──────────────────────────────────────────────
def generate_report(conn):
    cur = conn.cursor()
    report = {}

    # Total matches
    cur.execute("SELECT COUNT(*) FROM football_features_ml_v1")
    report["total_matches"] = cur.fetchone()[0]

    # Coverage per market
    for col, label in [
        ("has_1x2", "1X2 (base)"),
        ("has_total", "Total O/U (base)"),
        ("has_handicap", "Handicap (base)"),
        ("has_btts", "BTTS (base)"),
        ("has_corners", "Corners"),
        ("has_yellow_cards", "Yellow Cards"),
    ]:
        cur.execute(f"SELECT SUM({col}), COUNT(*) FROM football_features_ml_v1")
        cnt, total = cur.fetchone()
        report[f"coverage_{label}"] = {
            "count": cnt or 0,
            "pct": round((cnt or 0) * 100.0 / total, 2) if total else 0
        }

    # Top 15 leagues by match count
    cur.execute("""
    SELECT league, COUNT(*) as cnt
    FROM football_features_ml_v1
    GROUP BY league
    ORDER BY cnt DESC
    LIMIT 15
    """)
    report["top_leagues"] = [
        {"league": row[0], "matches": row[1]}
        for row in cur.fetchall()
    ]

    # Margin stats per market type
    for col, label in [
        ("margin_1x2", "1X2"),
        ("margin_total", "Total O/U"),
        ("margin_btts", "BTTS"),
        ("margin_corners_1x2", "Corners 1X2"),
        ("margin_corners_total", "Corners Total"),
        ("margin_yc_1x2", "YC 1X2"),
        ("margin_yc_total", "YC Total"),
    ]:
        cur.execute(f"""
        SELECT
            ROUND(AVG({col}), 4) as avg_margin,
            ROUND(MIN({col}), 4) as min_margin,
            ROUND(MAX({col}), 4) as max_margin,
            ROUND(AVG({col}) * 100, 2) as avg_margin_pct,
            COUNT({col}) as n
        FROM football_features_ml_v1
        WHERE {col} IS NOT NULL
        """)
        row = cur.fetchone()
        if row and row[4] > 0:
            report[f"margin_{label}"] = {
                "avg": row[0],
                "min": row[1],
                "max": row[2],
                "avg_pct": row[3],
                "n": row[4],
            }

    # Line consistency: compare total_line between base and corners/YC
    # NOTE: these are DIFFERENT markets (goals vs corners vs YC), so large diffs are expected.
    # The useful check is: do the lines cluster around typical values?
    cur.execute("""
    SELECT
        COUNT(*) as n,
        ROUND(AVG(total_line), 2) as avg_base_line,
        ROUND(AVG(corners_total_line), 2) as avg_corners_line,
        ROUND(AVG(yc_total_line), 2) as avg_yc_line
    FROM football_features_ml_v1
    WHERE total_line IS NOT NULL
      AND corners_total_line IS NOT NULL
      AND yc_total_line IS NOT NULL
    """)
    row = cur.fetchone()
    if row and row[0] > 0:
        report["line_consistency"] = {
            "n_overlap": row[0],
            "avg_base_total_line": row[1],
            "avg_corners_total_line": row[2],
            "avg_yc_total_line": row[3],
            "note": "Different markets have different typical lines — large diffs are expected",
        }

    # Value signals: negative margin (arb potential)
    for col, label in [
        ("margin_total", "Total O/U"),
        ("margin_btts", "BTTS"),
        ("margin_corners_total", "Corners Total"),
        ("margin_yc_total", "YC Total"),
    ]:
        cur.execute(f"SELECT COUNT(*) FROM football_features_ml_v1 WHERE {col} < 0")
        report[f"neg_margin_{label}"] = cur.fetchone()[0]

    # Low margin (sharp lines, < 3% for 1X2, < 2% for totals)
    cur.execute("SELECT COUNT(*) FROM football_features_ml_v1 WHERE margin_1x2 < 0.03 AND margin_1x2 IS NOT NULL")
    report["low_margin_1x2_lt_3pct"] = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM football_features_ml_v1 WHERE margin_total < 0.02 AND margin_total IS NOT NULL")
    report["low_margin_total_lt_2pct"] = cur.fetchone()[0]

    # Odds ratio stats
    for col, label in [
        ("odds_ratio_home_vs_corners", "Home vs Corners"),
        ("odds_ratio_away_vs_corners", "Away vs Corners"),
        ("odds_ratio_home_vs_yc", "Home vs YC"),
        ("odds_ratio_total_vs_corners", "Total vs Corners Over"),
        ("odds_ratio_total_vs_yc", "Total vs YC Over"),
    ]:
        cur.execute(f"""
        SELECT ROUND(AVG({col}),3), ROUND(MIN({col}),3), ROUND(MAX({col}),3), COUNT({col})
        FROM football_features_ml_v1 WHERE {col} IS NOT NULL
        """)
        r = cur.fetchone()
        if r and r[3] > 0:
            report[f"odds_ratio_{label}"] = {
                "avg": r[0], "min": r[1], "max": r[2], "n": r[3]
            }

    # Date range
    cur.execute("SELECT MIN(match_date), MAX(match_date) FROM football_features_ml_v1")
    row = cur.fetchone()
    report["date_range"] = {"min": row[0], "max": row[1]}

    # Column count
    cur.execute("PRAGMA table_info(football_features_ml_v1)")
    cols = cur.fetchall()
    report["total_features"] = len(cols)
    report["column_names"] = [c[1] for c in cols]

    return report


# ──────────────────────────────────────────────
# 4. Print report
# ──────────────────────────────────────────────
def print_report(report):
    print("\n" + "=" * 70)
    print("  FOOTBALL FEATURES ML V1 — SUMMARY REPORT")
    print("=" * 70)

    print(f"\n Total matches:  {report['total_matches']:,}")
    print(f" Total features: {report['total_features']}")
    print(f" Date range:     {report['date_range']['min']} → {report['date_range']['max']}")

    print("\n--- Market Coverage ---")
    for key in report:
        if key.startswith("coverage_"):
            label = key.replace("coverage_", "")
            d = report[key]
            print(f"  {label:25s}  {d['count']:>6,}  ({d['pct']:>5.1f}%)")

    print("\n--- Top 15 Leagues ---")
    for i, lg in enumerate(report["top_leagues"], 1):
        print(f"  {i:2d}. {lg['league']:<50s} {lg['matches']:>5,}")

    print("\n--- Margin Statistics ---")
    for key in report:
        if key.startswith("margin_") and not key.startswith("margin_"):
            pass
    for key in sorted(report.keys()):
        if key.startswith("margin_") and isinstance(report[key], dict):
            label = key.replace("margin_", "")
            d = report[key]
            print(f"  {label:25s}  avg={d['avg_pct']:>6.2f}%  min={d['min']:>6.4f}  max={d['max']:>6.4f}  n={d['n']:>6,}")

    if "line_consistency" in report:
        lc = report["line_consistency"]
        print(f"\n--- Line Consistency (overlap n={lc['n_overlap']}) ---")
        print(f"  Avg base total line:    {lc['avg_base_total_line']}")
        print(f"  Avg corners total line: {lc['avg_corners_total_line']}")
        print(f"  Avg YC total line:      {lc['avg_yc_total_line']}")
        print(f"  Note: {lc['note']}")

    print("\n--- Value Signals (Negative Margin = Arb Potential) ---")
    for key in sorted(report.keys()):
        if key.startswith("neg_margin_"):
            label = key.replace("neg_margin_", "")
            print(f"  {label:25s}  {report[key]:>6,} matches")
    if "low_margin_1x2_lt_3pct" in report:
        print(f"  {'1X2 sharp (<3%)':25s}  {report['low_margin_1x2_lt_3pct']:>6,} matches")
    if "low_margin_total_lt_2pct" in report:
        print(f"  {'Total sharp (<2%)':25s}  {report['low_margin_total_lt_2pct']:>6,} matches")

    print("\n--- Odds Ratios (cross-market) ---")
    for key in sorted(report.keys()):
        if key.startswith("odds_ratio_") and isinstance(report[key], dict):
            label = key.replace("odds_ratio_", "")
            d = report[key]
            print(f"  {label:25s}  avg={d['avg']:>6.3f}  min={d['min']:>6.3f}  max={d['max']:>6.3f}  n={d['n']:>6,}")

    print("\n" + "=" * 70)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
if __name__ == "__main__":
    conn = get_conn()
    print("Building football_features_ml_v1 ...")
    create_unified_table(conn)
    add_derived_features(conn)
    report = generate_report(conn)
    print_report(report)

    # Save report as JSON
    report_path = Path("/root/betagent/features_ml_v1_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to {report_path}")

    conn.close()
