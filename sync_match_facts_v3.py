#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified hockey sync for BetAgent.

What it does:
1) Keeps old TheSports -> live match_facts sync if TheSports-enriched source rows exist.
2) Builds/refreshes hockey facts + hockey features for upcoming live hockey matches
   from the historical backtest table already stored in betagent.db.

This lets the live pipeline use one file for:
- KHL / NHL / Czech upcoming hockey matches from Fonbet
- historical form / team strength / goal averages from backtest_hockey_matches
- writing match_facts + hockey_match_features for agent_handoff_v7.py

It does NOT settle results. Settling stays in updater_results.py / settler.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
THE_SPORTS_SOURCE_TOKENS = ["TheSports", "synced_from_the_sports"]
HISTORICAL_TABLE = "backtest_hockey_matches"


# -----------------------------------------------------------------------------
# DB helpers
# -----------------------------------------------------------------------------
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------
def row_get(row: Any, key: str, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except Exception:
        return default


def safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def safe_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def season_key_from_dt(dt: datetime) -> str:
    # For hockey season Jul-Jun.
    if dt.month >= 7:
        return f"{dt.year}/{dt.year + 1}"
    return f"{dt.year - 1}/{dt.year}"


def parse_datetime_flex(date_value: str, time_value: Optional[str] = None) -> Optional[datetime]:
    if not date_value:
        return None

    candidates: List[str] = []
    if time_value:
        candidates.append(f"{date_value} {time_value}")
    candidates.append(str(date_value))

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y",
    ]

    for raw in candidates:
        for fmt in formats:
            try:
                return datetime.strptime(raw[: len(fmt.replace('%', '')) + 10], fmt)
            except Exception:
                pass
        # final fallback for ISO-ish strings with T
        try:
            return datetime.fromisoformat(raw.replace("Z", ""))
        except Exception:
            pass
    return None


def parse_day(s: str):
    dt = parse_datetime_flex(s)
    if not dt:
        raise ValueError(f"Cannot parse date: {s}")
    return dt.date()


# -----------------------------------------------------------------------------
# League + team normalization
# -----------------------------------------------------------------------------
EXCLUDED_LEAGUE_TOKENS = [
    "nhl 26",
    "esports",
    "united esports",
    "liga pro",
    "h2h",
    "short",
    "шорт",
    "mnhl",
    "2x2",
    "3x4",
    "3x5",
    "3x7",
    "статистическ",
    "итоги турнира",
    "кто наберет",
    "до 20 лет",
    "u20",
    "maxa liga",
    "серии. до",
    "серии, до",
]


def detect_hockey_league_text(text: str) -> Optional[str]:
    t = (text or "").lower()
    if any(tok in t for tok in EXCLUDED_LEAGUE_TOKENS):
        return None
    if "кхл" in t or re.search(r"\bkhl\b", t):
        return "KHL"
    if "нхл" in t or re.search(r"\bnhl\b", t):
        return "NHL"
    if ("чех" in t or "czech" in t) and ("экстралига" in t or "extraliga" in t):
        return "CZECH"
    return None


def detect_hockey_league(row: Any) -> Optional[str]:
    for key in ("league", "source", "source_league"):
        val = row_get(row, key, "")
        league = detect_hockey_league_text(str(val))
        if league:
            return league
    # fallback by team names if source fields are weak
    home = normalize_hockey_team_name(row_get(row, "home_team", ""))
    away = normalize_hockey_team_name(row_get(row, "away_team", ""))
    czech_markers = {
        "спарта прага", "маунтфилд", "тршинец", "пардубице", "комета брно",
        "литвинов", "млада болеслав", "либерец", "карловы вары", "пльзень",
        "витковице", "ческе будеёвице", "кладно", "оломоуц",
    }
    if home in czech_markers or away in czech_markers:
        return "CZECH"
    return None


TEAM_ALIAS_MAP = {

    "спартак москва": "спартак",
    "локомотив ярославль": "локомотив ярославль",
    "торпедо нижний новгород": "торпедо нн",
    "ска санкт-петербург": "ска",
    "автомобилист екатеринбург": "автомобилист",
    "трактор челябинск": "трактор",
    "динамо москва": "динамо москва",
    "динамо минск": "динамо минск",
    # Czech
    "mountfield hk": "маунтфилд",
    "маунтфилд гк": "маунтфилд",
    "mountfield": "маунтфилд",
    "hc ocelari trinec": "тршинец",
    "оцеларжи тршинец": "тршинец",
    "trinec": "тршинец",
    "hc dynamo pardubice": "пардубице",
    "dynamo pardubice": "пардубице",
    "hc kometa brno": "комета брно",
    "kometa brno": "комета брно",
    "hc sparta praha": "спарта прага",
    "sparta prague": "спарта прага",
    "sparta praha": "спарта прага",
    "hc plzen": "пльзень",
    "plzen": "пльзень",
    "bili tygri liberec": "либерец",
    "liberec": "либерец",
    "energie karlovy vary": "карловы вары",
    "karlovy vary": "карловы вары",
    "bk mlada boleslav": "млада болеслав",
    "mlada boleslav": "млада болеслав",
    "vitkovice ridera": "витковице",
    "vitkovice": "витковице",
    "olomouc": "оломоуц",
    "rytirikladno": "кладно",
    "rytiri kladno": "кладно",
    "kladno": "кладно",
    "ceske budejovice": "ческе будеёвице",
    "motor ceske budejovice": "ческе будеёвице",
    # KHL / NHL common cleanup
    "динамо москва": "динамо москва",
    "динамо мск": "динамо москва",
    "торпедо нн": "торпедо нн",
    "локо": "локомотив ярославль",
    "utah hockey club": "юта",
}


def _basic_norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = s.replace("ё", "е")
    s = s.replace("-", " ")
    s = s.replace("/", " ")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"\b(hc|hk|bk|fc|club|team)\b", " ", s)
    s = re.sub(r"[^a-zа-я0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_hockey_team_name(name: str) -> str:
    base = _basic_norm(name)
    if base in TEAM_ALIAS_MAP:
        return TEAM_ALIAS_MAP[base]
    squashed = base.replace(" ", "")
    if squashed in TEAM_ALIAS_MAP:
        return TEAM_ALIAS_MAP[squashed]
    return base


# -----------------------------------------------------------------------------
# Schema
# -----------------------------------------------------------------------------
def ensure_match_facts(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS match_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER UNIQUE,
            home_form TEXT,
            away_form TEXT,
            home_position INTEGER,
            away_position INTEGER,
            home_points INTEGER,
            away_points INTEGER,
            h2h_summary TEXT,
            home_goals_scored_avg REAL,
            away_goals_scored_avg REAL,
            home_goals_allowed_avg REAL,
            away_goals_allowed_avg REAL,
            home_motivation TEXT,
            away_motivation TEXT,
            notes TEXT,
            source TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()


def ensure_hockey_features_table(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hockey_match_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER UNIQUE,
            strength_diff_ppg REAL,
            strength_diff_form5 REAL,
            strength_diff_form10 REAL,
            expected_goal_diff_proxy REAL,
            home_goal_diff_vol5 REAL,
            away_goal_diff_vol5 REAL,
            home_total_goals_vol5 REAL,
            away_total_goals_vol5 REAL,
            home_ppg_all_before REAL,
            away_ppg_all_before REAL,
            home_gf_avg5 REAL,
            away_gf_avg5 REAL,
            home_ga_avg5 REAL,
            away_ga_avg5 REAL,
            home_ga_avg10 REAL,
            away_ga_avg10 REAL,
            expected_total_goals_proxy REAL,
            expected_match_tightness REAL,
            expected_defense_balance REAL,
            home_games_before INTEGER,
            away_games_before INTEGER,
            updated_at TEXT
        )
        """
    )
    conn.commit()


# -----------------------------------------------------------------------------
# Existing TheSports sync source rows
# -----------------------------------------------------------------------------
def get_source_fact_rows(conn: sqlite3.Connection):
    token_conditions = " OR ".join(["mf.source LIKE ?" for _ in THE_SPORTS_SOURCE_TOKENS])
    token_params = [f"%{t}%" for t in THE_SPORTS_SOURCE_TOKENS]

    rows = conn.execute(
        f"""
        SELECT
            mf.match_id,
            m.league,
            m.home_team,
            m.away_team,
            substr(m.match_date, 1, 10) as match_day,
            mf.home_form,
            mf.away_form,
            mf.home_position,
            mf.away_position,
            mf.home_points,
            mf.away_points,
            mf.h2h_summary,
            mf.home_goals_scored_avg,
            mf.away_goals_scored_avg,
            mf.home_goals_allowed_avg,
            mf.away_goals_allowed_avg,
            mf.home_motivation,
            mf.away_motivation,
            mf.notes,
            mf.source
        FROM match_facts mf
        JOIN matches m ON m.id = mf.match_id
        WHERE ({token_conditions})
        """,
        token_params,
    ).fetchall()
    return rows


def get_live_candidates(conn: sqlite3.Connection, home_team: str, away_team: str, league_key: Optional[str] = None):
    rows = conn.execute(
        """
        SELECT id, home_team, away_team, league, match_date,
               substr(match_date, 1, 10) as match_day,
               odds_home, odds_draw, odds_away
        FROM matches
        WHERE sport='hockey'
          AND status='upcoming'
          AND odds_home IS NOT NULL
          AND odds_away IS NOT NULL
        """
    ).fetchall()
    home_n = normalize_hockey_team_name(home_team)
    away_n = normalize_hockey_team_name(away_team)
    result = []
    for r in rows:
        if league_key and detect_hockey_league(r) != league_key:
            continue
        if normalize_hockey_team_name(r["home_team"]) == home_n and normalize_hockey_team_name(r["away_team"]) == away_n:
            result.append(r)
    return result


def pick_best_candidate(source_day: str, candidates: Sequence[sqlite3.Row]):
    if not candidates:
        return None
    src = parse_day(source_day)
    scored = []
    for c in candidates:
        try:
            d = parse_day(c["match_day"])
        except Exception:
            continue
        delta = abs((d - src).days)
        if delta <= 1:
            scored.append((delta, c))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0])
    return scored[0][1]


def upsert_target_fact(conn: sqlite3.Connection, target_match_id: int, source_row: Any, source_text: str = "synced_from_the_sports_v3"):
    cur = conn.cursor()
    existing = cur.execute("SELECT id FROM match_facts WHERE match_id=?", (target_match_id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    values = (
        row_get(source_row, "home_form"),
        row_get(source_row, "away_form"),
        row_get(source_row, "home_position"),
        row_get(source_row, "away_position"),
        row_get(source_row, "home_points"),
        row_get(source_row, "away_points"),
        row_get(source_row, "h2h_summary"),
        row_get(source_row, "home_goals_scored_avg"),
        row_get(source_row, "away_goals_scored_avg"),
        row_get(source_row, "home_goals_allowed_avg"),
        row_get(source_row, "away_goals_allowed_avg"),
        row_get(source_row, "home_motivation"),
        row_get(source_row, "away_motivation"),
        row_get(source_row, "notes"),
        source_text,
        now,
        target_match_id,
    )

    if existing:
        cur.execute(
            """
            UPDATE match_facts
            SET home_form=?, away_form=?, home_position=?, away_position=?,
                home_points=?, away_points=?, h2h_summary=?,
                home_goals_scored_avg=?, away_goals_scored_avg=?,
                home_goals_allowed_avg=?, away_goals_allowed_avg=?,
                home_motivation=?, away_motivation=?, notes=?,
                source=?, updated_at=?
            WHERE match_id=?
            """,
            values,
        )
    else:
        cur.execute(
            """
            INSERT INTO match_facts (
                home_form, away_form, home_position, away_position,
                home_points, away_points, h2h_summary,
                home_goals_scored_avg, away_goals_scored_avg,
                home_goals_allowed_avg, away_goals_allowed_avg,
                home_motivation, away_motivation, notes,
                source, updated_at, match_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
    conn.commit()


# -----------------------------------------------------------------------------
# Historical feature builder for upcoming live matches
# -----------------------------------------------------------------------------
@dataclass
class TeamState:
    gp: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    points: int = 0
    gf: int = 0
    ga: int = 0
    home_gp: int = 0
    home_points: int = 0
    away_gp: int = 0
    away_points: int = 0
    last_played: Optional[datetime] = None
    last5: Deque[Dict[str, Any]] = None
    last10: Deque[Dict[str, Any]] = None

    def __post_init__(self):
        if self.last5 is None:
            self.last5 = deque(maxlen=5)
        if self.last10 is None:
            self.last10 = deque(maxlen=10)


@dataclass
class HistoricalMatch:
    id: int
    league: str
    match_date: str
    match_time: Optional[str]
    home_team: str
    away_team: str
    home_score: Optional[int]
    away_score: Optional[int]


def load_historical_matches(conn: sqlite3.Connection, league_key: str, before_dt: datetime) -> List[HistoricalMatch]:
    if not table_exists(conn, HISTORICAL_TABLE):
        return []
    rows = conn.execute(
        f"""
        SELECT id, league, match_date, COALESCE(match_time, '') AS match_time,
               home_team, away_team, home_score, away_score
        FROM {HISTORICAL_TABLE}
        WHERE home_team IS NOT NULL
          AND away_team IS NOT NULL
          AND match_date IS NOT NULL
        ORDER BY id
        """
    ).fetchall()
    out: List[HistoricalMatch] = []
    for r in rows:
        if detect_hockey_league(r) != league_key:
            continue
        dt = parse_datetime_flex(row_get(r, "match_date"), row_get(r, "match_time"))
        if not dt or dt >= before_dt:
            continue
        out.append(
            HistoricalMatch(
                id=r["id"],
                league=r["league"],
                match_date=row_get(r, "match_date"),
                match_time=row_get(r, "match_time") or None,
                home_team=normalize_hockey_team_name(r["home_team"]),
                away_team=normalize_hockey_team_name(r["away_team"]),
                home_score=safe_int(r["home_score"]),
                away_score=safe_int(r["away_score"]),
            )
        )
    out.sort(key=lambda m: parse_datetime_flex(m.match_date, m.match_time) or datetime.min)
    return out


# use 3-1-0 like existing hockey sync / TheSports

def _result_points(home_score: int, away_score: int) -> Tuple[str, str, int, int]:
    if home_score > away_score:
        return "W", "L", 3, 0
    if home_score < away_score:
        return "L", "W", 0, 3
    return "D", "D", 1, 1


def _summarize_last(items: Iterable[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    items = list(items)
    if not items:
        return None, None, None
    pts = sum(x["points"] for x in items) / len(items)
    gd = sum(x["gd"] for x in items) / len(items)
    wr = sum(1 for x in items if x["res"] == "W") / len(items)
    return pts, gd, wr


def _avg(items: Iterable[float]) -> Optional[float]:
    vals = [float(x) for x in items if x is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _stdev(vals: List[float], default: float) -> float:
    vals = [float(v) for v in vals if v is not None]
    if len(vals) <= 1:
        return default
    try:
        return float(statistics.stdev(vals))
    except Exception:
        return default


def _position_map(team_states: Dict[str, TeamState]) -> Dict[str, int]:
    ranking = sorted(
        team_states.items(),
        key=lambda kv: (kv[1].points, kv[1].gf - kv[1].ga, kv[1].gf, -kv[1].ga, kv[0]),
        reverse=True,
    )
    return {team: idx + 1 for idx, (team, _) in enumerate(ranking)}


def _motivation_text(position: Optional[int], total_teams: int, league_key: str) -> str:
    if position is None:
        return ""
    if league_key == "KHL":
        if position <= 4:
            return f"Верх таблицы / преимущество площадки (место {position})"
        if position <= 8:
            return f"Зона плей-офф, важно удержать место (место {position})"
        return f"Вне верхней зоны / давление результата (место {position})"
    if position <= max(1, total_teams // 4):
        return f"Верх таблицы (место {position})"
    if position <= max(2, total_teams // 2):
        return f"Середина таблицы (место {position})"
    return f"Нижняя часть таблицы (место {position})"


def _compute_history_snapshot(historical_matches: List[HistoricalMatch], home_team: str, away_team: str):
    states: Dict[str, TeamState] = defaultdict(TeamState)
    h2h: Deque[Tuple[str, int]] = deque(maxlen=5)  # result from home_team perspective, gd

    for m in historical_matches:
        if m.home_score is None or m.away_score is None:
            continue
        hs = states[m.home_team]
        aw = states[m.away_team]
        dt = parse_datetime_flex(m.match_date, m.match_time) or datetime.min
        home_res, away_res, home_pts, away_pts = _result_points(m.home_score, m.away_score)
        home_gd = m.home_score - m.away_score
        away_gd = -home_gd

        # update home
        hs.gp += 1
        hs.gf += m.home_score
        hs.ga += m.away_score
        hs.points += home_pts
        hs.home_gp += 1
        hs.home_points += home_pts
        hs.last_played = dt
        hs.last5.append({"points": home_pts, "gd": home_gd, "res": home_res, "gf": m.home_score, "ga": m.away_score})
        hs.last10.append({"points": home_pts, "gd": home_gd, "res": home_res, "gf": m.home_score, "ga": m.away_score})
        if home_res == "W":
            hs.wins += 1
        elif home_res == "D":
            hs.draws += 1
        else:
            hs.losses += 1

        # update away
        aw.gp += 1
        aw.gf += m.away_score
        aw.ga += m.home_score
        aw.points += away_pts
        aw.away_gp += 1
        aw.away_points += away_pts
        aw.last_played = dt
        aw.last5.append({"points": away_pts, "gd": away_gd, "res": away_res, "gf": m.away_score, "ga": m.home_score})
        aw.last10.append({"points": away_pts, "gd": away_gd, "res": away_res, "gf": m.away_score, "ga": m.home_score})
        if away_res == "W":
            aw.wins += 1
        elif away_res == "D":
            aw.draws += 1
        else:
            aw.losses += 1

        # H2H
        if {m.home_team, m.away_team} == {home_team, away_team}:
            if m.home_team == home_team:
                if home_res == "W":
                    h2h.append(("W", home_gd))
                elif home_res == "D":
                    h2h.append(("D", home_gd))
                else:
                    h2h.append(("L", home_gd))
            else:
                # reverse perspective
                if away_res == "W":
                    h2h.append(("W", away_gd))
                elif away_res == "D":
                    h2h.append(("D", away_gd))
                else:
                    h2h.append(("L", away_gd))

    pos_map = _position_map(states)
    return states, pos_map, list(h2h)


def compute_features_for_upcoming(conn: sqlite3.Connection, live_match: sqlite3.Row) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    league_key = detect_hockey_league(live_match)
    if not league_key:
        return None
    live_dt = parse_datetime_flex(live_match["match_date"])
    if not live_dt:
        return None

    home_team = normalize_hockey_team_name(live_match["home_team"])
    away_team = normalize_hockey_team_name(live_match["away_team"])

    historical_matches = load_historical_matches(conn, league_key, live_dt)
    if not historical_matches:
        return None

    states, pos_map, h2h = _compute_history_snapshot(historical_matches, home_team, away_team)
    hs = states.get(home_team)
    aw = states.get(away_team)
    if not hs or not aw or hs.gp < 3 or aw.gp < 3:
        return None

    home_form_str = ",".join(x["res"] for x in hs.last5)
    away_form_str = ",".join(x["res"] for x in aw.last5)

    home_ppg = hs.points / hs.gp if hs.gp else 0.0
    away_ppg = aw.points / aw.gp if aw.gp else 0.0

    form5_home_pts, form5_home_gd, _ = _summarize_last(hs.last5)
    form5_away_pts, form5_away_gd, _ = _summarize_last(aw.last5)
    form10_home_pts, _, _ = _summarize_last(hs.last10)
    form10_away_pts, _, _ = _summarize_last(aw.last10)

    home_gf_avg5 = _avg([x["gf"] for x in hs.last5]) or (hs.gf / hs.gp if hs.gp else 0.0)
    away_gf_avg5 = _avg([x["gf"] for x in aw.last5]) or (aw.gf / aw.gp if aw.gp else 0.0)
    home_ga_avg5 = _avg([x["ga"] for x in hs.last5]) or (hs.ga / hs.gp if hs.gp else 0.0)
    away_ga_avg5 = _avg([x["ga"] for x in aw.last5]) or (aw.ga / aw.gp if aw.gp else 0.0)
    home_ga_avg10 = _avg([x["ga"] for x in hs.last10]) or home_ga_avg5
    away_ga_avg10 = _avg([x["ga"] for x in aw.last10]) or away_ga_avg5

    expected_goal_diff_proxy = (home_gf_avg5 - away_ga_avg5) - (away_gf_avg5 - home_ga_avg5)
    expected_total_goals_proxy = home_gf_avg5 + away_gf_avg5
    denom = max(1.0, expected_total_goals_proxy)
    expected_match_tightness = max(0.0, min(1.0, 1.0 - abs(expected_goal_diff_proxy) / denom))
    def_bal_denom = max(1.0, (home_ga_avg5 + away_ga_avg5) / 2.0)
    expected_defense_balance = max(0.0, min(1.0, 1.0 - abs(home_ga_avg5 - away_ga_avg5) / def_bal_denom))

    home_goal_diff_vol5 = _stdev([x["gd"] for x in hs.last5], 1.0)
    away_goal_diff_vol5 = _stdev([x["gd"] for x in aw.last5], 1.0)
    home_total_goals_vol5 = _stdev([x["gf"] + x["ga"] for x in hs.last5], 1.5)
    away_total_goals_vol5 = _stdev([x["gf"] + x["ga"] for x in aw.last5], 1.5)

    h2h_w = sum(1 for res, _ in h2h if res == "W")
    h2h_d = sum(1 for res, _ in h2h if res == "D")
    h2h_l = sum(1 for res, _ in h2h if res == "L")
    h2h_gd = sum(gd for _, gd in h2h)
    h2h_summary = f"H2H5 {h2h_w}-{h2h_d}-{h2h_l}, gd={h2h_gd}"

    total_teams = len(pos_map)
    facts = {
        "home_form": home_form_str,
        "away_form": away_form_str,
        "home_position": pos_map.get(home_team),
        "away_position": pos_map.get(away_team),
        "home_points": hs.points,
        "away_points": aw.points,
        "h2h_summary": h2h_summary,
        "home_goals_scored_avg": round(home_gf_avg5, 3),
        "away_goals_scored_avg": round(away_gf_avg5, 3),
        "home_goals_allowed_avg": round(home_ga_avg5, 3),
        "away_goals_allowed_avg": round(away_ga_avg5, 3),
        "home_motivation": _motivation_text(pos_map.get(home_team), total_teams, league_key),
        "away_motivation": _motivation_text(pos_map.get(away_team), total_teams, league_key),
        "notes": f"historical_sync:{league_key} season={season_key_from_dt(live_dt)} rows={len(historical_matches)}",
    }

    features = {
        "strength_diff_ppg": round(home_ppg - away_ppg, 6),
        "strength_diff_form5": round((form5_home_pts or 0.0) - (form5_away_pts or 0.0), 6),
        "strength_diff_form10": round((form10_home_pts or 0.0) - (form10_away_pts or 0.0), 6),
        "expected_goal_diff_proxy": round(expected_goal_diff_proxy, 6),
        "home_goal_diff_vol5": round(home_goal_diff_vol5, 6),
        "away_goal_diff_vol5": round(away_goal_diff_vol5, 6),
        "home_total_goals_vol5": round(home_total_goals_vol5, 6),
        "away_total_goals_vol5": round(away_total_goals_vol5, 6),
        "home_ppg_all_before": round(home_ppg, 6),
        "away_ppg_all_before": round(away_ppg, 6),
        "home_gf_avg5": round(home_gf_avg5, 6),
        "away_gf_avg5": round(away_gf_avg5, 6),
        "home_ga_avg5": round(home_ga_avg5, 6),
        "away_ga_avg5": round(away_ga_avg5, 6),
        "home_ga_avg10": round(home_ga_avg10, 6),
        "away_ga_avg10": round(away_ga_avg10, 6),
        "expected_total_goals_proxy": round(expected_total_goals_proxy, 6),
        "expected_match_tightness": round(expected_match_tightness, 6),
        "expected_defense_balance": round(expected_defense_balance, 6),
        "home_games_before": hs.gp,
        "away_games_before": aw.gp,
    }
    return facts, features


def upsert_hockey_features(conn: sqlite3.Connection, match_id: int, features: Dict[str, Any]):
    existing = conn.execute("SELECT id FROM hockey_match_features WHERE match_id=?", (match_id,)).fetchone()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if existing:
        placeholders = ", ".join([f"{k}=?" for k in features.keys()])
        values = list(features.values()) + [now, match_id]
        conn.execute(
            f"UPDATE hockey_match_features SET {placeholders}, updated_at=? WHERE match_id=?",
            values,
        )
    else:
        cols = ", ".join(features.keys())
        q = ", ".join(["?"] * (len(features) + 2))
        values = [match_id] + list(features.values()) + [now]
        conn.execute(
            f"INSERT INTO hockey_match_features (match_id, {cols}, updated_at) VALUES ({q})",
            values,
        )
    conn.commit()


# -----------------------------------------------------------------------------
# Main flow
# -----------------------------------------------------------------------------
def sync_thesports_rows(conn: sqlite3.Connection) -> Tuple[int, int, int]:
    source_rows = get_source_fact_rows(conn)
    if not source_rows:
        print("Не найдено source match_facts от TheSports.")
        return 0, 0, 0

    synced = 0
    missed = 0
    updated_features = 0

    print(f"Найдено source match_facts: {len(source_rows)}\n")
    for row in source_rows:
        league_key = detect_hockey_league(row)
        candidates = get_live_candidates(conn, row["home_team"], row["away_team"], league_key)
        best = pick_best_candidate(row["match_day"], candidates)
        if not best:
            missed += 1
            continue
        upsert_target_fact(conn, best["id"], row, source_text="synced_from_the_sports_v4")
        # If we already have facts from TheSports, still ensure features exist or refresh from historical.
        hist = compute_features_for_upcoming(conn, best)
        if hist:
            _, features = hist
            upsert_hockey_features(conn, best["id"], features)
            updated_features += 1
        synced += 1
        print(
            f"SYNC: {row['home_team']} — {row['away_team']} | TheSports={row['match_day']} -> "
            f"Live={best['match_day']} | match_id={best['id']}"
        )
    return synced, missed, updated_features


def enrich_upcoming_from_history(conn: sqlite3.Connection) -> Tuple[int, int, int]:
    rows = conn.execute(
        """
        SELECT *
        FROM matches
        WHERE sport='hockey'
          AND status='upcoming'
          AND odds_home IS NOT NULL
          AND odds_away IS NOT NULL
        ORDER BY match_date, id
        """
    ).fetchall()

    scanned = 0
    facts_written = 0
    features_written = 0

    if not rows:
        print("Нет upcoming hockey матчей с коэффициентами.")
        return scanned, facts_written, features_written

    for row in rows:
        scanned += 1
        league_key = detect_hockey_league(row)
        if not league_key:
            continue
        hist = compute_features_for_upcoming(conn, row)
        if not hist:
            print(f"[HIST MISS] {league_key} | {row['home_team']} — {row['away_team']}")
            continue
        facts, features = hist
        upsert_target_fact(conn, row["id"], facts, source_text=f"historical_backtest_sync:{league_key}")
        upsert_hockey_features(conn, row["id"], features)
        facts_written += 1
        features_written += 1
        print(
            f"[HIST SYNC] {league_key} | {row['home_team']} — {row['away_team']} | "
            f"facts+features updated for match_id={row['id']}"
        )
    return scanned, facts_written, features_written



def sync_results_to_raw(conn: sqlite3.Connection) -> int:
    """Копирует завершённые матчи из backtest_hockey_matches в results_raw для сеттлера."""
    rows = conn.execute("""
        SELECT league, match_date, home_team, away_team,
               rt_home_score, rt_away_score, went_ot_or_so
        FROM backtest_hockey_matches
        WHERE rt_home_score IS NOT NULL
          AND rt_away_score IS NOT NULL
          AND match_date >= date('now', '-7 days')
    """).fetchall()

    saved = 0
    for r in rows:
        # Определяем лигу
        league_text = (r["league"] or "").lower()
        if "кхл" in league_text or "khl" in league_text or "континентальн" in league_text:
            league = "khl"
        elif "нхл" in league_text or "nhl" in league_text:
            league = "nhl"
        elif "чех" in league_text or "экстралига" in league_text or "czech" in league_text:
            league = "czech"
        else:
            continue  # Пропускаем лиги которые не отслеживаем

        # Дата в формате YYYY-MM-DD
        match_date = r["match_date"]
        try:
            from datetime import datetime
            dt = datetime.strptime(match_date, "%d.%m.%Y")
            match_date = dt.strftime("%Y-%m-%d")
        except Exception:
            pass

        existing = conn.execute("""
            SELECT id FROM results_raw
            WHERE league=? AND home_team=? AND away_team=? AND match_date=? AND is_finished=1
        """, (league, r["home_team"], r["away_team"], match_date)).fetchone()

        if existing:
            continue

        conn.execute("""
            INSERT INTO results_raw (league, match_date, home_team, away_team, home_score, away_score, is_finished, source)
            VALUES (?, ?, ?, ?, ?, ?, 1, 'betz.su_rt')
        """, (league, match_date, r["home_team"], r["away_team"],
              r["rt_home_score"], r["rt_away_score"]))
        saved += 1

    conn.commit()
    return saved

def main():
    conn = get_conn()
    ensure_match_facts(conn)
    ensure_hockey_features_table(conn)

    if not table_exists(conn, HISTORICAL_TABLE):
        print(f"⚠️  Не найдена таблица {HISTORICAL_TABLE}. Историческое обогащение пропущено.")

    results_synced = sync_results_to_raw(conn)
    print(f"Results synced to results_raw: {results_synced}")
    ts_synced, ts_missed, ts_features = sync_thesports_rows(conn)
    scanned, hist_facts, hist_features = enrich_upcoming_from_history(conn)

    conn.close()
    print("\n✅  Готово.")
    print(f"TheSports synced: {ts_synced}")
    print(f"TheSports missed: {ts_missed}")
    print(f"TheSports features refreshed: {ts_features}")
    print(f"Upcoming hockey scanned: {scanned}")
    print(f"Historical facts written: {hist_facts}")
    print(f"Historical features written: {hist_features}")
    print("\nТеперь запускай:")
    print("  python agent_handoff_v7.py --dry-run --sport hockey --limit 20")


if __name__ == "__main__":
    main()
