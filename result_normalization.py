# -*- coding: utf-8 -*-
"""
BETAGENT — result_normalization.py

Canonical normalized result layer for all sports.

Problem:
  - results_raw has 7+ different parsers writing in different formats
  - Hockey OT/SO semantics differ from regulation-time scores
  - Team names vary: "Монреаль" vs "Монреаль Канадиенс" vs "CGY"
  - Tennis has explicit winner_name, team sports derive from score
  - Settlement depends on fragile fuzzy matching against raw sources

Solution:
  - normalized_results table: single source of truth for "who won, by what score"
  - Per-sport normalization rules applied during ingestion
  - Confidence score reflecting match quality (exact vs fuzzy)
  - Settlement reads from normalized_results first, falls back to raw

Usage:
    python result_normalization.py --sport football --days 7
    python result_normalization.py --sport hockey --days 7
    python result_normalization.py --sport tennis --days 7
    python result_normalization.py --all --days 3
    python result_normalization.py --normalize-today   # all sports, today
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "betagent.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
)
log = logging.getLogger("result_normalization")


# ============================================================
# Schema
# ============================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS normalized_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source tracking
    source          TEXT NOT NULL,          -- 'results_raw', 'tennis_live_results', 'fonbet_api'
    source_match_id TEXT,                   -- original ID or composite key from source

    -- Sport & context
    sport           TEXT NOT NULL,          -- 'football', 'hockey', 'tennis'
    league          TEXT,
    match_date      TEXT NOT NULL,          -- YYYY-MM-DD

    -- Participants (canonical order: participant_1 is home/player1)
    participant_1   TEXT NOT NULL,          -- home team or player1 (normalized name)
    participant_2   TEXT NOT NULL,          -- away team or player2 (normalized name)

    -- Result (canonical — always from winner's perspective)
    winner_name     TEXT,                   -- canonical name of the winner
    loser_name      TEXT,                   -- canonical name of the loser
    winner_side     TEXT,                   -- 'participant_1', 'participant_2', or 'draw'

    -- Score
    score_p1        INTEGER,                -- score of participant_1 (regulation time for hockey)
    score_p2        INTEGER,                -- score of participant_2 (regulation time for hockey)
    score_detail    TEXT,                   -- sport-specific: sets for tennis, OT flag for hockey

    -- Status
    status          TEXT NOT NULL DEFAULT 'completed',
                                        -- 'completed', 'postponed', 'cancelled', 'void', 'unknown'

    -- Metadata
    is_overtime     INTEGER DEFAULT 0,      -- hockey: went to OT/SO
    raw_data        TEXT,                   -- JSON blob of original raw fields for audit

    -- Timestamps
    parsed_at       TEXT NOT NULL,          -- when the source parsed this result
    normalized_at   TEXT DEFAULT (datetime('now')),  -- when we normalized it

    -- Quality
    confidence      REAL DEFAULT 1.0,       -- 1.0 = exact match, 0.5-0.9 = fuzzy, <0.5 = uncertain

    -- Dedup
    UNIQUE(source, source_match_id, sport)
);
"""

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_nr_sport_date ON normalized_results(sport, match_date)",
    "CREATE INDEX IF NOT EXISTS idx_nr_winner ON normalized_results(winner_name)",
    "CREATE INDEX IF NOT EXISTS idx_nr_participants ON normalized_results(participant_1, participant_2)",
    "CREATE INDEX IF NOT EXISTS idx_nr_status ON normalized_results(status)",
    "CREATE INDEX IF NOT EXISTS idx_nr_source ON normalized_results(source)",
]


def ensure_table(conn: sqlite3.Connection):
    """Create normalized_results table and indexes if not exists."""
    conn.execute(CREATE_TABLE_SQL)
    for idx in INDEXES_SQL:
        conn.execute(idx)

    # Migrate: add columns if table exists from earlier version
    cols = [row[1] for row in conn.execute("PRAGMA table_info(normalized_results)").fetchall()]
    migrations = {
        "source_match_id": "ALTER TABLE normalized_results ADD COLUMN source_match_id TEXT",
        "score_detail": "ALTER TABLE normalized_results ADD COLUMN score_detail TEXT",
        "is_overtime": "ALTER TABLE normalized_results ADD COLUMN is_overtime INTEGER DEFAULT 0",
        "raw_data": "ALTER TABLE normalized_results ADD COLUMN raw_data TEXT",
        "confidence": "ALTER TABLE normalized_results ADD COLUMN confidence REAL DEFAULT 1.0",
    }
    for col, sql in migrations.items():
        if col not in cols:
            try:
                conn.execute(sql)
            except Exception:
                pass  # column may exist under different name
    conn.commit()


# ============================================================
# Name normalization helpers
# ============================================================

# Common hockey abbreviations -> canonical names
HOCKEY_ABBREVS = {
    "CGY": "Калгари",
    "EDM": "Эдмонтон",
    "VAN": "Ванкувер",
    "TOR": "Торонто",
    "MTL": "Монреаль",
    "BOS": "Бостон",
    "NYR": "Рейнджерс",
    "WSH": "Вашингтон",
    "TBL": "Тампа-Бэй",
    "FLA": "Флорида",
    "CAR": "Каролина",
    "NJD": "Нью-Джерси",
    "PIT": "Питтсбург",
    "PHI": "Филадельфия",
    "NYI": "Айлендерс",
    "CBJ": "Коламбус",
    "DET": "Детройт",
    "BUF": "Баффало",
    "OTT": "Оттава",
    "MIN": "Миннесота",
    "COL": "Колорадо",
    "DAL": "Даллас",
    "WPG": "Виннипег",
    "NSH": "Нэшвилл",
    "STL": "Сент-Луис",
    "CHI": "Чикаго",
    "ARI": "Аризона",
    "VGK": "Вегас",
    "LAK": "Лос-Анджелес",
    "ANA": "Анахайм",
    "SJS": "Сан-Хосе",
    "SEA": "Сиэтл",
}


def normalize_team_name(name: str, sport: str = "football") -> str:
    """Normalize a team name to canonical form.

    - Strips trailing parentheticals: "Монреаль (Канадиенс)" -> "Монреаль"
    - Expands hockey abbreviations: "CGY" -> "Калгари"
    - Normalizes whitespace
    """
    if not name:
        return ""
    name = name.strip()
    # Remove trailing parentheticals
    while "(" in name:
        idx = name.index("(")
        name = name[:idx].strip()
    # Expand hockey abbreviations
    if sport == "hockey" and name.upper() in HOCKEY_ABBREVS:
        return HOCKEY_ABBREVS[name.upper()]
    # Normalize whitespace
    name = " ".join(name.split())
    return name


def extract_surname(russian_name: str) -> str:
    """Extract surname from Russian tennis player name.
    'Мирра Андреева' -> 'Андреева'
    'Андреева М.' -> 'Андреева'
    """
    if not russian_name:
        return ""
    parts = russian_name.strip().replace(".", "").split()
    if not parts:
        return ""
    if len(parts) >= 2 and len(parts[-1]) <= 3:
        return parts[0]
    return parts[-1]


# ============================================================
# Per-sport normalization
# ============================================================

def normalize_football_result(row: dict) -> Optional[Dict[str, Any]]:
    """Normalize a football result from results_raw.

    Input: dict from results_raw (league, match_date, home_team, away_team,
           home_score, away_score, is_finished, source, updated_at)
    Output: normalized dict or None
    """
    if not row.get("is_finished"):
        return None

    home = normalize_team_name(row.get("home_team", ""), "football")
    away = normalize_team_name(row.get("away_team", ""), "football")
    if not home or not away:
        return None

    hs = row.get("home_score")
    as_ = row.get("away_score")
    if hs is None or as_ is None:
        return None

    # Determine winner
    if hs > as_:
        winner, loser, side = home, away, "participant_1"
    elif as_ > hs:
        winner, loser, side = away, home, "participant_2"
    else:
        winner, loser, side = None, None, "draw"

    return {
        "source": "results_raw",
        "source_match_id": f"fb_{row.get('league', 'unknown')}_{home}_{away}_{row.get('match_date', '')}",
        "sport": "football",
        "league": row.get("league"),
        "match_date": str(row.get("match_date", ""))[:10],
        "participant_1": home,
        "participant_2": away,
        "winner_name": winner,
        "loser_name": loser,
        "winner_side": side,
        "score_p1": hs,
        "score_p2": as_,
        "score_detail": None,
        "status": "completed",
        "is_overtime": 0,
        "raw_data": json.dumps({
            "raw_home": row.get("home_team"),
            "raw_away": row.get("away_team"),
            "raw_source": row.get("source"),
        }, ensure_ascii=False),
        "parsed_at": row.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "confidence": 1.0,
    }


def normalize_hockey_result(row: dict) -> Optional[Dict[str, Any]]:
    """Normalize a hockey result from results_raw.

    Key difference from football:
    - is_overtime flag indicates OT/SO
    - For settlement, regulation-time score matters for draw market
    - OT matches: regulation time was a draw (e.g., 1:1), then someone won in OT
    """
    if not row.get("is_finished"):
        return None

    home = normalize_team_name(row.get("home_team", ""), "hockey")
    away = normalize_team_name(row.get("away_team", ""), "hockey")
    if not home or not away:
        return None

    hs = row.get("home_score")
    as_ = row.get("away_score")
    if hs is None or as_ is None:
        return None

    is_ot = bool(row.get("is_overtime", 0))
    source = row.get("source", "")

    # For hockey, the score in results_raw is regulation-time only for most parsers.
    # But some parsers (sports.ru) write the final score including OT.
    # We trust betz.su as the primary source for regulation-time scores.
    # If is_overtime=1, the regulation score was a draw.
    confidence = 1.0
    if source == "betz.su":
        confidence = 1.0  # Primary source for hockey
    elif "sports.ru" in (source or ""):
        confidence = 0.9  # May include OT in score
    else:
        confidence = 0.85

    # Determine winner from the stored score
    if hs > as_:
        winner, loser, side = home, away, "participant_1"
    elif as_ > hs:
        winner, loser, side = away, home, "participant_2"
    else:
        winner, loser, side = None, None, "draw"

    return {
        "source": "results_raw",
        "source_match_id": f"hk_{row.get('league', 'unknown')}_{home}_{away}_{row.get('match_date', '')}",
        "sport": "hockey",
        "league": row.get("league"),
        "match_date": str(row.get("match_date", ""))[:10],
        "participant_1": home,
        "participant_2": away,
        "winner_name": winner,
        "loser_name": loser,
        "winner_side": side,
        "score_p1": hs,
        "score_p2": as_,
        "score_detail": "OT" if is_ot else None,
        "status": "completed",
        "is_overtime": 1 if is_ot else 0,
        "raw_data": json.dumps({
            "raw_home": row.get("home_team"),
            "raw_away": row.get("away_team"),
            "raw_source": source,
            "raw_league": row.get("league"),
        }, ensure_ascii=False),
        "parsed_at": row.get("updated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "confidence": confidence,
    }


def normalize_tennis_result(row: dict) -> Optional[Dict[str, Any]]:
    """Normalize a tennis result from tennis_live_results.

    Tennis already has explicit winner_name/loser_name — just needs canonical mapping.
    """
    winner = row.get("winner_name", "")
    loser = row.get("loser_name", "")
    if not winner or not loser:
        return None

    p1 = row.get("player1_raw", winner)  # Original first player if available
    p2 = row.get("player2_raw", loser)

    # In tennis, participant_1 = player who was listed first in the bet
    # But we don't have that info from results alone.
    # Convention: winner is participant_1
    participant_1 = winner
    participant_2 = loser

    sets_w = row.get("sets_winner", 0)
    sets_l = row.get("sets_loser", 0)
    score_detail = row.get("score_detail", "")

    return {
        "source": "tennis_live_results",
        "source_match_id": f"tn_{row.get('tournament', '')}_{winner}_{loser}_{row.get('match_date', '')}",
        "sport": "tennis",
        "league": row.get("tournament"),
        "match_date": str(row.get("match_date", ""))[:10],
        "participant_1": winner,
        "participant_2": loser,
        "winner_name": winner,
        "loser_name": loser,
        "winner_side": "participant_1",
        "score_p1": sets_w,
        "score_p2": sets_l,
        "score_detail": score_detail,
        "status": "completed",
        "is_overtime": 0,
        "raw_data": json.dumps({
            "tour": row.get("tour"),
            "level": row.get("level"),
            "surface": row.get("surface"),
            "raw_source": row.get("source"),
        }, ensure_ascii=False),
        "parsed_at": row.get("fetched_at", ""),
        "confidence": 1.0,
    }


# ============================================================
# Ingestion from raw sources
# ============================================================

def ingest_from_results_raw(conn: sqlite3.Connection, sport: str = "football",
                             days: int = 7) -> int:
    """Read from results_raw, normalize, upsert into normalized_results.

    Returns count of new/updated records.
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT league, match_date, home_team, away_team,
               home_score, away_score, is_finished, source, updated_at, is_overtime
        FROM results_raw
        WHERE match_date >= ?
          AND is_finished = 1
        ORDER BY match_date DESC, id DESC
    """, (since,)).fetchall()

    cols = ["league", "match_date", "home_team", "away_team",
            "home_score", "away_score", "is_finished", "source", "updated_at", "is_overtime"]
    dicts = [dict(zip(cols, r)) for r in rows]

    normalize_fn = normalize_hockey_result if sport == "hockey" else normalize_football_result

    # Filter to the right sport by league heuristics
    hockey_leagues = {"khl", "nhl", "czech", "nla"}
    football_leagues = {
        "rpl", "rpl_prev", "epl", "bundesliga", "laliga", "seriea",
        "ligue1", "BL1", "SA", "PD", "FL1",
    }

    if sport == "hockey":
        dicts = [d for d in dicts if d.get("league", "").lower() in hockey_leagues]
    else:
        # Football: include known football leagues OR anything not a known hockey league
        dicts = [d for d in dicts
                 if d.get("league", "").lower() in football_leagues
                 or d.get("league", "") in football_leagues
                 or (d.get("league", "").lower() not in hockey_leagues
                     and d.get("league", "").lower() != "unknown")]

    inserted = 0
    for d in dicts:
        norm = normalize_fn(d)
        if norm is None:
            continue

        # Upsert by unique key
        existing = conn.execute("""
            SELECT id, confidence FROM normalized_results
            WHERE source=? AND source_match_id=? AND sport=?
        """, (norm["source"], norm["source_match_id"], norm["sport"])).fetchone()

        if existing:
            # Only update if new source has higher confidence
            if norm["confidence"] > existing[1]:
                conn.execute("""
                    UPDATE normalized_results
                    SET winner_name=?, loser_name=?, winner_side=?,
                        score_p1=?, score_p2=?, score_detail=?,
                        is_overtime=?, raw_data=?, parsed_at=?,
                        normalized_at=datetime('now'), confidence=?
                    WHERE source=? AND source_match_id=? AND sport=?
                """, (
                    norm["winner_name"], norm["loser_name"], norm["winner_side"],
                    norm["score_p1"], norm["score_p2"], norm["score_detail"],
                    norm["is_overtime"], norm["raw_data"], norm["parsed_at"],
                    norm["confidence"],
                    norm["source"], norm["source_match_id"], norm["sport"],
                ))
                inserted += 1
        else:
            conn.execute("""
                INSERT INTO normalized_results
                (source, source_match_id, sport, league, match_date,
                 participant_1, participant_2, winner_name, loser_name, winner_side,
                 score_p1, score_p2, score_detail, status, is_overtime,
                 raw_data, parsed_at, confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                norm["source"], norm["source_match_id"], norm["sport"], norm["league"],
                norm["match_date"],
                norm["participant_1"], norm["participant_2"],
                norm["winner_name"], norm["loser_name"], norm["winner_side"],
                norm["score_p1"], norm["score_p2"], norm["score_detail"],
                norm["status"], norm["is_overtime"],
                norm["raw_data"], norm["parsed_at"], norm["confidence"],
            ))
            inserted += 1

    conn.commit()
    return inserted


def ingest_from_tennis_live_results(conn: sqlite3.Connection, days: int = 7) -> int:
    """Read from tennis_live_results, normalize, upsert into normalized_results."""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT tour, level, tournament, surface, match_date,
               winner_name, loser_name, sets_winner, sets_loser,
               score_detail, source, fetched_at
        FROM tennis_live_results
        WHERE match_date >= ?
        ORDER BY match_date DESC, id DESC
    """, (since,)).fetchall()

    cols = ["tour", "level", "tournament", "surface", "match_date",
            "winner_name", "loser_name", "sets_winner", "sets_loser",
            "score_detail", "source", "fetched_at"]
    dicts = [dict(zip(cols, r)) for r in rows]

    inserted = 0
    for d in dicts:
        norm = normalize_tennis_result(d)
        if norm is None:
            continue

        existing = conn.execute("""
            SELECT id FROM normalized_results
            WHERE source=? AND source_match_id=? AND sport=?
        """, (norm["source"], norm["source_match_id"], norm["sport"])).fetchone()

        if not existing:
            conn.execute("""
                INSERT INTO normalized_results
                (source, source_match_id, sport, league, match_date,
                 participant_1, participant_2, winner_name, loser_name, winner_side,
                 score_p1, score_p2, score_detail, status, is_overtime,
                 raw_data, parsed_at, confidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                norm["source"], norm["source_match_id"], norm["sport"], norm["league"],
                norm["match_date"],
                norm["participant_1"], norm["participant_2"],
                norm["winner_name"], norm["loser_name"], norm["winner_side"],
                norm["score_p1"], norm["score_p2"], norm["score_detail"],
                norm["status"], norm["is_overtime"],
                norm["raw_data"], norm["parsed_at"], norm["confidence"],
            ))
            inserted += 1
            log.info(f"  TENNIS: {norm['winner_name']} beat {norm['loser_name']} "
                     f"({norm['score_detail'] or '?'}) -> normalized")

    conn.commit()
    return inserted


# ============================================================
# Lookup API for settlement
# ============================================================

def lookup_normalized_result(conn: sqlite3.Connection, sport: str,
                              participant_1: str, participant_2: str,
                              match_date: str, market: str = None) -> Optional[Dict[str, Any]]:
    """
    Look up a normalized result for a given match.

    This is the primary lookup for settlement — clean, deterministic, no fuzzy matching.

    Args:
        sport: 'football', 'hockey', 'tennis'
        participant_1: home team or player1 name
        participant_2: away team or player2 name
        match_date: YYYY-MM-DD
        market: optional market for context (e.g., 'draw', 'X')

    Returns:
        Dict with winner_name, winner_side, score_p1, score_p2, is_overtime,
        status, confidence, source — or None if not found.
    """
    # Exact match on normalized names
    row = conn.execute("""
        SELECT winner_name, loser_name, winner_side,
               score_p1, score_p2, score_detail, status,
               is_overtime, confidence, source, league
        FROM normalized_results
        WHERE sport = ?
          AND match_date = ?
          AND (
              (participant_1 = ? AND participant_2 = ?)
              OR (participant_1 = ? AND participant_2 = ?)
          )
          AND status = 'completed'
        ORDER BY confidence DESC, normalized_at DESC
        LIMIT 1
    """, (
        sport, match_date,
        participant_1, participant_2,  # exact order
        participant_2, participant_1,  # reversed order
    )).fetchone()

    if row:
        return {
            "winner_name": row[0],
            "loser_name": row[1],
            "winner_side": row[2],
            "score_p1": row[3],
            "score_p2": row[4],
            "score_detail": row[5],
            "status": row[6],
            "is_overtime": row[7],
            "confidence": row[8],
            "source": row[9],
            "league": row[10],
        }

    # Fuzzy fallback: substring match on participant names (only if exact failed)
    p1_short = participant_1.split()[0] if participant_1 else ""
    p2_short = participant_2.split()[0] if participant_2 else ""
    if len(p1_short) >= 3 and len(p2_short) >= 3:
        row = conn.execute("""
            SELECT winner_name, loser_name, winner_side,
                   score_p1, score_p2, score_detail, status,
                   is_overtime, confidence, source, league
            FROM normalized_results
            WHERE sport = ?
              AND match_date = ?
              AND (
                  (participant_1 LIKE ? AND participant_2 LIKE ?)
                  OR (participant_1 LIKE ? AND participant_2 LIKE ?)
              )
              AND status = 'completed'
            ORDER BY confidence DESC, normalized_at DESC
            LIMIT 1
        """, (
            sport, match_date,
            f"%{p1_short}%", f"%{p2_short}%",
            f"%{p2_short}%", f"%{p1_short}%",
        )).fetchone()

        if row:
            return {
                "winner_name": row[0],
                "loser_name": row[1],
                "winner_side": row[2],
                "score_p1": row[3],
                "score_p2": row[4],
                "score_detail": row[5],
                "status": row[6],
                "is_overtime": row[7],
                "confidence": row[8],
                "source": row[9],
                "league": row[10],
            }

    return None


def result_for_market_normalized(market: str, winner_side: str,
                                  score_p1: int, score_p2: int,
                                  is_overtime: int = 0,
                                  sport: str = "football") -> Optional[str]:
    """
    Determine bet result using normalized data.

    This replaces settler.result_for_market() with normalized semantics.

    Key differences from raw:
    - winner_side is explicit ('participant_1', 'participant_2', 'draw')
    - Hockey OT: regulation time was a draw, so draw market wins
    - No need to re-compare scores for 1X2 markets
    """
    if sport == "hockey" and is_overtime and market in ("draw", "X"):
        # OT match means regulation time was a draw — draw bet wins
        return "won"

    if market in ("home", "home_win", "П1", "participant_1"):
        won = (winner_side == "participant_1")
    elif market in ("draw", "X"):
        won = (winner_side == "draw")
    elif market in ("away", "away_win", "П2", "participant_2"):
        won = (winner_side == "participant_2")
    elif market in ("btts_yes", "ОЗ да", "оз да"):
        won = (score_p1 > 0 and score_p2 > 0)
    elif market in ("btts_no", "ОЗ нет", "оз нет"):
        won = (score_p1 == 0 or score_p2 == 0)
    elif market in ("over_2_5", "тб 2.5", "ТБ 2.5"):
        won = (score_p1 + score_p2) > 2
    elif market in ("under_2_5", "тм 2.5", "ТМ 2.5"):
        won = (score_p1 + score_p2) <= 2
    elif market in ("over_1_5", "тб 1.5", "ТБ 1.5"):
        won = (score_p1 + score_p2) > 1
    elif market in ("under_1_5", "тм 1.5", "ТМ 1.5"):
        won = (score_p1 + score_p2) <= 1
    elif market in ("player1_win",):
        won = (winner_side == "participant_1")
    elif market in ("player2_win",):
        won = (winner_side == "participant_2")
    else:
        return None

    return "won" if won else "lost"


# ============================================================
# Settlement integration (dual-path)
# ============================================================

def settle_with_normalized(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """
    Settle pending bets using normalized_results as primary source.

    Dual-path approach:
    1. Try normalized_results first (exact match)
    2. Fall back to existing raw-source logic if not found
    3. Log which path was used for each settlement

    This is safe: existing flow is not broken, but we track what could
    be served from normalized layer.

    Returns count of settled bets.
    """
    from datetime import datetime as dt

    # Ensure settled_at column
    cols = [row[1] for row in conn.execute("PRAGMA table_info(bets)").fetchall()]
    if "settled_at" not in cols:
        conn.execute("ALTER TABLE bets ADD COLUMN settled_at TEXT")
        conn.commit()

    # Get pending bets with match info
    rows = conn.execute("""
        SELECT
            b.id, b.match_id, b.market, b.odds, b.stake, b.our_probability,
            m.sport, m.league, m.home_team, m.away_team,
            m.home_score, m.away_score, m.status, m.match_date
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE b.result = 'pending'
    """).fetchall()

    settled = 0
    normalized_count = 0
    fallback_count = 0

    for row in rows:
        (bet_id, match_id, market, odds, stake, our_probability,
         sport, league, home_team, away_team,
         home_score, away_score, match_status, match_date) = row

        # Try normalized layer first
        norm = lookup_normalized_result(
            conn, sport, home_team, away_team,
            str(match_date)[:10], market
        )

        if norm and norm["confidence"] >= 0.8:
            # Use normalized result
            result = result_for_market_normalized(
                market, norm["winner_side"],
                norm["score_p1"], norm["score_p2"],
                norm.get("is_overtime", 0), sport
            )
            if result is None:
                continue
            source_label = f"normalized({norm['source']})"
            normalized_count += 1
            hs, as_ = norm["score_p1"], norm["score_p2"]
        else:
            # Fall back to existing raw logic
            # For hockey, re-fetch regulation-time score from results_raw
            if sport == "hockey":
                rt = conn.execute("""
                    SELECT home_score, away_score, is_overtime
                    FROM results_raw
                    WHERE is_finished = 1
                      AND instr(home_team, '(') = 0
                      AND instr(away_team, '(') = 0
                      AND (
                        (home_team = ? AND away_team = ?) OR
                        (home_team LIKE ? AND away_team LIKE ?) OR
                        (home_team LIKE ? AND away_team LIKE ?)
                      )
                      AND match_date LIKE ?
                    ORDER BY CASE WHEN source = 'betz.su' THEN 0 ELSE 1 END,
                             updated_at DESC, id DESC
                    LIMIT 1
                """, (
                    home_team, away_team,
                    f"%{home_team.split()[0]}%", f"%{away_team.split()[0]}%",
                    f"%{home_team.split()[0].lower()}%", f"%{away_team.split()[0].lower()}%",
                    str(match_date)[:10] + "%"
                )).fetchone()

                if rt:
                    hs, as_ = rt[0], rt[1]
                    is_ot = rt[2] if rt[2] is not None else 0
                    if is_ot and market in ("draw", "X"):
                        hs, as_ = 1, 1
                else:
                    continue
            else:
                hs, as_ = home_score, away_score
                if hs is None or as_ is None:
                    continue

            # Import the original function
            from settler import result_for_market
            result = result_for_market(market, hs, as_)
            if result is None:
                continue
            source_label = "raw_fallback"
            fallback_count += 1

        # Calculate profit
        if result == "won":
            profit = round(stake * (odds - 1), 2)
            actual_result = 1
        else:
            profit = round(-stake, 2)
            actual_result = 0

        settled_at = dt.now().strftime("%Y-%m-%d %H:%M:%S")

        if not dry_run:
            conn.execute("""
                UPDATE bets
                SET result = ?, profit = ?, settled_at = COALESCE(settled_at, ?)
                WHERE id = ?
            """, (result, profit, settled_at, bet_id))

            conn.execute("""
                INSERT INTO accuracy_log
                (sport, league, market, predicted_prob, actual_result, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (sport, league, market, our_probability, actual_result, settled_at))

        settled += 1
        print(f"SETTLED [{source_label}]: {home_team} vs {away_team} | "
              f"{market} -> {result} | profit={profit}")

    if not dry_run:
        conn.commit()

    print(f"\nSettled {settled} bets total: "
          f"{normalized_count} from normalized, {fallback_count} from raw fallback")
    return settled


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(description="Result Normalization Layer")
    ap.add_argument("--sport", choices=["football", "hockey", "tennis"], default=None)
    ap.add_argument("--all", action="store_true", help="Normalize all sports")
    ap.add_argument("--days", type=int, default=7, help="Days back to normalize")
    ap.add_argument("--date", default=None, help="Specific date (YYYY-MM-DD)")
    ap.add_argument("--settle", action="store_true", help="Settle using normalized layer")
    ap.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    ap.add_argument("--stats", action="store_true", help="Show normalized_results stats")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    ensure_table(conn)

    if args.stats:
        print("\n=== Normalized Results Stats ===")
        for sport in ["football", "hockey", "tennis"]:
            count = conn.execute(
                "SELECT COUNT(*) FROM normalized_results WHERE sport=?", (sport,)
            ).fetchone()[0]
            print(f"  {sport}: {count}")

        total = conn.execute("SELECT COUNT(*) FROM normalized_results").fetchone()[0]
        print(f"  TOTAL: {total}")

        # Confidence distribution
        print("\nConfidence distribution:")
        for row in conn.execute("""
            SELECT
                CASE
                    WHEN confidence >= 1.0 THEN '1.0 (exact)'
                    WHEN confidence >= 0.9 THEN '0.9-0.99'
                    WHEN confidence >= 0.8 THEN '0.8-0.89'
                    ELSE '<0.8'
                END as bucket,
                COUNT(*) as cnt
            FROM normalized_results
            GROUP BY bucket
            ORDER BY bucket
        """).fetchall():
            print(f"  {row[0]}: {row[1]}")

        # Source distribution
        print("\nSource distribution:")
        for row in conn.execute("""
            SELECT source, sport, COUNT(*) as cnt
            FROM normalized_results
            GROUP BY source, sport
            ORDER BY cnt DESC
        """).fetchall():
            print(f"  {row[0]} / {row[1]}: {row[2]}")

        conn.close()
        return

    if args.settle:
        count = settle_with_normalized(conn, dry_run=args.dry_run)
        conn.close()
        print(f"\nDone: {count} bets settled")
        return

    # Normalize
    days = args.days
    if args.date:
        days = 1

    sports = []
    if args.all:
        sports = ["football", "hockey", "tennis"]
    elif args.sport:
        sports = [args.sport]
    else:
        sports = ["football", "hockey", "tennis"]

    total = 0
    for sport in sports:
        log.info(f"Normalizing {sport} (last {days} days)...")
        if sport == "tennis":
            count = ingest_from_tennis_live_results(conn, days=days)
        else:
            count = ingest_from_results_raw(conn, sport=sport, days=days)
        log.info(f"  {sport}: {count} records normalized")
        total += count

    conn.close()
    log.info(f"Done: {total} total records normalized")


if __name__ == "__main__":
    main()
