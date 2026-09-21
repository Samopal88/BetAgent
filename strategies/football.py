# -*- coding: utf-8 -*-
"""
Football-specific strategies and configuration.

Extracted from agent_handoff_v7.py to keep football logic in one place.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# ============================================================
# LEAGUE NAME NORMALIZATION
# ============================================================

BACKTEST_LEAGUE_NAME_MAP = {
    "SA": "Италия. Серия А",
    "BL1": "Германия. Бундеслига",
    "FL1": "Франция. Лига 1",
    "EPL": "Англия. Премьер-Лига",
    "PD": "Испания. Примера дивизион",
    "DNK": "Дания. Суперлига",
    "SWE": "Швеция. Аллсвенскан",
    "FIN": "Финляндия. Вейккаусліга",
    "NOR": "Норвегия. Элитесериен",
    "IRL": "Ирландия. Премьер-лига",
}


def normalize_rule_league_name(league: str) -> str:
    raw = (league or "").strip()
    return BACKTEST_LEAGUE_NAME_MAP.get(raw, raw)


# ============================================================
# LEAGUE DETECTORS (single-arg, reusable)
# ============================================================

def is_serie_a_league(league: str) -> bool:
    l = (league or "").lower()
    return "серия а" in l or "serie a" in l or l == "sa"


def is_bundesliga_league(league: str) -> bool:
    l = (league or "").lower()
    return "бундеслига" in l or "bundesliga" in l or l == "bl1"


def is_ligue1_league(league: str) -> bool:
    l = (league or "").lower()
    return "лига 1" in l or "ligue 1" in l or l == "fl1"


def is_epl_league(league: str) -> bool:
    l = (league or "").lower()
    return ("англия" in l and "премьер" in l) or "premier league" in l or l == "epl" or l == "pl"


def is_pd_league(league: str) -> bool:
    l = (league or "").lower()
    return ("примера" in l or "primera" in l or "laliga" in l
            or "la liga" in l or l == "pd" or l == "sp1")


def is_rpl_league(league: str) -> bool:
    l = (league or "").lower()
    return "россия" in l or l == "rpl" or l == "r1" or "rpl" in l


def is_fl1_league(league: str) -> bool:
    l = (league or "").lower()
    return "франц" in l or "ligue" in l or l == "fl1" or l == "f1"


def is_nla_league(league: str) -> bool:
    l = (league or "").lower()
    return "швейцар" in l or "national league" in l or l == "nla"


def is_mls_league(league: str) -> bool:
    l = (league or "").lower()
    return "сша" in l or "mls" in l


# ============================================================
# TEAM SETS used by rules
# ============================================================

SA_AWAY_TEAMS = frozenset({
    'Empoli', 'Genoa', 'Cremonese', 'Salernitana', 'Venezia',
})

_MLS_HOME_TEAMS = [
    "интер майами", "портленд тимберс", "фк торонто", "торонто фк",
    "атланта юнайтед", "орландо сити", "нэшвилл",
    "лос-анджелес гэлакси", "лос-анджелес гэлэкси",
    "сан-хосе эртквейкс", "сан-хосе",
]

# Летние лиги: league_key -> list of team names
SUMMER_TEAMS: Dict[str, list] = {
    "DNK": ["Виборг", "Оденсе", "Норшелланн"],
    "SWE": ["Хеккен"],
    "FIN": ["СИК", "Хака"],
}


# ============================================================
# FOOTBALL LEAGUE STAKING
# ============================================================

FOOTBALL_LEAGUE_STAKING: Dict[str, Dict[str, str]] = {
    "EPL": {
        "football_core_1x2": "flat_pct_1_00",
        "BTTS_YES_CORE": "flat_pct_0_50",
    },
    "BUNDESLIGA": {
        "football_core_1x2": "flat_pct_1_00",
        "DRAW_BL1_FL1": "flat_pct_1_00",
        "DRAW_BALANCED_LINE_BL1": "flat_pct_1_00",
    },
    "SERIE_A": {
        "football_core_1x2": "flat_pct_1_00",
        "DRAW_SA": "flat_pct_1_00",
        "DRAW_BALANCED_LOW_SCORING_SA": "flat_pct_1_00",
        "DRAW_BALANCED_LINE_SA": "flat_pct_1_00",
        "SA_AWAY_DRAW": "flat_pct_1_00",
    },
    "LALIGA": {
        "football_core_1x2": "flat_pct_1_00",
        "PD_AWAY_VALUE": "flat_pct_1_00",
        "PD_BTTS_DOUBLE": "flat_pct_1_00",
    },
    "MLS": {
        "MLS_BTTS_HOME": "flat_pct_1_00",
    },
    "LIGUE_1": {
        "football_core_1x2": "flat_pct_1_00",
        "DRAW_BL1_FL1": "flat_pct_1_00",
    },
    "RPL": {
        "football_core_1x2": "flat_pct_1_00",
        "RPL_OVER25_BTTS": "flat_pct_1_00",
    },
    "LIGUE_1": {
        "FL1_BTTS_DOUBLE": "flat_pct_1_00",
    },
    # Летние лиги
    "DNK": {"SUMMER_BTTS_HOME": "flat_pct_1_00"},
    "SWE": {"SUMMER_BTTS_HOME": "flat_pct_1_00"},
    "FIN": {"SUMMER_BTTS_HOME": "flat_pct_1_00"},
    "NOR": {"SUMMER_BTTS_HOME": "flat_pct_1_00"},
    "IRL": {"SUMMER_BTTS_HOME": "flat_pct_1_00"},
    "ECU_A": {
        "ECU_BTTS_NO": "flat_pct_1_00",
    },
}


# ============================================================
# detect_football_league_key
# ============================================================

def detect_football_league_key(league: str) -> Optional[str]:
    """
    Detect the football league key for staking configuration.

    Args:
        league: League name

    Returns:
        League key or None if not recognized
    """
    if not league:
        return None
    l = league.lower()

    # MLS detection
    if any(term in l for term in ["сша", "mls"]):
        return "MLS"

    # EPL detection
    if any(epl_term in l for epl_term in ["англия", "premier league", "epl", "pl"]):
        return "EPL"

    # Bundesliga detection
    if any(bl_term in l for bl_term in ["германия", "бундеслига", "bundesliga", "bl1"]):
        return "BUNDESLIGA"

    # Эквадор Серия А detection (before Serie A to avoid "serie a" false match)
    if any(x in l for x in ["эквадор", "ecuador"]) and any(x in l for x in ["серия а", "serie a"]):
        return "ECU_A"

    # Serie A detection
    if any(sa_term in l for sa_term in ["италия", "серия а", "serie a", "sa"]):
        return "SERIE_A"

    # La Liga detection
    if any(ll_term in l for ll_term in ["испания", "примера", "laliga", "la liga", "pd"]):
        return "LALIGA"

    # Ligue 1 detection
    if any(l1_term in l for l1_term in ["франция", "лига 1", "ligue 1", "fl1"]):
        return "LIGUE_1"
    # NLA detection
    if any(nla_term in l for nla_term in ["швейцар", "national league", "nla"]):
        return "NLA"
    # RPL detection
    if any(rpl_term in l for rpl_term in ["россия", "rpl", "r1"]):
        return "RPL"

    # Летние скандинавские лиги (коды из backtest_matches + названия Фонбет)
    if any(x in l for x in ["дания", "dansk", "dnk"]):
        return "DNK"
    if any(x in l for x in ["швеция. премьер", "швеция. аллсвен", "allsvenskan", "swe"]):
        return "SWE"
    if any(x in l for x in ["норвегия. суперлига", "eliteserien", "nor"]):
        return "NOR"
    if any(x in l for x in ["финляндия. суперлига", "вейккаус", "veikkausliiga", "fin"]):
        return "FIN"
    if any(x in l for x in ["ирландия. премьер", "irl"]):
        return "IRL"

    return None
