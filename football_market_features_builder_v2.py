#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

DEFAULT_DB = "/root/betagent/betagent.db"


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backtest_football_market_features_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_match_id TEXT NOT NULL UNIQUE,
            page_date TEXT,
            match_date TEXT,
            match_time TEXT,
            league TEXT,
            home_team TEXT,
            away_team TEXT,

            odds_home REAL,
            odds_draw REAL,
            odds_away REAL,

            odds_total_over REAL,
            odds_total_under REAL,
            total_line REAL,

            odds_handicap_home REAL,
            odds_handicap_away REAL,
            handicap_line_home REAL,
            handicap_line_away REAL,

            odds_btts_yes REAL,
            odds_btts_no REAL,

            corners_odds_home REAL,
            corners_odds_draw REAL,
            corners_odds_away REAL,
            corners_total_over REAL,
            corners_total_under REAL,
            corners_total_line REAL,
            corners_hcap_home REAL,
            corners_hcap_away REAL,
            corners_hcap_line_home REAL,
            corners_hcap_line_away REAL,

            yellow_cards_odds_home REAL,
            yellow_cards_odds_draw REAL,
            yellow_cards_odds_away REAL,
            yellow_cards_total_over REAL,
            yellow_cards_total_under REAL,
            yellow_cards_total_line REAL,
            yellow_cards_hcap_home REAL,
            yellow_cards_hcap_away REAL,
            yellow_cards_hcap_line_home REAL,
            yellow_cards_hcap_line_away REAL,

            fouls_odds_home REAL,
            fouls_odds_draw REAL,
            fouls_odds_away REAL,
            fouls_total_over REAL,
            fouls_total_under REAL,
            fouls_total_line REAL,
            fouls_hcap_home REAL,
            fouls_hcap_away REAL,
            fouls_hcap_line_home REAL,
            fouls_hcap_line_away REAL,

            shots_odds_home REAL,
            shots_odds_draw REAL,
            shots_odds_away REAL,
            shots_total_over REAL,
            shots_total_under REAL,
            shots_total_line REAL,
            shots_hcap_home REAL,
            shots_hcap_away REAL,
            shots_hcap_line_home REAL,
            shots_hcap_line_away REAL,

            shots_on_target_odds_home REAL,
            shots_on_target_odds_draw REAL,
            shots_on_target_odds_away REAL,
            shots_on_target_total_over REAL,
            shots_on_target_total_under REAL,
            shots_on_target_total_line REAL,
            shots_on_target_hcap_home REAL,
            shots_on_target_hcap_away REAL,
            shots_on_target_hcap_line_home REAL,
            shots_on_target_hcap_line_away REAL,

            offsides_odds_home REAL,
            offsides_odds_draw REAL,
            offsides_odds_away REAL,
            offsides_total_over REAL,
            offsides_total_under REAL,
            offsides_total_line REAL,
            offsides_hcap_home REAL,
            offsides_hcap_away REAL,
            offsides_hcap_line_home REAL,
            offsides_hcap_line_away REAL,

            source_url TEXT,
            fetched_at TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bfmf_v2_date ON backtest_football_market_features_v2(match_date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bfmf_v2_league ON backtest_football_market_features_v2(league)"
    )
    conn.commit()


def build_sql() -> str:
    return """
    WITH base AS (
        SELECT
            source_match_id,
            page_date,
            match_date,
            match_time,
            league,
            home_team,
            away_team,
            odds_home,
            odds_draw,
            odds_away,
            odds_total_over,
            odds_total_under,
            total_line,
            odds_handicap_home,
            odds_handicap_away,
            handicap_line_home,
            handicap_line_away,
            odds_btts_yes,
            odds_btts_no,
            source_url,
            fetched_at
        FROM backtest_football_matches_betz
    ),
    sm AS (
        SELECT
            base_match_id,
            market_type,
            odds_home,
            odds_draw,
            odds_away,
            odds_total_over,
            odds_total_under,
            total_line,
            odds_handicap_home,
            odds_handicap_away,
            handicap_line_home,
            handicap_line_away,
            id,
            ROW_NUMBER() OVER (
                PARTITION BY base_match_id, market_type
                ORDER BY id DESC
            ) AS rn
        FROM backtest_football_special_markets_betz
        WHERE base_match_id IS NOT NULL
    ),
    corners AS (SELECT * FROM sm WHERE market_type='corners' AND rn=1),
    yellow_cards AS (SELECT * FROM sm WHERE market_type='yellow_cards' AND rn=1),
    fouls AS (SELECT * FROM sm WHERE market_type='fouls' AND rn=1),
    shots AS (SELECT * FROM sm WHERE market_type='shots' AND rn=1),
    shots_on_target AS (SELECT * FROM sm WHERE market_type='shots_on_target' AND rn=1),
    offsides AS (SELECT * FROM sm WHERE market_type='offsides' AND rn=1)

    INSERT INTO backtest_football_market_features_v2 (
        source_match_id,
        page_date,
        match_date,
        match_time,
        league,
        home_team,
        away_team,

        odds_home,
        odds_draw,
        odds_away,

        odds_total_over,
        odds_total_under,
        total_line,

        odds_handicap_home,
        odds_handicap_away,
        handicap_line_home,
        handicap_line_away,

        odds_btts_yes,
        odds_btts_no,

        corners_odds_home, corners_odds_draw, corners_odds_away,
        corners_total_over, corners_total_under, corners_total_line,
        corners_hcap_home, corners_hcap_away, corners_hcap_line_home, corners_hcap_line_away,

        yellow_cards_odds_home, yellow_cards_odds_draw, yellow_cards_odds_away,
        yellow_cards_total_over, yellow_cards_total_under, yellow_cards_total_line,
        yellow_cards_hcap_home, yellow_cards_hcap_away, yellow_cards_hcap_line_home, yellow_cards_hcap_line_away,

        fouls_odds_home, fouls_odds_draw, fouls_odds_away,
        fouls_total_over, fouls_total_under, fouls_total_line,
        fouls_hcap_home, fouls_hcap_away, fouls_hcap_line_home, fouls_hcap_line_away,

        shots_odds_home, shots_odds_draw, shots_odds_away,
        shots_total_over, shots_total_under, shots_total_line,
        shots_hcap_home, shots_hcap_away, shots_hcap_line_home, shots_hcap_line_away,

        shots_on_target_odds_home, shots_on_target_odds_draw, shots_on_target_odds_away,
        shots_on_target_total_over, shots_on_target_total_under, shots_on_target_total_line,
        shots_on_target_hcap_home, shots_on_target_hcap_away, shots_on_target_hcap_line_home, shots_on_target_hcap_line_away,

        offsides_odds_home, offsides_odds_draw, offsides_odds_away,
        offsides_total_over, offsides_total_under, offsides_total_line,
        offsides_hcap_home, offsides_hcap_away, offsides_hcap_line_home, offsides_hcap_line_away,

        source_url,
        fetched_at,
        updated_at
    )
    SELECT
        b.source_match_id,
        b.page_date,
        b.match_date,
        b.match_time,
        b.league,
        b.home_team,
        b.away_team,

        b.odds_home,
        b.odds_draw,
        b.odds_away,

        b.odds_total_over,
        b.odds_total_under,
        b.total_line,

        b.odds_handicap_home,
        b.odds_handicap_away,
        b.handicap_line_home,
        b.handicap_line_away,

        b.odds_btts_yes,
        b.odds_btts_no,

        c.odds_home, c.odds_draw, c.odds_away, c.odds_total_over, c.odds_total_under, c.total_line,
        c.odds_handicap_home, c.odds_handicap_away, c.handicap_line_home, c.handicap_line_away,

        yc.odds_home, yc.odds_draw, yc.odds_away, yc.odds_total_over, yc.odds_total_under, yc.total_line,
        yc.odds_handicap_home, yc.odds_handicap_away, yc.handicap_line_home, yc.handicap_line_away,

        f.odds_home, f.odds_draw, f.odds_away, f.odds_total_over, f.odds_total_under, f.total_line,
        f.odds_handicap_home, f.odds_handicap_away, f.handicap_line_home, f.handicap_line_away,

        s.odds_home, s.odds_draw, s.odds_away, s.odds_total_over, s.odds_total_under, s.total_line,
        s.odds_handicap_home, s.odds_handicap_away, s.handicap_line_home, s.handicap_line_away,

        sot.odds_home, sot.odds_draw, sot.odds_away, sot.odds_total_over, sot.odds_total_under, sot.total_line,
        sot.odds_handicap_home, sot.odds_handicap_away, sot.handicap_line_home, sot.handicap_line_away,

        os.odds_home, os.odds_draw, os.odds_away, os.odds_total_over, os.odds_total_under, os.total_line,
        os.odds_handicap_home, os.odds_handicap_away, os.handicap_line_home, os.handicap_line_away,

        b.source_url,
        b.fetched_at,
        CURRENT_TIMESTAMP
    FROM base b
    LEFT JOIN corners c ON c.base_match_id = b.source_match_id
    LEFT JOIN yellow_cards yc ON yc.base_match_id = b.source_match_id
    LEFT JOIN fouls f ON f.base_match_id = b.source_match_id
    LEFT JOIN shots s ON s.base_match_id = b.source_match_id
    LEFT JOIN shots_on_target sot ON sot.base_match_id = b.source_match_id
    LEFT JOIN offsides os ON os.base_match_id = b.source_match_id
    ON CONFLICT(source_match_id) DO UPDATE SET
        page_date=excluded.page_date,
        match_date=excluded.match_date,
        match_time=excluded.match_time,
        league=excluded.league,
        home_team=excluded.home_team,
        away_team=excluded.away_team,

        odds_home=excluded.odds_home,
        odds_draw=excluded.odds_draw,
        odds_away=excluded.odds_away,

        odds_total_over=excluded.odds_total_over,
        odds_total_under=excluded.odds_total_under,
        total_line=excluded.total_line,

        odds_handicap_home=excluded.odds_handicap_home,
        odds_handicap_away=excluded.odds_handicap_away,
        handicap_line_home=excluded.handicap_line_home,
        handicap_line_away=excluded.handicap_line_away,

        odds_btts_yes=excluded.odds_btts_yes,
        odds_btts_no=excluded.odds_btts_no,

        corners_odds_home=excluded.corners_odds_home,
        corners_odds_draw=excluded.corners_odds_draw,
        corners_odds_away=excluded.corners_odds_away,
        corners_total_over=excluded.corners_total_over,
        corners_total_under=excluded.corners_total_under,
        corners_total_line=excluded.corners_total_line,
        corners_hcap_home=excluded.corners_hcap_home,
        corners_hcap_away=excluded.corners_hcap_away,
        corners_hcap_line_home=excluded.corners_hcap_line_home,
        corners_hcap_line_away=excluded.corners_hcap_line_away,

        yellow_cards_odds_home=excluded.yellow_cards_odds_home,
        yellow_cards_odds_draw=excluded.yellow_cards_odds_draw,
        yellow_cards_odds_away=excluded.yellow_cards_odds_away,
        yellow_cards_total_over=excluded.yellow_cards_total_over,
        yellow_cards_total_under=excluded.yellow_cards_total_under,
        yellow_cards_total_line=excluded.yellow_cards_total_line,
        yellow_cards_hcap_home=excluded.yellow_cards_hcap_home,
        yellow_cards_hcap_away=excluded.yellow_cards_hcap_away,
        yellow_cards_hcap_line_home=excluded.yellow_cards_hcap_line_home,
        yellow_cards_hcap_line_away=excluded.yellow_cards_hcap_line_away,

        fouls_odds_home=excluded.fouls_odds_home,
        fouls_odds_draw=excluded.fouls_odds_draw,
        fouls_odds_away=excluded.fouls_odds_away,
        fouls_total_over=excluded.fouls_total_over,
        fouls_total_under=excluded.fouls_total_under,
        fouls_total_line=excluded.fouls_total_line,
        fouls_hcap_home=excluded.fouls_hcap_home,
        fouls_hcap_away=excluded.fouls_hcap_away,
        fouls_hcap_line_home=excluded.fouls_hcap_line_home,
        fouls_hcap_line_away=excluded.fouls_hcap_line_away,

        shots_odds_home=excluded.shots_odds_home,
        shots_odds_draw=excluded.shots_odds_draw,
        shots_odds_away=excluded.shots_odds_away,
        shots_total_over=excluded.shots_total_over,
        shots_total_under=excluded.shots_total_under,
        shots_total_line=excluded.shots_total_line,
        shots_hcap_home=excluded.shots_hcap_home,
        shots_hcap_away=excluded.shots_hcap_away,
        shots_hcap_line_home=excluded.shots_hcap_line_home,
        shots_hcap_line_away=excluded.shots_hcap_line_away,

        shots_on_target_odds_home=excluded.shots_on_target_odds_home,
        shots_on_target_odds_draw=excluded.shots_on_target_odds_draw,
        shots_on_target_odds_away=excluded.shots_on_target_odds_away,
        shots_on_target_total_over=excluded.shots_on_target_total_over,
        shots_on_target_total_under=excluded.shots_on_target_total_under,
        shots_on_target_total_line=excluded.shots_on_target_total_line,
        shots_on_target_hcap_home=excluded.shots_on_target_hcap_home,
        shots_on_target_hcap_away=excluded.shots_on_target_hcap_away,
        shots_on_target_hcap_line_home=excluded.shots_on_target_hcap_line_home,
        shots_on_target_hcap_line_away=excluded.shots_on_target_hcap_line_away,

        offsides_odds_home=excluded.offsides_odds_home,
        offsides_odds_draw=excluded.offsides_odds_draw,
        offsides_odds_away=excluded.offsides_odds_away,
        offsides_total_over=excluded.offsides_total_over,
        offsides_total_under=excluded.offsides_total_under,
        offsides_total_line=excluded.offsides_total_line,
        offsides_hcap_home=excluded.offsides_hcap_home,
        offsides_hcap_away=excluded.offsides_hcap_away,
        offsides_hcap_line_home=excluded.offsides_hcap_line_home,
        offsides_hcap_line_away=excluded.offsides_hcap_line_away,

        source_url=excluded.source_url,
        fetched_at=excluded.fetched_at,
        updated_at=CURRENT_TIMESTAMP
    """


def main() -> None:
    parser = argparse.ArgumentParser(description="Build football market features v2")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite DB")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose)

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        ensure_table(conn)
        conn.execute(build_sql())
        conn.commit()

        total = conn.execute(
            "SELECT COUNT(*) FROM backtest_football_market_features_v2"
        ).fetchone()[0]
        with_btts = conn.execute(
            "SELECT COUNT(*) FROM backtest_football_market_features_v2 WHERE odds_btts_yes IS NOT NULL OR odds_btts_no IS NOT NULL"
        ).fetchone()[0]
        with_corners = conn.execute(
            "SELECT COUNT(*) FROM backtest_football_market_features_v2 WHERE corners_total_line IS NOT NULL OR corners_odds_home IS NOT NULL"
        ).fetchone()[0]
        with_yc = conn.execute(
            "SELECT COUNT(*) FROM backtest_football_market_features_v2 WHERE yellow_cards_total_line IS NOT NULL OR yellow_cards_odds_home IS NOT NULL"
        ).fetchone()[0]

        logging.info("Build completed")
        logging.info("Total rows: %s", total)
        logging.info("Rows with BTTS: %s", with_btts)
        logging.info("Rows with corners: %s", with_corners)
        logging.info("Rows with yellow cards: %s", with_yc)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
