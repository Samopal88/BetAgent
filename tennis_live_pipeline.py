#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — Tennis Live Pipeline

Loads live tennis matches from Fonbet (parser_v2), normalizes player names,
maps Russian -> English, builds feature rows from historical data,
predicts winner probability via the trained LightGBM model,
calculates fair odds / edge, filters betting opportunities,
and saves signals to SQLite.

Usage:
    python tennis_live_pipeline.py --dry-run
    python tennis_live_pipeline.py --dry-run --limit 5
    python tennis_live_pipeline.py  # live mode (saves signals)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import lightgbm as lgb
import numpy as np

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "betagent.db")
MODEL_PATH = str(BASE_DIR / "models/tennis_hybrid_v1.pkl")
META_PATH = str(BASE_DIR / "models/tennis_hybrid_meta_v1.pkl")

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("tennis_pipeline")

# ------------------------------------------------------------------
# Sport profile (from sport_profiles.json)
# ------------------------------------------------------------------
TENNIS_PROFILE = {
    "no_lineup_cap": 0.65,
    "weak_no_lineup_cap": 0.62,
    "lineup_cap": 0.75,
    "no_h2h_penalty": 0.00,
    "short_form_penalty_3": 0.02,
    "short_form_penalty_5": 0.01,
    "medium_no_lineup_penalty": 0.00,
    "weak_no_lineup_penalty": 0.01,
    "min_edge_vs_market": 0.04,
    "min_ev": 0.05,
    "probability_floor": 0.35,
}

# ------------------------------------------------------------------
# Model features (must match training)
# ------------------------------------------------------------------
FEATURE_COLS = [
    "rank_diff", "rank_pts_diff",
    "player_win_pct_5", "player_win_pct_10",
    "player_ss_pct_5", "player_ss_pct_10",
    "opponent_win_pct_5", "opponent_win_pct_10",
    "opponent_ss_pct_5", "opponent_ss_pct_10",
    "player_ace_avg", "player_df_avg", "player_1st_in_avg",
    "player_1st_won_pct", "player_bp_saved_pct", "player_minutes_avg",
    "opponent_ace_avg", "opponent_df_avg", "opponent_1st_in_avg",
    "opponent_1st_won_pct", "opponent_bp_saved_pct", "opponent_minutes_avg",
    "player_surface_win_pct", "player_surface_matches",
    "player_surface_ace_avg", "player_surface_1st_won_pct", "player_surface_bp_saved_pct",
    "opponent_surface_win_pct", "opponent_surface_matches",
    "opponent_surface_ace_avg", "opponent_surface_1st_won_pct", "opponent_surface_bp_saved_pct",
    "player_days_rest", "player_matches_7d", "player_matches_14d", "player_minutes_14d",
    "opponent_days_rest", "opponent_matches_7d", "opponent_matches_14d", "opponent_minutes_14d",
    "h2h_player_wins", "h2h_opponent_wins", "h2h_total",
]

DERIVED_COLS = [
    "player_form_diff", "opponent_form_diff",
    "serve_diff", "return_diff",
    "fatigue_diff", "surface_diff",
    "h2h_edge",
    # New hybrid features
    "rank_ratio", "surface_advantage", "momentum",
]

ALL_FEATURES = FEATURE_COLS + DERIVED_COLS


# ================================================================
# 1. Model loading
# ================================================================
def load_model():
    """Load the LightGBM winner model and metadata."""
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    with open(META_PATH, "rb") as f:
        meta = pickle.load(f)
    log.info(f"Model loaded: {meta.get('model_version')}, {model.num_trees()} trees, {model.num_feature()} features")
    return model, meta


# ================================================================
# 2. Name normalization & mapping
# ================================================================
# Russian -> Cyrillic initial -> English initial (for surname+initial parsing)
CYR_INITIAL_MAP = {
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E',
    'Ё': 'Yo', 'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L',
    'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S',
    'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch',
    'Ш': 'Sh', 'Щ': 'Sch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E',
    'Ю': 'Yu', 'Я': 'Ya',
}

# Secondary mapping from TENNIS_DATA_TO_BETZ (Cyrillic -> English)
# Loaded lazily from tennis_player_mapping_tdo.py
_SECONDARY_MAP: Optional[Dict[str, str]] = None


def _load_secondary_mapping() -> Dict[str, str]:
    """Load Cyrillic -> English mapping from tennis_player_mapping_tdo.py."""
    global _SECONDARY_MAP
    if _SECONDARY_MAP is not None:
        return _SECONDARY_MAP
    try:
        from tennis_player_mapping_tdo import TENNIS_DATA_TO_BETZ
        # Reverse: Russian -> English
        _SECONDARY_MAP = {}
        for eng, rus in TENNIS_DATA_TO_BETZ.items():
            _SECONDARY_MAP[rus.strip()] = eng.strip()
        log.info(f"Loaded {len(_SECONDARY_MAP)} secondary mappings from TENNIS_DATA_TO_BETZ")
    except ImportError:
        _SECONDARY_MAP = {}
        log.warning("TENNIS_DATA_TO_BETZ not available")
    return _SECONDARY_MAP


def load_name_mapping(conn) -> Dict[str, str]:
    """Load confident (needs_review=0) Russian -> English name mapping."""
    mapping = {}
    for rus, eng in conn.execute(
        "SELECT rus_name, eng_name FROM tennis_player_mapping WHERE needs_review = 0"
    ).fetchall():
        mapping[rus.strip()] = eng.strip()
    log.info(f"Loaded {len(mapping)} confident name mappings")
    return mapping


def load_name_lookup(conn) -> Dict[str, str]:
    """Load tennis_name_lookup: Fonbet betz_name -> stable English name.
    This table has broader coverage than tennis_player_mapping and catches
    name variants like 'Blockx A.', 'Mertens E.' that aren't in the main mapping.
    """
    lookup = {}
    for betz_name, eng_name in conn.execute(
        "SELECT betz_name, eng_name FROM tennis_name_lookup"
    ).fetchall():
        lookup[betz_name.strip().lower()] = eng_name.strip().lower()
    log.info(f"Loaded {len(lookup)} name lookup entries")
    return lookup


def normalize_player_name(raw_name: str) -> str:
    """Strip extra whitespace, normalize."""
    return " ".join(raw_name.strip().split())


def canonicalize_name(raw_name: str, name_map: Dict[str, str], name_lookup: Dict[str, str]) -> str:
    """Resolve any name variant (English or Russian) to a stable canonical form.

    Priority:
    1. tennis_name_lookup (betz_name -> eng_name) — widest coverage of Fonbet variants
    2. tennis_player_mapping (rus_name -> eng_name) — confident mappings only
    3. Fallback: lowercase + strip the raw name itself

    Returns lowercase stable English name for dedup purposes.
    """
    key = raw_name.strip().lower()

    # 1) Check name lookup first (catches 'Blockx A.', 'Mertens E.', etc.)
    if key in name_lookup:
        return name_lookup[key]

    # 2) Check player mapping (Russian -> English)
    if key in name_map:
        return name_map[key].lower()

    # 3) Fallback: use the raw name normalized
    return key


def normalize_tennis_russian_name(raw_name: str) -> str:
    """Stable Russian-first normalization for live tennis identity fallback."""
    return " ".join((raw_name or "").strip().lower().replace("ё", "е").replace(".", "").split())


def build_tennis_live_identity(
    source_match_id: Optional[str],
    player1: str,
    player2: str,
    match_date: str,
    market: str,
) -> str:
    """Stable live tennis identity.

    Primary:
    - source_match_id + market
    Fallback only if source_match_id missing:
    - normalized Russian player1 + player2 + match_date + market
    """
    source_key = (source_match_id or "").strip()
    if source_key:
        return f"tennis_live:{source_key}:{market}"
    return "tennis_live_fallback:{p1}:{p2}:{date}:{market}".format(
        p1=normalize_tennis_russian_name(player1),
        p2=normalize_tennis_russian_name(player2),
        date=(match_date or "")[:10],
        market=market,
    )


def build_tennis_match_identity(
    source_match_id: Optional[str],
    player1: str,
    player2: str,
    match_date: str,
) -> str:
    """Stable match identity for the shared matches row."""
    source_key = (source_match_id or "").strip()
    if source_key:
        return f"tennis_live_match:{source_key}"
    return "tennis_live_match_fallback:{p1}:{p2}:{date}".format(
        p1=normalize_tennis_russian_name(player1),
        p2=normalize_tennis_russian_name(player2),
        date=(match_date or "")[:10],
    )


def _strip_dots(s: str) -> str:
    """Remove dots and normalize spacing — 'Хачанов К.' -> 'Хачанов К'."""
    return s.replace('.', '').strip()


def _parse_surname_initial(rus_name: str) -> Optional[Tuple[str, str]]:
    """Parse 'Surname Initial' or 'Surname I.' format.
    Returns (surname_lower, initial_letter) or None.
    Handles hyphenated initials like 'Я-Л', 'Т-К', 'Э-М'.
    """
    cleaned = _strip_dots(rus_name)
    parts = cleaned.split()
    if len(parts) == 2:
        last = parts[1]
        # Check if last part looks like an initial (single letter or hyphenated initials)
        is_initial = (
            (len(last) <= 4 and last.replace('-', '').isalpha())
        )
        if is_initial:
            return parts[0].lower(), last.upper()
    if len(parts) >= 2:
        last = parts[-1]
        is_initial = (
            (len(last) <= 4 and last.replace('-', '').isalpha())
        )
        if is_initial:
            surname = ' '.join(parts[:-1]).lower()
            return surname, last.upper()
    return None


def map_player(rus_name: str, mapping: Dict[str, str]) -> Optional[str]:
    """Map a Russian bookmaker name to English. Returns None if not found.

    Tries in order:
    1. Exact match in confident mapping
    2. Case-insensitive match
    3. Strip dots and match (Fonbet has no dots, mapping table has dots)
    4. Parse 'Surname Initial' and match against mapping entries
    5. Secondary mapping from TENNIS_DATA_TO_BETZ
    6. Fallback surname-only lookup for top players
    """
    cleaned = normalize_player_name(rus_name)

    # 1. Exact match
    if cleaned in mapping:
        return mapping[cleaned]

    # 2. Case-insensitive
    lower_map = {k.lower(): v for k, v in mapping.items()}
    if cleaned.lower() in lower_map:
        return lower_map[cleaned.lower()]

    # 3. Strip dots and try again
    no_dots = _strip_dots(cleaned)
    if no_dots in mapping:
        return mapping[no_dots]
    if no_dots.lower() in lower_map:
        return lower_map[no_dots.lower()]

    # 4. Parse "Surname Initial" and try to match against mapping entries
    parsed = _parse_surname_initial(cleaned)
    if parsed:
        surname_lower, initial = parsed
        # Try matching against mapping entries with same surname+initial pattern
        for k, v in mapping.items():
            k_norm = _strip_dots(k).lower()
            if k_norm == f"{surname_lower} {initial}":
                return v
        # Try matching surname + initial against full names in mapping
        for k, v in mapping.items():
            k_lower = k.lower()
            k_parts = k_lower.split()
            if len(k_parts) >= 2:
                for part in k_parts:
                    part_clean = part.strip('.')
                    if part_clean == surname_lower:
                        for wp in k_parts:
                            wp_clean = wp.strip('.')
                            if wp_clean and wp_clean[0].upper() == initial:
                                return v

    # 5. Secondary mapping from TENNIS_DATA_TO_BETZ
    secondary = _load_secondary_mapping()
    if cleaned in secondary:
        return secondary[cleaned]
    if no_dots in secondary:
        return secondary[no_dots]
    # Try partial match in secondary (surname+initial against full names)
    if parsed:
        surname_lower, initial = parsed
        for k, v in secondary.items():
            k_norm = _strip_dots(k).lower()
            if k_norm == f"{surname_lower} {initial}":
                return v
            # Match surname + initial against full name entries
            # e.g. "Хачанов К" vs "Карен Хачанов"
            k_parts = k_norm.split()
            if len(k_parts) >= 2:
                for part in k_parts:
                    part_clean = part.strip('.')
                    if part_clean == surname_lower:
                        # Check if any word's first letter matches the initial
                        for wp in k_parts:
                            wp_clean = wp.strip('.')
                            if wp_clean:
                                first_char = wp_clean[0]
                                # Transliterate Cyrillic first char to Latin
                                latin_first = CYR_INITIAL_MAP.get(first_char.upper(), first_char.upper())
                                if latin_first == initial:
                                    return v

    # 6. Fallback: try matching just surname in secondary (no initial check)
    if parsed:
        surname_lower = parsed[0]
        for k, v in secondary.items():
            k_parts = k.lower().split()
            if len(k_parts) >= 2:
                # Check if any part matches the surname
                for part in k_parts:
                    if part.strip('.') == surname_lower:
                        return v

    return None


# ================================================================
# 3. Load live matches from parser_v2
# ================================================================
def load_live_matches(only_sport: str = "tennis") -> List[Dict[str, Any]]:
    """
    Import parser_v2 and call parse_fonbet_data.
    Returns list of tennis match dicts.
    """
    sys.path.insert(0, str(BASE_DIR))
    from parser_v2 import parse_fonbet_data, get_fonbet_data

    raw_data = get_fonbet_data()
    if not raw_data:
        log.warning("No data from Fonbet API")
        return []

    all_matches, all_tennis = parse_fonbet_data(raw_data, only_sport=only_sport)
    log.info(f"Parser returned {len(all_tennis)} tennis matches")
    return all_tennis


# ================================================================
# 4. Historical feature builder
# ================================================================
class TennisFeatureBuilder:
    """Builds feature rows for live tennis matches from historical SQLite data."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._cache_player_history: Dict[str, List[Tuple]] = {}
        self._cache_h2h: Dict[Tuple[str, str], List[Tuple]] = {}

    def _player_history(self, player_name: str) -> List[Tuple]:
        """Get all historical matches for a player (from backtest_tennis_players).

        Searches by Russian name first (winner_rus_name/loser_rus_name),
        then falls back to English name (winner_name/loser_name).
        Normalizes ё→е and strips dots for Cyrillic matching.
        Returns rows with both English and Russian names for comparison.
        """
        if player_name not in self._cache_player_history:
            # Normalize: ё→е, strip dots, for Cyrillic comparison
            rus_normalized = player_name.replace('ё', 'е').replace('.', '').strip()
            rows = self.conn.execute("""
                SELECT tourney_date, tour, surface,
                       winner_name, loser_name,
                       winner_rus_name, loser_rus_name,
                       winner_rank, loser_rank,
                       w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
                       l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
                       minutes, sets_loser, straight_sets
                FROM backtest_tennis_players
                WHERE REPLACE(REPLACE(LOWER(winner_rus_name), 'ё', 'е'), '.', '') = LOWER(?)
                   OR REPLACE(REPLACE(LOWER(loser_rus_name), 'ё', 'е'), '.', '') = LOWER(?)
                   OR LOWER(winner_name) = LOWER(?) OR LOWER(loser_name) = LOWER(?)
                ORDER BY tourney_date
            """, (rus_normalized, rus_normalized, player_name, player_name)).fetchall()
            self._cache_player_history[player_name] = rows
        return self._cache_player_history[player_name]

    def _h2h(self, p1: str, p2: str, before_date: str = None) -> List[Tuple]:
        """Get head-to-head matches between two players BEFORE a given date.

        Searches by both Russian and English name columns.
        Normalizes ё→е and strips dots for Cyrillic matching.
        """
        key = tuple(sorted([p1.lower(), p2.lower()]))
        if key not in self._cache_h2h:
            rus1 = p1.replace('ё', 'е').replace('.', '').strip()
            rus2 = p2.replace('ё', 'е').replace('.', '').strip()
            rows = self.conn.execute("""
                SELECT tourney_date, surface,
                       winner_name, loser_name,
                       winner_rus_name, loser_rus_name,
                       sets_loser
                FROM backtest_tennis_players
                WHERE (REPLACE(REPLACE(LOWER(winner_rus_name), 'ё', 'е'), '.', '') IN (LOWER(?), LOWER(?))
                       OR LOWER(winner_name) IN (LOWER(?), LOWER(?)))
                  AND (REPLACE(REPLACE(LOWER(loser_rus_name), 'ё', 'е'), '.', '') IN (LOWER(?), LOWER(?))
                       OR LOWER(loser_name) IN (LOWER(?), LOWER(?)))
                ORDER BY tourney_date
            """, (rus1, rus2, p1, p2, rus1, rus2, p1, p2)).fetchall()
            self._cache_h2h[key] = rows
        matches = self._cache_h2h[key]
        if before_date:
            matches = [m for m in matches if m[0] < before_date]
        return matches

    def _recent_matches(self, history: List[Tuple], eng_name: str, before_date: str, n: int = 10) -> List[Tuple]:
        """Get last n matches for a player before a given date."""
        col_w = "winner_name"
        col_l = "loser_name"
        prev = [
            r for r in history
            if r[0] < before_date
        ]
        prev.sort(key=lambda x: x[0], reverse=True)
        return prev[:n]

    def _player_stats(self, player_name: str, matches: List[Tuple], surface: str) -> Dict[str, float]:
        """Compute stats from a list of player matches."""
        if not matches:
            return {}

        wins = 0
        straight_sets = 0
        total_ace = 0
        total_df = 0
        total_1st_in = 0
        total_1st_won = 0
        total_bp_saved = 0
        total_bp_Faced = 0
        total_minutes = 0
        n = len(matches)

        for row in matches:
            (tourney_date, tour, surf,
             winner, loser, winner_rus, loser_rus,
             w_rank, l_rank,
             w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
             l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
             minutes, sets_loser, straight) = row

            # Match against both English and Russian names (normalize ё→е, strip dots)
            pn = player_name.lower().replace('ё', 'е').replace('.', '')
            is_winner = (winner.lower() == player_name.lower()
                         or (winner_rus and winner_rus.lower().replace('ё', 'е').replace('.', '') == pn))
            if is_winner:
                wins += 1
                if sets_loser == 0:
                    straight_sets += 1
                total_ace += (w_ace or 0)
                total_df += (w_df or 0)
                total_1st_in += (w_1stIn or 0)
                total_1st_won += (w_1stWon or 0)
                total_bp_saved += (w_bpSaved or 0)
                total_bp_Faced += (w_bpFaced or 0)
                total_minutes += (minutes or 0)
            else:
                total_ace += (l_ace or 0)
                total_df += (l_df or 0)
                total_1st_in += (l_1stIn or 0)
                total_1st_won += (l_1stWon or 0)
                total_bp_saved += (l_bpSaved or 0)
                total_bp_Faced += (l_bpFaced or 0)
                total_minutes += (minutes or 0)

        return {
            "win_pct": wins / n * 100 if n else 0,
            "ss_pct": straight_sets / n * 100 if n else 0,
            "ace_avg": total_ace / n if n else 0,
            "df_avg": total_df / n if n else 0,
            "1st_in_avg": total_1st_in / n if n else 0,
            "1st_won_pct": (total_1st_won / total_1st_in * 100) if total_1st_in > 0 else 0,
            "bp_saved_pct": (total_bp_saved / total_bp_Faced * 100) if total_bp_Faced > 0 else 0,
            "minutes_avg": total_minutes / n if n else 0,
        }

    def _surface_stats(self, eng_name: str, history: List[Tuple], surface: str) -> Dict[str, float]:
        """Compute surface-specific stats."""
        surf_matches = [r for r in history if r[2] and surface.lower() in str(r[2]).lower()]
        if not surf_matches:
            return {}
        return self._player_stats(eng_name, surf_matches, surface)

    def _rank_info(self, player_name: str, history: List[Tuple], before_date: str) -> Tuple[Optional[int], Optional[int]]:
        """Get latest rank before the match date."""
        prev = [r for r in history if r[0] < before_date]
        if not prev:
            return None, None
        prev.sort(key=lambda x: x[0], reverse=True)
        latest = prev[0]
        # Columns: 0=date, 1=tour, 2=surface, 3=winner_en, 4=loser_en, 5=winner_ru, 6=loser_ru, 7=w_rank, 8=l_rank
        pn = player_name.lower().replace('ё', 'е').replace('.', '')
        is_winner = (latest[3].lower() == player_name.lower()
                     or (latest[5] and latest[5].lower().replace('ё', 'е').replace('.', '') == pn))
        rank = latest[7] if is_winner else latest[8]
        rank_pts = None  # not always available
        return rank, rank_pts

    def _days_rest(self, eng_name: str, history: List[Tuple], match_date: str) -> int:
        """Days since last match."""
        prev = [r for r in history if r[0] < match_date]
        if not prev:
            return 14  # default
        prev.sort(key=lambda x: x[0], reverse=True)
        last_date = prev[0][0]
        try:
            d1 = datetime.strptime(match_date, "%Y-%m-%d")
            d2 = datetime.strptime(last_date, "%Y-%m-%d")
            return (d1 - d2).days
        except Exception:
            return 14

    def _matches_in_window(self, eng_name: str, history: List[Tuple], match_date: str, days: int) -> int:
        """Count matches in the last N days."""
        try:
            md = datetime.strptime(match_date, "%Y-%m-%d")
        except Exception:
            return 0
        cutoff = md - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        return sum(1 for r in history if cutoff_str <= r[0] < match_date)

    def _minutes_in_window(self, player_name: str, history: List[Tuple], match_date: str, days: int) -> int:
        """Sum minutes played in the last N days."""
        try:
            md = datetime.strptime(match_date, "%Y-%m-%d")
        except Exception:
            return 0
        cutoff = md - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        total = 0
        pn = player_name.lower().replace('ё', 'е').replace('.', '')
        for r in history:
            if cutoff_str <= r[0] < match_date:
                # Columns: 3=winner_en, 5=winner_ru, 24=minutes
                is_winner = (r[3].lower() == player_name.lower()
                             or (r[5] and r[5].lower().replace('ё', 'е').replace('.', '') == pn))
                total += (r[24] or 0)  # minutes
        return total

    def _h2h_stats(self, p1: str, p2: str, before_date: str = None) -> Dict[str, int]:
        """H2H wins for each player, only counting matches before the given date."""
        matches = self._h2h(p1, p2, before_date=before_date)
        def _normalize(name: str) -> str:
            return name.lower().replace('ё', 'е').replace('.', '')
        def _is_p1_winner(m):
            return (_normalize(m[2]) == _normalize(p1) or (m[4] and _normalize(m[4]) == _normalize(p1)))
        def _is_p2_winner(m):
            return (_normalize(m[2]) == _normalize(p2) or (m[4] and _normalize(m[4]) == _normalize(p2)))
        p1_wins = sum(1 for m in matches if _is_p1_winner(m))
        p2_wins = sum(1 for m in matches if _is_p2_winner(m))
        return {
            "h2h_player_wins": p1_wins,
            "h2h_opponent_wins": p2_wins,
            "h2h_total": len(matches),
        }

    def build_features(self, player1_eng: str, player2_eng: str,
                       match_date: str, surface: str = "hard") -> Optional[Dict[str, float]]:
        """Build a complete feature row for a match."""
        hist1 = self._player_history(player1_eng)
        hist2 = self._player_history(player2_eng)

        if not hist1 and not hist2:
            return None

        # Recent form (last 5 and 10)
        recent1_5 = self._recent_matches(hist1, player1_eng, match_date, n=5)
        recent1_10 = self._recent_matches(hist1, player1_eng, match_date, n=10)
        recent2_5 = self._recent_matches(hist2, player2_eng, match_date, n=5)
        recent2_10 = self._recent_matches(hist2, player2_eng, match_date, n=10)

        stats1_5 = self._player_stats(player1_eng, recent1_5, surface)
        stats1_10 = self._player_stats(player1_eng, recent1_10, surface)
        stats2_5 = self._player_stats(player2_eng, recent2_5, surface)
        stats2_10 = self._player_stats(player2_eng, recent2_10, surface)

        # Surface stats
        surf1 = self._surface_stats(player1_eng, hist1, surface)
        surf2 = self._surface_stats(player2_eng, hist2, surface)

        # Rank
        rank1, rank_pts1 = self._rank_info(player1_eng, hist1, match_date)
        rank2, rank_pts2 = self._rank_info(player2_eng, hist2, match_date)

        # Rest & fatigue
        rest1 = self._days_rest(player1_eng, hist1, match_date)
        rest2 = self._days_rest(player2_eng, hist2, match_date)
        m7_1 = self._matches_in_window(player1_eng, hist1, match_date, 7)
        m7_2 = self._matches_in_window(player2_eng, hist2, match_date, 7)
        m14_1 = self._matches_in_window(player1_eng, hist1, match_date, 14)
        m14_2 = self._matches_in_window(player2_eng, hist2, match_date, 14)
        min14_1 = self._minutes_in_window(player1_eng, hist1, match_date, 14)
        min14_2 = self._minutes_in_window(player2_eng, hist2, match_date, 14)

        # H2H (only prior matches)
        h2h = self._h2h_stats(player1_eng, player2_eng, before_date=match_date)

        # Build feature dict
        feat = {
            "player_rank": rank1 or 500,
            "opponent_rank": rank2 or 500,
            "rank_diff": (rank1 or 500) - (rank2 or 500),
            "rank_pts_diff": (rank_pts1 or 0) - (rank_pts2 or 0),
            "player_win_pct_5": stats1_5.get("win_pct", 50),
            "player_win_pct_10": stats1_10.get("win_pct", 50),
            "player_ss_pct_5": stats1_5.get("ss_pct", 30),
            "player_ss_pct_10": stats1_10.get("ss_pct", 30),
            "opponent_win_pct_5": stats2_5.get("win_pct", 50),
            "opponent_win_pct_10": stats2_10.get("win_pct", 50),
            "opponent_ss_pct_5": stats2_5.get("ss_pct", 30),
            "opponent_ss_pct_10": stats2_10.get("ss_pct", 30),
            "player_ace_avg": stats1_10.get("ace_avg", 3),
            "player_df_avg": stats1_10.get("df_avg", 2),
            "player_1st_in_avg": stats1_10.get("1st_in_avg", 40),
            "player_1st_won_pct": stats1_10.get("1st_won_pct", 65),
            "player_bp_saved_pct": stats1_10.get("bp_saved_pct", 60),
            "player_minutes_avg": stats1_10.get("minutes_avg", 90),
            "opponent_ace_avg": stats2_10.get("ace_avg", 3),
            "opponent_df_avg": stats2_10.get("df_avg", 2),
            "opponent_1st_in_avg": stats2_10.get("1st_in_avg", 40),
            "opponent_1st_won_pct": stats2_10.get("1st_won_pct", 65),
            "opponent_bp_saved_pct": stats2_10.get("bp_saved_pct", 60),
            "opponent_minutes_avg": stats2_10.get("minutes_avg", 90),
            "player_surface_win_pct": surf1.get("win_pct", 50),
            "player_surface_matches": surf1.get("win_pct", 0) and len([r for r in hist1 if r[2] and surface.lower() in str(r[2]).lower()]) or 0,
            "player_surface_ace_avg": surf1.get("ace_avg", 3),
            "player_surface_1st_won_pct": surf1.get("1st_won_pct", 65),
            "player_surface_bp_saved_pct": surf1.get("bp_saved_pct", 60),
            "opponent_surface_win_pct": surf2.get("win_pct", 50),
            "opponent_surface_matches": surf2.get("win_pct", 0) and len([r for r in hist2 if r[2] and surface.lower() in str(r[2]).lower()]) or 0,
            "opponent_surface_ace_avg": surf2.get("ace_avg", 3),
            "opponent_surface_1st_won_pct": surf2.get("1st_won_pct", 65),
            "opponent_surface_bp_saved_pct": surf2.get("bp_saved_pct", 60),
            "player_days_rest": rest1,
            "player_matches_7d": m7_1,
            "player_matches_14d": m14_1,
            "player_minutes_14d": min14_1,
            "opponent_days_rest": rest2,
            "opponent_matches_7d": m7_2,
            "opponent_matches_14d": m14_2,
            "opponent_minutes_14d": min14_2,
            **h2h,
        }

        # Derived features
        feat["player_form_diff"] = feat["player_win_pct_5"] - feat["opponent_win_pct_5"]
        feat["opponent_form_diff"] = feat["opponent_win_pct_10"] - feat["player_win_pct_10"]
        feat["serve_diff"] = feat["player_1st_won_pct"] - feat["opponent_1st_won_pct"]
        feat["return_diff"] = feat["player_bp_saved_pct"] - feat["opponent_bp_saved_pct"]
        feat["fatigue_diff"] = feat["player_matches_14d"] - feat["opponent_matches_14d"]
        feat["surface_diff"] = feat["player_surface_win_pct"] - feat["opponent_surface_win_pct"]
        feat["h2h_edge"] = feat["h2h_player_wins"] - feat["h2h_opponent_wins"]

        # New hybrid features
        opp_rank = max(feat["opponent_rank"], 1)
        feat["rank_ratio"] = feat["player_rank"] / opp_rank
        feat["rank_ratio"] = max(0.01, min(100, feat["rank_ratio"]))
        feat["surface_advantage"] = feat["player_surface_win_pct"] - feat["opponent_surface_win_pct"]
        feat["momentum"] = feat["player_win_pct_5"] - feat["player_win_pct_10"]

        return feat


# ================================================================
# 5. Probability calibration — RAW probabilities (no temperature scaling)
# ================================================================
def calibrate_probability(raw_prob: float, profile: Dict,
                          n_form: int = 10, has_h2h: bool = False) -> float:
    """Return RAW model probability — no temperature scaling.

    Temperature scaling was found to create artificial edge for underdogs.
    Raw probabilities give honest EV calculation: EV = raw_prob * odds - 1.
    """
    return round(raw_prob, 4)


# ================================================================
# 6. EV / Kelly
# ================================================================
def compute_ev(probability: float, odds: float) -> float:
    return probability * odds - 1.0


def compute_kelly(probability: float, odds: float) -> float:
    if odds <= 1.0:
        return -1.0
    return (probability * odds - 1.0) / (odds - 1.0)


def _create_tennis_bet(conn, sig: dict, bankroll: float) -> Optional[int]:
    """Create matches + bets entries for a tennis signal. Returns bet id or None."""
    p1 = sig["player1"]
    p2 = sig["player2"]
    match_date = sig["match_date"]
    league = sig["league"]
    market = sig["market"]
    odds = sig["odds_p1"] if market == "player1_win" else sig["odds_p2"]
    our_prob = sig["our_probability"]
    ev = sig["ev"]
    edge = sig["edge"]
    kelly_q = sig["kelly_quarter"]
    stake_pct = sig["stake_pct"]
    stake_amount = round(bankroll * stake_pct, 2)
    signal_type = sig["signal_type"]
    confidence = sig["confidence"]
    facts = sig["confirmed_facts"]
    source_match_id = sig.get("source_match_id")
    live_identity = sig["live_identity"]
    match_identity = sig["match_identity"]

    existing = conn.execute("""
        SELECT id FROM bets WHERE created_by = ? LIMIT 1
    """, (live_identity,)).fetchone()
    if existing:
        return existing[0]

    # Create matches entry using the live match identity.
    fonbet_id = source_match_id or match_identity
    conn.execute("""
        INSERT OR IGNORE INTO matches (fonbet_id, sport, league, home_team, away_team, match_date)
        VALUES (?, 'tennis', ?, ?, ?, ?)
    """, (fonbet_id, league, p1, p2, match_date))
    match_id = conn.execute("SELECT id FROM matches WHERE fonbet_id = ?", (fonbet_id,)).fetchone()[0]

    # Create bets entry
    cursor = conn.execute("""
        INSERT INTO bets (
            match_id, market, odds, our_probability, ev, kelly_quarter,
            stake, stake_pct, result, created_at, signal_type, confidence,
            created_by, edge, model_prob, market_prob
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'), ?, ?,
                  ?, ?, ?, ?)
    """, (
        match_id, market, odds, our_prob, ev, kelly_q,
        stake_amount, stake_pct, signal_type, confidence,
        live_identity, edge, our_prob, sig["market_probability"],
    ))
    bet_id = cursor.lastrowid
    log.info(f"  BET created: {p1} vs {p2} | {market} @ {odds:.2f} | stake={stake_amount:.0f} RUB")
    return bet_id


def _get_bankroll() -> float:
    """Read current bankroll from bets table."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        row = conn.execute(
            "SELECT COALESCE(SUM(profit),0) FROM bets WHERE result IN ('won','lost')"
        ).fetchone()
        conn.close()
        initial = float(os.getenv("BETAGENT_BANK", "100000"))
        return initial + float(row[0] or 0)
    except Exception:
        return float(os.getenv("BETAGENT_BANK", "100000"))


# ================================================================
# 7. Main pipeline
# ================================================================
def run_pipeline(dry_run: bool = False, limit: Optional[int] = None):
    """
    Full tennis live pipeline:
    1. Load live matches from Fonbet
    2. Map player names
    3. Build features from historical data
    4. Predict winner probability
    5. Calculate fair odds / edge
    6. Filter betting opportunities
    7. Save signals to DB
    """
    t0 = time.time()
    log.info("=" * 70)
    log.info("TENNIS LIVE PIPELINE")
    log.info("=" * 70)

    # Load model
    model, meta = load_model()
    profile = TENNIS_PROFILE

    # Connect to DB
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    # Load live matches
    live_matches = load_live_matches(only_sport="tennis")
    if not live_matches:
        log.warning("No live tennis matches found. Exiting.")
        conn.close()
        return []

    if limit:
        live_matches = live_matches[:limit]
        log.info(f"Limited to {limit} matches")

    # Feature builder
    builder = TennisFeatureBuilder(conn)

    # Ensure signals table exists for tennis
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tennis_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_date TEXT,
            league TEXT,
            player1 TEXT,
            player2 TEXT,
            player1_eng TEXT,
            player2_eng TEXT,
            surface TEXT,
            odds_p1 REAL,
            odds_p2 REAL,
            market TEXT,
            our_probability REAL,
            market_probability REAL,
            ev REAL,
            edge REAL,
            kelly REAL,
            kelly_quarter REAL,
            stake_pct REAL,
            confidence INTEGER,
            signal_type TEXT,
            confirmed_facts TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            source_match_id TEXT,
            live_identity TEXT,
            bet_id INTEGER,
            signal_key TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_signals_date ON tennis_signals(match_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_signals_status ON tennis_signals(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_signals_live_identity ON tennis_signals(live_identity)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tennis_signals_bet_id ON tennis_signals(bet_id)")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tennis_signals_signal_key_pending
        ON tennis_signals(signal_key)
        WHERE signal_key IS NOT NULL
          AND TRIM(signal_key) <> ''
          AND COALESCE(NULLIF(TRIM(result), ''), 'pending') = 'pending'
          AND COALESCE(status, 'pending') = 'pending'
    """)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tennis_signals)").fetchall()}
    for col_name, col_type in (
        ("source_match_id", "TEXT"),
        ("live_identity", "TEXT"),
        ("bet_id", "INTEGER"),
        ("signal_key", "TEXT"),
        ("result", "TEXT"),
        ("profit", "REAL"),
        ("settled_at", "TEXT"),
        ("winner_name", "TEXT"),
    ):
        if col_name not in cols:
            conn.execute(f"ALTER TABLE tennis_signals ADD COLUMN {col_name} {col_type}")
    conn.commit()

    # Load name mapping for settlement helpers only. Active live dedup is Russian-first.
    name_map = load_name_mapping(conn)
    name_lookup = load_name_lookup(conn)

    # Load existing signals for deduplication using stable live identity.
    existing_signals = set()
    for row in conn.execute("""
        SELECT match_date, player1, player2, market, source_match_id, live_identity
        FROM tennis_signals
        WHERE status = 'pending'
    """).fetchall():
        key = row[5] or build_tennis_live_identity(row[4], row[1], row[2], row[0], row[3])
        existing_signals.add(key)
    if existing_signals:
        log.info(f"Dedup: {len(existing_signals)} existing pending signals loaded")

    signals = []
    passed_rules = 0
    skipped_no_mapping = 0
    skipped_no_features = 0
    skipped_no_edge = 0
    skipped_duplicate = 0
    skipped_started = 0
    skipped_horizon = 0
    skipped_tour = 0
    skipped_form = 0
    skipped_kill_switch = 0

    # Kill switch tracking: monthly PnL
    current_month = datetime.now().strftime("%Y-%m")
    monthly_pnl = 0.0
    kill_switch_active = False

    # Tour filter: block low-tier tournaments (Challenger, ITF, WTA 125K, qualifying)
    _BLOCKED_TOUR_KEYWORDS = [
        "challenger", "челлендж", "itf", "125k",
        "квалификац", "qualifying",
    ]

    # 3-day horizon: only matches starting within 72 hours
    horizon_cutoff = datetime.now() + timedelta(hours=72)
    log.info(f"3-day horizon cutoff: {horizon_cutoff.strftime('%Y-%m-%d %H:%M')}")

    # Get current bankroll for fixed 0.5% stake
    bankroll = _get_bankroll()
    log.info(f"Bankroll: {bankroll:.0f} RUB, fixed stake: 0.5% = {bankroll * 0.005:.0f} RUB")

    for match in live_matches:
        p1_raw = match.get("player1", "")
        p2_raw = match.get("player2", "")
        odds_p1 = float(match.get("odds_p1", 0))
        odds_p2 = float(match.get("odds_p2", 0))
        league = match.get("league", "")
        match_date = match.get("match_date", "")[:10]  # YYYY-MM-DD
        source_match_id = str(match.get("source_match_id") or match.get("fonbet_id") or "").strip() or None

        # Kill switch: if monthly PnL < -5% of bankroll, skip rest of month
        if kill_switch_active:
            skipped_kill_switch += 1
            continue

        if not odds_p1 or not odds_p2:
            continue

        # Tour guardrail: block Challenger, ITF, WTA 125K, qualifying
        league_lower_check = league.lower()
        if any(kw in league_lower_check for kw in _BLOCKED_TOUR_KEYWORDS):
            skipped_tour += 1
            continue

        # 3-day horizon filter: skip matches starting beyond 72 hours
        try:
            match_dt = datetime.strptime(match.get("match_date", ""), "%Y-%m-%d %H:%M")
            if match_dt > horizon_cutoff:
                skipped_horizon += 1
                log.info(f"  SKIP (horizon >3d): {p1_raw} vs {p2_raw} on {match_dt.strftime('%Y-%m-%d %H:%M')}")
                continue
        except ValueError:
            pass

        # Use Russian names directly — backtest_tennis_players now has rus_name columns
        p1_name = p1_raw
        p2_name = p2_raw

        market_id_p1 = build_tennis_live_identity(source_match_id, p1_name, p2_name, match_date, "player1_win")
        market_id_p2 = build_tennis_live_identity(source_match_id, p1_name, p2_name, match_date, "player2_win")
        if market_id_p1 in existing_signals or market_id_p2 in existing_signals:
            skipped_duplicate += 1
            log.info(f"  SKIP (duplicate): {p1_name} vs {p2_name}")
            continue

        # Skip already-started matches (check if match_date is in the past)
        try:
            match_dt = datetime.strptime(match_date, "%Y-%m-%d")
            if match_dt.date() < datetime.now().date():
                skipped_started += 1
                log.info(f"  SKIP (already started / past): {p1_name} vs {p2_name} on {match_date}")
                continue
        except ValueError:
            pass

        # Detect surface from league name
        surface = "hard"
        league_lower = league.lower()
        if "clay" in league_lower or "грунт" in league_lower:
            surface = "clay"
        elif "grass" in league_lower or "трава" in league_lower:
            surface = "grass"
        elif "indoor" in league_lower:
            surface = "indoor"

        # Build features from P1 perspective
        features_p1 = builder.build_features(p1_name, p2_name, match_date, surface)
        if features_p1 is None:
            skipped_no_features += 1
            log.info(f"  SKIP (no features): {p1_name} vs {p2_name}")
            continue

        # Build features from P2 perspective (symmetric inference)
        # The model has ~5.85% mean asymmetry: P2(swapped) != 1 - P1
        # So we must run the model twice for correct evaluation of both sides.
        features_p2 = builder.build_features(p2_name, p1_name, match_date, surface)

        # Prepare feature vectors
        try:
            x_p1 = np.array([[features_p1.get(col, 0) for col in ALL_FEATURES]])
        except Exception as e:
            log.warning(f"  SKIP (feature error P1): {p1_name} vs {p2_name}: {e}")
            continue

        x_p2 = None
        if features_p2 is not None:
            try:
                x_p2 = np.array([[features_p2.get(col, 0) for col in ALL_FEATURES]])
            except Exception:
                pass

        # Predict P1 win probability (P1 as "player")
        raw_prob_p1 = model.predict(x_p1)[0]

        # Predict P2 win probability (P2 as "player") — NOT 1 - raw_prob_p1
        raw_prob_p2 = None
        if x_p2 is not None:
            raw_prob_p2 = model.predict(x_p2)[0]

        # Calibration for both perspectives
        n_form_p1 = min(10, len(builder._player_history(p1_name)))
        n_form_p2 = min(10, len(builder._player_history(p2_name)))
        has_h2h = features_p1.get("h2h_total", 0) > 0

        our_prob_p1 = calibrate_probability(raw_prob_p1, profile, n_form=n_form_p1, has_h2h=has_h2h)
        our_prob_p2 = calibrate_probability(raw_prob_p2, profile, n_form=n_form_p2, has_h2h=has_h2h) if raw_prob_p2 is not None else None

        # Market probabilities (implied from odds, removing vig)
        implied_p1 = 1.0 / odds_p1
        implied_p2 = 1.0 / odds_p2
        total_implied = implied_p1 + implied_p2
        market_p1 = implied_p1 / total_implied
        market_p2 = implied_p2 / total_implied

        # Edge for both sides (our_prob - market_prob, for logging)
        edge_p1 = our_prob_p1 - market_p1
        edge_p2 = (our_prob_p2 - market_p2) if our_prob_p2 is not None else -999

        # EV for both sides — use RAW probabilities for FAVORITE strategy
        ev_p1_raw = raw_prob_p1 * odds_p1 - 1
        ev_p2_raw = raw_prob_p2 * odds_p2 - 1 if raw_prob_p2 is not None else -999

        log.info(f"  {p1_name} vs {p2_name} | {surface} | "
                 f"p1: raw={raw_prob_p1:.3f} our={our_prob_p1:.3f} mkt={market_p1:.3f} edge={edge_p1:.3f} EV={ev_p1_raw:.3f} | "
                 f"p2: raw={raw_prob_p2:.3f} our={our_prob_p2:.3f} mkt={market_p2:.3f} edge={edge_p2:.3f} EV={ev_p2_raw:.3f} | "
                 f"odds={odds_p1:.2f}/{odds_p2:.2f}")

        # FAVORITE strategy — raw probabilities, no temperature scaling
        # Only bet on favorites: odds 1.40-2.00, raw_prob >= 0.60, EV >= 0.03
        min_odds = 1.40
        max_odds = 2.00
        min_raw_prob = 0.60
        min_ev = 0.03

        # Form check: need at least 5 matches for reliable features
        p1_form_ok = n_form_p1 >= 5
        p2_form_ok = n_form_p2 >= 5

        if not p1_form_ok and not p2_form_ok:
            skipped_form += 1
            continue

        # Evaluate both sides with FAVORITE filters
        def favorite_passes(raw_prob, odds, form_ok):
            if not form_ok:
                return False
            if odds < min_odds or odds > max_odds:
                return False
            if raw_prob < min_raw_prob:
                return False
            ev = raw_prob * odds - 1
            return ev >= min_ev

        p1_passes = favorite_passes(raw_prob_p1, odds_p1, p1_form_ok)
        p2_passes = favorite_passes(raw_prob_p2, odds_p2, p2_form_ok) if raw_prob_p2 is not None else False

        if not p1_passes and not p2_passes:
            skipped_no_edge += 1
            continue

        # Pick the side with highest EV
        ev_p1 = raw_prob_p1 * odds_p1 - 1 if p1_passes else -999
        ev_p2 = raw_prob_p2 * odds_p2 - 1 if p2_passes else -999

        if p1_passes and p2_passes:
            pick_side = "p1" if ev_p1 >= ev_p2 else "p2"
        elif p1_passes:
            pick_side = "p1"
        else:
            pick_side = "p2"

        # Extract chosen side's values
        if pick_side == "p1":
            raw_prob = raw_prob_p1
            our_prob = our_prob_p1
            market_prob = market_p1
            ev = ev_p1
            odds = odds_p1
            n_form = n_form_p1
            features = features_p1
        else:
            raw_prob = raw_prob_p2
            our_prob = our_prob_p2
            market_prob = market_p2
            ev = ev_p2
            odds = odds_p2
            n_form = n_form_p2
            features = features_p2

        passed_rules += 1

        # Kelly (for logging only) — use raw probability
        kelly = compute_kelly(raw_prob, odds)
        kelly_q = max(0, kelly * 0.25)
        # Fixed 0.5% bankroll stake for tennis
        stake_pct = 0.005

        # Confidence (1-10 scale based on EV strength)
        confidence = min(10, max(1, int(ev * 100)))

        # Signal type
        if has_h2h and n_form >= 5:
            signal_type = "Medium"
        else:
            signal_type = "Weak"

        # Confirmed facts
        facts = []
        if has_h2h:
            facts.append(f"H2H: {features['h2h_player_wins']}-{features['h2h_opponent_wins']}")
        if n_form >= 5:
            facts.append(f"Form {n_form} matches")
        if surface != "hard":
            facts.append(f"Surface: {surface}")
        facts.append(f"FAVORITE: odds={odds:.2f} raw_prob={raw_prob:.3f}")

        # Dynamic market: player1_win or player2_win
        market = "player1_win" if pick_side == "p1" else "player2_win"

        signal = {
            "match_date": match_date,
            "league": league,
            "source_match_id": source_match_id,
            "player1": p1_name,
            "player2": p2_name,
            "player1_eng": p1_name,
            "player2_eng": p2_name,
            "surface": surface,
            "odds_p1": odds_p1,
            "odds_p2": odds_p2,
            "market": market,
            "our_probability": round(raw_prob, 4),
            "market_probability": market_prob,
            "ev": round(ev, 4),
            "edge": round(raw_prob - market_prob, 4),
            "kelly": round(kelly, 4),
            "kelly_quarter": round(kelly_q, 4),
            "stake_pct": round(stake_pct, 4),
            "confidence": confidence,
            "signal_type": signal_type,
            "confirmed_facts": json.dumps(facts, ensure_ascii=False),
        }
        signal["live_identity"] = build_tennis_live_identity(
            source_match_id, p1_name, p2_name, match_date, market
        )
        signal["match_identity"] = build_tennis_match_identity(
            source_match_id, p1_name, p2_name, match_date
        )
        signals.append(signal)
        existing_signals.add(signal["live_identity"])

    # Kill switch check: compute monthly PnL from settled signals this month
    settled_this_month = conn.execute("""
        SELECT COALESCE(SUM(profit), 0) FROM tennis_signals
        WHERE result IN ('won', 'lost')
          AND created_at LIKE ?
    """, (f"{current_month}%",)).fetchone()
    if settled_this_month:
        monthly_pnl = float(settled_this_month[0])
        kill_threshold = 0.05 * bankroll
        if monthly_pnl < -kill_threshold:
            kill_switch_active = True
            log.warning(f"KILL SWITCH ACTIVATED: monthly PnL={monthly_pnl:+.0f} RUB < -{kill_threshold:.0f} RUB (5% of BR)")

    # Save signals
    if signals:
        if dry_run:
            log.info(f"\n[DRY RUN] Would save {len(signals)} signals")
        else:
            bets_created = 0
            for sig in signals:
                bet_id = _create_tennis_bet(conn, sig, bankroll)
                conn.execute("""
                    INSERT INTO tennis_signals
                    (match_date, league, player1, player2, player1_eng, player2_eng,
                     surface, odds_p1, odds_p2, market, our_probability, market_probability,
                     ev, edge, kelly, kelly_quarter, stake_pct, confidence, signal_type,
                     confirmed_facts, status, source_match_id, live_identity, bet_id, signal_key)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    sig["match_date"], sig["league"], sig["player1"], sig["player2"],
                    sig["player1_eng"], sig["player2_eng"], sig["surface"],
                    sig["odds_p1"], sig["odds_p2"], sig["market"],
                    sig["our_probability"], sig["market_probability"],
                    sig["ev"], sig["edge"], sig["kelly"], sig["kelly_quarter"],
                    sig["stake_pct"], sig["confidence"], sig["signal_type"],
                    sig["confirmed_facts"], "pending", sig["source_match_id"],
                    sig["live_identity"], bet_id, sig["live_identity"],
                ))
                if bet_id:
                    bets_created += 1
            conn.commit()
            log.info(f"Saved {len(signals)} signals to tennis_signals table")
            log.info(f"Created {bets_created} bets entries for tennis signals")

    # Summary
    elapsed = time.time() - t0
    log.info(f"\n{'=' * 70}")
    log.info(f"PIPELINE SUMMARY")
    log.info(f"{'=' * 70}")
    log.info(f"Live matches parsed:     {len(live_matches)}")
    log.info(f"Within 3-day horizon:    {len(live_matches) - skipped_horizon}")
    log.info(f"Skipped (horizon >3d):   {skipped_horizon}")
    log.info(f"Skipped (no mapping):    {skipped_no_mapping}")
    log.info(f"Skipped (no features):   {skipped_no_features}")
    log.info(f"Skipped (tour filter):   {skipped_tour}")
    log.info(f"Skipped (no edge/EV):    {skipped_no_edge}")
    log.info(f"Skipped (duplicate):     {skipped_duplicate}")
    log.info(f"Skipped (started):       {skipped_started}")
    log.info(f"Skipped (form <5):       {skipped_form}")
    log.info(f"Skipped (kill switch):   {skipped_kill_switch}")
    log.info(f"Monthly PnL:             {monthly_pnl:+.0f} RUB")
    log.info(f"Kill switch:             {'ACTIVE' if kill_switch_active else 'inactive'}")
    log.info(f"Signals generated:       {len(signals)}")

    # P1/P2 distribution
    if signals:
        p1_count = sum(1 for s in signals if s["market"] == "player1_win")
        p2_count = len(signals) - p1_count
        log.info(f"  P1 signals:            {p1_count} ({p1_count/len(signals):.0%})")
        log.info(f"  P2 signals:            {p2_count} ({p2_count/len(signals):.0%})")

    log.info(f"Time:                    {elapsed:.1f}s")

    if signals:
        log.info(f"\nTop signals by EV:")
        for i, sig in enumerate(sorted(signals, key=lambda s: -s["ev"])[:5]):
            sig_odds = sig["odds_p1"] if sig["market"] == "player1_win" else sig["odds_p2"]
            log.info(f"  {i+1}. {sig['player1_eng']} vs {sig['player2_eng']} | "
                     f"{sig['market']} @ {sig_odds:.2f} | "
                     f"our_p={sig['our_probability']:.3f} EV={sig['ev']:.3f} "
                     f"edge={sig['edge']:.3f} stake={sig['stake_pct']:.2%}")

    conn.close()
    return signals


# ================================================================
# 8. Settlement for tennis signals
# ================================================================
def _load_eng_to_rus_map(conn) -> Dict[str, str]:
    """Load English -> Russian player name mapping."""
    mapping = {}
    for rus, eng in conn.execute(
        "SELECT rus_name, eng_name FROM tennis_player_mapping WHERE needs_review = 0"
    ).fetchall():
        mapping[eng.strip()] = rus.strip()
    return mapping


def _find_result_in_live(conn, p1_eng: str, p2_eng: str, match_date: str,
                         eng_to_rus: Dict[str, str]) -> Optional[str]:
    """
    Look up match result in tennis_live_results (betz.su source).
    Returns 'p1_won', 'p2_won', or None.

    Compares against explicit winner_name column — not player positions.

    Name matching handles two formats:
    - Full names: "Мирра Андреева" (from betz.su results)
    - Surname+Initial: "Андреева М." (from tennis_player_mapping)

    Uses COLLATE NOCASE for Cyrillic-aware case-insensitive matching
    (SQLite LOWER() does not handle Cyrillic characters).
    """
    rus_p1 = eng_to_rus.get(p1_eng)
    rus_p2 = eng_to_rus.get(p2_eng)

    # If inputs are already Russian names (contain Cyrillic), use them directly
    def _has_cyrillic(s: str) -> bool:
        return any('\u0400' <= c <= '\u04FF' for c in s)

    if _has_cyrillic(p1_eng):
        rus_p1 = p1_eng
    if _has_cyrillic(p2_eng):
        rus_p2 = p2_eng

    def _extract_surname(rus_name: str) -> str:
        """Extract surname from Russian name in any format.
        'Мирра Андреева' -> 'Андреева'
        'Андреева М.' -> 'Андреева'
        """
        if not rus_name:
            return ""
        parts = rus_name.strip().replace('.', '').split()
        if not parts:
            return ""
        # If format is "Surname Initial", surname is first
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            return parts[0]
        # If format is "First Surname", surname is last
        return parts[-1]

    # Try matching with whatever Russian names we have (both, one, or none)
    candidates = []
    if rus_p1 and rus_p2:
        s1 = _extract_surname(rus_p1)
        s2 = _extract_surname(rus_p2)
        candidates.append((s1, s2, "p1", "p2"))
    elif rus_p1:
        s1 = _extract_surname(rus_p1)
        candidates.append((s1, None, "p1", None))
    elif rus_p2:
        s2 = _extract_surname(rus_p2)
        candidates.append((None, s2, None, "p2"))
    else:
        # No Russian mapping — fallback: use English surnames directly
        # betz.su stores Russian names, but many surnames are similar
        # (Baptiste, Cobolli, Ferro, etc.) or transliteratable
        def _eng_surname(name: str) -> str:
            if not name:
                return ""
            parts = name.strip().replace('.', '').split()
            if not parts:
                return ""
            if len(parts) >= 2 and len(parts[-1]) <= 3:
                return parts[0]
            return parts[-1]

        s1 = _eng_surname(p1_eng)
        s2 = _eng_surname(p2_eng)
        if s1 and s2:
            candidates.append((s1, s2, "p1", "p2"))
        elif s1:
            candidates.append((s1, None, "p1", None))
        elif s2:
            candidates.append((None, s2, None, "p2"))

    # Build list of dates to search: match_date ± 1 day
    # Matches may be postponed/rain-delayed and completed a day later
    try:
        dt = datetime.strptime(str(match_date)[:10], "%Y-%m-%d")
        search_dates = [
            (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            str(match_date)[:10],
            (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]
    except Exception:
        search_dates = [str(match_date)[:10]]

    for s1, s2, label_p1, label_p2 in candidates:
        for d in search_dates:
            if s1 and s2:
                # Both surnames known — exact pair match
                row = conn.execute("""
                    SELECT winner_name FROM tennis_live_results
                    WHERE match_date = ?
                      AND (
                          (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                           AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                          OR (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                              AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                      )
                    LIMIT 1
                """, (d, s1, s2, s2, s1)).fetchone()
                if row:
                    winner_rus = row[0]
                    if s1.lower() in winner_rus.lower():
                        return "p1_won"
                    return "p2_won"
            elif s1:
                # Only p1 surname known — find match where p1 is one of the players
                row = conn.execute("""
                    SELECT winner_name FROM tennis_live_results
                    WHERE match_date = ?
                      AND (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                           OR loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                    LIMIT 1
                """, (d, s1, s1)).fetchone()
                if row:
                    winner_rus = row[0]
                    if s1.lower() in winner_rus.lower():
                        return "p1_won"
                    return "p2_won"
            elif s2:
                row = conn.execute("""
                    SELECT winner_name FROM tennis_live_results
                    WHERE match_date = ?
                      AND (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                           OR loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                    LIMIT 1
                """, (d, s2, s2)).fetchone()
                if row:
                    winner_rus = row[0]
                    if s2.lower() in winner_rus.lower():
                        return "p2_won"
                    return "p1_won"

    return None


def _find_result_in_backtest(conn, p1_eng: str, p2_eng: str, match_date: str) -> Optional[str]:
    """
    Fallback: look up match result in backtest_tennis_players (historical source).
    Returns 'p1_won', 'p2_won', or None.
    """
    match_date_prefix = match_date[:10]

    p1_won = conn.execute("""
        SELECT 1 FROM backtest_tennis_players
        WHERE tourney_date LIKE ?
          AND (LOWER(winner_name) = LOWER(?) OR winner_name LIKE '%' || ? || '%')
          AND (LOWER(loser_name) = LOWER(?) OR loser_name LIKE '%' || ? || '%')
        LIMIT 1
    """, (match_date_prefix + "%", p1_eng, p1_eng.split()[-1], p2_eng, p2_eng.split()[-1])).fetchone()

    if p1_won:
        return "p1_won"

    p2_won = conn.execute("""
        SELECT 1 FROM backtest_tennis_players
        WHERE tourney_date LIKE ?
          AND (LOWER(winner_name) = LOWER(?) OR winner_name LIKE '%' || ? || '%')
          AND (LOWER(loser_name) = LOWER(?) OR loser_name LIKE '%' || ? || '%')
        LIMIT 1
    """, (match_date_prefix + "%", p2_eng, p2_eng.split()[-1], p1_eng, p1_eng.split()[-1])).fetchone()

    if p2_won:
        return "p2_won"

    return None


def _fetch_fresh_results_if_needed(conn) -> bool:
    """Always fetch fresh tennis results before settlement.

    betz.su updates results throughout the day, so we always re-fetch
    to catch newly completed matches (postponed, rain-delayed, etc.).

    Returns True if results were fetched, False otherwise.
    """
    try:
        log.info("Fetching fresh tennis results for settlement (last 3 days)...")
        import subprocess
        result = subprocess.run(
            ["python3", "tennis_results_updater.py", "--days", "3"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            log.info(f"Fresh tennis results fetched: {result.stdout.strip()[-200:]}")
            return True
        else:
            log.warning(f"Results updater failed: {result.stderr[-300:]}")
            return False
    except Exception as e:
        log.warning(f"Auto-fetch results failed (non-fatal): {e}")
        return False


def _find_result_in_normalized(conn, p1_eng: str, p2_eng: str, match_date: str) -> Optional[str]:
    """Look up match result in normalized_results (canonical source).

    Returns 'p1_won', 'p2_won', or None.
    Searches match_date ± 1 day for postponed matches.
    """
    try:
        dt = datetime.strptime(str(match_date)[:10], "%Y-%m-%d")
        search_dates = [
            (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            str(match_date)[:10],
            (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]
    except Exception:
        search_dates = [str(match_date)[:10]]

    def _surname(name: str) -> str:
        """Extract surname from English name."""
        if not name:
            return ""
        parts = name.strip().replace('.', '').split()
        if not parts:
            return ""
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            return parts[0]
        return parts[-1]

    s1 = _surname(p1_eng)
    s2 = _surname(p2_eng)

    if not s1 or not s2:
        return None

    for d in search_dates:
        # Find match where both players are present
        row = conn.execute("""
            SELECT winner_name, loser_name
            FROM normalized_results
            WHERE sport = 'tennis'
              AND match_date = ?
              AND (
                  (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                   AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                  OR (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                      AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
              )
            LIMIT 1
        """, (d, s1, s2, s2, s1)).fetchone()

        if row:
            winner_rus, loser_rus = row
            # Check which English player matches the Russian winner name
            if s1.lower() in winner_rus.lower():
                return "p1_won"
            elif s2.lower() in winner_rus.lower():
                return "p2_won"
            # Fallback: if winner matches p1 surname, p1 won
            return "p1_won"

    return None


def settle_tennis_signals(dry_run: bool = False):
    """
    Settle pending tennis signals by checking match results.

    Uses Russian names directly from tennis_signals (player1/player2)
    to match against tennis_live_results (betz.su) — no mapping needed.

    Priority:
    1. tennis_live_results (betz.su — Russian names, updated daily)
    2. normalized_results (canonical — dual-path settlement)
    3. backtest_tennis_players (historical — updated with delay)

    Handles cancelled matches (отмена) — marks as 'cancelled' (no PnL impact).
    Auto-fetches fresh results before settlement.
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    # Ensure columns exist
    cols = [row[1] for row in conn.execute("PRAGMA table_info(tennis_signals)").fetchall()]
    for col in ("result", "profit", "settled_at", "winner_name"):
        if col not in cols:
            conn.execute(f"ALTER TABLE tennis_signals ADD COLUMN {col} TEXT" if col != "profit" else "ALTER TABLE tennis_signals ADD COLUMN profit REAL")
    conn.commit()

    # Load name mapping and lookup for canonical bet lookups
    name_map = load_name_mapping(conn)
    name_lookup = load_name_lookup(conn)

    _sync_linked_tennis_signals(conn, dry_run=dry_run)

    # Find pending signals — include Russian names for direct lookup
    pending = conn.execute("""
        SELECT id, match_date, player1, player2, player1_eng, player2_eng,
               market, odds_p1, odds_p2, stake_pct, our_probability, league, surface, bet_id
        FROM tennis_signals
        WHERE result IS NULL OR result = 'pending'
    """).fetchall()

    if not pending:
        log.info("No pending tennis signals to settle")
        conn.close()
        return 0

    # Always fetch fresh results — betz.su updates throughout the day
    _fetch_fresh_results_if_needed(conn)

    settled_count = 0
    cancelled_count = 0

    for row in pending:
        (sig_id, match_date, p1_rus, p2_rus, p1_eng, p2_eng,
         market, odds_p1, odds_p2, stake_pct, our_prob, league, surface, linked_bet_id) = row

        bet_odds = odds_p1 if market == "player1_win" else odds_p2

        # --- Step 1: Check for cancelled match in tennis_live_results ---
        cancelled = _check_cancelled(conn, p1_rus, p2_rus, match_date)
        if cancelled:
            _mark_cancelled(conn, sig_id, market, p1_rus or p1_eng, p2_rus or p2_eng, match_date, cancelled, dry_run, linked_bet_id)
            cancelled_count += 1
            continue

        # --- Step 2: Try to find result (Russian names direct lookup) ---
        winner_side, source = _find_tennis_result(conn, p1_rus, p2_rus, match_date)

        if winner_side is None:
            continue

        # --- Step 3: Settle ---
        if winner_side == "p1_won":
            result = "won" if market == "player1_win" else "lost"
            winner = p1_rus or p1_eng
        else:
            result = "lost" if market == "player1_win" else "won"
            winner = p2_rus or p2_eng

        profit = round(stake_pct * (bet_odds - 1) if result == "won" else -stake_pct, 4)
        settled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if dry_run:
            log.info(f"  [DRY RUN] {p1_rus or p1_eng} vs {p2_rus or p2_eng} -> {result} | profit={profit} | source={source}")
        else:
            bet_row = _find_tennis_bet_row(
                conn,
                match_date,
                p1_rus or p1_eng,
                p2_rus or p2_eng,
                market,
                linked_bet_id,
            )
            if not bet_row:
                log.warning(
                    "Skip tennis settlement: bet row not found for %s vs %s | %s | %s",
                    p1_rus or p1_eng,
                    p2_rus or p2_eng,
                    match_date,
                    market,
                )
                continue

            bet_id, original_stake = bet_row

            conn.execute("""
                UPDATE tennis_signals
                SET status = ?, result = ?, profit = ?, settled_at = COALESCE(settled_at, ?), winner_name = ?, bet_id = COALESCE(bet_id, ?)
                WHERE id = ?
            """, (result, result, profit, settled_at, winner, bet_id, sig_id))

            # Use the original stake from bets table, not recompute from current bankroll.
            # This ensures profit reflects the actual amount risked at bet creation time.
            bet_profit = round(original_stake * (bet_odds - 1) if result == "won" else -original_stake, 2)
            conn.execute("""
                UPDATE bets
                SET result = ?, profit = ?, settled_at = COALESCE(settled_at, ?)
                WHERE id = ?
            """, (result, bet_profit, settled_at, bet_id))
            _sync_tennis_signal_with_bet(conn, sig_id, bet_id)
            log.info(f"  SETTLED [{source}]: {p1_rus or p1_eng} vs {p2_rus or p2_eng} -> {result} | profit={profit} | bet_profit={bet_profit:.0f}")

        settled_count += 1

    if not dry_run:
        conn.commit()

    conn.close()
    log.info(f"Settled {settled_count} tennis signals, cancelled {cancelled_count}")
    return settled_count + cancelled_count


def _find_tennis_bet_row(
    conn,
    match_date: str,
    p1_name: str,
    p2_name: str,
    market: str,
    linked_bet_id: Optional[int] = None,
):
    """
    Resolve the stored tennis bet row via match identity instead of recomputing
    created_by from mutable name mappings.
    """
    if linked_bet_id:
        row = conn.execute("""
            SELECT id, stake
            FROM bets
            WHERE id = ?
            LIMIT 1
        """, (linked_bet_id,)).fetchone()
        if row:
            return row
    return conn.execute("""
        SELECT b.id, b.stake
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE m.sport = 'tennis'
          AND m.match_date = ?
          AND m.home_team = ?
          AND m.away_team = ?
          AND b.market = ?
        ORDER BY CASE WHEN b.result = 'pending' THEN 0 ELSE 1 END,
                 b.id DESC
        LIMIT 1
    """, (match_date, p1_name, p2_name, market)).fetchone()


def _check_cancelled(conn, p1_rus: str, p2_rus: str, match_date: str) -> Optional[str]:
    """Check if match was cancelled/postponed in tennis_live_results.

    Looks for 'отмена' in score_detail for the given players.
    Returns reason string if cancelled, None otherwise.
    """
    try:
        dt = datetime.strptime(str(match_date)[:10], "%Y-%m-%d")
        search_dates = [
            (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            str(match_date)[:10],
            (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]
    except Exception:
        search_dates = [str(match_date)[:10]]

    def _surname(name: str) -> str:
        if not name:
            return ""
        parts = name.strip().replace('.', '').split()
        if not parts:
            return ""
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            return parts[0]
        return parts[-1]

    s1 = _surname(p1_rus)
    s2 = _surname(p2_rus)

    if not s1 or not s2:
        return None

    for d in search_dates:
        row = conn.execute("""
            SELECT score_detail FROM tennis_live_results
            WHERE match_date = ?
              AND score_detail LIKE ?
              AND (
                  (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                   AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                  OR (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                      AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
              )
            LIMIT 1
        """, (d, '%отмена%', s1, s2, s2, s1)).fetchone()
        if row:
            return row[0]

    return None


def _mark_cancelled(
    conn,
    sig_id: int,
    market: str,
    p1_name: str,
    p2_name: str,
    match_date: str,
    reason: str,
    dry_run: bool,
    linked_bet_id: Optional[int] = None,
):
    """Mark signal and bet as cancelled — no PnL impact."""
    settled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    display_name = f"{p1_name} vs {p2_name}"

    if dry_run:
        log.info(f"  [DRY RUN] CANCELLED: {display_name} | reason={reason}")
    else:
        bet_row = _find_tennis_bet_row(conn, match_date, p1_name, p2_name, market, linked_bet_id)
        if not bet_row:
            log.warning(
                "Skip tennis cancellation: bet row not found for %s | %s | %s",
                display_name,
                match_date,
                market,
            )
            return

        bet_id = bet_row[0]

        conn.execute("""
            UPDATE tennis_signals
            SET status = 'cancelled', result = 'cancelled', profit = 0, settled_at = COALESCE(settled_at, ?), winner_name = ?, bet_id = COALESCE(bet_id, ?)
            WHERE id = ?
        """, (settled_at, f"cancelled: {reason}", bet_id, sig_id))

        conn.execute("""
            UPDATE bets
            SET result = 'cancelled', profit = 0, settled_at = COALESCE(settled_at, ?)
            WHERE id = ?
        """, (settled_at, bet_id))
        _sync_tennis_signal_with_bet(conn, sig_id, bet_id)
        log.info(f"  CANCELLED: {display_name} | reason={reason}")


def _sync_tennis_signal_with_bet(conn, sig_id: int, bet_id: int) -> None:
    """Keep one linked signal aligned with its bet."""
    row = conn.execute("""
        SELECT result, profit, settled_at
        FROM bets
        WHERE id = ?
        LIMIT 1
    """, (bet_id,)).fetchone()
    if not row:
        return
    bet_result, bet_profit, bet_settled_at = row
    if not bet_result or bet_result == "pending":
        conn.execute(
            "UPDATE tennis_signals SET bet_id = COALESCE(bet_id, ?), status = 'pending' WHERE id = ?",
            (bet_id, sig_id),
        )
        return
    conn.execute("""
        UPDATE tennis_signals
        SET bet_id = COALESCE(bet_id, ?),
            status = ?,
            result = ?,
            profit = COALESCE(?, profit),
            settled_at = COALESCE(settled_at, ?)
        WHERE id = ?
    """, (bet_id, bet_result, bet_result, bet_profit, bet_settled_at, sig_id))


def _sync_linked_tennis_signals(conn, dry_run: bool = False) -> int:
    """Repair linked signal/bet mismatches without touching other sports."""
    rows = conn.execute("""
        SELECT ts.id, ts.status, ts.result, ts.bet_id, b.result, b.profit, b.settled_at
        FROM tennis_signals ts
        JOIN bets b ON b.id = ts.bet_id
        WHERE ts.bet_id IS NOT NULL
          AND COALESCE(b.result, 'pending') != 'pending'
          AND (
              COALESCE(ts.status, 'pending') = 'pending'
              OR COALESCE(ts.result, 'pending') = 'pending'
              OR COALESCE(ts.result, '') != COALESCE(b.result, '')
          )
    """).fetchall()
    if dry_run:
        for row in rows:
            log.info(
                "  [DRY RUN] SYNC linked signal %s -> bet %s | signal=%s/%s bet=%s",
                row[0], row[3], row[1], row[2], row[4]
            )
        return len(rows)
    for sig_id, _sig_status, _sig_result, bet_id, _bet_result, _bet_profit, _bet_settled_at in rows:
        _sync_tennis_signal_with_bet(conn, sig_id, bet_id)
    if rows:
        log.info("Synced %s linked tennis signals from settled bets", len(rows))
    return len(rows)


def _find_tennis_result(conn, p1_rus: str, p2_rus: str, match_date: str) -> Tuple[Optional[str], str]:
    """Find tennis result using Russian names directly.

    Returns (winner_side, source) where winner_side is 'p1_won'/'p2_won'/None.
    Sources: 'live' (tennis_live_results), 'normalized' (normalized_results), 'backtest'.
    """
    try:
        dt = datetime.strptime(str(match_date)[:10], "%Y-%m-%d")
        search_dates = [
            (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            str(match_date)[:10],
            (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
        ]
    except Exception:
        search_dates = [str(match_date)[:10]]

    def _surname(name: str) -> str:
        if not name:
            return ""
        parts = name.strip().replace('.', '').split()
        if not parts:
            return ""
        if len(parts) >= 2 and len(parts[-1]) <= 3:
            return parts[0]
        return parts[-1]

    def _surname_tokens(name: str) -> list[str]:
        """Return a list of surname tokens to try.

        Handles hyphenated surnames like 'Будков-Кьер Н':
        _surname() returns 'Будков-Кьер' but betz.su writes 'Будков Кьер' (space).
        We try the hyphenated form first, then each half of the hyphen.
        """
        s = _surname(name)
        if not s:
            return []
        if '-' in s:
            parts = s.split('-', 1)
            return [s, parts[0], parts[1]]
        return [s]

    s1_tokens = _surname_tokens(p1_rus)
    s2_tokens = _surname_tokens(p2_rus)
    s1 = s1_tokens[0] if s1_tokens else ""
    s2 = s2_tokens[0] if s2_tokens else ""

    if s1 and s2:
        # --- Priority 1: tennis_live_results (betz.su) ---
        for d in search_dates:
            for t1 in s1_tokens:
                for t2 in s2_tokens:
                    row = conn.execute("""
                        SELECT winner_name, loser_name FROM tennis_live_results
                        WHERE match_date = ?
                          AND (
                              (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                               AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                              OR (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                                  AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                          )
                        LIMIT 1
                    """, (d, t1, t2, t2, t1)).fetchone()
                    if row:
                        winner_rus = row[0]
                        if t1.lower() in winner_rus.lower():
                            return "p1_won", "live"
                        return "p2_won", "live"

        # --- Priority 2: normalized_results ---
        for d in search_dates:
            row = conn.execute("""
                SELECT winner_name, loser_name FROM normalized_results
                WHERE sport = 'tennis'
                  AND match_date = ?
                  AND (
                      (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                       AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                      OR (winner_name LIKE '%' || ? || '%' COLLATE NOCASE
                          AND loser_name LIKE '%' || ? || '%' COLLATE NOCASE)
                  )
                LIMIT 1
            """, (d, s1, s2, s2, s1)).fetchone()
            if row:
                winner_rus = row[0]
                if s1.lower() in winner_rus.lower():
                    return "p1_won", "normalized"
                return "p2_won", "normalized"

    # --- Priority 3: backtest_tennis_players (English names fallback) ---
    match_date_prefix = match_date[:10]
    p1_won = conn.execute("""
        SELECT 1 FROM backtest_tennis_players
        WHERE tourney_date LIKE ?
          AND (LOWER(winner_name) = LOWER(?) OR winner_name LIKE '%' || ? || '%')
          AND (LOWER(loser_name) = LOWER(?) OR loser_name LIKE '%' || ? || '%')
        LIMIT 1
    """, (match_date_prefix + "%", p1_rus, s1 or p1_rus, p2_rus, s2 or p2_rus)).fetchone()
    if p1_won:
        return "p1_won", "backtest"

    p2_won = conn.execute("""
        SELECT 1 FROM backtest_tennis_players
        WHERE tourney_date LIKE ?
          AND (LOWER(winner_name) = LOWER(?) OR winner_name LIKE '%' || ? || '%')
          AND (LOWER(loser_name) = LOWER(?) OR loser_name LIKE '%' || ? || '%')
        LIMIT 1
    """, (match_date_prefix + "%", p2_rus, s2 or p2_rus, p1_rus, s1 or p1_rus)).fetchone()
    if p2_won:
        return "p2_won", "backtest"

    return None, ""


# ================================================================
# Entry point
# ================================================================
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Tennis Live Pipeline")
    ap.add_argument("--dry-run", action="store_true", help="Don't save signals")
    ap.add_argument("--limit", type=int, default=None, help="Limit number of matches")
    ap.add_argument("--settle", action="store_true", help="Settle pending signals instead of running pipeline")
    args = ap.parse_args()

    if args.settle:
        settle_tennis_signals(dry_run=args.dry_run)
    else:
        signals = run_pipeline(dry_run=args.dry_run, limit=args.limit)
        sys.exit(0 if signals is not None else 1)
