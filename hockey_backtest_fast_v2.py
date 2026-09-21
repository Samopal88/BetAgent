#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — hockey_backtest_fast.py

Быстрый бэктест для проверки хоккейных гипотез.
Сделан по духу проще, как футбольный backtest.py:
- один проход по уже отфильтрованным матчам
- одна лига / тип соревнования за запуск
- 1-3 стратегии за запуск, без чудовищного grid search

Работает с backtest_hockey_features_v2
и использует result_regulation (исход в основное время).

Примеры:
  python hockey_backtest_fast.py --league "Хоккей. NHL. Регулярный чемпионат." --competition-type regular
  python hockey_backtest_fast.py --league "Хоккей. КХЛ. Регулярный чемпионат." --strategy collapse_favorite_fade
  python hockey_backtest_fast.py --league "Хоккей. Швеция. SHL." --all-strategies --report
"""

import argparse
import csv
import os
import sqlite3
from datetime import datetime
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
BANK = float(os.getenv("BETAGENT_BANK", "100000"))
FEATURE_TABLE = "backtest_hockey_features"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def parse_ddmmyyyy(s: str):
    if not s or len(s) < 10:
        return 0, 0, 0
    s = str(s)
    if s[4] == "-":
        # YYYY-MM-DD
        return int(s[0:4]), int(s[5:7]), int(s[8:10])
    else:
        # DD.MM.YYYY
        return int(s[6:10]), int(s[3:5]), int(s[0:2])


def month_key(date_str: str) -> str:
    y, m, _ = parse_ddmmyyyy(date_str)
    return f"{y:04d}-{m:02d}" if y and m else "unknown"


def season_key(date_str: str) -> str:
    y, m, _ = parse_ddmmyyyy(date_str)
    if not y:
        return "unknown"
    if m >= 9:
        return f"{y}/{y+1}"
    return f"{y-1}/{y}"


def season_year_start(sk: str) -> str:
    if sk and "/" in sk:
        return sk.split("/")[0]
    return "unknown"


def classify_competition(league: str) -> str:
    s = (league or "").lower()
    if any(x in s for x in ["плей-офф", "playoff", "play-offs", "play off"]):
        return "playoff"
    if any(x in s for x in ["cup", "кубок", "champions league", "лига чемпионов", "memorial", "мемориал", "товарищ", "предсезон"]):
        return "cup"
    return "regular"


def implied_probs(row) -> Optional[Dict[str, float]]:
    oh = safe_float(row["odds_home"])
    od = safe_float(row["odds_draw"])
    oa = safe_float(row["odds_away"])
    if not oh or not od or not oa or oh <= 1.01 or od <= 1.01 or oa <= 1.01:
        return None
    ih, idr, ia = 1.0 / oh, 1.0 / od, 1.0 / oa
    s = ih + idr + ia
    if s <= 0:
        return None
    return {"H": ih / s, "D": idr / s, "A": ia / s}


def odds_for_market(row, market: str) -> Optional[float]:
    mapping = {"H": "odds_home", "D": "odds_draw", "A": "odds_away"}
    val = safe_float(row[mapping[market]])
    if not val or val <= 1.01:
        return None
    return val


def getv(row, key: str, default: float = 0.0) -> float:
    try:
        v = safe_float(row[key])
        return default if v is None else v
    except Exception:
        return default


def history_games(row) -> int:
    candidates = [
        "home_games_before", "away_games_before",
        "team_games_before_home", "team_games_before_away",
        "form5_games_home", "form5_games_away",
    ]
    vals = []
    for c in candidates:
        try:
            vals.append(int(row[c] or 0))
        except Exception:
            pass
    return min(vals) if vals else 999999


@dataclass
class Pick:
    market: str
    model_prob: float
    edge: float
    ev: float
    score: float


def underdog_live(row) -> Optional[Pick]:
    imp = implied_probs(row)
    if not imp:
        return None

    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    vol = (getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5")
           + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0
    home_edge = getv(row, "home_ppg_all_before") - getv(row, "away_ppg_all_before")
    home_attack = getv(row, "home_gf_avg5") - getv(row, "away_ga_avg5")
    away_attack = getv(row, "away_gf_avg5") - getv(row, "home_ga_avg5")

    if imp["H"] < imp["A"]:
        signal = 0.0
        signal += clamp(-ppg, 0, 3) * 0.18
        signal += clamp(-form5, 0, 3) * 0.24
        signal += clamp(home_edge, -2, 2) * 0.12
        signal += clamp(home_attack, -2, 2) * 0.14
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(1.0 - vol, -1, 1) * 0.08
        market = "H"
        model_prob = clamp(imp["H"] + signal * 0.07, 0.02, 0.90)
        edge = model_prob - imp["H"]
    else:
        signal = 0.0
        signal += clamp(ppg, 0, 3) * 0.18
        signal += clamp(form5, 0, 3) * 0.24
        signal += clamp(-home_edge, -2, 2) * 0.12
        signal += clamp(away_attack, -2, 2) * 0.14
        signal += clamp(exp_diff, -2, 2) * 0.18
        signal += clamp(1.0 - vol, -1, 1) * 0.08
        market = "A"
        model_prob = clamp(imp["A"] + signal * 0.07, 0.02, 0.90)
        edge = model_prob - imp["A"]

    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    return Pick(market, model_prob, edge, ev, signal)


def collapse_favorite_fade(row) -> Optional[Pick]:
    imp = implied_probs(row)
    if not imp:
        return None

    fav = "H" if imp["H"] > imp["A"] else "A"
    dog = "A" if fav == "H" else "H"

    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    form10 = getv(row, "strength_diff_form10")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    vol = (getv(row, "home_goal_diff_vol5") + getv(row, "away_goal_diff_vol5")
           + getv(row, "home_total_goals_vol5") + getv(row, "away_total_goals_vol5")) / 4.0

    if fav == "H":
        fav_ga = getv(row, "home_ga_avg5")
        signal = 0.0
        signal += clamp(-form5, -3, 3) * 0.26
        signal += clamp(-form10, -3, 3) * 0.10
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(fav_ga - 2.5, -2, 2) * 0.18
        signal += clamp(vol - 0.8, -1, 1) * 0.10
        signal += clamp(-ppg, -3, 3) * 0.10
        market = dog
        model_prob = clamp(imp[dog] + signal * 0.07, 0.02, 0.90)
        edge = model_prob - imp[dog]
    else:
        fav_ga = getv(row, "away_ga_avg5")
        signal = 0.0
        signal += clamp(form5, -3, 3) * 0.26
        signal += clamp(form10, -3, 3) * 0.10
        signal += clamp(exp_diff, -2, 2) * 0.18
        signal += clamp(fav_ga - 2.5, -2, 2) * 0.18
        signal += clamp(vol - 0.8, -1, 1) * 0.10
        signal += clamp(ppg, -3, 3) * 0.10
        market = dog
        model_prob = clamp(imp[dog] + signal * 0.07, 0.02, 0.90)
        edge = model_prob - imp[dog]

    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    return Pick(market, model_prob, edge, ev, signal)


def defensive_wall(row) -> Optional[Pick]:
    imp = implied_probs(row)
    if not imp:
        return None

    dog = "H" if imp["H"] < imp["A"] else "A"
    exp_total = getv(row, "expected_total_goals_proxy")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    tight = getv(row, "expected_match_tightness")
    def_bal = getv(row, "expected_defense_balance")
    form5 = getv(row, "strength_diff_form5")
    ppg = getv(row, "strength_diff_ppg")

    if dog == "H":
        ga10 = getv(row, "home_ga_avg10")
        signal = 0.0
        signal += clamp(2.4 - ga10, -1.5, 1.5) * 0.24
        signal += clamp(5.4 - exp_total, -2, 2) * 0.18
        signal += clamp(-exp_diff, -2, 2) * 0.18
        signal += clamp(tight, -2, 2) * 0.10
        signal += clamp(def_bal, -2, 2) * 0.10
        signal += clamp(-form5, -3, 3) * 0.12
        signal += clamp(-ppg, -3, 3) * 0.08
        market = "H"
        model_prob = clamp(imp["H"] + signal * 0.07, 0.02, 0.90)
        edge = model_prob - imp["H"]
    else:
        ga10 = getv(row, "away_ga_avg10")
        signal = 0.0
        signal += clamp(2.4 - ga10, -1.5, 1.5) * 0.24
        signal += clamp(5.4 - exp_total, -2, 2) * 0.18
        signal += clamp(exp_diff, -2, 2) * 0.18
        signal += clamp(tight, -2, 2) * 0.10
        signal += clamp(def_bal, -2, 2) * 0.10
        signal += clamp(form5, -3, 3) * 0.12
        signal += clamp(ppg, -3, 3) * 0.08
        market = "A"
        model_prob = clamp(imp["A"] + signal * 0.07, 0.02, 0.90)
        edge = model_prob - imp["A"]

    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    return Pick(market, model_prob, edge, ev, signal)


def favorite_pressure(row) -> Optional[Pick]:
    imp = implied_probs(row)
    if not imp:
        return None

    fav = "H" if imp["H"] > imp["A"] else "A"
    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    form10 = getv(row, "strength_diff_form10")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    exp_total = getv(row, "expected_total_goals_proxy")
    home_edge = getv(row, "home_ppg_all_before") - getv(row, "away_ppg_all_before")
    home_attack_gap = getv(row, "home_gf_avg5") - getv(row, "away_ga_avg5")
    away_attack_gap = getv(row, "away_gf_avg5") - getv(row, "home_ga_avg5")

    if fav == "H":
        signal = 0.0
        signal += clamp(ppg, -3, 3) * 0.22
        signal += clamp(form5, -3, 3) * 0.20
        signal += clamp(form10, -3, 3) * 0.10
        signal += clamp(exp_diff, -2, 2) * 0.22
        signal += clamp(home_edge, -2, 2) * 0.10
        signal += clamp(home_attack_gap, -2, 2) * 0.12
        signal += clamp(exp_total - 5.4, -2, 2) * 0.04
        market = "H"
        model_prob = clamp(imp["H"] + signal * 0.06, 0.03, 0.95)
        edge = model_prob - imp["H"]
    else:
        signal = 0.0
        signal += clamp(-ppg, -3, 3) * 0.22
        signal += clamp(-form5, -3, 3) * 0.20
        signal += clamp(-form10, -3, 3) * 0.10
        signal += clamp(-exp_diff, -2, 2) * 0.22
        signal += clamp(-home_edge, -2, 2) * 0.10
        signal += clamp(away_attack_gap, -2, 2) * 0.12
        signal += clamp(exp_total - 5.4, -2, 2) * 0.04
        market = "A"
        model_prob = clamp(imp["A"] + signal * 0.06, 0.03, 0.95)
        edge = model_prob - imp["A"]

    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    return Pick(market, model_prob, edge, ev, signal)


def draw_tight(row) -> Optional[Pick]:
    imp = implied_probs(row)
    if not imp:
        return None

    abs_ppg = abs(getv(row, "strength_diff_ppg"))
    abs_form5 = abs(getv(row, "strength_diff_form5"))
    abs_form10 = abs(getv(row, "strength_diff_form10"))
    exp_total = getv(row, "expected_total_goals_proxy")
    exp_diff = abs(getv(row, "expected_goal_diff_proxy"))
    tight = getv(row, "expected_match_tightness")
    def_bal = getv(row, "expected_defense_balance")
    home_ga = getv(row, "home_ga_avg5")
    away_ga = getv(row, "away_ga_avg5")

    signal = 0.0
    signal += clamp(1.2 - abs_ppg, -1, 1.2) * 0.24
    signal += clamp(1.0 - abs_form5, -1, 1.0) * 0.22
    signal += clamp(1.2 - abs_form10, -1, 1.0) * 0.10
    signal += clamp(5.5 - exp_total, -2, 2) * 0.16
    signal += clamp(1.0 - exp_diff, -1, 1.0) * 0.18
    signal += clamp(tight, -2, 2) * 0.08
    signal += clamp(def_bal, -2, 2) * 0.06
    signal += clamp(2.6 - (home_ga + away_ga) / 2.0, -1, 1) * 0.06

    market = "D"
    model_prob = clamp(imp["D"] + signal * 0.07, 0.02, 0.75)
    edge = model_prob - imp["D"]

    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    return Pick(market, model_prob, edge, ev, signal)


def favorite_bounceback(row) -> Optional[Pick]:
    imp = implied_probs(row)
    if not imp:
        return None

    fav = "H" if imp["H"] > imp["A"] else "A"
    ppg = getv(row, "strength_diff_ppg")
    form5 = getv(row, "strength_diff_form5")
    form10 = getv(row, "strength_diff_form10")
    exp_diff = getv(row, "expected_goal_diff_proxy")
    home_edge = getv(row, "home_ppg_all_before") - getv(row, "away_ppg_all_before")

    if fav == "H":
        long_strength = clamp(ppg, -3, 3) * 0.26
        short_term = clamp(-form5, -3, 3) * 0.22 + clamp(-form10, -3, 3) * 0.10
        rebound = clamp(exp_diff, -2, 2) * 0.20 + clamp(home_edge, -2, 2) * 0.10
        signal = long_strength + short_term + rebound
        market = "H"
        model_prob = clamp(imp["H"] + signal * 0.055, 0.03, 0.95)
        edge = model_prob - imp["H"]
    else:
        long_strength = clamp(-ppg, -3, 3) * 0.26
        short_term = clamp(form5, -3, 3) * 0.22 + clamp(form10, -3, 3) * 0.10
        rebound = clamp(-exp_diff, -2, 2) * 0.20 + clamp(-home_edge, -2, 2) * 0.10
        signal = long_strength + short_term + rebound
        market = "A"
        model_prob = clamp(imp["A"] + signal * 0.055, 0.03, 0.95)
        edge = model_prob - imp["A"]

    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    return Pick(market, model_prob, edge, ev, signal)



def nhl_draw_tight(row) -> Optional[Pick]:
    """
    НХЛ ничья в основное время.
    Условия: odds_draw 3.5-5.0, ABS(strength_diff_ppg) < 0.2,
             ABS(strength_diff_form5) < 0.5, odds_home > 1.8
    ROI +23.3% на 106 матчах (3/4 сезонов в плюсе)
    """
    imp = implied_probs(row)
    if not imp:
        return None

    oh = safe_float(row.get("odds_home") if hasattr(row, "get") else getattr(row, "odds_home", None))
    od = safe_float(row.get("odds_draw") if hasattr(row, "get") else getattr(row, "odds_draw", None))

    if not oh or not od:
        return None
    if not (3.5 <= od <= 5.0):
        return None
    if oh <= 1.8:
        return None

    ppg = abs(getv(row, "strength_diff_ppg"))
    form5 = abs(getv(row, "strength_diff_form5"))

    if ppg >= 0.2 or form5 >= 0.5:
        return None

    # home_drawrate_before не доступен в live — пропускаем фильтр

    market = "D"
    model_prob = imp["D"] * 1.15  # небольшой буст
    model_prob = clamp(model_prob, 0.02, 0.75)
    edge = model_prob - imp["D"]
    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    signal = (0.2 - ppg) + (0.5 - form5)
    return Pick(market, model_prob, edge, ev, signal)


def czech_home_favorite(row) -> Optional[Pick]:
    """
    Чехия Extraliga — ставка на П1 хозяина в основное время.
    Условия: odds_home 1.6-2.0, strength_diff_ppg > 0.5
    ROI +15.6% на 84 матчах, 4/4 сезонов в плюсе, MaxLS~7
    П1 = победа хозяев в основное время (3 периода), без ОТ.
    """
    imp = implied_probs(row)
    if not imp:
        return None

    oh = safe_float(row.get("odds_home") if hasattr(row, "get") else getattr(row, "odds_home", None))
    if not oh:
        return None
    if not (1.6 <= oh <= 2.0):
        return None

    ppg = getv(row, "strength_diff_ppg")
    if ppg <= 0.5:
        return None

    market = "H"
    model_prob = clamp(imp["H"] * 1.10, 0.03, 0.95)
    edge = model_prob - imp["H"]
    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    signal = ppg + (2.0 - oh)
    return Pick(market, model_prob, edge, ev, signal)


def del_home_form5(row) -> Optional[Pick]:
    """
    DEL (Германия) — ставка на П1 хозяина в основное время.
    Условия: odds_home 1.70-2.00, form5_home_winrate > 0.5
    П1 = победа хозяев в основное время (3 периода), без ОТ.
    """
    imp = implied_probs(row)
    if not imp:
        return None

    oh = safe_float(row.get("odds_home") if hasattr(row, "get") else getattr(row, "odds_home", None))
    if not oh:
        return None
    if not (1.70 <= oh <= 2.00):
        return None

    form5_wr = getv(row, "form5_home_winrate")
    if form5_wr <= 0.5:
        return None

    market = "H"
    model_prob = clamp(imp["H"] * 1.08, 0.03, 0.95)
    edge = model_prob - imp["H"]
    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    signal = form5_wr + (2.0 - oh)
    return Pick(market, model_prob, edge, ev, signal)


def czech_home_sd(row) -> Optional[Pick]:
    """
    Чехия Extraliga — ставка на П1 хозяина в основное время.
    Условия: odds_home 2.00-2.30, strength_diff_ppg > 0.2
    П1 = победа хозяев в основное время (3 периода), без ОТ.
    """
    imp = implied_probs(row)
    if not imp:
        return None

    oh = safe_float(row.get("odds_home") if hasattr(row, "get") else getattr(row, "odds_home", None))
    if not oh:
        return None
    if not (2.00 <= oh <= 2.30):
        return None

    ppg = getv(row, "strength_diff_ppg")
    if ppg <= 0.2:
        return None

    market = "H"
    model_prob = clamp(imp["H"] * 1.08, 0.03, 0.95)
    edge = model_prob - imp["H"]
    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    signal = ppg + (2.30 - oh)
    return Pick(market, model_prob, edge, ev, signal)


def shl_skelleftea_home(row) -> Optional[Pick]:
    """
    SHL Skelleftea home — ставка на П1 Шеллефтео в основное время.
    Условия: home_team = 'Шеллефтео', odds_home 1.50-2.50, только regular season.
    П1 = победа хозяев в основное время (3 периода), без ОТ.
    """
    imp = implied_probs(row)
    if not imp:
        return None

    home_team = row.get("home_team", "") if hasattr(row, "get") else getattr(row, "home_team", "")
    if "\u0428\u0435\u043b\u043b\u0435\u0444\u0442\u0435\u043e" not in str(home_team):
        return None

    oh = safe_float(row.get("odds_home") if hasattr(row, "get") else getattr(row, "odds_home", None))
    if not oh:
        return None
    if not (1.50 <= oh <= 2.50):
        return None

    league = row.get("league", "") if hasattr(row, "get") else getattr(row, "league", "")
    league_lower = str(league).lower()
    if any(x in league_lower for x in ["плей", "playoff", "play-off", "финал", "final", "серии"]):
        return None
    if any(x in league_lower for x in ["товарищ", "friendly", "предсезон", "cup", "кубок"]):
        return None

    market = "H"
    model_prob = clamp(imp["H"] * 1.08, 0.03, 0.95)
    edge = model_prob - imp["H"]
    odds = odds_for_market(row, market)
    if not odds:
        return None
    ev = model_prob * odds - 1.0
    signal = (2.50 - oh)
    return Pick(market, model_prob, edge, ev, signal)


STRATEGIES = {
    "underdog_live": underdog_live,
    "collapse_favorite_fade": collapse_favorite_fade,
    "defensive_wall": defensive_wall,
    "favorite_pressure": favorite_pressure,
    "draw_tight": draw_tight,
    "favorite_bounceback": favorite_bounceback,
    "nhl_draw_tight": nhl_draw_tight,
    "czech_home_favorite": czech_home_favorite,
    "del_home_form5": del_home_form5,
    "czech_home_sd": czech_home_sd,
    "shl_skelleftea_home": shl_skelleftea_home,
}


ENSEMBLE_STRATEGIES = {
    "strict_intersection",
    "relaxed_odds",
    "relaxed_edge",
    "fp_or_fb",
    "fp_and_fb",
    "fp_or_fb_priority_fb",
}


def underdog_market(row) -> Optional[str]:
    imp = implied_probs(row)
    if not imp:
        return None
    fav = "H" if imp["H"] > imp["A"] else "A"
    return "A" if fav == "H" else "H"


def combined_pick(row, mode: str) -> Optional[Pick]:
    """
    Комбинированные режимы для favorite стратегий:

    fp_or_fb:
      - favorite_pressure OR favorite_bounceback
      - если только одна стратегия дает сигнал, используем ее
      - если обе дают сигнал на один рынок, берем с большим edge
      - если сигналы на разные рынки, пропускаем

    fp_and_fb:
      - favorite_pressure AND favorite_bounceback
      - обе стратегии должны дать сигнал
      - оба сигнала должны быть на один рынок
      - берем более консервативный (с меньшим edge)
      
    fp_or_fb_priority_fb:
      - favorite_pressure OR favorite_bounceback
      - если только одна стратегия дает сигнал, используем ее
      - если обе дают сигнал на один рынок, берем с большим edge
      - если сигналы на разные рынки, используем favorite_bounceback
    """
    pick1 = favorite_pressure(row)
    pick2 = favorite_bounceback(row)

    if not pick1 and not pick2:
        return None

    if mode == "fp_or_fb":
        # Если только одна стратегия дает сигнал
        if pick1 and not pick2:
            return pick1
        if pick2 and not pick1:
            return pick2
        
        # Если обе дают сигнал
        if pick1.market != pick2.market:
            return None  # Разные рынки - пропускаем
        
        # Выбираем с большим edge
        return pick1 if pick1.edge >= pick2.edge else pick2
    
    elif mode == "fp_or_fb_priority_fb":
        # Если только одна стратегия дает сигнал
        if pick1 and not pick2:
            return pick1
        if pick2 and not pick1:
            return pick2
        
        # Если обе дают сигнал
        if pick1 and pick2:
            if pick1.market == pick2.market:
                # Если рынки совпадают, выбираем с большим edge
                return pick1 if pick1.edge >= pick2.edge else pick2
            else:
                # При конфликте приоритет у favorite_bounceback
                return pick2
        
        # Если ни одна стратегия не дает сигнал
        return None
    
    elif mode == "fp_and_fb":
        # Обе стратегии должны дать сигнал
        if not pick1 or not pick2:
            return None
        
        # Оба сигнала должны быть на один рынок
        if pick1.market != pick2.market:
            return None
        
        # Берем более консервативный (с меньшим edge)
        model_prob = min(pick1.model_prob, pick2.model_prob)
        edge = min(pick1.edge, pick2.edge)
        odds = odds_for_market(row, pick1.market)
        if not odds:
            return None
        ev = model_prob * odds - 1.0
        score = min(pick1.score, pick2.score)
        return Pick(pick1.market, model_prob, edge, ev, score)
    
    return None


def ensemble_pick(row, mode: str) -> Optional[Pick]:
    """
    3 исследовательских режима для KHL ensemble:

    strict_intersection:
      - underdog_live + defensive_wall
      - один и тот же рынок
      - только андердог
      - обе edge >= 0.005
      - odds 1.70-3.80
      - history >= 3

    relaxed_odds:
      - как strict_intersection
      - но odds <= 6.00

    relaxed_edge:
      - как strict_intersection
      - но только underdog_live.edge >= 0.005
      - defensive_wall.edge не гейтит
    """
    pick1 = underdog_live(row)
    pick2 = defensive_wall(row)

    if not pick1 or not pick2:
        return None
    if pick1.market != pick2.market:
        return None
    if history_games(row) < 3:
        return None

    dog = underdog_market(row)
    if not dog or pick1.market != dog:
        return None

    odds = odds_for_market(row, pick1.market)
    if not odds:
        return None

    if mode == "strict_intersection":
        if pick1.edge < 0.005 or pick2.edge < 0.005:
            return None
        if not (1.70 <= odds <= 3.80):
            return None
    elif mode == "relaxed_odds":
        if pick1.edge < 0.005 or pick2.edge < 0.005:
            return None
        if not (1.70 <= odds <= 6.00):
            return None
    elif mode == "relaxed_edge":
        if pick1.edge < 0.005:
            return None
        if not (1.70 <= odds <= 3.80):
            return None
    else:
        raise ValueError(f"Unknown ensemble mode: {mode}")

    model_prob = pick1.model_prob
    edge = min(pick1.edge, pick2.edge) if mode != "relaxed_edge" else pick1.edge
    ev = model_prob * odds - 1.0
    score = min(pick1.score, pick2.score)
    return Pick(pick1.market, model_prob, edge, ev, score)


def fetch_rows(conn, league: Optional[str], competition_type: str, season: Optional[str]):
    where = [
        "result_regulation IN ('home','draw','away')",
        "odds_home > 0", "odds_draw > 0", "odds_away > 0",
    ]
    params: List[str] = []

    if league:
        where.append("league = ?")
        params.append(league)

    if season:
        # season_key stored in v2; if absent then compute later, but query by season_key when available
        where.append("(season_key = ? OR season_key IS NULL)")
        params.append(season)

    rows = conn.execute(f"""
        SELECT *
        FROM {FEATURE_TABLE}
        WHERE {' AND '.join(where)}
        ORDER BY substr(match_date, 7, 4), substr(match_date, 4, 2), substr(match_date, 1, 2), league, home_team, away_team
    """, params).fetchall()

    if competition_type == "all":
        return rows
    return [r for r in rows if classify_competition(r["league"]) == competition_type]


def pass_filters(row, pick: Pick, args) -> bool:
    if history_games(row) < args.min_history:
        return False
    odds = odds_for_market(row, pick.market)
    if not odds:
        return False
    if odds < args.min_odds or odds > args.max_odds:
        return False
    if pick.edge < args.min_edge:
        return False
    if pick.ev < args.min_ev:
        return False

    imp = implied_probs(row)
    if not imp:
        return False

    fav = "H" if imp["H"] > imp["A"] else "A"
    dog = "A" if fav == "H" else "H"

    if args.market_mode == "favorite" and pick.market != fav:
        return False
    if args.market_mode == "underdog" and pick.market != dog:
        return False
    if args.market_mode == "home" and pick.market != "H":
        return False
    if args.market_mode == "away" and pick.market != "A":
        return False

    if args.score_min is not None and pick.score < args.score_min:
        return False
    if args.score_max is not None and pick.score > args.score_max:
        return False
    return True




def run_combined_backtest(rows: List, strategy: str, bank: float, args) -> dict:
    current_bank = bank
    peak = bank
    max_dd_abs = 0.0
    max_dd_pct = 0.0
    current_losing_streak = 0
    max_losing_streak = 0

    bets = []
    monthly = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})
    yearly = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})
    seasonal = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})

    for row in rows:
        row = dict(row)
        pick = combined_pick(row, strategy)
        if not pick:
            continue
            
        # Apply the same filters as regular strategies
        if not pass_filters(row, pick, args):
            continue

        odds = odds_for_market(row, pick.market)
        if not odds:
            continue

        # Calculate stake based on stake mode
        if args.stake_mode == "flat":
            stake = args.flat_stake
        else:  # kelly mode
            if not (0 < pick.model_prob < 1):
                continue  # Skip if model_prob is invalid
                
            b = odds - 1
            p = pick.model_prob
            q = 1 - p
            kelly_raw = (b * p - q) / b
            
            if kelly_raw <= 0:
                continue  # Skip negative expectation bets
                
            stake_pct = min(kelly_raw * args.kelly_fraction, args.max_stake_pct)
            stake = current_bank * stake_pct
            
            # Store for reporting
            row["stake_pct"] = stake_pct
            row["kelly_raw"] = kelly_raw

        won = row["result_regulation"] == {"H": "home", "D": "draw", "A": "away"}.get(pick.market, pick.market)
        profit = stake * (odds - 1) if won else -stake
        current_bank += profit

        if won:
            current_losing_streak = 0
        else:
            current_losing_streak += 1
            max_losing_streak = max(max_losing_streak, current_losing_streak)

        peak = max(peak, current_bank)
        dd_abs = peak - current_bank
        dd_pct = dd_abs / peak * 100.0 if peak > 0 else 0.0
        max_dd_abs = max(max_dd_abs, dd_abs)
        max_dd_pct = max(max_dd_pct, dd_pct)

        mkey = month_key(row["match_date"])
        skey = row["season_key"] if "season_key" in row.keys() and row["season_key"] else season_key(row["match_date"])
        ykey = season_year_start(skey)

        for key, bucket_map in ((mkey, monthly), (ykey, yearly), (skey, seasonal)):
            bucket = bucket_map[key]
            bucket["bets"] += 1
            bucket["wins"] += 1 if won else 0
            bucket["stake"] += stake
            bucket["profit"] += profit
            bucket["bank_after"] = current_bank

        bet_record = {
            "date": row["match_date"],
            "league": row["league"],
            "home": row["home_team"],
            "away": row["away_team"],
            "market": pick.market,
            "odds": odds,
            "our_p": round(pick.model_prob, 4),
            "edge": round(pick.edge, 4),
            "ev": round(pick.ev, 4),
            "score": round(pick.score, 4),
            "stake": stake,
            "won": won,
            "profit": round(profit, 2),
            "bank_after": round(current_bank, 2),
            "stake_mode": args.stake_mode,
        }
        
        # Add Kelly-specific fields if using Kelly staking
        if args.stake_mode == "kelly":
            bet_record["stake_pct"] = round(row.get("stake_pct", 0), 4)
            bet_record["kelly_raw"] = round(row.get("kelly_raw", 0), 4)
            
        bets.append(bet_record)

    if not bets:
        return {"bets": 0, "strategy": strategy, "bets_list": []}

    wins = sum(1 for b in bets if b["won"])
    total_staked = sum(b["stake"] for b in bets)
    total_profit = sum(b["profit"] for b in bets)
    roi = total_profit / total_staked * 100 if total_staked > 0 else 0
    winrate = wins / len(bets) * 100
    avg_odds = sum(b["odds"] for b in bets) / len(bets)

    return {
        "strategy": strategy,
        "bets": len(bets),
        "wins": wins,
        "losses": len(bets) - wins,
        "winrate": winrate,
        "total_staked": total_staked,
        "total_profit": total_profit,
        "roi": roi,
        "avg_odds": avg_odds,
        "final_bank": current_bank,
        "bank_growth": (current_bank - bank) / bank * 100,
        "max_drawdown_abs": max_dd_abs,
        "max_drawdown_pct": max_dd_pct,
        "max_losing_streak": max_losing_streak,
        "best_bet": max(bets, key=lambda b: b["profit"]),
        "worst_bet": min(bets, key=lambda b: b["profit"]),
        "bets_list": bets,
        "monthly": monthly,
        "yearly": yearly,
        "seasonal": seasonal,
    }


def run_ensemble_backtest(rows: List, strategy: str, bank: float, args) -> dict:
    current_bank = bank
    peak = bank
    max_dd_abs = 0.0
    max_dd_pct = 0.0
    current_losing_streak = 0
    max_losing_streak = 0

    bets = []
    monthly = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})
    yearly = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})
    seasonal = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})

    for row in rows:
        row = dict(row)
        if strategy in ["fp_or_fb", "fp_and_fb", "fp_or_fb_priority_fb"]:
            pick = combined_pick(row, strategy)
        else:
            pick = ensemble_pick(row, strategy)
        if not pick:
            continue

        odds = odds_for_market(row, pick.market)
        if not odds:
            continue

        # Calculate stake based on stake mode
        if args.stake_mode == "flat":
            stake = args.flat_stake
        else:  # kelly mode
            if not (0 < pick.model_prob < 1):
                continue  # Skip if model_prob is invalid
                
            b = odds - 1
            p = pick.model_prob
            q = 1 - p
            kelly_raw = (b * p - q) / b
            
            if kelly_raw <= 0:
                continue  # Skip negative expectation bets
                
            stake_pct = min(kelly_raw * args.kelly_fraction, args.max_stake_pct)
            stake = current_bank * stake_pct
            
            # Store for reporting
            row["stake_pct"] = stake_pct
            row["kelly_raw"] = kelly_raw

        won = row["result_regulation"] == {"H": "home", "D": "draw", "A": "away"}.get(pick.market, pick.market)
        profit = stake * (odds - 1) if won else -stake
        current_bank += profit

        if won:
            current_losing_streak = 0
        else:
            current_losing_streak += 1
            max_losing_streak = max(max_losing_streak, current_losing_streak)

        peak = max(peak, current_bank)
        dd_abs = peak - current_bank
        dd_pct = dd_abs / peak * 100.0 if peak > 0 else 0.0
        max_dd_abs = max(max_dd_abs, dd_abs)
        max_dd_pct = max(max_dd_pct, dd_pct)

        mkey = month_key(row["match_date"])
        skey = row["season_key"] if "season_key" in row.keys() and row["season_key"] else season_key(row["match_date"])
        ykey = season_year_start(skey)

        for key, bucket_map in ((mkey, monthly), (ykey, yearly), (skey, seasonal)):
            bucket = bucket_map[key]
            bucket["bets"] += 1
            bucket["wins"] += 1 if won else 0
            bucket["stake"] += stake
            bucket["profit"] += profit
            bucket["bank_after"] = current_bank

        bet_record = {
            "date": row["match_date"],
            "league": row["league"],
            "home": row["home_team"],
            "away": row["away_team"],
            "market": pick.market,
            "odds": odds,
            "our_p": round(pick.model_prob, 4),
            "edge": round(pick.edge, 4),
            "ev": round(pick.ev, 4),
            "score": round(pick.score, 4),
            "stake": stake,
            "won": won,
            "profit": round(profit, 2),
            "bank_after": round(current_bank, 2),
            "stake_mode": args.stake_mode,
        }
        
        # Add Kelly-specific fields if using Kelly staking
        if args.stake_mode == "kelly":
            bet_record["stake_pct"] = round(row.get("stake_pct", 0), 4)
            bet_record["kelly_raw"] = round(row.get("kelly_raw", 0), 4)
            
        bets.append(bet_record)

    if not bets:
        return {"bets": 0, "strategy": strategy, "bets_list": []}

    wins = sum(1 for b in bets if b["won"])
    total_staked = sum(b["stake"] for b in bets)
    total_profit = sum(b["profit"] for b in bets)
    roi = total_profit / total_staked * 100 if total_staked > 0 else 0
    winrate = wins / len(bets) * 100
    avg_odds = sum(b["odds"] for b in bets) / len(bets)

    return {
        "strategy": strategy,
        "bets": len(bets),
        "wins": wins,
        "losses": len(bets) - wins,
        "winrate": winrate,
        "total_staked": total_staked,
        "total_profit": total_profit,
        "roi": roi,
        "avg_odds": avg_odds,
        "final_bank": current_bank,
        "bank_growth": (current_bank - bank) / bank * 100,
        "max_drawdown_abs": max_dd_abs,
        "max_drawdown_pct": max_dd_pct,
        "max_losing_streak": max_losing_streak,
        "best_bet": max(bets, key=lambda b: b["profit"]),
        "worst_bet": min(bets, key=lambda b: b["profit"]),
        "bets_list": bets,
        "monthly": monthly,
        "yearly": yearly,
        "seasonal": seasonal,
    }


def run_backtest(rows: List, strategy: str, bank: float, args) -> dict:
    current_bank = bank
    peak = bank
    max_dd_abs = 0.0
    max_dd_pct = 0.0
    current_losing_streak = 0
    max_losing_streak = 0

    bets = []
    monthly = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})
    yearly = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})
    seasonal = defaultdict(lambda: {"bets": 0, "wins": 0, "stake": 0.0, "profit": 0.0, "bank_after": bank})

    fn = STRATEGIES[strategy]

    for row in rows:
        row = dict(row)
        pick = fn(row)
        if not pick:
            continue
        if not pass_filters(row, pick, args):
            continue

        odds = odds_for_market(row, pick.market)
        if not odds:
            continue

        # Calculate stake based on stake mode
        if args.stake_mode == "flat":
            stake = args.flat_stake
        else:  # kelly mode
            if not (0 < pick.model_prob < 1):
                continue  # Skip if model_prob is invalid
                
            b = odds - 1
            p = pick.model_prob
            q = 1 - p
            kelly_raw = (b * p - q) / b
            
            if kelly_raw <= 0:
                continue  # Skip negative expectation bets
                
            stake_pct = min(kelly_raw * args.kelly_fraction, args.max_stake_pct)
            stake = current_bank * stake_pct
            
            # Store for reporting
            row["stake_pct"] = stake_pct
            row["kelly_raw"] = kelly_raw

        won = row["result_regulation"] == {"H": "home", "D": "draw", "A": "away"}.get(pick.market, pick.market)
        profit = stake * (odds - 1) if won else -stake
        current_bank += profit

        if won:
            current_losing_streak = 0
        else:
            current_losing_streak += 1
            max_losing_streak = max(max_losing_streak, current_losing_streak)

        peak = max(peak, current_bank)
        dd_abs = peak - current_bank
        dd_pct = dd_abs / peak * 100.0 if peak > 0 else 0.0
        max_dd_abs = max(max_dd_abs, dd_abs)
        max_dd_pct = max(max_dd_pct, dd_pct)

        mkey = month_key(row["match_date"])
        skey = row["season_key"] if "season_key" in row.keys() and row["season_key"] else season_key(row["match_date"])
        ykey = season_year_start(skey)

        for key, bucket_map in ((mkey, monthly), (ykey, yearly), (skey, seasonal)):
            bucket = bucket_map[key]
            bucket["bets"] += 1
            bucket["wins"] += 1 if won else 0
            bucket["stake"] += stake
            bucket["profit"] += profit
            bucket["bank_after"] = current_bank

        bet_record = {
            "date": row["match_date"],
            "league": row["league"],
            "home": row["home_team"],
            "away": row["away_team"],
            "market": pick.market,
            "odds": odds,
            "our_p": round(pick.model_prob, 4),
            "edge": round(pick.edge, 4),
            "ev": round(pick.ev, 4),
            "score": round(pick.score, 4),
            "stake": stake,
            "won": won,
            "profit": round(profit, 2),
            "bank_after": round(current_bank, 2),
            "stake_mode": args.stake_mode,
        }
        
        # Add Kelly-specific fields if using Kelly staking
        if args.stake_mode == "kelly":
            bet_record["stake_pct"] = round(row.get("stake_pct", 0), 4)
            bet_record["kelly_raw"] = round(row.get("kelly_raw", 0), 4)
            
        bets.append(bet_record)

    if not bets:
        return {"bets": 0, "strategy": strategy, "bets_list": []}

    wins = sum(1 for b in bets if b["won"])
    total_staked = sum(b["stake"] for b in bets)
    total_profit = sum(b["profit"] for b in bets)
    roi = total_profit / total_staked * 100 if total_staked > 0 else 0
    winrate = wins / len(bets) * 100

    return {
        "strategy": strategy,
        "bets": len(bets),
        "wins": wins,
        "losses": len(bets) - wins,
        "winrate": winrate,
        "total_staked": total_staked,
        "total_profit": total_profit,
        "roi": roi,
        "final_bank": current_bank,
        "bank_growth": (current_bank - bank) / bank * 100,
        "max_drawdown_abs": max_dd_abs,
        "max_drawdown_pct": max_dd_pct,
        "max_losing_streak": max_losing_streak,
        "best_bet": max(bets, key=lambda b: b["profit"]),
        "worst_bet": min(bets, key=lambda b: b["profit"]),
        "bets_list": bets,
        "monthly": monthly,
        "yearly": yearly,
        "seasonal": seasonal,
    }


def print_result(r: dict, verbose: bool = False):
    if r["bets"] == 0:
        print(f"  {r.get('strategy','?'):24s} | 0 ставок")
        return

    roi_icon = "✅" if r["roi"] >= 4 else ("⚠️" if r["roi"] >= 0 else "❌")
    print(f"\n  Стратегия: {r['strategy']}")
    print(f"  Ставок: {r['bets']} | W:{r['wins']} L:{r['losses']} | "
          f"Винрейт: {r['winrate']:.1f}%")
    print(f"  Поставлено: {r['total_staked']:,.0f} руб")
    print(f"  Прибыль: {r['total_profit']:+,.0f} руб")
    print(f"  {roi_icon} ROI: {r['roi']:+.2f}%")
    if "avg_odds" in r:
        print(f"  Ср. коэффициент: {r['avg_odds']:.2f}")
    print(f"  Банк: {BANK:,.0f} → {r['final_bank']:,.0f} руб "
          f"({r['bank_growth']:+.1f}%)")
    print(f"  Просадка: {r['max_drawdown_abs']:,.0f} руб | {r['max_drawdown_pct']:.2f}%")
    print(f"  Лузстрик: {r['max_losing_streak']}")

    if verbose and r["bets_list"]:
        print(f"\n  Лучшая ставка: {r['best_bet']['home']} — {r['best_bet']['away']} "
              f"| {r['best_bet']['market']} @ {r['best_bet']['odds']} "
              f"| +{r['best_bet']['profit']:,.0f} руб")
        print(f"  Худшая ставка: {r['worst_bet']['home']} — {r['worst_bet']['away']} "
              f"| {r['worst_bet']['market']} @ {r['worst_bet']['odds']} "
              f"| {r['worst_bet']['profit']:,.0f} руб")


def write_breakdown_csv(path: Path, results: List[dict], bucket_name: str):
    rows_out = []
    for r in results:
        bucket = r.get(bucket_name, {})
        for key, d in bucket.items():
            roi = d["profit"] / d["stake"] * 100 if d["stake"] > 0 else 0
            rows_out.append({
                "strategy": r["strategy"],
                bucket_name[:-2] if bucket_name.endswith("ly") else bucket_name: key,
                "bets": d["bets"],
                "wins": d["wins"],
                "hit_rate": round(d["wins"] / d["bets"] * 100 if d["bets"] else 0, 4),
                "stake": round(d["stake"], 2),
                "profit": round(d["profit"], 2),
                "roi": round(roi, 4),
                "bank_after": round(d["bank_after"], 2),
            })
    if not rows_out:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)


def write_bets_csv(path: Path, results: List[dict]):
    rows_out = []
    for r in results:
        for b in r.get("bets_list", []):
            row = dict(b)
            row["strategy"] = r["strategy"]
            rows_out.append(row)
    if not rows_out:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)


def write_summary_csv(path: Path, results: List[dict], league: str, competition_type: str):
    rows_out = []
    for r in results:
        rows_out.append({
            "league": league,
            "competition_type": competition_type,
            "strategy": r["strategy"],
            "bets": r["bets"],
            "wins": r.get("wins", 0),
            "losses": r.get("losses", 0),
            "winrate": round(r.get("winrate", 0), 4),
            "total_staked": round(r.get("total_staked", 0), 2),
            "total_profit": round(r.get("total_profit", 0), 2),
            "roi": round(r.get("roi", 0), 4),
            "final_bank": round(r.get("final_bank", BANK), 2),
            "bank_growth": round(r.get("bank_growth", 0), 4),
            "max_drawdown_abs": round(r.get("max_drawdown_abs", 0), 2),
            "max_drawdown_pct": round(r.get("max_drawdown_pct", 0), 4),
            "max_losing_streak": r.get("max_losing_streak", 0),
        })
    if not rows_out:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        writer.writeheader()
        writer.writerows(rows_out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default=None, help="Точное название лиги из базы")
    ap.add_argument("--competition-type", choices=["all", "regular", "playoff", "cup"], default="all")
    ap.add_argument("--season", default=None, help="Например 2023/2024")
    ap.add_argument("--strategy", nargs="+", default=None, help="Одна или несколько стратегий")
    ap.add_argument("--all-strategies", action="store_true")
    ap.add_argument("--min-odds", type=float, default=1.50)
    ap.add_argument("--max-odds", type=float, default=6.00)
    ap.add_argument("--min-edge", type=float, default=0.00)
    ap.add_argument("--min-ev", type=float, default=0.00)
    ap.add_argument("--min-history", type=int, default=3)
    ap.add_argument("--market-mode", choices=["any", "favorite", "underdog", "home", "away"], default="any")
    ap.add_argument("--score-min", type=float, default=None)
    ap.add_argument("--score-max", type=float, default=None)
    ap.add_argument("--flat-stake", type=float, default=1000.0)
    ap.add_argument("--stake-mode", choices=["flat", "kelly"], default="flat", help="Режим ставок: фиксированный или Келли")
    ap.add_argument("--kelly-fraction", type=float, default=0.25, help="Доля от полного Келли (0.1-0.5)")
    ap.add_argument("--max-stake-pct", type=float, default=0.05, help="Максимальный % банка на одну ставку")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    conn = get_conn()
    count = conn.execute(f"SELECT COUNT(*) FROM {FEATURE_TABLE}").fetchone()[0]
    if count == 0:
        print("❌ Нет исторических хоккейных данных")
        conn.close()
        return

    rows = fetch_rows(conn, args.league, args.competition_type, args.season)
    conn.close()

    if not rows:
        print("❌ Нет матчей для бэктеста")
        return

    print(f"\n{'='*72}")
    print("  BETAGENT — HOCKEY FAST BACKTEST")
    print(f"  Матчей: {len(rows)}")
    if args.league:
        print(f"  Лига: {args.league}")
    print(f"  Тип: {args.competition_type}")
    if args.season:
        print(f"  Сезон: {args.season}")
    print(f"  Банк: {BANK:,.0f} руб | Режим ставок: {args.stake_mode}")
    if args.stake_mode == "flat":
        print(f"  Flat stake: {args.flat_stake:,.0f}")
    else:
        print(f"  Kelly fraction: {args.kelly_fraction:.2f} | Max stake: {args.max_stake_pct:.1%} от банка")
    print(f"  Odds: {args.min_odds:.2f}-{args.max_odds:.2f} | Edge >= {args.min_edge:.3f} | EV >= {args.min_ev:.3f}")
    print(f"{'='*72}")

    if args.strategy:
        strategies = args.strategy
    elif args.all_strategies:
        strategies = list(STRATEGIES.keys()) + sorted(list(ENSEMBLE_STRATEGIES))
    else:
        strategies = [
            "underdog_live",
            "collapse_favorite_fade",
            "defensive_wall",
            "strict_intersection",
            "relaxed_odds",
            "relaxed_edge",
            "fp_or_fb",
            "fp_and_fb",
            "fp_or_fb_priority_fb",
        ]

    results = []
    for strategy in strategies:
        if strategy in ["fp_or_fb", "fp_and_fb", "fp_or_fb_priority_fb"]:
            r = run_combined_backtest(rows, strategy, BANK, args)
        elif strategy in ENSEMBLE_STRATEGIES:
            r = run_ensemble_backtest(rows, strategy, BANK, args)
        else:
            r = run_backtest(rows, strategy, BANK, args)
        r["strategy"] = strategy
        results.append(r)
        print_result(r, verbose=args.verbose)

    print(f"\n{'='*72}")
    print("  СВОДКА (по ROI):")
    valid = [r for r in results if r["bets"] > 0]
    valid.sort(key=lambda r: r["roi"], reverse=True)
    for r in valid:
        roi_icon = "✅" if r["roi"] >= 4 else ("⚠️" if r["roi"] >= 0 else "❌")
        print(f"  {roi_icon} {r['strategy']:24s} | "
              f"{r['bets']:4d} ставок | "
              f"ROI: {r['roi']:+6.2f}% | "
              f"Прибыль: {r['total_profit']:+,.0f} руб | "
              f"DD: {r['max_drawdown_pct']:.2f}% | "
              f"LS: {r['max_losing_streak']}")

    if args.report:
        reports_dir = DB_PATH.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        league_slug = (args.league or "all").replace("/", "_").replace(" ", "_").replace(".", "").replace(",", "")[:80]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        summary_path = reports_dir / f"hockey_fast_summary_{league_slug}_{ts}.csv"
        monthly_path = reports_dir / f"hockey_fast_monthly_{league_slug}_{ts}.csv"
        yearly_path = reports_dir / f"hockey_fast_yearly_{league_slug}_{ts}.csv"
        seasonal_path = reports_dir / f"hockey_fast_seasonal_{league_slug}_{ts}.csv"
        bets_path = reports_dir / f"hockey_fast_bets_{league_slug}_{ts}.csv"

        write_summary_csv(summary_path, results, args.league or "all", args.competition_type)
        write_breakdown_csv(monthly_path, results, "monthly")
        write_breakdown_csv(yearly_path, results, "yearly")
        write_breakdown_csv(seasonal_path, results, "seasonal")
        write_bets_csv(bets_path, results)

        print(f"\nSaved reports:")
        print(summary_path)
        print(monthly_path)
        print(yearly_path)
        print(seasonal_path)
        print(bets_path)

    if args.verbose or args.top:
        all_bets = []
        for r in valid:
            for b in r.get("bets_list", []):
                row = dict(b)
                row["strategy"] = r["strategy"]
                all_bets.append(row)

        if all_bets:
            all_bets.sort(key=lambda b: b["profit"], reverse=True)
            print(f"\n  ТОП-{args.top} лучших ставок:")
            for b in all_bets[:args.top]:
                print(f"  ✅ {b['date']} | {b['home']} — {b['away']} | "
                      f"{b['market']} @ {b['odds']} | "
                      f"+{b['profit']:,.0f} руб | {b['strategy']}")

            print(f"\n  ТОП-{args.top} худших ставок:")
            all_bets.sort(key=lambda b: b["profit"])
            for b in all_bets[:args.top]:
                print(f"  ❌ {b['date']} | {b['home']} — {b['away']} | "
                      f"{b['market']} @ {b['odds']} | "
                      f"{b['profit']:,.0f} руб | {b['strategy']}")

    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
