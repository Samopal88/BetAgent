#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build pre-match historical features from backtest_matches only.
No future leakage: for each match, features are computed strictly from matches
played earlier in the same league, then standings/history are updated.

Usage:
  python3 historical_feature_builder.py --db /root/betagent/betagent.db
  python3 historical_feature_builder.py --db /root/betagent/betagent.db --limit-league "Англия. Премьер-Лига"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RawMatch:
    id: int
    league: str
    match_date: str
    home_team: str
    away_team: str
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]
    home_score: Optional[int]
    away_score: Optional[int]


def parse_dt(s: str) -> datetime:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return datetime.min


def safe_float(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None


def safe_int(x: Any) -> Optional[int]:
    try:
        return None if x is None else int(x)
    except Exception:
        return None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS historical_match_features (
        match_id INTEGER PRIMARY KEY,
        league TEXT,
        match_date TEXT,
        home_team TEXT,
        away_team TEXT,

        home_position INTEGER,
        away_position INTEGER,
        home_points INTEGER,
        away_points INTEGER,
        home_goal_diff INTEGER,
        away_goal_diff INTEGER,

        form_last_5_home TEXT,
        form_last_5_away TEXT,
        form_points_last_5_home INTEGER,
        form_points_last_5_away INTEGER,

        home_goals_scored_avg REAL,
        away_goals_scored_avg REAL,
        home_goals_allowed_avg REAL,
        away_goals_allowed_avg REAL,

        home_home_goals_scored_avg REAL,
        home_home_goals_allowed_avg REAL,
        away_away_goals_scored_avg REAL,
        away_away_goals_allowed_avg REAL,

        h2h_summary TEXT,
        h2h_home_wins INTEGER,
        h2h_draws INTEGER,
        h2h_away_wins INTEGER,
        h2h_matches_count INTEGER,

        matches_played_home_before INTEGER,
        matches_played_away_before INTEGER,

        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()


def load_matches(conn: sqlite3.Connection, league_filter: Optional[str] = None) -> List[RawMatch]:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(backtest_matches)").fetchall()}

    league_expr = "league_name" if "league_name" in cols else ("league" if "league" in cols else "''")
    home_score_expr = "home_score" if "home_score" in cols else ("score_home" if "score_home" in cols else "NULL")
    away_score_expr = "away_score" if "away_score" in cols else ("score_away" if "score_away" in cols else "NULL")

    q = f"""
        SELECT
            id,
            {league_expr} AS league,
            match_date,
            home_team,
            away_team,
            odds_home,
            odds_draw,
            odds_away,
            {home_score_expr} AS home_score,
            {away_score_expr} AS away_score
        FROM backtest_matches
        WHERE home_team IS NOT NULL
          AND away_team IS NOT NULL
    """
    params: List[Any] = []
    if league_filter:
        q += " AND " + league_expr + " = ?"
        params.append(league_filter)

    rows = conn.execute(q, params).fetchall()
    out: List[RawMatch] = []
    for r in rows:
        out.append(RawMatch(
            id=int(r["id"]),
            league=r["league"] or "",
            match_date=r["match_date"] or "",
            home_team=r["home_team"] or "",
            away_team=r["away_team"] or "",
            odds_home=safe_float(r["odds_home"]),
            odds_draw=safe_float(r["odds_draw"]),
            odds_away=safe_float(r["odds_away"]),
            home_score=safe_int(r["home_score"]),
            away_score=safe_int(r["away_score"]),
        ))
    out.sort(key=lambda m: (m.league, parse_dt(m.match_date), m.id))
    return out


def points_for(res: str) -> int:
    return 3 if res == "W" else 1 if res == "D" else 0


def avg_or_none(vals: List[float]) -> Optional[float]:
    return round(sum(vals) / len(vals), 3) if vals else None


def position_map(table: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    ordered = sorted(
        table.items(),
        key=lambda kv: (
            -(kv[1]["points"]),
            -((kv[1]["gf"] - kv[1]["ga"])),
            -(kv[1]["gf"]),
            kv[0].lower(),
        ),
    )
    return {team: idx + 1 for idx, (team, _) in enumerate(ordered)}


def make_h2h_summary(home: str, away: str, h2h: List[Tuple[str, int, int]]) -> Tuple[str, int, int, int, int]:
    home_wins = draws = away_wins = 0
    lines = []
    for h_team, hg, ag in h2h[-5:]:
        if hg == ag:
            draws += 1
            lines.append(f"{h_team} {hg}:{ag}")
        elif hg > ag:
            if h_team == home:
                home_wins += 1
            elif h_team == away:
                away_wins += 1
            lines.append(f"{h_team} {hg}:{ag}")
        else:
            if h_team == home:
                away_wins += 1
            elif h_team == away:
                home_wins += 1
            lines.append(f"{h_team} {hg}:{ag}")
    return (" | ".join(lines), home_wins, draws, away_wins, len(h2h[-5:]))


def build_features(matches: List[RawMatch]) -> List[Dict[str, Any]]:
    by_league: Dict[str, List[RawMatch]] = defaultdict(list)
    for m in matches:
        by_league[m.league].append(m)

    all_rows: List[Dict[str, Any]] = []

    for league, lm in by_league.items():
        table: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "points": 0, "gf": 0, "ga": 0, "played": 0,
            "results": [],
            "gf_hist": [], "ga_hist": [],
            "home_gf_hist": [], "home_ga_hist": [],
            "away_gf_hist": [], "away_ga_hist": [],
        })
        h2h_store: Dict[Tuple[str, str], List[Tuple[str, int, int]]] = defaultdict(list)

        for m in sorted(lm, key=lambda x: (parse_dt(x.match_date), x.id)):
            pos = position_map(table)

            home = table[m.home_team]
            away = table[m.away_team]

            form_home = home["results"][-5:]
            form_away = away["results"][-5:]

            h2h_key = tuple(sorted([m.home_team, m.away_team]))
            h2h_hist = h2h_store[h2h_key]
            h2h_summary, h2h_home_wins, h2h_draws, h2h_away_wins, h2h_matches_count = make_h2h_summary(
                m.home_team, m.away_team, h2h_hist
            )

            row = {
                "match_id": m.id,
                "league": league,
                "match_date": m.match_date,
                "home_team": m.home_team,
                "away_team": m.away_team,

                "home_position": pos.get(m.home_team),
                "away_position": pos.get(m.away_team),
                "home_points": home["points"] if home["played"] > 0 else None,
                "away_points": away["points"] if away["played"] > 0 else None,
                "home_goal_diff": (home["gf"] - home["ga"]) if home["played"] > 0 else None,
                "away_goal_diff": (away["gf"] - away["ga"]) if away["played"] > 0 else None,

                "form_last_5_home": json.dumps(form_home, ensure_ascii=False),
                "form_last_5_away": json.dumps(form_away, ensure_ascii=False),
                "form_points_last_5_home": sum(points_for(x) for x in form_home) if form_home else None,
                "form_points_last_5_away": sum(points_for(x) for x in form_away) if form_away else None,

                "home_goals_scored_avg": avg_or_none(home["gf_hist"][-5:]),
                "away_goals_scored_avg": avg_or_none(away["gf_hist"][-5:]),
                "home_goals_allowed_avg": avg_or_none(home["ga_hist"][-5:]),
                "away_goals_allowed_avg": avg_or_none(away["ga_hist"][-5:]),

                "home_home_goals_scored_avg": avg_or_none(home["home_gf_hist"][-5:]),
                "home_home_goals_allowed_avg": avg_or_none(home["home_ga_hist"][-5:]),
                "away_away_goals_scored_avg": avg_or_none(away["away_gf_hist"][-5:]),
                "away_away_goals_allowed_avg": avg_or_none(away["away_ga_hist"][-5:]),

                "h2h_summary": h2h_summary,
                "h2h_home_wins": h2h_home_wins,
                "h2h_draws": h2h_draws,
                "h2h_away_wins": h2h_away_wins,
                "h2h_matches_count": h2h_matches_count,

                "matches_played_home_before": home["played"],
                "matches_played_away_before": away["played"],
            }
            all_rows.append(row)

            if m.home_score is None or m.away_score is None:
                continue

            hg, ag = m.home_score, m.away_score
            if hg > ag:
                home_res, away_res = "W", "L"
                home_pts, away_pts = 3, 0
            elif hg < ag:
                home_res, away_res = "L", "W"
                home_pts, away_pts = 0, 3
            else:
                home_res = away_res = "D"
                home_pts = away_pts = 1

            home["points"] += home_pts
            home["gf"] += hg
            home["ga"] += ag
            home["played"] += 1
            home["results"].append(home_res)
            home["gf_hist"].append(hg)
            home["ga_hist"].append(ag)
            home["home_gf_hist"].append(hg)
            home["home_ga_hist"].append(ag)

            away["points"] += away_pts
            away["gf"] += ag
            away["ga"] += hg
            away["played"] += 1
            away["results"].append(away_res)
            away["gf_hist"].append(ag)
            away["ga_hist"].append(hg)
            away["away_gf_hist"].append(ag)
            away["away_ga_hist"].append(hg)

            h2h_store[h2h_key].append((m.home_team, hg, ag))

    return all_rows


def save_rows(conn: sqlite3.Connection, rows: List[Dict[str, Any]]) -> None:
    sql = """
    INSERT OR REPLACE INTO historical_match_features (
        match_id, league, match_date, home_team, away_team,
        home_position, away_position, home_points, away_points, home_goal_diff, away_goal_diff,
        form_last_5_home, form_last_5_away, form_points_last_5_home, form_points_last_5_away,
        home_goals_scored_avg, away_goals_scored_avg, home_goals_allowed_avg, away_goals_allowed_avg,
        home_home_goals_scored_avg, home_home_goals_allowed_avg, away_away_goals_scored_avg, away_away_goals_allowed_avg,
        h2h_summary, h2h_home_wins, h2h_draws, h2h_away_wins, h2h_matches_count,
        matches_played_home_before, matches_played_away_before
    ) VALUES (
        :match_id, :league, :match_date, :home_team, :away_team,
        :home_position, :away_position, :home_points, :away_points, :home_goal_diff, :away_goal_diff,
        :form_last_5_home, :form_last_5_away, :form_points_last_5_home, :form_points_last_5_away,
        :home_goals_scored_avg, :away_goals_scored_avg, :home_goals_allowed_avg, :away_goals_allowed_avg,
        :home_home_goals_scored_avg, :home_home_goals_allowed_avg, :away_away_goals_scored_avg, :away_away_goals_allowed_avg,
        :h2h_summary, :h2h_home_wins, :h2h_draws, :h2h_away_wins, :h2h_matches_count,
        :matches_played_home_before, :matches_played_away_before
    )
    """
    conn.executemany(sql, rows)
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to sqlite db")
    ap.add_argument("--limit-league", default=None, help="Optional exact league name")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    ensure_schema(conn)
    matches = load_matches(conn, args.limit_league)
    if not matches:
        print("No matches found in backtest_matches.")
        return 1

    rows = build_features(matches)
    save_rows(conn, rows)

    total = conn.execute("SELECT COUNT(*) AS c FROM historical_match_features").fetchone()["c"]
    print(f"historical_match_features rows: {total}")
    for row in conn.execute("""
        SELECT league, COUNT(*) AS c
        FROM historical_match_features
        GROUP BY league
        ORDER BY c DESC
        LIMIT 20
    """):
        print(f"{row['league']}: {row['c']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
