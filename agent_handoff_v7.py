#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — agent_handoff_v7.py

Архитектура: единый движок + sport profiles.

Что нового в v7:
  - Калибровка вероятности вынесена в sport_profiles.json
  - Один движок для всех видов спорта
  - Профиль подгружается по match.sport
  - Weak/Medium без составов режутся по-разному (из профиля)
  - Добавлен pre-flight фильтр: если данных совсем нет → PASS без LLM
  - Хоккей использует стратегии из hockey_backtest_fast_v2.py

Запуск:
  python agent_handoff_v7.py --dry-run --sport hockey --limit 11
  python agent_handoff_v7.py --dry-run --sport football --limit 20
  python agent_handoff_v7.py --sport hockey --limit 11
  python agent_handoff_v7.py --dry-run --sport football --limit 10 --no-llm
  python agent_handoff_v7.py --sport football --limit 100 --backtest
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, Counter
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from validator import (
    confidence_cap_pct,
    compute_kelly,
)

# Import hockey strategy functions from hockey_backtest_fast_v2.py
from hockey_backtest_fast_v2 import (
    implied_probs, odds_for_market, getv, safe_float, clamp,
    underdog_live, defensive_wall, history_games, Pick,
    nhl_draw_tight, favorite_pressure, favorite_bounceback, combined_pick,
    czech_home_favorite
)

from strategies.football import (
    FOOTBALL_LEAGUE_STAKING,
    BACKTEST_LEAGUE_NAME_MAP,
    normalize_rule_league_name,
    detect_football_league_key,
    SA_AWAY_TEAMS,
    SUMMER_TEAMS,
)
from strategies.football_rules import get_pruned_live_rule

from analysis_helpers.probability_pipeline import (
    SPORT_PROFILES,
    DEFAULT_PROFILE,
    get_profile,
    _wins,
    _draws,
    _norm_form_list,
    _pick_first_nonempty,
    normalize_known_facts_for_rules,
    merge_known_facts,
    is_backtest_approved,
    pre_flight_check,
    calibrate_probability,
)
from analysis_helpers.backtest_reporting import (
    is_shadow_recommendation,
    get_strategy_bucket,
    init_strategy_row,
    update_strategy_stats,
    update_equity_metrics,
    update_streaks,
    print_strategy_summary,
    resolve_actual_market_from_match,
)
from analysis_helpers.llm_utils import (
    extract_json_object,
    normalize_response,
    build_structured_comment,
)
from analysis_helpers.match_utils import (
    ba_rule_to_market,
    _ba_tag,
    _rule_tag,
    get_market_family,
    is_placeholder_match,
    safe_prob,
    _coerce_float,
)

from strategies.hockey import (
    HOCKEY_LEAGUE_CONFIG,
    detect_league_key,
    get_hockey_features,
    validate_hockey_recommendation,
    process_hockey_match,
    _set_dependencies,
)

def validate_recommendation(
    rec: Dict[str, Any],
    payload: Dict[str, Any],
    bankroll: float,
) -> Tuple[bool, List[str]]:
    """
    Валидирует рекомендацию по бизнес-правилам.
    Возвращает (valid, notes).
    """
    notes = []
    valid = True
    
    # Check if we're in dry-run mode
    dry_run_mode = getattr(GLOBAL_ARGS, "dry_run", False)
    
    # Get market family for market-specific exposure checks
    market = rec.get("market", "")
    market_family = get_market_family(market)
    is_btts_market = market_family == "BTTS"

    # Проверка 1: Нет рынка или odds
    if rec.get("market") == "pass" or not rec.get("odds"):
        return False, ["Нет рынка или коэффициента"]

    # Проверка 2: Нет нашей вероятности
    our_p = rec.get("our_probability")
    if not our_p:
        return False, ["Нет нашей вероятности"]

    # Проверка 3: Нет edge
    market_p = rec.get("market_probability")
    if not market_p or our_p <= market_p:
        return False, ["Нет edge: our_p <= market_p"]

    # Проверка 4: Слишком низкий EV
    ev = rec.get("ev")
    if not ev or ev < 0.03:
        return False, [f"Низкий EV: {ev:.3f} < 0.03"]

    # Проверка 5: Слишком низкая уверенность (только если поле явно задано)
    confidence = rec.get("confidence")
    if confidence is not None and confidence < 5:
        return False, [f"Низкая уверенность: {confidence} < 5"]

    # Проверка 6: Слишком высокая открытая экспозиция
    stake_pct = rec.get("stake_pct")
    if not stake_pct:
        return False, ["Нет размера ставки"]

    # Получаем текущую открытую экспозицию
    conn = get_conn()
    
    # Get global exposure
    row = conn.execute(
        "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending'"
    ).fetchone()
    current_exposure = float(row["s"] or 0.0)
    # В бэктесте обнуляем экспозицию
    if GLOBAL_ARGS and getattr(GLOBAL_ARGS, "backtest", False):
        current_exposure = 0.0
    
    # Get market family specific exposure
    if market_family == "1X2":
        row_family = conn.execute(
            "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending' AND market IN ('home', 'draw', 'away')"
        ).fetchone()
    elif market_family == "BTTS":
        row_family = conn.execute(
            "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending' AND (market LIKE 'btts_%' OR market LIKE 'BTTS_%')"
        ).fetchone()
    elif market_family == "TOTALS":
        row_family = conn.execute(
            "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending' AND (market LIKE 'over_%' OR market LIKE 'under_%' OR market LIKE '%total%')"
        ).fetchone()
    else:
        row_family = conn.execute(
            "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending' AND market = ?",
            (market,)
        ).fetchone()
    
    current_family_exposure = float(row_family["s"] or 0.0)
    conn.close()

    # Считаем новую экспозицию
    new_stake = bankroll * stake_pct
    new_exposure = current_exposure + new_stake
    new_exposure_pct = new_exposure / bankroll
    
    new_family_exposure = current_family_exposure + new_stake
    new_family_exposure_pct = new_family_exposure / bankroll

    # Проверяем лимит экспозиции
    if new_exposure_pct > 0.5:  # 50% лимит
        # In dry-run mode, use market family specific limits for BTTS
        if dry_run_mode and is_btts_market:
            # For BTTS in dry-run, use a separate exposure check
            if new_family_exposure_pct > 0.25:  # 25% limit for BTTS family
                valid = False
                notes.append(f"BTTS экспозиция превысит 25%: {new_family_exposure_pct:.1%}")
            else:
                # Just add a warning note but don't invalidate
                notes.append(f"[ПРЕДУПРЕЖДЕНИЕ] Общая экспозиция превысит 50%: {new_exposure_pct:.1%}, но разрешено в dry-run для BTTS")
        else:
            # Standard behavior for production or non-BTTS markets
            valid = False
            notes.append(f"Открытая экспозиция превысит 50%: {new_exposure_pct:.1%}")

    # Проверка 7: Слишком большая ставка
    if stake_pct > 0.1:  # 10% лимит на одну ставку
        valid = False
        notes.append(f"Слишком большая ставка: {stake_pct:.1%} > 10%")

    # Проверка 8: Нет объяснения ошибки рынка
    market_error = rec.get("market_error")
    if not market_error or len(market_error) < 5:
        valid = False
        notes.append("Нет объяснения ошибки рынка")

    return valid, notes

RULES_VERSION = "v2.2"
DB_PATH = Path(os.getenv("BETAGENT_DB_PATH", os.getenv("BETAGENT_DB", "betagent.db")))
DEFAULT_BANK = float(os.getenv("BETAGENT_BANK", "100000"))
GLOBAL_ARGS = None
TIMEZONE = timezone.utc

args = None


def build_rule_recommendation(match: "Match", facts: Dict[str, Any], rule_name: str, market: str, bankroll: float) -> Dict[str, Any]:
    """
    Создает рекомендацию на основе правила из pruned portfolio.
    """
    # Базовые параметры для всех правил
    lineup_ok = bool(facts.get("lineup_data_available", False))
    odds_map = {"home": match.odds_home, "draw": match.odds_draw, "away": match.odds_away}
    
    # Add BTTS markets if available
    if hasattr(match, "odds_btts_yes"):
        odds_map["btts_yes"] = match.odds_btts_yes
    if hasattr(match, "odds_btts_no"):
        odds_map["btts_no"] = match.odds_btts_no
    # Add totals markets if available
    if hasattr(match, "odds_over_2_5") and match.odds_over_2_5:
        odds_map["over_2_5"] = match.odds_over_2_5
    if hasattr(match, "odds_under_2_5") and match.odds_under_2_5:
        odds_map["under_2_5"] = match.odds_under_2_5
        
    odds = float(odds_map.get(market, 0))
    market_p = 1.0 / odds if odds > 0 else 0
    
    # Базовые probability для каждого правила (из исторических данных)
    rule_probabilities = {
        "DRAW_SA": 0.40,
        "PD_AWAY_VALUE": 0.504,
        "SA_AWAY_DRAW": 0.483,
        "DRAW_BL1_FL1": 0.39,
        "AWAY_SA": 0.43,
        "DRAW_BALANCED_LOW_SCORING_SA": 0.40,
        "DRAW_BALANCED_LINE_SA": 0.37,
        "DRAW_BALANCED_LINE_BL1": 0.34,
        "AWAY_SA_STRICT_PLUS": 0.42,
        "BTTS_YES_CORE": 0.60,  # Historical probability for BTTS_YES
        "RPL_OVER25_BTTS": 0.57,  # Historical WR in backtest
        "PD_BTTS_DOUBLE": 0.62,   # Historical WR in backtest
        "FL1_BTTS_DOUBLE": 0.576,  # Historical WR in backtest
        "NLA_BERN_AWAY_DRAW": 0.342,  # Historical WR in backtest
        "SUMMER_BTTS_HOME": 0.734,
        "MLS_BTTS_HOME": 0.693,   # Historical WR in backtest
        "ECU_BTTS_NO": 0.762,     # HR_no=76.2%, ROI+32.5%, MaxLS=2, n=84
    }
    
    # Базовая уверенность для каждого правила
    rule_confidence = {
        "DRAW_SA": 6,
        "SA_AWAY_DRAW": 6,
        "DRAW_BL1_FL1": 6,
        "AWAY_SA": 6,
        "DRAW_BALANCED_LOW_SCORING_SA": 5,
        "DRAW_BALANCED_LINE_SA": 5,
        "DRAW_BALANCED_LINE_BL1": 5,
        "AWAY_SA_STRICT_PLUS": 6,
        "BTTS_YES_CORE": 7,  # Higher confidence for BTTS_YES_CORE
        "RPL_OVER25_BTTS": 7,
        "PD_BTTS_DOUBLE": 7,
        "FL1_BTTS_DOUBLE": 7,
        "NLA_BERN_AWAY_DRAW": 5,
        "SUMMER_BTTS_HOME": 7,
        "ECU_BTTS_NO": 7,
    }
    
    # Описания ошибок рынка для каждого правила
    market_error_map = {
        "DRAW_SA": "Рынок недооценивает ничью в равном низовом матче Серии А",
        "SA_AWAY_DRAW": "Аутсайдеры SA в гостях системно дают ничью при low-scoring матче",
        "DRAW_BL1_FL1": "Рынок недооценивает ничью в равном матче с паритетной линией",
        "AWAY_SA": "Рынок недооценивает гостя с лучшей формой и позицией в таблице",
        "DRAW_BALANCED_LOW_SCORING_SA": "Рынок недооценивает ничью в низовом матче равных команд",
        "DRAW_BALANCED_LINE_SA": "Рынок недооценивает ничью при равной линии и близких командах",
        "DRAW_BALANCED_LINE_BL1": "Рынок недооценивает ничью при равной линии в Бундеслиге",
        "AWAY_SA_STRICT_PLUS": "Рынок недооценивает сильного гостя с явным преимуществом",
        "BTTS_YES_CORE": "Рынок недооценивает вероятность обе забьют в матче атакующих команд",
        "RPL_OVER25_BTTS": "Рынок неэффективно оценивает голевые матчи РПЛ — двойной сигнал Over2.5 и BTTS",
        "PD_BTTS_DOUBLE": "Рынок Ла Лиги недооценивает BTTS когда оба рынка (Over2.5 + BTTS) в голевом диапазоне",
        "FL1_BTTS_DOUBLE": "Рынок Лиги 1 недооценивает BTTS когда оба рынка (Over2.5 + BTTS) в голевом диапазоне",
        "SUMMER_BTTS_HOME": "Топ-команды летних лиг системно дают BTTS дома — рынок недооценивает вероятность",
        "ECU_BTTS_NO": "Рынок Эквадора систематически переоценивает BTTS yes при коэф 1.90-2.15 — обе не забивают в 76% случаев",
    }
    
    # Подтвержденные факты для каждого правила
    home_pos = facts.get("home_position")
    away_pos = facts.get("away_position")
    home_scored = facts.get("home_goals_scored_avg")
    away_scored = facts.get("away_goals_scored_avg")
    home_allowed = facts.get("home_goals_allowed_avg")
    away_allowed = facts.get("away_goals_allowed_avg")
    home_form = facts.get("form_last_5_home") or []
    away_form = facts.get("form_last_5_away") or []
    home_w = _wins(home_form)
    away_w = _wins(away_form)
    
    # Calculate form stats for BTTS
    form_scored_last5_home = 0
    form_conceded_last5_home = 0
    form_scored_last5_away = 0
    form_conceded_last5_away = 0
    
    # Extract goals from form data if available
    for match_data in facts.get("home_form_details", []):
        if isinstance(match_data, dict) and "goals_for" in match_data and "goals_against" in match_data:
            form_scored_last5_home += match_data["goals_for"]
            form_conceded_last5_home += match_data["goals_against"]
            
    for match_data in facts.get("away_form_details", []):
        if isinstance(match_data, dict) and "goals_for" in match_data and "goals_against" in match_data:
            form_scored_last5_away += match_data["goals_for"]
            form_conceded_last5_away += match_data["goals_against"]
    
    # Calculate averages
    home_form_len = len(facts.get("home_form_details", [])) or len(home_form) or 5
    away_form_len = len(facts.get("away_form_details", [])) or len(away_form) or 5
    
    if home_form_len > 0:
        form_scored_last5_home /= home_form_len
        form_conceded_last5_home /= home_form_len
    if away_form_len > 0:
        form_scored_last5_away /= away_form_len
        form_conceded_last5_away /= away_form_len
    
    # Fallback to season averages if form details not available
    if form_scored_last5_home == 0 and home_scored is not None:
        form_scored_last5_home = float(home_scored)
    if form_conceded_last5_home == 0 and home_allowed is not None:
        form_conceded_last5_home = float(home_allowed)
    if form_scored_last5_away == 0 and away_scored is not None:
        form_scored_last5_away = float(away_scored)
    if form_conceded_last5_away == 0 and away_allowed is not None:
        form_conceded_last5_away = float(away_allowed)
    
    confirmed_facts = []
    
    if "DRAW" in rule_name:
        confirmed_facts.extend([
            f"Правило {rule_name} для ничьих",
            f"Коэффициент на X: {odds:.2f}",
        ])
        if home_pos is not None and away_pos is not None:
            confirmed_facts.append(f"Близкие позиции в таблице: {home_pos} vs {away_pos}")
        if "BALANCED_LINE" in rule_name and match.odds_home is not None and match.odds_away is not None:
            confirmed_facts.append(f"Равная линия: {match.odds_home:.2f} vs {match.odds_away:.2f}")
        if "LOW_SCORING" in rule_name and home_scored is not None and away_scored is not None:
            confirmed_facts.append(f"Низкая атака: {home_scored:.2f} / {away_scored:.2f}")
    elif "AWAY" in rule_name:
        confirmed_facts.extend([
            f"Правило {rule_name} для П2",
            f"Коэффициент на П2: {odds:.2f}",
        ])
        if home_pos is not None and away_pos is not None:
            confirmed_facts.append(f"Гости выше в таблице: {away_pos} vs {home_pos}")
        if home_w is not None and away_w is not None:
            confirmed_facts.append(f"Лучшая форма у гостей: {away_w}W vs {home_w}W")
        if home_allowed is not None and away_scored is not None:
            confirmed_facts.append(f"Хозяева пропускают {home_allowed:.2f}, гости забивают {away_scored:.2f}")
    elif "BTTS" in rule_name:
        confirmed_facts.extend([
            f"Правило {rule_name} для Обе забьют",
            f"Коэффициент на ОЗ: {odds:.2f}",
        ])
        confirmed_facts.append(f"Хозяева забивают: {form_scored_last5_home:.2f} за матч")
        confirmed_facts.append(f"Гости забивают: {form_scored_last5_away:.2f} за матч")
        confirmed_facts.append(f"Хозяева пропускают: {form_conceded_last5_home:.2f} за матч")
        confirmed_facts.append(f"Гости пропускают: {form_conceded_last5_away:.2f} за матч")
    elif rule_name == "RPL_OVER25_BTTS":
        o25 = getattr(match, "odds_over_2_5", None)
        btts = getattr(match, "odds_btts_yes", None)
        confirmed_facts.extend([
            f"Двойной сигнал: Over2.5={o25:.2f} и BTTS={btts:.2f}",
            f"Оба рынка подтверждают голевой матч РПЛ",
            f"Рыночная неэффективность: ROI +13.4% за 5 сезонов",
        ])
    elif rule_name == "PD_BTTS_DOUBLE":
        o25 = getattr(match, "odds_over_2_5", None)
        btts = getattr(match, "odds_btts_yes", None)
        confirmed_facts.extend([
            f"Двойной сигнал Ла Лиги: Over2.5={o25:.2f} и BTTS={btts:.2f}",
            f"Низкий Over2.5 подтверждает голевой матч",
            f"Рыночная неэффективность: ROI +15% за 5 сезонов",
        ])
    elif rule_name == "RPL_OVER25_BTTS":
        o25 = getattr(match, "odds_over_2_5", None)
        btts = getattr(match, "odds_btts_yes", None)
        confirmed_facts.extend([
            f"Двойной сигнал: Over2.5={o25:.2f} и BTTS={btts:.2f}",
            f"Оба рынка подтверждают голевой матч РПЛ",
            f"Рыночная неэффективность: ROI +13.4% за 5 сезонов",
        ])
    elif rule_name == "PD_BTTS_DOUBLE":
        o25 = getattr(match, "odds_over_2_5", None)
        btts = getattr(match, "odds_btts_yes", None)
        confirmed_facts.extend([
            f"Двойной сигнал Ла Лиги: Over2.5={o25:.2f} и BTTS={btts:.2f}",
            f"Низкий Over2.5 подтверждает голевой матч",
            f"Рыночная неэффективность: ROI +15% за 5 сезонов",
        ])
    
    # Создаем базовую рекомендацию
    our_probability = rule_probabilities.get(rule_name, 0.38)
    
    # Определяем market_family
    market_family = get_market_family(market)
    
    # Создаем краткое описание для BTTS_YES_CORE
    explanation_short = ""
    if rule_name == "BTTS_YES_CORE":
        explanation_short = "Обе команды стабильно забивают и пропускают; коэффициент в рабочем диапазоне стратегии."
    
    # Создаем рекомендацию
    rec = {
        "market": market,
        "market_label": {"home": "П1", "draw": "X", "away": "П2", "btts_yes": "Обе забьют — Да", "btts_no": "Обе забьют — Нет", "over_2_5": "ТБ 2.5", "under_2_5": "ТМ 2.5", "over_1_5": "ТБ 1.5", "under_1_5": "ТМ 1.5"}.get(market, market),
        "odds": odds,
        "our_probability": our_probability,
        "market_probability": market_p,
        "ev": our_probability * odds - 1.0,
        "market_error": market_error_map.get(rule_name, f"Правило {rule_name} нашло edge"),
        "market_error_summary": f"Rule-driven: {rule_name}",
        "confirmed_facts": confirmed_facts,
        "unconfirmed": [],
        "lineup_data_available": lineup_ok,
        "signal_type": "Medium",
        "confidence": rule_confidence.get(rule_name, 5),
        "decision": "BET",
        "recommended_action": "BET",
        "rule_driven": True,
        "live_rule_family": rule_name,
        "shadow_only": False,
        "strategy_family": rule_name,
        "market_family": market_family,
        "reason_summary": market_error_map.get(rule_name, f"Правило {rule_name} нашло edge"),
        "supporting_facts": ", ".join(confirmed_facts[:3]),
        "explanation_short": explanation_short,
    }
    
    # Apply stake mode if available (will be applied in enrich_with_math)
    conn = get_conn()
    try:
        # Try to get stake from config
        override_stake_pct, override_stake_abs, stake_meta = resolve_stake_pct_and_meta(conn, bankroll, match, rec)
        if override_stake_pct is not None and rule_name != "BTTS_YES_CORE":
            # Add stake mode metadata to recommendation
            if stake_meta:
                rec.update({
                    "stake_mode_name": stake_meta.get("stake_mode_name"),
                    "stake_mode_type": stake_meta.get("stake_mode_type"),
                    "stake_mode_reason": stake_meta.get("stake_mode_reason"),
                })
                
                # Add bankroll regime info if available
                if "base_bankroll" in stake_meta:
                    rec.update({
                        "base_bankroll": stake_meta.get("base_bankroll"),
                        "current_bankroll": stake_meta.get("current_bankroll"),
                        "bankroll_regime": stake_meta.get("bankroll_regime"),
                    })
    except Exception as e:
        # Log error but continue
        rec["stake_mode_error"] = str(e)
    finally:
        conn.close()
    
    return rec

# ba_rule_to_market, _ba_tag, _rule_tag moved to analysis_helpers/match_utils.py


# ============================================================
# PROMPTS
# ============================================================

SYSTEM_PROMPT = """Ты — BETAGENT, спортивный агент ставок.
Работай СТРОГО по BETAGENT v2.2.

Верни ответ ТОЛЬКО в JSON, без markdown и без пояснений вне JSON.

Верни ТОЛЬКО эти поля:
{
  "match": "Команда1 — Команда2",
  "sport": "football|hockey",
  "market": "home|draw|away|pass",
  "market_label": "П1|X|П2|PASS",
  "our_probability": 0.55,
  "market_error": "Кратко: где ошибка рынка",
  "confirmed_facts": ["факт 1", "факт 2"],
  "unconfirmed": ["гипотеза 1"],
  "lineup_data_available": false,
  "signal_type": "Strong|Medium|Weak|Pass",
  "confidence": 6,
  "decision": "BET|SMALL|PASS"
}

ВАЖНО:
- НЕ считай EV, Kelly, probability рынка, stake_pct
- Если матч не проходит → market=pass, signal_type=Pass, decision=PASS
- Если нет конкретного ответа где ошибка рынка → PASS

ЛОГИКА НИЧЬИХ (draw):
Ничья — отдельный рынок со своими условиями. Рассматривай X если:
- Обе команды близки по таблице (разница ≤ 5 мест) И по форме (разница ≤ 1 победы из 5)
- Обе команды с низкой атакой (голы за матч < 1.5 у обеих) — матч будет закрытым
- Коэффициент на X в диапазоне 3.0–4.5
- H2H показывает ничьи или чередование результатов
- Обе команды мотивированы на осторожность (середина таблицы, нет давления)

НЕ ставь на X если:
- Одна команда явно сильнее (5+ мест разницы И форма 4W vs 1W)
- Одна команда в зоне вылета — будет атаковать
- Коэффициент X > 4.5 без составов

СОСТАВЫ И ТРАВМЫ:

Общая логика:
- lineup_data_available = true только если confirmed стартовый состав
- Strong без confirmed lineups невозможен
- Medium без lineups возможен при: форма 3+, таблица есть, edge ≥ 3%
- injury_data в notes — реальные данные, используй как подтверждённые факты

Хоккей (КХЛ/НХЛ) — особый режим данных:
- Составы и травмы системно недоступны — это НОРМА, не повод для PASS
- Medium без lineups разрешён на основе формы/таблицы/голов/мотивации/H2H
- Не пиши "без составов невозможно" для хоккея
- Strong только при явном доп.подтверждении
- Мотивация в конце регулярки критична (танкование, беречь игроков)

Футбол — injury data:
- "Травмы X: Игрок (причина)" — подтверждённый факт, учитывай в анализе
- SEVERITY уровни (важно различать!):
  * Сильный сигнал: Knee/Muscle/Broken/Suspended/Red Card — confirmed out
  * Слабый сигнал: Illness/Coach's decision — doubtful, может сыграть
  * Почти не влияет: Yellow Cards risk, loan agreement
- Считай только confirmed out (уровень 1) как реальные потери
- Red Card/Suspended = вес x2 (гарантировано не сыграет)
- Рынок частично учитывает известные травмы — ищи где НЕ учёл

ПРОВЕРКА СОГЛАСОВАННОСТИ (обязательно перед выбором рынка):
- Перечитай свой reasoning: он поддерживает выбранную команду?
- Если пишешь "команда X ослаблена/слабее" → не ставь на неё
- Если пишешь "рынок адекватен" → это PASS
- Выбранная команда должна иметь преимущество хотя бы по 1 ключевому фактору: форма ИЛИ таблица ИЛИ голы ИЛИ мотивация ИЛИ травмы соперника

БАЗОВОЕ КАЧЕСТВО КОМАНДЫ (обязательная проверка):
- Травмы соперника и мотивация дают edge ТОЛЬКО если у выбранной команды есть базовое качество
- Базовое качество = минимум 2 из 3: форма 2W+, голы за матч > 1.0, таблица топ-15
- Если базового качества нет → травмы соперника и мотивация НЕ дают edge → PASS
- Примеры плохих ставок которые нельзя делать:
  * Бернли П1: форма 1W из 5, забивает 1.4 но пропускает 2.2 — нет базы для победы
  * Овьедо П1: форма 0W+4L, забивает 1.0 — мотивация не поможет если команда не умеет забивать
  * Лорьян П1 @ 5.0: нет формы соперника, нет H2H — слишком много неизвестных

СТОП без составов:
- Коэффициент > 6.0 → PASS
- Форма команды на которую ставишь: 3L+ из 5 → PASS
- Если у выбранной команды менее 2W из последних 5 → нужен очень сильный аргумент (не только травмы соперника)
- Разница в таблице > 15 мест → не ставить на аутсайдера
- Обе команды с 3+ confirmed out → травмы снижают edge, но не обнуляют его — смотри кто потерял более ключевых игроков
- Коэффициент >= 4.5 без составов → edge максимум market_p + 0.08
"""

USER_PROMPT_TEMPLATE = """Проведи анализ матча по BETAGENT v2.2.

Открытая экспозиция: {open_exposure_pct:.4f}
Серия проигрышей 72ч (этот спорт): {loss_streak_72h_same_sport}
Банк: {bankroll:.2f}

Матч:
{payload_json}

Правила:
- Если нет конкретной ошибки рынка → PASS
- Strong без составов невозможен (кроме хоккея с явным доп.подтверждением)
- Выбери один рынок: home, draw или away
- Если матч не проходит → market=pass, signal_type=Pass, decision=PASS
- Травмы в notes — реальные данные, используй в анализе
- НЕ используй "рынок адекватен" как причину PASS без конкретного обоснования
- Ищи edge активно: форма, таблица, голы, мотивация, травмы. Если одно из них явно в пользу одной команды + коэффициент выше 2.0 → анализируй edge, не отмахивайся
"""


# ============================================================
# WHITELIST CONFIGURATION
# ============================================================

# Stake mode registry
STAKE_MODES = {
    "flat_1000": {"type": "flat_rub", "amount": 1000},
    "flat_pct_0_75": {"type": "flat_pct", "pct": 0.0075},
    "flat_pct_1_00": {"type": "flat_pct", "pct": 0.0100},
    "flat_pct_1_25": {"type": "flat_pct", "pct": 0.0125},
    "flat_pct_1_50": {"type": "flat_pct", "pct": 0.0150},
    "bankroll_regime_v1": {
        "type": "bankroll_regime",
        "initial_base": 90000,
        "band_pct": 0.10,
        "below_base_pct": 0.0075,
        "at_base_pct": 0.0100,
        "high_pct": 0.0125,
        "base_hold_days": 2,
        "confirm_high_next_day": True,
    },
}

# HOCKEY_LEAGUE_CONFIG — imported from strategies.hockey


# FOOTBALL_LEAGUE_STAKING is imported from strategies.football

# Strict whitelist of allowed leagues by sport
ALLOWED_LEAGUES = {
    "football": [
        "Англия. Премьер-Лига",
        "Германия. Бундеслига",
        "Испания. Примера дивизион",
        "Италия. Серия А",
        "Франция. Лига 1",
        "Россия. Премьер-Лига",
        # Летние лиги (паттерн-матчинг через is_league_allowed)
        "Дания.",
        "Швеция.",
        "Норвегия.",
        "Финляндия.",
        "Ирландия.",
        "США.",
        "Эквадор.",
        "Ecuador.",
    ],
    "hockey": [
        "НХЛ. Регулярный сезон",
        "Фонбет КХЛ. Регулярный сезон",
        "TheSports KHL",
        "Чехия. Экстралига",
        "Хоккей. Швейцария. National League.",
    ],
}

# detect_league_key is now imported from strategies.hockey



def is_league_allowed(sport: str, league: str) -> bool:
    """
    Check if a league is allowed for a given sport.
    Football keeps strict whitelist.
    Hockey uses pattern-based matching, then strategy config decides whether to run.
    """
    if sport not in ALLOWED_LEAGUES:
        return False

    league_lower = league.lower() if league else ""

    if sport == "hockey":
        # Allow KHL/Czech/NHL league families at pipeline level.
        # Actual execution is controlled later by detect_league_key + HOCKEY_LEAGUE_CONFIG.
        if any(x in league_lower for x in ["кхл", "khl", "чех", "czech", "extraliga", "нхл", "nhl", "швейцар", "national league"]):
            return True
        return False

    # Football backtest short codes (from backtest_matches.league column)
    BACKTEST_SHORT_CODES = {"epl", "bl1", "sa", "pd", "fl1", "rpl", "r1", "e0", "d1", "i1", "sp1", "f1"}
    if league_lower in BACKTEST_SHORT_CODES:
        return True

    # Football and other sports keep exact/near-exact whitelist logic
    for allowed_league in ALLOWED_LEAGUES[sport]:
        allowed_lower = allowed_league.lower()
        if allowed_lower in league_lower or league_lower in allowed_lower:
            return True
    return False

# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Match:
    id: int
    fonbet_id: Optional[str]
    sport: str
    league: str
    home_team: str
    away_team: str
    match_date: str
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]
    odds_over_2_5: Optional[float] = None
    odds_under_2_5: Optional[float] = None
    odds_over_3_5: Optional[float] = None
    odds_under_3_5: Optional[float] = None
    odds_btts_yes: Optional[float] = None
    odds_btts_no: Optional[float] = None
    status: str = "upcoming"
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    rt_home_score: Optional[int] = None
    rt_away_score: Optional[int] = None
    result: Optional[str] = None
    fonbet_home: Optional[float] = None
    fonbet_draw: Optional[float] = None
    fonbet_away: Optional[float] = None
    market_home: Optional[float] = None
    market_draw: Optional[float] = None
    market_away: Optional[float] = None
    best_home_book: Optional[str] = None
    best_draw_book: Optional[str] = None
    best_away_book: Optional[str] = None


# ============================================================
# DB HELPERS
# ============================================================

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_handoff_decisions_table(conn: sqlite3.Connection) -> None:
    """
    Create handoff_decisions table if it doesn't exist.
    This table stores ALL decisions made by the handoff process, including PASS decisions.
    """
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS handoff_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            run_mode TEXT,
            created_by TEXT,
            match_id INTEGER,
            fonbet_match_id TEXT,
            sport TEXT,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            match_date TEXT,
            market TEXT,
            market_label TEXT,
            odds REAL,
            our_probability REAL,
            market_probability REAL,
            ev REAL,
            edge REAL,
            confidence INTEGER,
            signal_type TEXT,
            decision TEXT,
            valid INTEGER,
            validator_rejected INTEGER DEFAULT 0,
            recommended_action TEXT,
            notes TEXT,
            market_error TEXT,
            payload_json TEXT,
            recommendation_json TEXT,
            match_snapshot TEXT,
            fingerprint TEXT
        )
    """)
    
    # Create indexes for efficient querying
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_handoff_decisions_created_at ON handoff_decisions(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_handoff_decisions_match_id ON handoff_decisions(match_id)",
        "CREATE INDEX IF NOT EXISTS idx_handoff_decisions_sport ON handoff_decisions(sport)",
        "CREATE INDEX IF NOT EXISTS idx_handoff_decisions_league ON handoff_decisions(league)",
        "CREATE INDEX IF NOT EXISTS idx_handoff_decisions_decision ON handoff_decisions(decision)",
        "CREATE INDEX IF NOT EXISTS idx_handoff_decisions_valid ON handoff_decisions(valid)"
    ]
    
    for index_sql in indexes:
        cur.execute(index_sql)
    
    conn.commit()

def ensure_bankroll_state_table(conn: sqlite3.Connection) -> None:
    """
    Create bankroll_state table if it doesn't exist.
    This table stores the state of the bankroll for regime-based staking.
    """
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bankroll_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            base_bankroll REAL,
            candidate_bankroll REAL,
            candidate_since TEXT,
            high_watermark REAL,
            high_reached_at TEXT,
            high_confirmed_at TEXT,
            last_bankroll REAL,
            updated_at TEXT
        )
    """)
    conn.commit()

def ensure_agent_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(bets)")
    existing = {row[1] for row in cur.fetchall()}
    required = {
        "rules_version": "TEXT",
        "signal_type": "TEXT",
        "confidence": "INTEGER",
        "market_probability": "REAL",
        "lineup_data_available": "INTEGER",
        "market_error_summary": "TEXT",
        "validated": "INTEGER DEFAULT 0",
        "validation_notes": "TEXT",
        "stake_pct": "REAL",
        "kelly_quarter": "REAL",
        "recommended_action": "TEXT",
        "created_by": "TEXT",
        "match_snapshot": "TEXT",
        # New structured bet comment fields
        "reasons": "TEXT",
        "rule": "TEXT",
        "edge": "REAL",
        "model_prob": "REAL",
        "market_prob": "REAL",
    }
    for col, col_type in required.items():
        if col not in existing:
            cur.execute(f"ALTER TABLE bets ADD COLUMN {col} {col_type}")
    conn.commit()

def load_or_init_bankroll_state(conn: sqlite3.Connection, current_bankroll: float) -> dict:
    """
    Load bankroll state from database or initialize if not exists.
    
    Args:
        conn: Database connection
        current_bankroll: Current bankroll value
        
    Returns:
        Dictionary with bankroll state
    """
    ensure_bankroll_state_table(conn)
    
    # Check if state exists
    row = conn.execute("SELECT * FROM bankroll_state WHERE id = 1").fetchone()
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not row:
        # Initialize with default values
        initial_base = STAKE_MODES["bankroll_regime_v1"]["initial_base"]
        conn.execute("""
            INSERT INTO bankroll_state 
            (id, base_bankroll, candidate_bankroll, candidate_since, 
             high_watermark, high_reached_at, high_confirmed_at, last_bankroll, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, NULL, ?, ?)
        """, (initial_base, current_bankroll, now, current_bankroll, now, current_bankroll, now))
        conn.commit()
        
        return {
            "base_bankroll": initial_base,
            "candidate_bankroll": current_bankroll,
            "candidate_since": now,
            "high_watermark": current_bankroll,
            "high_reached_at": now,
            "high_confirmed_at": None,
            "last_bankroll": current_bankroll,
            "updated_at": now
        }
    
    # Return existing state as dictionary
    return {
        "base_bankroll": row["base_bankroll"],
        "candidate_bankroll": row["candidate_bankroll"],
        "candidate_since": row["candidate_since"],
        "high_watermark": row["high_watermark"],
        "high_reached_at": row["high_reached_at"],
        "high_confirmed_at": row["high_confirmed_at"],
        "last_bankroll": row["last_bankroll"],
        "updated_at": row["updated_at"]
    }

def update_bankroll_state(conn: sqlite3.Connection, current_bankroll: float, now_dt: datetime) -> dict:
    """
    Update bankroll state based on current bankroll value.
    
    Args:
        conn: Database connection
        current_bankroll: Current bankroll value
        now_dt: Current datetime
        
    Returns:
        Updated bankroll state dictionary
    """
    # Load current state
    state = load_or_init_bankroll_state(conn, current_bankroll)
    
    # Format datetime
    now = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # Get bankroll regime parameters
    regime_config = STAKE_MODES["bankroll_regime_v1"]
    band_pct = regime_config["band_pct"]
    base_hold_days = regime_config["base_hold_days"]
    
    base_bankroll = state["base_bankroll"]
    
    # Calculate bands
    lower_band = base_bankroll * (1 - band_pct)
    upper_band = base_bankroll * (1 + band_pct)
    
    # Update high watermark if needed
    if current_bankroll > state["high_watermark"]:
        state["high_watermark"] = current_bankroll
        state["high_reached_at"] = now
        state["high_confirmed_at"] = None
    
    # Check if we need to confirm high
    if (state["high_reached_at"] and not state["high_confirmed_at"] and 
            current_bankroll >= state["high_watermark"] * 0.95):
        # If high was reached at least a day ago and still persists
        high_reached_dt = datetime.strptime(state["high_reached_at"], "%Y-%m-%d %H:%M:%S")
        if (now_dt - high_reached_dt).days >= 1:
            state["high_confirmed_at"] = now
    
    # Check if current bankroll is outside bands
    if current_bankroll < lower_band or current_bankroll > upper_band:
        # Set new candidate
        state["candidate_bankroll"] = current_bankroll
        state["candidate_since"] = now
    elif state["candidate_bankroll"] is not None:
        # Check if candidate has been stable for required days
        candidate_since_dt = datetime.strptime(state["candidate_since"], "%Y-%m-%d %H:%M:%S")
        if (now_dt - candidate_since_dt).days >= base_hold_days:
            # Promote candidate to base
            state["base_bankroll"] = state["candidate_bankroll"]
            state["candidate_bankroll"] = None
            state["candidate_since"] = None
    
    # Update last values
    state["last_bankroll"] = current_bankroll
    state["updated_at"] = now
    
    # Save to database
    conn.execute("""
        UPDATE bankroll_state SET
        base_bankroll = ?,
        candidate_bankroll = ?,
        candidate_since = ?,
        high_watermark = ?,
        high_reached_at = ?,
        high_confirmed_at = ?,
        last_bankroll = ?,
        updated_at = ?
        WHERE id = 1
    """, (
        state["base_bankroll"],
        state["candidate_bankroll"],
        state["candidate_since"],
        state["high_watermark"],
        state["high_reached_at"],
        state["high_confirmed_at"],
        state["last_bankroll"],
        state["updated_at"]
    ))
    conn.commit()
    
    return state

def resolve_stake_mode_name(match, rec) -> Optional[str]:
    """
    Resolve the stake mode name based on match and recommendation.
    
    Args:
        match: Match object
        rec: Recommendation dictionary
        
    Returns:
        Stake mode name or None if not found
    """
    # Special case: BTTS_YES_CORE uses its own staking logic
    if rec.get("live_rule_family") == "BTTS_YES_CORE":
        return None
    
    # For hockey matches
    if match.sport == "hockey":
        league_key = detect_league_key(match.league)
        if league_key:
            league_config = HOCKEY_LEAGUE_CONFIG.get(league_key, {})
            return league_config.get("stake_mode")
    
    # For football matches
    if match.sport == "football":
        league_key = detect_football_league_key(match.league)
        if league_key:
            # Get strategy key
            strategy_key = None
            if rec.get("live_rule_family"):
                strategy_key = rec.get("live_rule_family")
            elif not rec.get("rule_driven", False):
                strategy_key = "football_core_1x2"
            
            if strategy_key:
                league_staking = FOOTBALL_LEAGUE_STAKING.get(league_key, {})
                return league_staking.get(strategy_key)
    
    return None

def resolve_stake_pct_and_meta(conn, bankroll: float, match, rec) -> tuple[Optional[float], Optional[float], dict]:
    """
    Resolve stake percentage and metadata based on stake mode.
    
    Args:
        conn: Database connection
        bankroll: Current bankroll
        match: Match object
        rec: Recommendation dictionary
        
    Returns:
        Tuple of (stake_pct, stake_abs, metadata)
    """
    # Initialize metadata
    meta = {
        "stake_mode_name": None,
        "stake_mode_type": None,
        "stake_mode_reason": None,
    }
    
    # Special case: BTTS_YES_CORE uses its own staking logic
    if rec.get("live_rule_family") == "BTTS_YES_CORE":
        return None, None, meta
    
    # Get stake mode name
    stake_mode_name = resolve_stake_mode_name(match, rec)
    if not stake_mode_name or stake_mode_name not in STAKE_MODES:
        return None, None, meta
    
    # Get stake mode config
    stake_mode = STAKE_MODES[stake_mode_name]
    stake_mode_type = stake_mode["type"]
    
    meta["stake_mode_name"] = stake_mode_name
    meta["stake_mode_type"] = stake_mode_type
    
    # Calculate stake based on mode type
    if stake_mode_type == "flat_rub":
        stake_abs = stake_mode["amount"]
        stake_pct = stake_abs / bankroll
        meta["stake_mode_reason"] = f"Fixed {stake_abs} RUB stake"
        return stake_pct, stake_abs, meta
    
    elif stake_mode_type == "flat_pct":
        stake_pct = stake_mode["pct"]
        stake_abs = bankroll * stake_pct
        meta["stake_mode_reason"] = f"Fixed {stake_pct:.2%} of bankroll"
        return stake_pct, stake_abs, meta
    
    elif stake_mode_type == "bankroll_regime":
        # First ensure we have a bankroll state
        load_or_init_bankroll_state(conn, bankroll)
        
        # Update bankroll state
        now_dt = datetime.now()
        state = update_bankroll_state(conn, bankroll, now_dt)
        
        # Determine regime
        base_bankroll = state["base_bankroll"]
        band_pct = stake_mode["band_pct"]
        lower_band = base_bankroll * (1 - band_pct)
        upper_band = base_bankroll * (1 + band_pct)
        
        # Add state info to metadata
        meta["base_bankroll"] = base_bankroll
        meta["current_bankroll"] = bankroll
        
        # Determine which stake to use
        if bankroll < lower_band:
            stake_pct = stake_mode["below_base_pct"]
            meta["bankroll_regime"] = "below_base"
            meta["stake_mode_reason"] = f"Below base bankroll ({bankroll:.0f} < {lower_band:.0f})"
        elif bankroll > upper_band:
            if state["high_confirmed_at"]:
                # Check if high is confirmed for next day
                high_confirmed_dt = datetime.strptime(state["high_confirmed_at"], "%Y-%m-%d %H:%M:%S")
                if stake_mode["confirm_high_next_day"] and (now_dt - high_confirmed_dt).days >= 1:
                    stake_pct = stake_mode["high_pct"]
                    meta["bankroll_regime"] = "confirmed_high"
                    meta["stake_mode_reason"] = f"Confirmed high bankroll ({bankroll:.0f} > {upper_band:.0f})"
                else:
                    # High reached but not yet confirmed for next day
                    stake_pct = stake_mode["at_base_pct"]
                    meta["bankroll_regime"] = "high_pending"
                    meta["stake_mode_reason"] = f"Above high threshold ({bankroll:.0f} > {upper_band:.0f}), pending next-day confirmation"
            else:
                # High reached but not yet confirmed at all
                stake_pct = stake_mode["at_base_pct"]
                meta["bankroll_regime"] = "high_pending"
                meta["stake_mode_reason"] = f"Above high threshold ({bankroll:.0f} > {upper_band:.0f}), pending confirmation"
        else:
            stake_pct = stake_mode["at_base_pct"]
            meta["bankroll_regime"] = "at_base"
            meta["stake_mode_reason"] = f"Within base band ({lower_band:.0f} - {upper_band:.0f})"
        
        stake_abs = bankroll * stake_pct
        return stake_pct, stake_abs, meta
    
    # Fallback
    return None, None, meta

# is_placeholder_match moved to analysis_helpers/match_utils.py

def apply_market_books(conn: sqlite3.Connection, match: Match) -> Match:
    row = conn.execute(
        """
        SELECT avg_home, avg_draw, avg_away,
               best_home_book, best_home,
               best_draw_book, best_draw,
               best_away_book, best_away
        FROM odds_merged
        WHERE match_id=?
        LIMIT 1
        """,
        (match.id,)
    ).fetchone()

    match.fonbet_home = match.odds_home
    match.fonbet_draw = match.odds_draw
    match.fonbet_away = match.odds_away

    if not row:
        match.market_home = match.odds_home
        match.market_draw = match.odds_draw
        match.market_away = match.odds_away
        match.best_home_book = "fonbet"
        match.best_draw_book = "fonbet"
        match.best_away_book = "fonbet"
        return match

    match.market_home = row["avg_home"] or match.odds_home
    match.market_draw = row["avg_draw"] or match.odds_draw
    match.market_away = row["avg_away"] or match.odds_away

    match.best_home_book = row["best_home_book"] or "fonbet"
    match.best_draw_book = row["best_draw_book"] or "fonbet"
    match.best_away_book = row["best_away_book"] or "fonbet"

    match.odds_home = row["best_home"] or match.odds_home
    match.odds_draw = row["best_draw"] or match.odds_draw
    match.odds_away = row["best_away"] or match.odds_away

    return match

# _coerce_float moved to analysis_helpers/match_utils.py

def simulate_llm_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Heuristic fallback when LLM is disabled. Keeps the pipeline working."""
    facts = payload.get("known_facts", {}) or {}
    market_probs = payload.get("market_probabilities", {}) or {}
    match_sport = payload.get("sport", "").lower()
    
    # Check for pure BA mode execution
    pure_ba_mode = getattr(GLOBAL_ARGS, "pure_ba", False)
    is_ba_approved = payload.get("is_backtest_approved", False)
    ba_rule = payload.get("ba_rule")
    
    # If in pure BA mode and match is BA-approved, force the market from the rule
    if pure_ba_mode and is_ba_approved and ba_rule:
        forced_market = ba_rule_to_market(ba_rule)
        if forced_market:
            # Get the probability for this market
            market_prob = float(market_probs.get(forced_market) or 0.33)
            # Add edge for BA rule
            our_prob = min(market_prob + 0.08, 0.65)
            
            return {
                "market": forced_market,
                "our_probability": round(our_prob, 4),
                "market_error": f"Pure BA mode: {ba_rule} → {forced_market}",
                "confirmed_facts": [f"BA rule {ba_rule} forces market {forced_market}"],
                "unconfirmed": [],
                "lineup_data_available": bool(facts.get("lineup_data_available", False)),
                "signal_type": "Medium",
                "confidence": 6,
                "decision": "BET",
                "market_error_summary": f"Pure BA execution: {ba_rule}",
                "validated": True,
                "validation_notes": ["Pure BA mode execution"],
                "pure_ba_execution": True,
            }
    
    # For football, we now use shadow mode for old heuristic logic
    if match_sport == "football":
        # Regular heuristic logic for football now in shadow mode
        home_pos = _coerce_float(facts.get("home_position"))
        away_pos = _coerce_float(facts.get("away_position"))
        home_pts = _coerce_float(facts.get("home_points"))
        away_pts = _coerce_float(facts.get("away_points"))
        home_scored = _coerce_float(facts.get("home_goals_scored_avg"))
        away_scored = _coerce_float(facts.get("away_goals_scored_avg"))
        home_allowed = _coerce_float(facts.get("home_goals_allowed_avg"))
        away_allowed = _coerce_float(facts.get("away_goals_allowed_avg"))
        home_form = facts.get("form_last_5_home") or []
        away_form = facts.get("form_last_5_away") or []

        home_w = sum(1 for x in home_form if str(x).upper() == "W")
        away_w = sum(1 for x in away_form if str(x).upper() == "W")

        scores = {
            "home": float(market_probs.get("home") or 0.33),
            "draw": float(market_probs.get("draw") or 0.28),
            "away": float(market_probs.get("away") or 0.33),
        }

        scores["home"] += 0.03  # small home edge
        if home_pos is not None and away_pos is not None:
            scores["home"] += (away_pos - home_pos) * 0.01
            scores["away"] += (home_pos - away_pos) * 0.01
            if abs(home_pos - away_pos) <= 4:
                scores["draw"] += 0.02
        if home_pts is not None and away_pts is not None:
            scores["home"] += (home_pts - away_pts) * 0.002
            scores["away"] += (away_pts - home_pts) * 0.002
        if home_scored is not None and away_scored is not None:
            scores["home"] += (home_scored - away_scored) * 0.04
            scores["away"] += (away_scored - home_scored) * 0.04
            if max(home_scored, away_scored) <= 1.4:
                scores["draw"] += 0.03
        if home_allowed is not None and away_allowed is not None:
            scores["home"] += (away_allowed - home_allowed) * 0.03
            scores["away"] += (home_allowed - away_allowed) * 0.03
            if max(home_allowed, away_allowed) <= 1.4:
                scores["draw"] += 0.02
        scores["home"] += (home_w - away_w) * 0.02
        scores["away"] += (away_w - home_w) * 0.02

        candidate = max(scores, key=scores.get)
        if candidate == "draw" and not payload.get("markets", {}).get("draw"):
            candidate = "home" if scores["home"] >= scores["away"] else "away"

        total = sum(max(v, 0.05) for v in scores.values()) or 1.0
        probs = {k: max(v, 0.05) / total for k, v in scores.items()}

        confirmed = []
        if home_pos is not None and away_pos is not None:
            confirmed.append(f"Позиции: {int(home_pos)} vs {int(away_pos)}")
        if home_pts is not None and away_pts is not None:
            confirmed.append(f"Очки: {int(home_pts)} vs {int(away_pts)}")
        if home_w or away_w:
            confirmed.append(f"Форма: {home_w}W vs {away_w}W")
        if home_scored is not None and away_scored is not None:
            confirmed.append(f"Голы: {home_scored:.1f} vs {away_scored:.1f}")

        return {
            "market": candidate,
            "our_probability": round(probs[candidate], 4),
            "market_error": "Heuristic fallback without LLM (shadow mode)",
            "confirmed_facts": confirmed[:5],
            "unconfirmed": ["LLM disabled; heuristic estimate only"],
            "lineup_data_available": bool(facts.get("lineup_data_available", False)),
            "signal_type": "Medium",
            "confidence": 5,
            "decision": "BET",
            "market_error_summary": "LLM disabled heuristic mode",
            "validated": True,
            "validation_notes": ["LLM disabled heuristic mode"],
            "shadow_only": True,  # Football heuristic is now shadow-only
        }
    
    # For other sports, keep the original behavior (except hockey which is handled separately)
    home_pos = _coerce_float(facts.get("home_position"))
    away_pos = _coerce_float(facts.get("away_position"))
    home_pts = _coerce_float(facts.get("home_points"))
    away_pts = _coerce_float(facts.get("away_points"))
    home_scored = _coerce_float(facts.get("home_goals_scored_avg"))
    away_scored = _coerce_float(facts.get("away_goals_scored_avg"))
    home_allowed = _coerce_float(facts.get("home_goals_allowed_avg"))
    away_allowed = _coerce_float(facts.get("away_goals_allowed_avg"))
    home_form = facts.get("form_last_5_home") or []
    away_form = facts.get("form_last_5_away") or []

    home_w = sum(1 for x in home_form if str(x).upper() == "W")
    away_w = sum(1 for x in away_form if str(x).upper() == "W")

    scores = {
        "home": float(market_probs.get("home") or 0.33),
        "draw": float(market_probs.get("draw") or 0.28),
        "away": float(market_probs.get("away") or 0.33),
    }

    scores["home"] += 0.03  # small home edge
    if home_pos is not None and away_pos is not None:
        scores["home"] += (away_pos - home_pos) * 0.01
        scores["away"] += (home_pos - away_pos) * 0.01
        if abs(home_pos - away_pos) <= 4:
            scores["draw"] += 0.02
    if home_pts is not None and away_pts is not None:
        scores["home"] += (home_pts - away_pts) * 0.002
        scores["away"] += (away_pts - home_pts) * 0.002
    if home_scored is not None and away_scored is not None:
        scores["home"] += (home_scored - away_scored) * 0.04
        scores["away"] += (away_scored - home_scored) * 0.04
        if max(home_scored, away_scored) <= 1.4:
            scores["draw"] += 0.03
    if home_allowed is not None and away_allowed is not None:
        scores["home"] += (away_allowed - home_allowed) * 0.03
        scores["away"] += (home_allowed - away_allowed) * 0.03
        if max(home_allowed, away_allowed) <= 1.4:
            scores["draw"] += 0.02
    scores["home"] += (home_w - away_w) * 0.02
    scores["away"] += (away_w - home_w) * 0.02

    candidate = max(scores, key=scores.get)
    if candidate == "draw" and not payload.get("markets", {}).get("draw"):
        candidate = "home" if scores["home"] >= scores["away"] else "away"

    total = sum(max(v, 0.05) for v in scores.values()) or 1.0
    probs = {k: max(v, 0.05) / total for k, v in scores.items()}

    confirmed = []
    if home_pos is not None and away_pos is not None:
        confirmed.append(f"Позиции: {int(home_pos)} vs {int(away_pos)}")
    if home_pts is not None and away_pts is not None:
        confirmed.append(f"Очки: {int(home_pts)} vs {int(away_pts)}")
    if home_w or away_w:
        confirmed.append(f"Форма: {home_w}W vs {away_w}W")
    if home_scored is not None and away_scored is not None:
        confirmed.append(f"Голы: {home_scored:.1f} vs {away_scored:.1f}")

    return {
        "market": candidate,
        "our_probability": round(probs[candidate], 4),
        "market_error": "Heuristic fallback without LLM",
        "confirmed_facts": confirmed[:5],
        "unconfirmed": ["LLM disabled; heuristic estimate only"],
        "lineup_data_available": bool(facts.get("lineup_data_available", False)),
        "signal_type": "Medium",
        "confidence": 5,
        "decision": "BET",
        "market_error_summary": "LLM disabled heuristic mode",
        "validated": True,
        "validation_notes": ["LLM disabled heuristic mode"],
    }

def fetch_backtest_matches(
    conn: sqlite3.Connection,
    sport: Optional[str] = None,
    limit: int = 100,
    match_id: Optional[int] = None,
) -> List[Match]:
    """Load historical matches for backtesting.

    Football history is stored in backtest_matches, while hockey history is stored
    directly in matches with status != upcoming.
    """
    # Football history
    if sport in (None, "football"):
        has_backtest_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backtest_matches'"
        ).fetchone()
        if has_backtest_table:
            q = """
                SELECT
                    id,
                    NULL AS fonbet_id,
                    'football' AS sport,
                    COALESCE(league_name, league) AS league,
                    home_team,
                    away_team,
                    match_date,
                    odds_home,
                    odds_draw,
                    odds_away,
                    COALESCE(odds_btts_yes, NULL) AS odds_btts_yes,
                    COALESCE(odds_btts_no, NULL) AS odds_btts_no,
                    COALESCE(odds_over_2_5, NULL) AS odds_over_2_5,
                    COALESCE(odds_under_2_5, NULL) AS odds_under_2_5,
                    home_score,
                    away_score,
                    COALESCE(result, 
                        CASE 
                            WHEN home_score > away_score THEN 'H'
                            WHEN away_score > home_score THEN 'A'
                            WHEN home_score = away_score AND home_score IS NOT NULL THEN 'D'
                            ELSE NULL
                        END
                    ) AS result,
                    'finished' AS status
                FROM backtest_matches
                WHERE odds_home IS NOT NULL
                  AND odds_away IS NOT NULL
            """
            params: List[Any] = []
            if match_id:
                q += " AND id=?"
                params.append(match_id)
            q += " ORDER BY datetime(match_date) DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
            matches = []
            for row in rows:
                try:
                    m = Match(**dict(row))
                    if not is_placeholder_match(m.home_team, m.away_team):
                        matches.append(m)
                except Exception:
                    pass
            if sport == "football":
                return matches

    # ALL SPORTS mode — объединяем футбол и хоккей по дате
    if sport is None:
        football_matches = fetch_backtest_matches(conn, sport="football", limit=limit)
        hockey_matches = fetch_backtest_matches(conn, sport="hockey", limit=limit)
        all_matches = football_matches + hockey_matches
        # Сортируем по дате
        def sort_key(m):
            try:
                d = str(m.match_date)
                # Пробуем разные форматы
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                    try:
                        return datetime.strptime(d[:len(fmt.replace("%Y","0000").replace("%m","00").replace("%d","00").replace("%H","00").replace("%M","00").replace("%S","00"))], fmt)
                    except:
                        pass
            except:
                pass
            return datetime.min
        all_matches.sort(key=sort_key)
        return all_matches[:limit]

    # Hockey history from backtest_hockey_matches
    if sport in (None, "hockey"):
        has_hockey_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backtest_hockey_matches'"
        ).fetchone()
        if has_hockey_table:
            q = """
                SELECT
                    id, NULL AS fonbet_id, 'hockey' AS sport, league,
                    home_team, away_team, match_date,
                    odds_home AS odds_home,
                    odds_draw AS odds_draw,
                    odds_away AS odds_away,
                    NULL AS odds_over_2_5, NULL AS odds_under_2_5,
                    NULL AS odds_over_3_5, NULL AS odds_under_3_5,
                    NULL AS odds_btts_yes, NULL AS odds_btts_no,
                    'finished' AS status,
                    rt_home_score AS home_score,
                    rt_away_score AS away_score
                FROM backtest_hockey_matches
                WHERE odds_home IS NOT NULL
                  AND odds_away IS NOT NULL
                  AND rt_home_score IS NOT NULL
                  AND rt_away_score IS NOT NULL
            """
            params: List[Any] = []
            if match_id:
                q += " AND id=?"
                params.append(match_id)
            # Фильтруем только нужные лиги для бэктеста
            # ============================================================
            # HOCKEY BACKTEST LEAGUE WHITELIST
            # Добавляй новые лиги сюда при разработке стратегий
            # ============================================================
            q += """ AND (
                league LIKE '%КХЛ%' OR league LIKE '%KHL%'        -- КХЛ (стратегия: hockey_underdog_defensive)
                OR (league LIKE '%Чехия%' AND league LIKE '%Extraliga%')  -- Чехия (стратегия: fp_or_fb, отключена)
                OR league LIKE '%NHL%' OR league LIKE '%НХЛ%'     -- НХЛ (стратегия: nhl_draw_tight)
                OR (league LIKE '%Швейцар%' AND league LIKE '%National League%')  -- NLA (стратегия: nla_bern_away_draw)
            )"""
            # Исключаем статистические и нестандартные турниры
            q += " AND (league NOT LIKE '%3x3%' AND league NOT LIKE '%Силовые%' AND league NOT LIKE '%Блокированные%' AND league NOT LIKE '%Статистика%')"
            q += " ORDER BY match_date DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(q, params).fetchall()
            matches = []
            for row in rows:
                d = dict(row)
                try:
                    matches.append(Match(**d))
                except Exception:
                    pass
            matches = [m for m in matches if not is_placeholder_match(m.home_team, m.away_team)]
            if sport == "hockey":
                return matches

    # Fallback / hockey history from live matches table
    q = """
        SELECT id, fonbet_id, sport, league, home_team, away_team,
               match_date, odds_home, odds_draw, odds_away, 
               odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5,
               odds_btts_yes, odds_btts_no, status
        FROM matches m
        LEFT JOIN odds_merged om ON om.match_id = m.id
        WHERE status != 'upcoming'
          AND odds_home IS NOT NULL
          AND odds_away IS NOT NULL
    """
    params: List[Any] = []
    if sport:
        q += " AND sport=?"
        params.append(sport)
    if match_id:
        q += " AND id=?"
        params.append(match_id)
    q += " ORDER BY datetime(match_date) DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    matches = [apply_market_books(conn, Match(**dict(row))) for row in rows]
    return [m for m in matches if not is_placeholder_match(m.home_team, m.away_team)]

def _get_actual_outcome(conn: sqlite3.Connection, match_id: int) -> Optional[str]:
    # First try hockey backtest table (RT score = regulation time)
    try:
        row = conn.execute(
            "SELECT rt_home_score, rt_away_score FROM backtest_hockey_matches WHERE id=?", (match_id,)
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            if row[0] > row[1]: return "home"
            if row[0] < row[1]: return "away"
            return "draw"
    except Exception:
        pass
    # Then try football backtest table
    has_backtest_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='backtest_matches'"
    ).fetchone()
    if has_backtest_table:
        row = conn.execute(
            "SELECT home_score, away_score FROM backtest_matches WHERE id=?", (match_id,)
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            if row[0] > row[1]:
                return "home"
            if row[0] < row[1]:
                return "away"
            return "draw"

    # Then try live matches table
    cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)").fetchall()}
    for hcol, acol in (("home_score", "away_score"), ("score_home", "score_away"), ("goals_home", "goals_away")):
        if hcol in cols and acol in cols:
            row = conn.execute(f"SELECT {hcol}, {acol} FROM matches WHERE id=?", (match_id,)).fetchone()
            if row and row[0] is not None and row[1] is not None:
                if row[0] > row[1]:
                    return "home"
                if row[0] < row[1]:
                    return "away"
                return "draw"

    # Try results_raw (RT score for hockey)
    match_info = conn.execute("SELECT home_team, away_team, match_date, sport, league FROM matches WHERE id=?", (match_id,)).fetchone()
    if match_info:
        home_team, away_team, match_date = match_info
        date_str = str(match_date)[:10]
        row = conn.execute("""
            SELECT home_score, away_score FROM results_raw
            WHERE is_finished=1
              AND match_date=?
              AND (
                (home_team=? AND away_team=?) OR
                (home_team LIKE ? AND away_team LIKE ?)
              )
            ORDER BY id DESC LIMIT 1
        """, (date_str, home_team, away_team,
              f"%{home_team.split()[0]}%", f"%{away_team.split()[0]}%")).fetchone()
        if row and row[0] is not None:
            if row[0] > row[1]: return "home"
            if row[0] < row[1]: return "away"
            return "draw"

        # Try backtest_hockey_matches — RT счёт (основное время, Фонбет П1/П2 без ОТ)
        row = conn.execute("""
            SELECT rt_home_score, rt_away_score FROM backtest_hockey_matches
            WHERE rt_home_score IS NOT NULL
              AND match_date=?
              AND (
                (home_team=? AND away_team=?) OR
                (home_team LIKE ? AND away_team LIKE ?)
              )
            ORDER BY id DESC LIMIT 1
        """, (str(match_date)[0:10].replace("-", ".") if "-" in str(match_date) else str(match_date)[:8],
              home_team, away_team,
              f"%{home_team.split()[0]}%", f"%{away_team.split()[0]}%")).fetchone()
        if row and row[0] is not None:
            if row[0] > row[1]: return "home"
            if row[0] < row[1]: return "away"
            return "draw"

    return None

def _save_equity(conn, backtest_results):
    """Сохраняет результаты бэктеста в backtest_equity."""
    from datetime import datetime
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_equity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            sport TEXT, strategy TEXT,
            match_date TEXT, home_team TEXT, away_team TEXT,
            market TEXT, odds REAL, stake REAL,
            profit REAL, result TEXT, hit INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_beq_strategy ON backtest_equity(strategy, match_date)")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Удаляем старый прогон
    old_run = conn.execute("SELECT DISTINCT run_id FROM backtest_equity ORDER BY created_at DESC LIMIT 1").fetchone()
    if old_run:
        conn.execute("DELETE FROM backtest_equity WHERE run_id=?", (old_run[0],))

    def _normalize_date(d):
        """Конвертирует DD.MM.YYYY в YYYY-MM-DD если нужно."""
        d = str(d or "")[:10]
        if len(d) == 10 and d[2] == "." and d[5] == ".":
            dd, mm, yyyy = d[:2], d[3:5], d[6:]
            return f"{yyyy}-{mm}-{dd}"
        return d

    rows = [{
        "run_id": run_id, "created_at": created_at,
        "sport": r.get("sport",""), "strategy": r.get("strategy","unknown"),
        "match_date": _normalize_date(r.get("match_date","")),
        "home_team": r.get("home_team",""),
        "away_team": r.get("away_team",""), "market": r.get("market",""),
        "odds": r.get("odds",0), "stake": r.get("stake",0),
        "profit": r.get("profit",0), "result": r.get("result",""),
        "hit": 1 if r.get("result")=="won" else 0,
    } for r in backtest_results if r.get("result") in ("won","lost")]

    conn.executemany("""
        INSERT INTO backtest_equity
        (run_id,created_at,sport,strategy,match_date,home_team,away_team,market,odds,stake,profit,result,hit)
        VALUES
        (:run_id,:created_at,:sport,:strategy,:match_date,:home_team,:away_team,:market,:odds,:stake,:profit,:result,:hit)
    """, rows)
    conn.commit()
    print(f"\n✅ backtest_equity: {len(rows)} строк сохранено (run_id={run_id})")

def print_backtest_summary(results: List[Dict[str, Any]], bankroll: float) -> None:
    if not results:
        print("\nBacktest: нет результатов.")
        return
    settled = [r for r in results if r.get("actual_outcome")]
    wins = sum(1 for r in settled if r.get("market") == r.get("actual_outcome"))
    losses = sum(1 for r in settled if r.get("market") != r.get("actual_outcome"))
    no_result = len(results) - len(settled)
    profit = 0.0
    staked = 0.0
    for r in settled:
        stake = float(r.get("stake_abs", 0.0) or 0.0)
        odds = float(r.get("odds", 0.0) or 0.0)
        staked += stake
        if r.get("market") == r.get("actual_outcome"):
            profit += stake * (odds - 1.0)
        else:
            profit -= stake
    roi = (profit / staked * 100.0) if staked else 0.0
    print("\n" + "=" * 80)
    print(f"BACKTEST SUMMARY: total={len(results)} | settled={len(settled)} | wins={wins} | losses={losses} | no_result={no_result}")
    print(f"Staked={staked:.2f} | Profit={profit:.2f} | ROI={roi:.2f}%")
    # Global drawdown from peak
    try:
        if pnl_log:
            peak = 0.0
            cur = 0.0
            max_dd = 0.0
            for p in pnl_log:
                cur += p
                if cur > peak:
                    peak = cur
                dd = peak - cur
                if dd > max_dd:
                    max_dd = dd
            print(f"  Макс. просадка от пика: {max_dd:.0f} руб ({max_dd/bankroll*100:.1f}%)")
    except Exception as e:
        print(f"  [drawdown error: {e}]")
    print("=" * 80)

def fetch_upcoming_matches(
    conn: sqlite3.Connection,
    sport: Optional[str] = None,
    limit: int = 20,
    match_id: Optional[int] = None,
) -> List[Match]:
    q = """
        SELECT id, fonbet_id, sport, league, home_team, away_team,
               match_date, odds_home, odds_draw, odds_away, 
               odds_over_2_5, odds_under_2_5, odds_over_3_5, odds_under_3_5,
               odds_btts_yes, odds_btts_no, status
        FROM matches
        WHERE status='upcoming'
          AND odds_home IS NOT NULL
          AND odds_away IS NOT NULL
    """
    params: List[Any] = []
    if sport:
        q += " AND sport=?"
        params.append(sport)
    if match_id:
        q += " AND id=?"
        params.append(match_id)
    # Ограничиваем горизонт — не ставим на матчи дальше 5 дней
    from datetime import datetime, timedelta
    horizon = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    q += " AND datetime(match_date) <= ?"
    params.append(horizon)

    # Не ставим на матчи, которые уже начались или начнутся менее чем через 30 минут.
    # match_date хранится в UTC (parser_v2 использует datetime.fromtimestamp на UTC-сервере).
    cutoff = (datetime.now(TIMEZONE) - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    q += " AND datetime(match_date) >= ?"
    params.append(cutoff)

    q += " ORDER BY datetime(match_date) ASC LIMIT ?"
    params.append(limit)

    rows = conn.execute(q, params).fetchall()
    matches = [apply_market_books(conn, Match(**dict(row))) for row in rows]
    return [m for m in matches if not is_placeholder_match(m.home_team, m.away_team)]

def load_historical_features(conn: sqlite3.Connection) -> Dict[int, Dict[str, Any]]:
    """
    Build historical match features dynamically from backtest_matches.
    For each match builds form, goals avg, table position at the time of the match.
    """
    from collections import defaultdict

    result = {}

    # First try the old table if it exists
    try:
        rows = conn.execute("SELECT * FROM historical_match_features").fetchall()
        if rows:
            for row in rows:
                try:
                    match_id = int(row["match_id"])
                    features = dict(row)
                    for form_field in ["form_last_5_home", "form_last_5_away"]:
                        if form_field in features and features[form_field]:
                            try:
                                features[form_field] = json.loads(features[form_field])
                            except (json.JSONDecodeError, TypeError):
                                features[form_field] = []
                        else:
                            features[form_field] = []
                    result[match_id] = features
                except Exception:
                    continue
            if result:
                return result
    except sqlite3.OperationalError:
        pass

    # Build dynamically from backtest_matches
    try:
        all_rows = conn.execute("""
            SELECT id, league, season, match_date, home_team, away_team,
                   home_score, away_score, result, odds_home, odds_draw, odds_away
            FROM backtest_matches
            WHERE home_score IS NOT NULL AND result IS NOT NULL
            ORDER BY league, season, match_date ASC
        """).fetchall()
    except Exception:
        return result

    # Group by league+season
    by_league_season: Dict[str, list] = defaultdict(list)
    for row in all_rows:
        key = f"{row['league']}|{row['season']}"
        by_league_season[key].append(dict(row))

    def build_form(matches, team, before_date, n=5):
        form = []
        for m in sorted(matches, key=lambda x: x["match_date"], reverse=True):
            if m["match_date"] >= before_date:
                continue
            if m["home_team"] == team:
                r = "W" if m["result"] == "H" else ("D" if m["result"] == "D" else "L")
            elif m["away_team"] == team:
                r = "W" if m["result"] == "A" else ("D" if m["result"] == "D" else "L")
            else:
                continue
            form.append(r)
            if len(form) >= n:
                break
        return form

    def build_goals(matches, team, before_date, n=5):
        scored, conceded, count = 0, 0, 0
        for m in sorted(matches, key=lambda x: x["match_date"], reverse=True):
            if m["match_date"] >= before_date:
                continue
            if m["home_team"] == team:
                scored += m["home_score"] or 0
                conceded += m["away_score"] or 0
                count += 1
            elif m["away_team"] == team:
                scored += m["away_score"] or 0
                conceded += m["home_score"] or 0
                count += 1
            if count >= n:
                break
        if count == 0:
            return None, None
        return round(scored / count, 2), round(conceded / count, 2)

    def build_table(matches, before_date):
        pts: Dict[str, int] = defaultdict(int)
        played: Dict[str, int] = defaultdict(int)
        for m in matches:
            if m["match_date"] >= before_date:
                continue
            h, a = m["home_team"], m["away_team"]
            played[h] += 1
            played[a] += 1
            if m["result"] == "H":
                pts[h] += 3
            elif m["result"] == "A":
                pts[a] += 3
            else:
                pts[h] += 1
                pts[a] += 1
        all_teams = set(played.keys())
        sorted_teams = sorted(all_teams, key=lambda t: (-pts[t], t))
        positions = {t: i + 1 for i, t in enumerate(sorted_teams)}
        return positions, pts

    for row in all_rows:
        match_id = row["id"]
        key = f"{row['league']}|{row['season']}"
        league_matches = by_league_season[key]
        before = row["match_date"]
        home = row["home_team"]
        away = row["away_team"]

        home_form = build_form(league_matches, home, before)
        away_form = build_form(league_matches, away, before)
        home_s, home_c = build_goals(league_matches, home, before)
        away_s, away_c = build_goals(league_matches, away, before)
        positions, pts = build_table(league_matches, before)

        result[match_id] = {
            "form_last_5_home": home_form,
            "form_last_5_away": away_form,
            "home_goals_scored_avg": home_s,
            "away_goals_scored_avg": away_s,
            "home_goals_allowed_avg": home_c,
            "away_goals_allowed_avg": away_c,
            "home_position": positions.get(home),
            "away_position": positions.get(away),
            "home_points": pts.get(home, 0),
            "away_points": pts.get(away, 0),
            "h2h_summary": "",
            "notes": "",
            "lineup_data_available": False,
            "injury_data_available": False,
        }

    return result

def _load_match_facts(conn: sqlite3.Connection, match_id: int) -> dict:
    cur = conn.cursor()
    try:
        row = cur.execute(
            "SELECT * FROM match_facts WHERE match_id=?", (match_id,)
        ).fetchone()
    except Exception:
        row = None

    empty = {
        "form_last_5_home": [], "form_last_5_away": [],
        "home_position": None, "away_position": None,
        "home_points": None, "away_points": None,
        "h2h_summary": "",
        "home_goals_scored_avg": None, "away_goals_scored_avg": None,
        "home_goals_allowed_avg": None, "away_goals_allowed_avg": None,
        "home_motivation": "", "away_motivation": "",
        "notes": "", "lineup_data_available": False,
    }

    if not row:
        return empty

    def parse_form(val):
        if not val:
            return []
        try:
            return json.loads(val)
        except Exception:
            return []

    return {
        "form_last_5_home": parse_form(row["home_form"]),
        "form_last_5_away": parse_form(row["away_form"]),
        "home_position": row["home_position"],
        "away_position": row["away_position"],
        "home_points": row["home_points"],
        "away_points": row["away_points"],
        "h2h_summary": row["h2h_summary"] or "",
        "home_goals_scored_avg": row["home_goals_scored_avg"],
        "away_goals_scored_avg": row["away_goals_scored_avg"],
        "home_goals_allowed_avg": row["home_goals_allowed_avg"],
        "away_goals_allowed_avg": row["away_goals_allowed_avg"],
        "home_motivation": row["home_motivation"] or "",
        "away_motivation": row["away_motivation"] or "",
        "notes": row["notes"] or "",
        # lineup_data_available = True только если confirmed стартовый состав (за 1ч до матча)
        "lineup_data_available": bool(row["lineup_data_available"]) if row["lineup_data_available"] else False,
        # injury_data_available = True если в notes есть данные о травмах (из injuries_fetcher)
        "injury_data_available": bool(row["notes"] and ("Травмы" in (row["notes"] or "") or "Injury" in (row["notes"] or ""))),
    }


# get_market_family moved to analysis_helpers/match_utils.py

def has_active_market_exposure(conn: sqlite3.Connection, match_id: int, market_family: str) -> bool:
    """
    Check if there's already an active/pending bet for this match in the same market family.
    
    Args:
        conn: Database connection
        match_id: Match ID to check
        market_family: Market family to check (1X2, TOTALS, etc.)
        
    Returns:
        True if active exposure exists, False otherwise
    """
    if market_family == "1X2":
        # Check for any 1X2 market (home, draw, away)
        row = conn.execute("""
            SELECT 1 FROM bets 
            WHERE match_id = ? 
            AND market IN ('home', 'draw', 'away') 
            AND result = 'pending'
            LIMIT 1
        """, (match_id,)).fetchone()
    elif market_family == "TOTALS":
        # Check for any totals market
        row = conn.execute("""
            SELECT 1 FROM bets 
            WHERE match_id = ? 
            AND (market LIKE 'over_%' OR market LIKE 'under_%' OR market LIKE '%total%')
            AND result = 'pending'
            LIMIT 1
        """, (match_id,)).fetchone()
    elif market_family == "BTTS":
        # Check for any BTTS market
        row = conn.execute("""
            SELECT 1 FROM bets 
            WHERE match_id = ? 
            AND (market LIKE 'btts_%' OR market LIKE 'BTTS_%')
            AND result = 'pending'
            LIMIT 1
        """, (match_id,)).fetchone()
    else:
        # For other market families, check exact match
        row = conn.execute("""
            SELECT 1 FROM bets 
            WHERE match_id = ? 
            AND market = ? 
            AND result = 'pending'
            LIMIT 1
        """, (match_id,)).fetchone()
    
    return bool(row)

def get_match_data_quality(conn: sqlite3.Connection, match_id: int) -> Dict[str, Any]:
    """
    Load data quality flags from match_features when available.
    Falls back to lightweight inference from known facts.
    """
    empty = {
        "league": None,
        "has_standings": 0,
        "has_form": 0,
        "has_goals": 0,
        "has_h2h": 0,
        "has_injuries": 0,
        "data_completeness_score": 0.0,
    }
    try:
        row = conn.execute("""
            SELECT league, has_standings, has_form, has_goals, has_h2h, has_injuries, data_completeness_score
            FROM match_features
            WHERE match_id=?
            LIMIT 1
        """, (match_id,)).fetchone()
        if row:
            return {
                "league": row["league"],
                "has_standings": int(row["has_standings"] or 0),
                "has_form": int(row["has_form"] or 0),
                "has_goals": int(row["has_goals"] or 0),
                "has_h2h": int(row["has_h2h"] or 0),
                "has_injuries": int(row["has_injuries"] or 0),
                "data_completeness_score": float(row["data_completeness_score"] or 0.0),
            }
    except sqlite3.OperationalError:
        pass
    return empty

# safe_prob moved to analysis_helpers/match_utils.py

def get_open_exposure_pct(conn: sqlite3.Connection, bankroll: float) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending'"
    ).fetchone()
    s = float(row["s"] or 0.0)
    return s / bankroll if bankroll > 0 else 0.0

def get_loss_streak_72h_same_sport(conn: sqlite3.Connection, sport: str) -> int:
    since = (datetime.now(TIMEZONE) - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute("""
        SELECT b.result FROM bets b
        JOIN matches m ON b.match_id = m.id
        WHERE m.sport=? AND b.created_at>=?
          AND b.result IN ('loss','won','lost')
        ORDER BY b.created_at DESC
    """, (sport, since)).fetchall()
    streak = 0
    for row in rows:
        if row["result"] in ("loss", "lost"):
            streak += 1
        else:
            break
    return streak

def load_rules_for_sport(conn: sqlite3.Connection, sport: str) -> List[str]:
    rows = conn.execute(
        "SELECT rule_text FROM rules WHERE sport=? ORDER BY id", (sport,)
    ).fetchall()
    return [r["rule_text"] for r in rows]

def build_payload(conn, match: Match, bankroll: float) -> Dict[str, Any]:
    # Get totals markets if they exist
    totals_markets = {}
    totals_probabilities = {}
    
    # Add totals if they exist as attributes on the match object
    if hasattr(match, "odds_over_2_5") and match.odds_over_2_5:
        totals_markets["over_2_5"] = match.odds_over_2_5
        totals_probabilities["over_2_5"] = safe_prob(match.odds_over_2_5)
    
    if hasattr(match, "odds_under_2_5") and match.odds_under_2_5:
        totals_markets["under_2_5"] = match.odds_under_2_5
        totals_probabilities["under_2_5"] = safe_prob(match.odds_under_2_5)
        
    if hasattr(match, "odds_over_3_5") and match.odds_over_3_5:
        totals_markets["over_3_5"] = match.odds_over_3_5
        totals_probabilities["over_3_5"] = safe_prob(match.odds_over_3_5)
        
    if hasattr(match, "odds_under_3_5") and match.odds_under_3_5:
        totals_markets["under_3_5"] = match.odds_under_3_5
        totals_probabilities["under_3_5"] = safe_prob(match.odds_under_3_5)
        
    # Add BTTS markets if they exist
    btts_markets = {}
    btts_probabilities = {}
    
    if hasattr(match, "odds_btts_yes") and match.odds_btts_yes:
        btts_markets["btts_yes"] = match.odds_btts_yes
        btts_probabilities["btts_yes"] = safe_prob(match.odds_btts_yes)
        
    if hasattr(match, "odds_btts_no") and match.odds_btts_no:
        btts_markets["btts_no"] = match.odds_btts_no
        btts_probabilities["btts_no"] = safe_prob(match.odds_btts_no)
    
    return {
        "match_id": match.id,
        "fonbet_id": match.fonbet_id,
        "sport": match.sport,
        "league": match.league,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "match_date": match.match_date,
        "markets": {
            "home": match.odds_home,
            "draw": match.odds_draw,
            "away": match.odds_away,
            **totals_markets,
            **btts_markets
        },
        "market_probabilities": {
            "home": safe_prob(match.odds_home),
            "draw": safe_prob(match.odds_draw),
            "away": safe_prob(match.odds_away),
            **totals_probabilities,
            **btts_probabilities
        },
        "open_exposure_pct": get_open_exposure_pct(conn, bankroll),
        "loss_streak_72h_same_sport": get_loss_streak_72h_same_sport(conn, match.sport),
        "rules_version": RULES_VERSION,
        "sport_rules": load_rules_for_sport(conn, match.sport),
        "known_facts": _load_match_facts(conn, match.id),
        "is_backtest_approved": False,
        "ba_rule": None,
        "shortlist_source": "live",
    }



# ============================================================
# MATH ENGINE
# ============================================================

def enrich_with_math(rec: Dict[str, Any], match: Match, facts: Dict = None) -> Dict[str, Any]:
    if rec.get("market") == "pass":
        for key in ("odds", "market_probability", "ev", "kelly", "kelly_quarter"):
            rec.setdefault(key, None)
        rec.setdefault("stake_pct", 0.0)
        return rec

    profile = get_profile(match.sport)
    market = rec["market"]
    bankroll = (GLOBAL_ARGS.bankroll if GLOBAL_ARGS else None) or (args.bankroll if args else 100000)
    
    # Check if this is a BTTS market
    is_btts_market = market.startswith("btts_")
    
    # Handle BTTS markets
    if market == "btts_yes" and hasattr(match, "odds_btts_yes"):
        odds = match.odds_btts_yes
    elif market == "btts_no" and hasattr(match, "odds_btts_no"):
        odds = match.odds_btts_no
    elif market == "over_2_5" and hasattr(match, "odds_over_2_5"):
        odds = match.odds_over_2_5
    elif market == "under_2_5" and hasattr(match, "odds_under_2_5"):
        odds = match.odds_under_2_5
    elif market == "over_1_5" and hasattr(match, "odds_over_1_5"):
        odds = match.odds_over_1_5
    elif market == "under_1_5" and hasattr(match, "odds_under_1_5"):
        odds = match.odds_under_1_5
    else:
        odds = {"home": match.odds_home, "draw": match.odds_draw, "away": match.odds_away}.get(market)

    market_odds = odds
    recommended_bookmaker = "fonbet"
    if market == "home":
        market_odds = match.market_home or odds
        recommended_bookmaker = match.best_home_book or "fonbet"
    elif market == "draw":
        market_odds = match.market_draw or odds
        recommended_bookmaker = match.best_draw_book or "fonbet"
    elif market == "away":
        market_odds = match.market_away or odds
        recommended_bookmaker = match.best_away_book or "fonbet"

    if odds is None:
        rec["market"] = "pass"
        rec["market_label"] = "PASS"
        rec["decision"] = "PASS"
        rec["stake_pct"] = 0.0
        return rec

    our_p = float(rec["our_probability"])
    market_p = 1.0 / float(market_odds or odds)
    ev = our_p * float(odds) - 1.0
    rec["recommended_bookmaker"] = recommended_bookmaker
    
    # Store original probability for BTTS debug
    btts_calibration = rec.get("btts_calibration", {})
    original_p = btts_calibration.get("original_p", our_p)

    # Защита: без составов не ставим на аутсайдеров с коэффициентом > 6.0
    lineup_ok = bool(rec.get("lineup_data_available", False))
    if not lineup_ok and float(odds) > 6.0:
        rec["market"] = "pass"
        rec["market_label"] = "PASS"
        rec["decision"] = "PASS"
        rec["signal_type"] = "Pass"
        rec["odds"] = float(odds)
        rec["market_probability"] = market_p
        rec["ev"] = ev
        rec["kelly"] = 0.0
        rec["kelly_quarter"] = 0.0
        rec["stake_pct"] = 0.0
        rec["auto_pass_reason"] = f"Коэффициент {odds} > 6.0 без составов — слишком высокий риск"
        return rec

    # Мягкий cap для odds >= 4.5 без составов
    # Ограничиваем нашу вероятность на market_p + 0.08
    if not lineup_ok and float(odds) >= 4.5:
        max_p = market_p + 0.08
        if our_p > max_p:
            our_p = max_p
            rec["our_probability"] = round(our_p, 4)
            adjs = rec.get("probability_adjustments", [])
            adjs.append(f"cap аутсайдер@{odds} без составов: →{max_p:.3f}")
            rec["probability_adjustments"] = adjs

    # Защита: не ставим на гостевую команду которая пропускает выше порога без составов
    # Порог берётся из профиля (away_goals_allowed_threshold), по умолчанию 1.8
    if not lineup_ok and market == "away" and facts:
        away_allowed = facts.get("away_goals_allowed_avg")
        threshold = profile.get("away_goals_allowed_threshold", 99.0)
        if away_allowed and float(away_allowed) > threshold:
            rec["market"] = "pass"
            rec["market_label"] = "PASS"
            rec["decision"] = "PASS"
            rec["signal_type"] = "Pass"
            rec["odds"] = float(odds)
            rec["market_probability"] = market_p
            rec["ev"] = ev
            rec["kelly"] = 0.0
            rec["kelly_quarter"] = 0.0
            rec["stake_pct"] = 0.0
            rec["auto_pass_reason"] = f"Гостевая команда пропускает {away_allowed:.1f} г/матч > {threshold} без составов"
            return rec

    # Защита: ничья без составов — cap коэффициента
    if not lineup_ok and market == "draw" and float(odds) > 4.5:
        rec["market"] = "pass"
        rec["market_label"] = "PASS"
        rec["decision"] = "PASS"
        rec["signal_type"] = "Pass"
        rec["odds"] = float(odds)
        rec["market_probability"] = market_p
        rec["ev"] = ev
        rec["kelly"] = 0.0
        rec["kelly_quarter"] = 0.0
        rec["stake_pct"] = 0.0
        rec["auto_pass_reason"] = f"Ничья @ {odds} > 4.5 без составов — слишком неопределённо"
        return rec

    # Валидация ничьей по данным
    # SA_AWAY_DRAW использует свои фильтры — пропускаем стандартную валидацию ничьей
    _rule = rec.get("rule") or rec.get("live_rule_family") or rec.get("market_error", "")
    _skip_draw_validation = any(x in _rule for x in ["SA_AWAY_DRAW", "NLA_BERN_AWAY_DRAW"])
    if market == "draw" and facts and not _skip_draw_validation:
        home_pos = facts.get("home_position")
        away_pos = facts.get("away_position")
        home_scored = facts.get("home_goals_scored_avg") or 0
        away_scored = facts.get("away_goals_scored_avg") or 0

        # Проверка разницы в таблице
        max_table_diff = profile.get("draw_max_table_diff", 5)
        if home_pos and away_pos:
            table_diff = abs(int(home_pos) - int(away_pos))
            if table_diff > max_table_diff:
                rec["market"] = "pass"
                rec["market_label"] = "PASS"
                rec["decision"] = "PASS"
                rec["signal_type"] = "Pass"
                rec["odds"] = float(odds)
                rec["market_probability"] = market_p
                rec["ev"] = ev
                rec["kelly"] = 0.0
                rec["kelly_quarter"] = 0.0
                rec["stake_pct"] = 0.0
                rec["auto_pass_reason"] = (
                    f"Ничья: разница в таблице {table_diff} мест > {max_table_diff} — команды неравны"
                )
                return rec

        # Проверка атаки — если одна из команд атакующая, ничья маловероятна
        attack_threshold = profile.get("draw_max_attack_avg", 1.7)
        if max(home_scored, away_scored) > attack_threshold:
            rec["market"] = "pass"
            rec["market_label"] = "PASS"
            rec["decision"] = "PASS"
            rec["signal_type"] = "Pass"
            rec["odds"] = float(odds)
            rec["market_probability"] = market_p
            rec["ev"] = ev
            rec["kelly"] = 0.0
            rec["kelly_quarter"] = 0.0
            rec["stake_pct"] = 0.0
            rec["auto_pass_reason"] = (
                f"Ничья: атака {max(home_scored, away_scored):.1f} г/матч > {attack_threshold} — матч будет открытым"
            )
            return rec

    # Нет edge после калибровки → auto PASS
    # Use different threshold for BTTS markets
    is_btts_market = market in ("btts_yes", "btts_no")
    is_totals_market = market in ("over_2_5", "under_2_5", "over_1_5", "under_1_5", "over_3_5", "under_3_5")
    # Ensure BTTS and totals markets use the correct threshold
    if is_btts_market or is_totals_market:
        min_edge = profile.get("min_edge_vs_market_btts", 0.015)
    else:
        min_edge = profile["min_edge_vs_market"]
    
    # Store raw values for debug output
    rec["debug_info"] = {
        "market": market,
        "odds": float(odds),
        "market_p": market_p,
        "our_p": our_p,
        "our_p_raw": original_p,
        "threshold": min_edge,
        "threshold_value": market_p + min_edge,
        "is_btts_market": is_btts_market,
        "edge": our_p - market_p,
        "calibration_adjustment": btts_calibration.get("adjustment", 0),
        "calibration_details": btts_calibration.get("adjustments", [])
    }
    
    if our_p <= market_p + min_edge:
        rec["market"] = "pass"
        rec["market_label"] = "PASS"
        rec["decision"] = "PASS"
        rec["signal_type"] = "Pass"
        rec["odds"] = float(odds)
        rec["market_probability"] = market_p
        rec["ev"] = ev
        rec["kelly"] = 0.0
        rec["kelly_quarter"] = 0.0
        rec["stake_pct"] = 0.0
        market_type = "BTTS" if is_btts_market else "1X2"
        rec["auto_pass_reason"] = (
            f"Нет edge ({market_type}): our_p={our_p:.3f} ≤ market_p+{min_edge}={market_p+min_edge:.3f}"
        )
        return rec

    kelly = compute_kelly(our_p, float(odds))
    kelly_quarter = max(0.0, kelly * 0.25)
    cap = confidence_cap_pct(int(rec["confidence"]))
    
    # Standard stake calculation
    stake_pct = min(kelly_quarter, cap, 0.10)
    
    # Apply adaptive staking for BTTS_YES_CORE
    if rec.get("live_rule_family") == "BTTS_YES_CORE":
        # Get current bankroll and peak bankroll
        conn = get_conn()
        current_bankroll = bankroll
        try:
            # Get current profit to calculate current bankroll
            profit_row = conn.execute("""
                SELECT COALESCE(SUM(profit), 0) as total_profit 
                FROM bets 
                WHERE result IN ('won', 'lost')
            """).fetchone()
            if profit_row:
                current_bankroll += float(profit_row[0] or 0)
                
            # Get peak bankroll from last 30 days
            peak_row = conn.execute("""
                SELECT MAX(running_balance) as peak_balance
                FROM (
                    SELECT 
                        created_at,
                        SUM(CASE WHEN result IN ('won', 'lost') THEN profit ELSE 0 END) 
                        OVER (ORDER BY created_at) + ? as running_balance
                    FROM bets
                    WHERE created_at >= date('now', '-30 days')
                )
            """, (bankroll,)).fetchone()
            
            peak_bankroll = float(peak_row[0] or current_bankroll)
            
            # Calculate drawdown percentage
            drawdown_pct = 0
            if peak_bankroll > 0:
                drawdown_pct = max(0, (peak_bankroll - current_bankroll) / peak_bankroll * 100)
                
            # Check if we're at a new equity high (within 0.5%)
            at_equity_high = current_bankroll >= peak_bankroll * 0.995
            
            # Check if we've been near equity high for at least 1 day
            days_at_high = 0
            if at_equity_high:
                high_days_row = conn.execute("""
                    SELECT COUNT(DISTINCT DATE(created_at)) as days
                    FROM bets
                    WHERE created_at >= date('now', '-7 days')
                    AND result IN ('won', 'lost')
                    AND (
                        SELECT SUM(CASE WHEN result IN ('won', 'lost') THEN profit ELSE 0 END)
                        FROM bets b2
                        WHERE b2.created_at <= bets.created_at
                    ) + ? >= ?
                """, (bankroll, peak_bankroll * 0.995)).fetchone()
                if high_days_row:
                    days_at_high = high_days_row[0] or 0
            
            # Base stake for BTTS_YES_CORE is 1.0% of current bankroll
            btts_base_stake = 0.01
            
            # Apply drawdown adjustment
            if drawdown_pct > 12:
                btts_base_stake = 0.005  # 0.50%
            elif drawdown_pct > 8:
                btts_base_stake = 0.0075  # 0.75%
                
            # Apply upshift rule if at equity high for at least 1 day
            if at_equity_high and days_at_high >= 1:
                btts_base_stake = 0.0125  # 1.25%
                
            # Use the adaptive stake for BTTS_YES_CORE
            stake_pct = btts_base_stake
            
            # Store the adaptive staking info in the recommendation
            rec["adaptive_staking"] = {
                "current_bankroll": current_bankroll,
                "peak_bankroll": peak_bankroll,
                "drawdown_pct": drawdown_pct,
                "at_equity_high": at_equity_high,
                "days_at_high": days_at_high,
                "base_stake": btts_base_stake,
            }
            
        except Exception as e:
            # Fallback to base stake on error
            stake_pct = 0.01
            rec["adaptive_staking_error"] = str(e)
        finally:
            conn.close()
    else:
        # Apply stake mode system for non-BTTS_YES_CORE recommendations
        conn = get_conn()
        try:
            # Try to get stake from config
            override_stake_pct, override_stake_abs, stake_meta = resolve_stake_pct_and_meta(conn, bankroll, match, rec)
            if override_stake_pct is not None:
                stake_pct = override_stake_pct
                
                # Add stake mode metadata to recommendation
                if stake_meta:
                    rec.update({
                        "stake_mode_name": stake_meta.get("stake_mode_name"),
                        "stake_mode_type": stake_meta.get("stake_mode_type"),
                        "stake_mode_reason": stake_meta.get("stake_mode_reason"),
                    })
                    
                    # Add bankroll regime info if available
                    if "base_bankroll" in stake_meta:
                        rec.update({
                            "base_bankroll": stake_meta.get("base_bankroll"),
                            "current_bankroll": stake_meta.get("current_bankroll"),
                            "bankroll_regime": stake_meta.get("bankroll_regime"),
                        })
        except Exception as e:
            # Log error but continue with standard stake calculation
            rec["stake_mode_error"] = str(e)
        finally:
            conn.close()

    rec["odds"] = float(odds)
    rec["market_probability"] = market_p
    rec["ev"] = ev
    rec["kelly"] = kelly
    rec["kelly_quarter"] = kelly_quarter
    rec["stake_pct"] = stake_pct
    rec["confidence_cap"] = cap
    return rec


# ============================================================
# LLM
# ============================================================

# extract_json_object moved to analysis_helpers/llm_utils.py

def call_llm(payload: Dict[str, Any], bankroll: float) -> Dict[str, Any]:
    # Check for pure BA mode first
    pure_ba_mode = getattr(GLOBAL_ARGS, "pure_ba", False)
    is_ba_approved = payload.get("is_backtest_approved", False)
    ba_rule = payload.get("ba_rule")
    
    # If in pure BA mode and match is BA-approved, force the market from the rule
    if pure_ba_mode and is_ba_approved and ba_rule:
        # Set pure_ba_mode flag on match object for display purposes
        match_id = payload.get("match_id")
        if match_id:
            for match in getattr(GLOBAL_ARGS, "_matches_cache", []):
                if getattr(match, "id", None) == match_id:
                    setattr(match, "pure_ba_mode", True)
                    break
    
    # Check for football and pruned live rules
    match_sport = payload.get("sport", "").lower()
    if match_sport == "football" and not getattr(GLOBAL_ARGS, "backtest", False):
        # For live football, we'll check if there's a match with pruned rules
        # This is handled in main() before calling this function
        pass
    
    if getattr(GLOBAL_ARGS, "no_llm", False):
        # При --no-llm football всегда PASS (rule-driven должен был сработать раньше)
        if match_sport == "football":
            return {
                "market": "pass",
                "market_label": "PASS",
                "decision": "PASS",
                "signal_type": "Pass",
                "market_error": "LLM disabled by --no-llm",
                "strategy_family": "no_llm_disabled",
                "rule_driven": False,
                "shadow_only": False,
            }
        return simulate_llm_response(payload)

    api_url = os.getenv("LLM_API_URL")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    if not api_url or not api_key or not model:
        raise RuntimeError("Нужны ENV: LLM_API_URL, LLM_API_KEY, LLM_MODEL")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        open_exposure_pct=payload["open_exposure_pct"],
        loss_streak_72h_same_sport=payload["loss_streak_72h_same_sport"],
        bankroll=bankroll,
        payload_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    body = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(3):
        try:
            resp = requests.post(api_url, headers=headers, json=body, timeout=120, verify=False)
            # Retry на серверные ошибки 500/502/503
            if resp.status_code in (500, 502, 503) and attempt < 2:
                print(f"  ⚠️  HTTP {resp.status_code}, retry {attempt+1}/3 через 15 сек...")
                time.sleep(15)
                continue
            resp.raise_for_status()
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < 2:
                print(f"  ⏳ Timeout/ConnError, retry {attempt+1}/3 через 10 сек...")
                time.sleep(10)
            else:
                raise
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"].strip()
        result = extract_json_object(content)
        
        # For football, mark as shadow_only
        if match_sport == "football" and not getattr(GLOBAL_ARGS, "backtest", False):
            result["shadow_only"] = True
            
        return result
    except Exception as e:
        raise RuntimeError(f"Ошибка разбора ответа: {e}\nRAW={data}")

# normalize_response, build_structured_comment moved to analysis_helpers/llm_utils.py

# ============================================================
# SAVE & PRINT
# ============================================================

def save_handoff_decision(
    # SKIP in backtest mode
    *args, **kwargs
) -> None:
    import inspect
    _args = args
    if len(_args) > 0:
        pass
    global GLOBAL_ARGS
    if GLOBAL_ARGS and getattr(GLOBAL_ARGS, 'backtest', False):
        return
    return _save_handoff_decision_impl(*_args, **kwargs)

def _save_handoff_decision_impl(
    conn, match: Match, payload, rec, valid, notes, run_mode: str
):
    """
    Save ALL decisions made by the handoff process to handoff_decisions table.
    This includes PASS decisions, invalid decisions, and validator rejected decisions.
    
    Args:
        conn: Database connection
        match: Match object
        payload: Original payload sent to LLM
        rec: Recommendation dictionary
        valid: Whether the recommendation passed validation
        notes: Validation notes
        run_mode: Run mode (dry-run, live, backtest)
    """
    # Create a fingerprint for deduplication
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    created_at_minute = datetime.now().strftime("%Y-%m-%d %H:%M")
    fingerprint = f"{match.id}_{rec.get('market', 'pass')}_{created_at_minute}"
    
    # Extract data from match
    match_data = {
        "match_id": match.id,
        "fonbet_match_id": getattr(match, "fonbet_id", None),
        "sport": match.sport,
        "league": match.league,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "match_date": match.match_date,
    }
    
    # Extract data from recommendation
    rec_data = {
        "market": rec.get("market", "pass"),
        "market_label": rec.get("market_label", "PASS"),
        "odds": rec.get("odds"),
        "our_probability": rec.get("our_probability"),
        "market_probability": rec.get("market_probability"),
        "ev": rec.get("ev"),
        "edge": rec.get("edge", rec.get("ev")),  # Use EV as edge if not provided
        "confidence": rec.get("confidence"),
        "signal_type": rec.get("signal_type", "Pass"),
        "decision": rec.get("decision", "PASS"),
        "recommended_action": rec.get("recommended_action", rec.get("decision", "PASS")),
        "market_error": rec.get("market_error", rec.get("auto_pass_reason", "")),
        "validator_rejected": 1 if rec.get("validator_rejected", False) else 0,
    }
    
    # Join notes as string
    notes_str = " | ".join(notes) if notes else ""
    
    # Prepare JSON data
    payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
    recommendation_json = json.dumps(rec, ensure_ascii=False) if rec else None
    match_snapshot = payload.get("match_snapshot") if payload else None
    
    # Insert into handoff_decisions
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO handoff_decisions (
            created_at, run_mode, created_by,
            match_id, fonbet_match_id, sport, league, home_team, away_team, match_date,
            market, market_label, odds, our_probability, market_probability, ev, edge,
            confidence, signal_type, decision, valid, validator_rejected, recommended_action,
            notes, market_error, payload_json, recommendation_json, match_snapshot, fingerprint
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        created_at, run_mode, "agent_handoff_v7",
        match_data["match_id"], match_data["fonbet_match_id"], match_data["sport"], match_data["league"],
        match_data["home_team"], match_data["away_team"], match_data["match_date"],
        rec_data["market"], rec_data["market_label"], rec_data["odds"], rec_data["our_probability"],
        rec_data["market_probability"], rec_data["ev"], rec_data["edge"],
        rec_data["confidence"], rec_data["signal_type"], rec_data["decision"], 
        1 if valid else 0, rec_data["validator_rejected"], rec_data["recommended_action"],
        notes_str, rec_data["market_error"], payload_json, recommendation_json, match_snapshot, fingerprint
    ))
    conn.commit()

def save_recommendation(
    conn, match: Match, payload, rec, valid, notes, bankroll, dry_run=False
):
    if dry_run:
        return
    # Shadow rec blocked in save_recommendation when disable-shadow is active
    try:
        if 'args' in globals() and getattr(args, "disable_shadow", False) and is_shadow_recommendation(rec):
            return
    except Exception:
        pass
    
    # Skip shadow-only recommendations
    if rec.get("shadow_only", False):
        print(f"⚠️ SKIP SAVE: Shadow-only recommendation for match_id={match.id}, market={rec.get('market')}")
        return
        
    # Skip any dry-run override recommendations
    if rec.get("dry_run_btts_override", False) or rec.get("dry_run_rule_override", False) or rec.get("dry_run_exposure_override", False):
        override_type = "BTTS" if rec.get("dry_run_btts_override") else "RULE" if rec.get("dry_run_rule_override") else "EXPOSURE"
        print(f"⚠️ SKIP SAVE: {override_type} dry-run override for match_id={match.id}, market={rec.get('market')}")
        return
        
    # Hard gate: never save invalid recommendations
    if not valid:
        print(f"⚠️ SKIP SAVE: Invalid recommendation for match_id={match.id}, market={rec.get('market')}")
        return
    
    # Check for existing pending bet with same match_id and market family to prevent duplicates
    market = rec.get("market")
    market_family = get_market_family(market)
    
    # Check if this market family already exists for this match
    if has_active_market_exposure(conn, match.id, market_family):
        print(f"⚠️ SKIP: Already have pending bet for match_id={match.id}, market_family={market_family}")
        return
    
    cur = conn.cursor()
        
    stake_pct = float(rec.get("stake_pct", 0.0))
    stake_abs = round(bankroll * stake_pct, 2)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Prepare additional fields for agent_reasoning
    agent_reasoning = {
        "market_error": rec.get("market_error"),
        "confirmed_facts": rec.get("confirmed_facts", []),
        "unconfirmed": rec.get("unconfirmed", []),
        "probability_adjustments": rec.get("probability_adjustments", []),
        "ba_flag": bool(payload.get("is_backtest_approved", False)),
        "ba_rule": payload.get("ba_rule"),
        "shortlist_source": payload.get("shortlist_source"),
        "rule_driven": rec.get("rule_driven", False),
        "live_rule_family": rec.get("live_rule_family"),
        "legacy_path_used": rec.get("legacy_path_used", False),
        "strategy_family": rec.get("strategy_family"),
        "market_family": rec.get("market_family"),
        "reason_summary": rec.get("reason_summary"),
        "supporting_facts": rec.get("supporting_facts"),
        "explanation_short": rec.get("explanation_short"),
    }
    
    # Add adaptive staking info if available
    if rec.get("adaptive_staking"):
        agent_reasoning["adaptive_staking"] = rec["adaptive_staking"]
        
    # Build structured comment
    structured_comment = build_structured_comment(rec, payload)
    
    # Determine rule name for the rule column
    rule_name = None
    if rec.get("live_rule_family"):
        rule_name = rec.get("live_rule_family")
    elif payload.get("ba_rule"):
        rule_name = payload.get("ba_rule")
    elif rec.get("strategy_family"):
        rule_name = rec.get("strategy_family")
    
    cur.execute("""
        INSERT INTO bets (
            match_id, market, odds, our_probability, ev,
            kelly_size, stake, result, profit,
            agent_reasoning, created_at,
            rules_version, signal_type, confidence,
            market_probability, lineup_data_available,
            market_error_summary, validated, validation_notes,
            stake_pct, kelly_quarter, recommended_action,
            created_by, match_snapshot, recommended_bookmaker,
            reasons, rule, edge, model_prob, market_prob
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        match.id,
        rec.get("market"), rec.get("odds"), rec.get("our_probability"), rec.get("ev"),
        rec.get("kelly"),  # kelly_size = полный Kelly (не quarter)
        stake_abs, "pending", None,
        json.dumps(agent_reasoning, ensure_ascii=False),
        created_at,
        RULES_VERSION, rec.get("signal_type"), rec.get("confidence"),
        rec.get("market_probability"), 1 if rec.get("lineup_data_available") else 0,
        rec.get("market_error", ""), 1 if valid else 0, " | ".join(notes),
        stake_pct, rec.get("kelly_quarter"), rec.get("decision"),
        "agent_handoff_v7.py",
        json.dumps(payload, ensure_ascii=False),
        rec.get("recommended_bookmaker", "fonbet"),
        # New structured fields
        json.dumps(structured_comment, ensure_ascii=False),
        rule_name,
        rec.get("ev"),
        rec.get("our_probability"),
        rec.get("market_probability"),
    ))
    conn.commit()

def enforce_validator_gate(rec: Dict[str, Any], valid: bool, notes: List[str]) -> Dict[str, Any]:
    """
    Enforce validator as a hard gate. If validation fails, force decision to PASS.
    """
    # Check if we're in dry-run mode
    dry_run_mode = getattr(GLOBAL_ARGS, "dry_run", False)
    market = rec.get("market", "")
    is_btts_market = market.startswith("btts_")
    is_rule_driven = rec.get("rule_driven", False)
    
    # Check if the only validation issue is exposure-related
    exposure_only_issue = False
    if not valid:
        exposure_issue = any("экспозиция превысит" in note for note in notes)
        other_issues = [note for note in notes if "экспозиция превысит" not in note]
        exposure_only_issue = exposure_issue and not other_issues
    
    if not valid:
        # In dry-run mode, handle exposure issues differently
        if dry_run_mode and exposure_only_issue:
            if is_btts_market:
                # For BTTS in dry-run, use the existing override
                rec["dry_run_btts_override"] = True
                rec["validator_notes"] = notes
                rec["validator_rejected"] = True
                rec["override_reason"] = "BTTS в dry-run: игнорируем глобальный лимит экспозиции"
            elif is_rule_driven:
                # For rule-driven candidates in dry-run, mark but don't reject
                rec["dry_run_rule_override"] = True
                rec["validator_notes"] = notes
                rec["validator_rejected"] = True
                rec["override_reason"] = "Rule-driven в dry-run: игнорируем глобальный лимит экспозиции"
            else:
                # For other markets in dry-run with exposure issues, mark but don't fully reject
                rec["dry_run_exposure_override"] = True
                rec["validator_notes"] = notes
                rec["validator_rejected"] = True
                rec["override_reason"] = "Dry-run: игнорируем глобальный лимит экспозиции"
        else:
            # Standard behavior - reject the recommendation
            rec.update({
                "market": "pass",
                "market_label": "PASS",
                "decision": "PASS",
                "signal_type": "Pass",
                "kelly": 0.0,
                "kelly_quarter": 0.0,
                "stake_pct": 0.0,
                "auto_pass_reason": "Validator rejected recommendation"
            })
            # Keep the original validator notes
            rec["validator_notes"] = notes
            # Keep track that this was rejected by validator
            rec["validator_rejected"] = True
    
    return rec

def print_result(match: Match, rec, valid, notes, bankroll):
    stake_abs = round(bankroll * float(rec.get("stake_pct", 0.0)), 2)
    profile = get_profile(match.sport)
    using_historical = " [HIST]" if getattr(match, "using_historical_features", False) or rec.get("using_historical_features", False) else ""
    
    # Add override tag if applicable
    override_tag = ""
    if rec.get("dry_run_btts_override"):
        override_tag = " [BTTS_OVERRIDE]"
    elif rec.get("dry_run_rule_override"):
        override_tag = " [RULE_OVERRIDE]"
    elif rec.get("dry_run_exposure_override"):
        override_tag = " [EXPOSURE_OVERRIDE]"
    elif rec.get("hockey_path"):
        override_tag = " [HOCKEY_PATH]"
    
    print("=" * 80)
    print(f"{match.home_team} — {match.away_team} [{match.league}]{_ba_tag(match)}{_rule_tag(rec)}{using_historical}{override_tag}")
    print(f"Исход: {rec.get('market_label')} @ {rec.get('odds')} | БК: {rec.get('recommended_bookmaker', 'fonbet')} | Профиль: {match.sport}")
    print(f"Рынок: {float(rec.get('market_probability',0)):.4f} | "
          f"Наша: {float(rec.get('our_probability',0)):.4f} | "
          f"EV: {float(rec.get('ev',0)):.4f}")
    
    # Print detailed BTTS debug info if available
    debug_info = rec.get("debug_info", {})
    if debug_info and debug_info.get("is_btts_market"):
        raw_p = debug_info.get('our_p_raw', debug_info.get('our_p', 0))
        print(f"BTTS DEBUG: odds={debug_info.get('odds'):.2f} | "
              f"market_p={debug_info.get('market_p'):.4f} | "
              f"our_p={debug_info.get('our_p'):.4f} | "
              f"raw_p={raw_p:.4f} | "
              f"adjustment={debug_info.get('calibration_adjustment', 0):.4f} | "
              f"threshold=+{debug_info.get('threshold'):.3f} | "
              f"required={debug_info.get('threshold_value'):.4f} | "
              f"edge={debug_info.get('edge'):.4f}")
        
        # Print detailed calibration adjustments
        calibration_details = debug_info.get('calibration_details', [])
        if calibration_details:
            print(f"BTTS CALIBRATION: {' | '.join(calibration_details)}")
    
    # Print exposure information
    market = rec.get("market", "")
    market_family = get_market_family(market)
    if market != "pass":
        conn = get_conn()
        # Get global exposure
        row = conn.execute(
            "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending'"
        ).fetchone()
        global_exposure = float(row["s"] or 0.0)
        global_exposure_pct = global_exposure / bankroll
        
        # Get market family specific exposure
        if market_family == "1X2":
            row_family = conn.execute(
                "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending' AND market IN ('home', 'draw', 'away')"
            ).fetchone()
        elif market_family == "BTTS":
            row_family = conn.execute(
                "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending' AND (market LIKE 'btts_%' OR market LIKE 'BTTS_%')"
            ).fetchone()
        elif market_family == "TOTALS":
            row_family = conn.execute(
                "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending' AND (market LIKE 'over_%' OR market LIKE 'under_%' OR market LIKE '%total%')"
            ).fetchone()
        else:
            row_family = conn.execute(
                "SELECT COALESCE(SUM(stake), 0) AS s FROM bets WHERE result='pending' AND market = ?",
                (market,)
            ).fetchone()
        
        family_exposure = float(row_family["s"] or 0.0)
        family_exposure_pct = family_exposure / bankroll
        conn.close()
        
        # Calculate new exposures
        new_stake = bankroll * float(rec.get("stake_pct", 0.0))
        new_global_exposure_pct = (global_exposure + new_stake) / bankroll
        new_family_exposure_pct = (family_exposure + new_stake) / bankroll
        
        print(f"Экспозиция: Глобальная={global_exposure_pct:.1%}→{new_global_exposure_pct:.1%} | "
              f"{market_family}={family_exposure_pct:.1%}→{new_family_exposure_pct:.1%}")
    
    adj = rec.get("probability_adjustments", [])
    if adj:
        print(f"Калибровка: {' | '.join(adj)}")
    print(f"Сигнал: {rec.get('signal_type')} | Уверенность: {rec.get('confidence')}/10")
    print(f"Kelly: {float(rec.get('kelly',0)):.4f} | "
          f"Kelly×0.25: {float(rec.get('kelly_quarter',0)):.4f} | "
          f"Stake%: {float(rec.get('stake_pct',0)):.4f}")
    print(f"Ставка: {stake_abs} | Решение: {rec.get('decision')} | VALID={valid}")
    
    # Print adaptive staking info if available
    if rec.get("adaptive_staking"):
        as_info = rec["adaptive_staking"]
        print(f"Адаптивный стейкинг: {as_info.get('base_stake', 0)*100:.2f}% | "
              f"Drawdown: {as_info.get('drawdown_pct', 0):.1f}% | "
              f"At equity high: {as_info.get('at_equity_high', False)}")
    
    # Print stake mode info if available
    if rec.get("stake_mode_name"):
        print(f"Stake mode: {rec.get('stake_mode_name')} ({rec.get('stake_mode_type')}) | "
              f"Reason: {rec.get('stake_mode_reason')}")
        
        # Print bankroll regime info if available
        if rec.get("bankroll_regime"):
            print(f"Bankroll regime: {rec.get('bankroll_regime')} | "
                  f"Base: {rec.get('base_bankroll', 0):.0f} | "
                  f"Current: {rec.get('current_bankroll', 0):.0f}")
    
    if not valid:
        print(f"Причина отклонения: {rec.get('auto_pass_reason', 'Validator rejected')}")
    print(f"Ошибка рынка: {rec.get('market_error')}")
    
    # Print explanation_short if available
    if rec.get("explanation_short"):
        print(f"Краткое объяснение: {rec.get('explanation_short')}")
        
    if rec.get("confirmed_facts"):
        print("Подтверждено:")
        for x in rec["confirmed_facts"]:
            print(f"  - {x}")
    if rec.get("unconfirmed"):
        print("Не подтверждено:")
        for x in rec["unconfirmed"]:
            print(f"  - {x}")
    if notes:
        print("Validator:")
        for n in notes:
            print(f"  - {n}")


# ============================================================
# MAIN
# ============================================================

args = None







def main() -> int:
    global args
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=["football", "hockey", "tennis", "mma", "esports"], default=None)
    ap.add_argument("--all-sports", action="store_true", help="Run backtest for all sports combined")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--match-id", type=int, default=None)
    ap.add_argument("--bankroll", type=float, default=DEFAULT_BANK)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="Disable LLM calls")
    ap.add_argument("--backtest", action="store_true", help="Run in backtest mode")
    ap.add_argument("--pure-ba", action="store_true", help="Use strict BA rule->market execution")
    ap.add_argument("--disable-shadow", action="store_true", help="Disable heuristic/shadow fallback as final betting source")
    ap.add_argument("--export-equity", action="store_true", help="Сохранить бэктест в backtest_equity")
    global GLOBAL_ARGS
    args = ap.parse_args()

    # --all-sports: запускаем футбол и хоккей последовательно с общим банком
    if getattr(args, "all_sports", False) and args.backtest:
        args.sport = None  # fetch_backtest_matches вернёт футбол + хоккей по дате
        args.dry_run = True  # ОБЯЗАТЕЛЬНО dry-run чтобы не писать в БД

    GLOBAL_ARGS = args

    # Wire hockey module dependencies (must be after resolve_stake_pct_and_meta is defined)
    from strategies.hockey import _set_dependencies
    _set_dependencies(compute_kelly, resolve_stake_pct_and_meta, lambda: GLOBAL_ARGS)

    backtest_results = []

    conn = get_conn()
    ensure_agent_schema(conn)
    ensure_handoff_decisions_table(conn)
    ensure_bankroll_state_table(conn)
    
    # Determine run mode
    run_mode = "backtest" if args.backtest else ("dry-run" if args.dry_run else "live")
    
    # Initialize decision tracking counters
    decision_stats = {
        "total": 0,
        "BET": 0,
        "SMALL": 0,
        "PASS": 0,
        "valid": 0,
        "invalid": 0
    }
    strategy_stats = defaultdict(init_strategy_row)

    # Load historical features for backtest mode
    historical_features = {}
    if args.backtest:
        historical_features = load_historical_features(conn)
        if historical_features:
            print(f"Loaded historical features for {len(historical_features)} matches")

    matches = (
        fetch_backtest_matches(conn, sport=args.sport, limit=args.limit, match_id=args.match_id)
        if args.backtest
        else fetch_upcoming_matches(conn, sport=args.sport, limit=args.limit, match_id=args.match_id)
    )
    if not matches:
        print("Нет матчей для backtest." if args.backtest else "Нет upcoming-матчей с коэффициентами.")
        return 0
    
    # Store matches for reference in other functions
    setattr(args, "_matches_cache", matches)
    
    # Validate pure-ba mode is only used with backtest
    if args.pure_ba and not args.backtest:
        print("ВНИМАНИЕ: --pure-ba работает только с --backtest. Игнорируется.")
        args.pure_ba = False

    preflight_skipped = 0
    llm_called = 0
    bets_made = 0
    pnl_log = []  # chronological PnL for drawdown calc
    rule_driven_bets = 0
    rule_driven_found = 0
    rule_driven_accepted = 0
    rule_driven_blocked_exposure = 0
    rule_driven_blocked_market_lock = 0
    btts_found = 0
    btts_accepted = 0
    btts_blocked_exposure = 0
    btts_blocked_market_lock = 0
    
    # Hockey stats
    hockey_matches_seen_all = 0
    hockey_matches_seen_khl = 0
    hockey_features_found_all = 0
    hockey_features_found_khl = 0
    defensive_wall_signals_all = 0
    defensive_wall_signals_khl = 0
    underdog_live_signals_all = 0
    underdog_live_signals_khl = 0
    intersection_signals_all = 0
    intersection_signals_khl = 0
    hockey_recommendations_all = 0
    hockey_recommendations_khl = 0
    hockey_bets_accepted_khl = 0
    hockey_bets_rejected_khl = 0
    
    # Throttle for live football recommendations (not in backtest)
    live_football_count = 0
    live_football_max = 3 if not args.backtest else 999999  # no limit in backtest
    
    # Track processed matches to avoid duplicates
    processed_matches = set()
    
    # Check if we've hit the daily limit for football recommendations
    # Only apply limit in production mode (not dry-run or backtest)
    if not args.backtest and args.sport == "football" and not args.dry_run:
        today = datetime.now().strftime("%Y-%m-%d")
        daily_count = conn.execute("""
            SELECT COUNT(*) FROM bets 
            WHERE created_at >= ? 
            AND created_by = 'agent_handoff_v7.py'
            AND match_id IN (SELECT id FROM matches WHERE sport = 'football')
        """, (f"{today} 00:00:00",)).fetchone()[0]
        
        if daily_count >= 5:  # Max 5 per day
            print(f"ВНИМАНИЕ: Достигнут дневной лимит футбольных рекомендаций ({daily_count}/5)")
            print("Выход. Используйте --dry-run для тестирования.")
            return 0

    for match in matches:
        match_key = f"{match.id}_{match.sport}"
        if match_key in processed_matches:
            print(f"SKIP: {match.home_team} — {match.away_team} | Уже обработан в этом запуске")
            continue
        
        # Check if league is allowed for this sport (before normalization)
        if not is_league_allowed(match.sport.lower(), match.league):
            print(f"SKIP: {match.home_team} — {match.away_team} | league not allowed by pipeline whitelist")
            continue

        # Normalize league name for backtest football AFTER whitelist check
        if args.backtest and getattr(match, "sport", "") == "football":
            try:
                match.league = normalize_rule_league_name(getattr(match, "league", ""))
            except Exception:
                pass
        
        processed_matches.add(match_key)
        
        # Process hockey matches separately
        if match.sport == "hockey":
            hockey_matches_seen_all += 1
            is_khl_regular = detect_league_key(match.league) == "KHL"
            if is_khl_regular:
                hockey_matches_seen_khl += 1
            
            # Check if league is allowed to run strategies
            league_key = detect_league_key(match.league)
            print(f"[LEAGUE DETECT] raw='{match.league}' -> key='{league_key}'")
            
            # Get league configuration
            league_config = HOCKEY_LEAGUE_CONFIG.get(league_key)
            
            # If no config or disabled mode, skip processing
            if not league_config or league_config.get("mode") == "disabled":
                # Create a minimal pass recommendation
                hockey_rec = {
                    "market": "pass",
                    "market_label": "PASS",
                    "decision": "PASS",
                    "signal_type": "DisabledLeague",
                    "auto_pass_reason": f"No enabled hockey strategy for league: {league_key or 'unknown'}"
                }
                valid = False
                notes = [f"League {league_key or 'unknown'} has no enabled strategies"]
                
                print(f"[SKIP LEAGUE] {league_key or 'unknown'} | {match.home_team} vs {match.away_team}")
                
                # Log the decision
                payload = build_payload(conn, match, bankroll=args.bankroll)
                save_handoff_decision(conn, match, payload, hockey_rec, valid, notes, run_mode)
                update_strategy_stats(strategy_stats, match, hockey_rec, valid, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)

                # Update decision stats
                decision_stats["total"] += 1
                decision_stats["PASS"] += 1
                decision_stats["invalid"] += 1
                continue  # Skip further processing for disabled leagues
        # Process hockey matches separately

            # Process based on league configuration mode
            if league_key == "KHL" and league_config.get("mode") == "intersection":
                print(f"[KHL INTERSECTION] {match.home_team} vs {match.away_team}")
                # KHL uses intersection of underdog_live and defensive_wall
                hockey_rec, hockey_debug = process_hockey_match(conn, match, args.bankroll)
            elif league_key == "CZECH" and league_config.get("mode") == "single":
                strategy = league_config.get("strategies", ["fp_or_fb"])[0]
                print(f"[CZECH {strategy.upper()}] {match.home_team} vs {match.away_team}")
                hockey_rec, hockey_debug = process_hockey_match(conn, match, args.bankroll)
            elif league_key == "NHL" and league_config and league_config.get("mode") == "single":
                print(f"[NHL DRAW_TIGHT] {match.home_team} vs {match.away_team}")
                hockey_rec, hockey_debug = process_hockey_match(conn, match, args.bankroll)
            elif league_key == "NLA" and league_config.get("mode") == "single":
                print(f"[NLA BERN_AWAY_DRAW] {match.home_team} vs {match.away_team}")
                hockey_rec, hockey_debug = process_hockey_match(conn, match, args.bankroll)
            elif league_key == "DEL" and league_config.get("mode") == "single":
                print(f"[DEL HOME_FORM5] {match.home_team} vs {match.away_team}")
                hockey_rec, hockey_debug = process_hockey_match(conn, match, args.bankroll)
            elif league_key == "SHL" and league_config.get("mode") == "single":
                print(f"[SHL SKELLEFTEA_HOME] {match.home_team} vs {match.away_team}")
                hockey_rec, hockey_debug = process_hockey_match(conn, match, args.bankroll)
            else:
                # Fallback - should not happen with proper configuration
                hockey_rec = None
                hockey_debug = {"failed_reason": f"Unsupported league mode: {league_config.get('mode') if league_config else 'no_config'}"}
            
            # Update counters based on debug info
            is_khl_regular = (league_key == "KHL")
            
            # Track features found - only count once per match
            if hockey_debug.get("features_found", False):
                hockey_features_found_all += 1
                if is_khl_regular:
                    hockey_features_found_khl += 1
            
            # Track strategy signals
            if hockey_debug.get("pick1_exists", False):
                underdog_live_signals_all += 1
                if is_khl_regular:
                    underdog_live_signals_khl += 1
                    
            if hockey_debug.get("pick2_exists", False):
                defensive_wall_signals_all += 1
                if is_khl_regular:
                    defensive_wall_signals_khl += 1
            
            # Track intersection signals
            if hockey_debug.get("markets_match", False) and hockey_debug.get("both_edges_positive", False):
                intersection_signals_all += 1
                if is_khl_regular:
                    intersection_signals_khl += 1
            
            if hockey_rec:
                hockey_recommendations_all += 1
                if is_khl_regular:
                    hockey_recommendations_khl += 1
                
                # For hockey, we use a lightweight validation instead of the full football pipeline
                # No calibration, no generic math enrichment, no standard validator
                payload = build_payload(conn, match, bankroll=args.bankroll)
                valid, notes = validate_hockey_recommendation(hockey_rec, match)
                
                # Print result
                print(f"[HOCKEY] {match.home_team} — {match.away_team} | {hockey_rec.get('market_label')} @ {hockey_rec.get('odds')}")
                print_result(match, hockey_rec, valid, notes, args.bankroll)
                
                # Log the decision
                save_handoff_decision(conn, match, payload, hockey_rec, valid, notes, run_mode)
                update_strategy_stats(strategy_stats, match, hockey_rec, valid, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)

                # Update decision stats
                decision_stats["total"] += 1
                decision_stats[hockey_rec.get("decision", "PASS")] += 1
                if valid:
                    decision_stats["valid"] += 1
                else:
                    decision_stats["invalid"] += 1
                # Сохраняем в backtest_results для --export-equity
                if args.backtest and valid:
                    _h_odds = float(hockey_rec.get("odds") or 0)
                    _h_stake = round(args.bankroll * float(hockey_rec.get("stake_pct", 0.01) or 0.01), 2)
                    _h_market = hockey_rec.get("market", "")
                    _h_actual = _get_actual_outcome(conn, match.id)
                    _h_win = (_h_actual == _h_market)
                    _h_profit = round(_h_stake * (_h_odds - 1), 2) if _h_win else -_h_stake
                    backtest_results.append({
                        "sport": "hockey",
                        "strategy": hockey_rec.get("rule") or hockey_rec.get("strategy_name") or hockey_rec.get("live_rule_family") or "unknown",
                        "match_date": str(match.match_date)[:10] if hasattr(match, "match_date") else "",
                        "home_team": match.home_team if hasattr(match, "home_team") else "",
                        "away_team": match.away_team if hasattr(match, "away_team") else "",
                        "market": _h_market,
                        "odds": _h_odds,
                        "stake": _h_stake,
                        "profit": _h_profit,
                        "result": "won" if _h_win else "lost",
                        "actual_outcome": _h_actual,
                    })
                
                # Save recommendation if valid
                if valid and not args.backtest:
                    if not args.dry_run:
                        save_recommendation(conn, match, payload, hockey_rec, valid, notes, args.bankroll, args.dry_run)
                    bets_made += 1
                    if is_khl_regular:
                        hockey_bets_accepted_khl += 1
                    # Log PnL for monthly report
                    if args.backtest:
                        _actual = resolve_actual_market_from_match(match, hockey_rec)
                        _market_h = hockey_rec.get("market")
                        _odds_h = float(hockey_rec.get("odds") or 0)
                        _stake_h = float(hockey_rec.get("stake") or (hockey_rec.get("stake_pct", 0.01) * args.bankroll))
                        _raw_date = str(match.match_date)
                        if len(_raw_date) >= 7 and _raw_date[4:5] == '-':
                            _mdate = _raw_date[:7]
                        elif len(_raw_date) >= 10 and _raw_date[2:3] == '.':
                            _mdate = _raw_date[6:10] + '-' + _raw_date[3:5]
                        else:
                            _mdate = _raw_date[:7]
                        if _actual and _market_h == _actual:
                            pnl_log.append((_mdate, _stake_h * (_odds_h - 1)))
                        elif _actual:
                            pnl_log.append((_mdate, -_stake_h))
                else:
                    if is_khl_regular:
                        hockey_bets_rejected_khl += 1
            else:
                # Print failure reason if available
                failed_reason = hockey_debug.get("failed_reason", "Unknown reason")
                if not args.dry_run:  # In dry-run mode, debug output is already handled in process_hockey_match
                    if hockey_debug.get("features_found", False):
                        print(f"HOCKEY PASS: {match.home_team} — {match.away_team} | {failed_reason}")
                    else:
                        print(f"HOCKEY PASS: {match.home_team} — {match.away_team} | No hockey features")
            
            # Skip LLM for hockey
            continue
        
        payload = build_payload(conn, match, bankroll=args.bankroll)
        
        # Use historical features if available in backtest mode
        if args.backtest:
            try:
                match_id_int = int(match.id)
                if match_id_int in historical_features:
                    # Backtest must use historical snapshot as the source of truth
                    payload["known_facts"] = historical_features[match_id_int]
                    payload["using_historical_features"] = True
                    setattr(match, "using_historical_features", True)
                    print(f"Using historical features for match {match_id_int}: {match.home_team} vs {match.away_team}")
            except (ValueError, TypeError):
                pass

        facts = normalize_known_facts_for_rules(payload.get("known_facts", {}) or {})
        payload["known_facts"] = facts
        data_quality = get_match_data_quality(conn, match.id)

        # BA shortlist — backtest-approved rules get a bypass through pre-flight
        ba_ok, ba_rule = is_backtest_approved(match, facts)
        live_skip_reason = pre_flight_check(facts, match.sport)
        live_ok = live_skip_reason is None

        setattr(match, "is_backtest_approved", ba_ok)
        setattr(match, "ba_rule", ba_rule)
        if ba_ok and live_ok:
            setattr(match, "shortlist_source", "live+ba")
        elif ba_ok:
            setattr(match, "shortlist_source", "ba")
        else:
            setattr(match, "shortlist_source", "live")

        payload["is_backtest_approved"] = ba_ok
        payload["ba_rule"] = ba_rule
        payload["shortlist_source"] = getattr(match, "shortlist_source", "live")
        # In football backtest, prefer persisted match_facts for rule-driven logic,
        # but merge with historical snapshot so empty fields do not kill rule detection.
        if args.backtest and match.sport == "football":
            bt_match_facts = _load_match_facts(conn, match.id) or {}
            facts = merge_known_facts(bt_match_facts, facts)
            payload["known_facts"] = facts
        
        # For football, first check pruned rules in both live and backtest
        rule_rec = None
        if match.sport == "football":
            rule_name, market = get_pruned_live_rule(match, facts, conn)
            if rule_name and market:
                print(f"[{market.upper()}_CANDIDATE] {match.home_team} — {match.away_team} | Rule: {rule_name}")
                
                # Count rule-driven and BTTS candidates found
                is_btts = market.startswith("btts_")
                rule_driven_found += 1
                if is_btts:
                    btts_found += 1
                
                # Check if we've hit the throttle limit
                if live_football_count >= live_football_max:
                    print(f"THROTTLE: {match.home_team} — {match.away_team} | [LIVE_RULE:{rule_name}] | Достигнут лимит {live_football_max} рекомендаций за запуск")
                    continue
                
                # Check for market family lock
                market_family = get_market_family(market)
                if has_active_market_exposure(conn, match.id, market_family):
                    print(f"[MARKET_LOCK][{market_family}] {match.home_team} — {match.away_team} | Rule: {rule_name}")
                    if is_btts:
                        btts_blocked_market_lock += 1
                    else:
                        rule_driven_blocked_market_lock += 1
                    continue
                
                # Build rule-driven recommendation
                rule_rec = build_rule_recommendation(match, facts, rule_name, market, args.bankroll)
                
                # Store original probability before calibration for BTTS debug
                original_prob = rule_rec.get("our_probability")
                
                # Стратегии на чистых коэфах не нуждаются в калибровке
                _no_calib = {"RPL_OVER25_BTTS", "PD_BTTS_DOUBLE", "FL1_BTTS_DOUBLE", "NLA_BERN_AWAY_DRAW", "SA_AWAY_DRAW", "SUMMER_BTTS_HOME", "MLS_BTTS_HOME", "ECU_BTTS_NO"}
                if rule_name not in _no_calib:
                    rule_rec = calibrate_probability(rule_rec, match, facts, data_quality)
                rule_rec = enrich_with_math(rule_rec, match, facts)
                
                # Add original probability to debug info for BTTS
                if market.startswith("btts_") and "debug_info" in rule_rec:
                    rule_rec["debug_info"]["our_p_raw"] = original_prob
                
                if rule_rec.get("market") != "pass":
                    # Rolling xG BTTS filter — LIVE mode only (no lookahead bias)
                    _live_league_raw = normalize_rule_league_name(getattr(match, "league", "")).lower()
                    _is_bl1_live = "бундеслига" in _live_league_raw or "bundesliga" in _live_league_raw
                    _is_epl_live = "англи" in _live_league_raw or "premier" in _live_league_raw
                    _league_key = "BL1" if _is_bl1_live else ("EPL" if _is_epl_live else None)
                    is_roll_btts = (
                        rule_name == "BTTS_YES_CORE"
                        and not args.backtest
                        and _league_key is not None
                    )
                    if is_roll_btts:
                        from team_name_mapping import map_team
                        ROLL_XG = {"BL1": {"league_rus": "Футбол. Германия. Бундеслига.", "conv_h": 0.322, "conv_a": 0.323, "thr": 3.0},
                                   "EPL": {"league_rus": "Футбол. Англия. Премьер-лига.", "conv_h": 0.277, "conv_a": 0.288, "thr": 2.8}}
                        cfg = ROLL_XG.get(_league_key)
                        if cfg:
                            home_rus = map_team(match.home_team, _league_key)
                            away_rus = map_team(match.away_team, _league_key)
                            match_date_val = str(match.match_date)[:10]
                            try:
                                h_rows = conn.execute("""
                                    SELECT shots_home FROM backtest_football_stats
                                    WHERE league = ? AND home_team = ?
                                      AND shots_home IS NOT NULL
                                      AND match_date < ?
                                    ORDER BY match_date DESC LIMIT 5
                                """, (cfg["league_rus"], home_rus, match_date_val)).fetchall()
                                a_rows = conn.execute("""
                                    SELECT shots_away FROM backtest_football_stats
                                    WHERE league = ? AND away_team = ?
                                      AND shots_away IS NOT NULL
                                      AND match_date < ?
                                    ORDER BY match_date DESC LIMIT 5
                                """, (cfg["league_rus"], away_rus, match_date_val)).fetchall()
                            except Exception:
                                h_rows, a_rows = [], []

                            if len(h_rows) >= 3 and len(a_rows) >= 3:
                                xg_home_roll = (sum(r[0] for r in h_rows) / len(h_rows)) * cfg["conv_h"]
                                xg_away_roll = (sum(r[0] for r in a_rows) / len(a_rows)) * cfg["conv_a"]
                                xg_sum = xg_home_roll + xg_away_roll
                                rule_rec["xg_home_roll"] = round(xg_home_roll, 2)
                                rule_rec["xg_away_roll"] = round(xg_away_roll, 2)
                                rule_rec["xg_roll_sum"] = round(xg_sum, 2)
                                if xg_sum < cfg["thr"]:
                                    print(f"[XG_ROLL] {match.home_team} ({home_rus}) — {match.away_team} ({away_rus}) | "
                                          f"xg_home={xg_home_roll:.2f} xg_away={xg_away_roll:.2f} "
                                          f"sum={xg_sum:.2f} < {cfg['thr']} → PASS")
                                    save_handoff_decision(conn, match, payload, rule_rec, False,
                                                          [f"Rolling xG filter: {xg_sum:.2f} < {cfg['thr']}"], run_mode)
                                    update_strategy_stats(strategy_stats, match, rule_rec, False, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)
                                    decision_stats["total"] += 1
                                    decision_stats["PASS"] += 1
                                    decision_stats["invalid"] += 1
                                    continue
                                print(f"[XG_ROLL] {match.home_team} ({home_rus}) — {match.away_team} ({away_rus}) | "
                                      f"xg_home={xg_home_roll:.2f} xg_away={xg_away_roll:.2f} "
                                      f"sum={xg_sum:.2f} >= {cfg['thr']} → BET")
                            else:
                                print(f"[XG_ROLL_NODATA] {match.home_team} — {match.away_team} | "
                                      f"home_hist={len(h_rows)} away_hist={len(a_rows)} → fail-safe allow")

                    valid, notes = validate_recommendation(rule_rec, payload, args.bankroll)
                    # Apply hard validator gate
                    rule_rec = enforce_validator_gate(rule_rec, valid, notes)

                    if not valid:
                        print(f"[RULE_REJECTED] {match.home_team} — {match.away_team} | Rule: {rule_name}")
                    else:
                        print(f"[LIVE_RULE:{rule_name}] {match.home_team} — {match.away_team}")
                    
                    print_result(match, rule_rec, valid, notes, args.bankroll)
                    
                    # Log the decision
                    save_handoff_decision(conn, match, payload, rule_rec, valid, notes, run_mode)
                    update_strategy_stats(strategy_stats, match, rule_rec, valid, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)

                    # Update decision stats
                    decision_stats["total"] += 1
                    decision_stats[rule_rec.get("decision", "PASS")] += 1
                    if valid:
                        decision_stats["valid"] += 1
                    else:
                        decision_stats["invalid"] += 1
                    
                    if valid:
                        live_football_count += 1
                        rule_driven_bets += 1
                        rule_driven_accepted += 1
                        bets_made += 1
                        # Log PnL for global drawdown
                        if args.backtest:
                            actual = resolve_actual_market_from_match(match, rule_rec)
                            odds_val = float(rule_rec.get("odds") or 0)
                            stake_val = float(rule_rec.get("stake") or (rule_rec.get("stake_pct",0)*args.bankroll))
                            _raw_date = str(match.match_date)
                            if len(_raw_date) >= 7 and _raw_date[4:5] == '-':
                                _match_date = _raw_date[:7]
                            elif len(_raw_date) >= 10 and _raw_date[2:3] == '.':
                                _match_date = _raw_date[6:10] + '-' + _raw_date[3:5]
                            else:
                                _match_date = _raw_date[:7]
                            if actual and market == actual:
                                pnl_log.append((_match_date, stake_val * (odds_val - 1)))
                            elif actual:
                                pnl_log.append((_match_date, -stake_val))
                        if args.backtest:
                            _f_odds = float(rule_rec.get("odds") or 0)
                            _f_stake = float(rule_rec.get("stake") or (float(rule_rec.get("stake_pct", 0.01) or 0.01) * args.bankroll))
                            _f_market = rule_rec.get("market", "")
                            _f_actual = resolve_actual_market_from_match(match, rule_rec)
                            _f_win = (_f_actual == _f_market)
                            _f_profit = round(_f_stake * (_f_odds - 1), 2) if _f_win else -_f_stake
                            backtest_results.append({
                                "sport": "football",
                                "strategy": rule_rec.get("rule") or rule_rec.get("live_rule_family") or rule_rec.get("strategy_name") or "unknown",
                                "match_date": str(match.match_date)[:10] if hasattr(match, "match_date") else "",
                                "home_team": match.home_team if hasattr(match, "home_team") else "",
                                "away_team": match.away_team if hasattr(match, "away_team") else "",
                                "market": _f_market,
                                "odds": _f_odds,
                                "stake": _f_stake,
                                "profit": _f_profit,
                                "result": "won" if _f_win else "lost",
                            })
                        if is_btts:
                            btts_accepted += 1
                        if not args.backtest:
                            save_recommendation(conn, match, payload, rule_rec, valid, notes, args.bankroll, args.dry_run)
                    elif rule_rec.get("validator_rejected") and any("экспозиция превысит" in note for note in notes):
                        # Count exposure blocks
                        if is_btts:
                            btts_blocked_exposure += 1
                        else:
                            rule_driven_blocked_exposure += 1
                    continue
                else:
                    reason = rule_rec.get('auto_pass_reason', 'Не прошел математику')
                    debug_info = rule_rec.get("debug_info", {})
                    
                    # Log the PASS decision
                    save_handoff_decision(conn, match, payload, rule_rec, False, [reason], run_mode)
                    update_strategy_stats(strategy_stats, match, rule_rec, False, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)

                    # Update decision stats
                    decision_stats["total"] += 1
                    decision_stats["PASS"] += 1
                    decision_stats["invalid"] += 1

                    # Add detailed debug for BTTS rule pass
                    if is_btts and debug_info:
                        btts_debug = (f"odds={debug_info.get('odds', 0):.2f} | "
                                     f"market_p={debug_info.get('market_p', 0):.4f} | "
                                     f"our_p={debug_info.get('our_p', 0):.4f} | "
                                     f"threshold=+{debug_info.get('threshold', 0):.3f} | "
                                     f"required={debug_info.get('threshold_value', 0):.4f}")
                        print(f"RULE PASS: {match.home_team} — {match.away_team} | [LIVE_RULE:{rule_name}] | {reason}")
                        print(f"BTTS DEBUG: {btts_debug}")
                    else:
                        print(f"RULE PASS: {match.home_team} — {match.away_team} | [LIVE_RULE:{rule_name}] | {reason}")

        # Pre-flight фильтр — BA match bypasses the skip
        skip_reason = live_skip_reason
        if skip_reason and not ba_ok:
            print(f"SKIP: {match.home_team} — {match.away_team}{_ba_tag(match)} | {skip_reason}")
            
            # Create a minimal recommendation for logging
            skip_rec = {
                "market": "pass",
                "market_label": "PASS",
                "decision": "PASS",
                "signal_type": "Pass",
                "market_error": skip_reason,
                "auto_pass_reason": skip_reason
            }
            
            # Log the pre-flight skip
            save_handoff_decision(conn, match, payload, skip_rec, False, [skip_reason], run_mode)
            update_strategy_stats(strategy_stats, match, skip_rec, False, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)

            # Update decision stats
            decision_stats["total"] += 1
            decision_stats["PASS"] += 1
            decision_stats["invalid"] += 1

            preflight_skipped += 1
            continue

            # LLM / heuristic fallback
        # При --no-llm + --disable-shadow для football — всегда PASS
        # (rule-driven уже отработал выше и сделал continue если нашёл match)
        if args.no_llm and getattr(args, "disable_shadow", False):
            rec = {
                "market": "pass",
                "market_label": "PASS",
                "decision": "PASS",
                "signal_type": "Pass",
                "auto_pass_reason": "no-llm + disable-shadow: no rule matched",
                "market_error": "no-llm + disable-shadow: no rule matched",
                "rule_driven": False,
                "live_rule_family": None,
                "strategy_family": "no_llm_disabled",
            }
        elif args.no_llm:
            rec = normalize_response(simulate_llm_response(payload))
        else:
            # LLM DISABLED
            continue

        if rec.get("decision") == "PASS":
            reason = rec.get("market_error") or rec.get("market_error_summary", "")
            print(f"PASS: {match.home_team} — {match.away_team}{_ba_tag(match)} | {reason}")
            
            # Log the LLM PASS decision
            save_handoff_decision(conn, match, payload, rec, False, [reason], run_mode)
            update_strategy_stats(strategy_stats, match, rec, False, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)

            # Update decision stats
            decision_stats["total"] += 1
            decision_stats["PASS"] += 1
            decision_stats["invalid"] += 1

            continue

        # Калибровка → математика
        rec = calibrate_probability(rec, match, facts, data_quality)
        rec = enrich_with_math(rec, match, facts)

        # Hard gate: shadow/heuristic must never become final betting source
        if getattr(args, "disable_shadow", False) and is_shadow_recommendation(rec):
            rec = {
                **rec,
                "market": "pass",
                "market_label": "PASS",
                "decision": "PASS",
                "signal_type": "Pass",
                "auto_pass_reason": "Shadow/heuristic path disabled by --disable-shadow",
            }

        if rec.get("market") == "pass":
            reason = rec.get("auto_pass_reason") or rec.get("market_error", "")
            adj = rec.get("probability_adjustments", [])
            adj_str = f" [{', '.join(adj)}]" if adj else ""
            print(f"PASS: {match.home_team} — {match.away_team}{_ba_tag(match)} | {reason}{adj_str}")
            
            # Log the math-rejected decision
            notes = [reason]
            if adj:
                notes.append(f"Adjustments: {', '.join(adj)}")
            save_handoff_decision(conn, match, payload, rec, False, notes, run_mode)
            update_strategy_stats(strategy_stats, match, rec, False, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)

            # Update decision stats
            decision_stats["total"] += 1
            decision_stats["PASS"] += 1
            decision_stats["invalid"] += 1

            continue

        valid, notes = validate_recommendation(rec, payload, args.bankroll)
        
        # Track rule-driven candidates before validator gate
        is_rule_driven = rec.get("rule_driven", False)
        is_btts = rec.get("market", "").startswith("btts_")
        
        # Count rule-driven candidates found
        if is_rule_driven:
            rule_driven_found += 1
            if is_btts:
                btts_found += 1
        
        # Apply hard validator gate
        rec = enforce_validator_gate(rec, valid, notes)
        
        # Check for various dry-run overrides
        btts_override = args.dry_run and rec.get("dry_run_btts_override", False)
        rule_override = args.dry_run and rec.get("dry_run_rule_override", False)
        exposure_override = args.dry_run and rec.get("dry_run_exposure_override", False)
        any_override = btts_override or rule_override or exposure_override
        
        # Handle rejection and override messages
        if not valid and not any_override:
            rule_family = rec.get("live_rule_family", "")
            rule_tag = f" | Rule: {rule_family}" if rule_family else ""
            print(f"[RULE_REJECTED] {match.home_team} — {match.away_team}{rule_tag}")
        elif btts_override:
            print(f"[BTTS_DRY_RUN_OVERRIDE] {match.home_team} — {match.away_team} | {rec.get('override_reason', '')}")
        elif rule_override:
            print(f"[RULE_DRY_RUN_OVERRIDE] {match.home_team} — {match.away_team} | {rec.get('override_reason', '')}")
        elif exposure_override:
            print(f"[DRYRUN_EXPOSURE_BLOCK] {match.home_team} — {match.away_team} | {rec.get('override_reason', '')}")
            
        print_result(match, rec, valid or any_override, notes, args.bankroll)

        # Log the final decision
        save_handoff_decision(conn, match, payload, rec, valid, notes, run_mode)
        update_strategy_stats(strategy_stats, match, rec, valid, bankroll=args.bankroll, detect_league_key_fn=detect_league_key)

        # Update decision stats
        decision_stats["total"] += 1
        decision_stats[rec.get("decision", "PASS")] += 1
        if valid:
            decision_stats["valid"] += 1
        else:
            decision_stats["invalid"] += 1

        if args.backtest and valid and rec.get("decision") == "BET":
            _actual_outcome = _get_actual_outcome(conn, match.id)
            _stake_abs = round(args.bankroll * float(rec.get("stake_pct", 0.0) or 0.0), 2)
            _odds_val = float(rec.get("odds") or 0)
            _is_win = (_actual_outcome == rec.get("market"))
            _profit = round(_stake_abs * (_odds_val - 1), 2) if _is_win else -_stake_abs
            backtest_results.append({
                "match_id": match.id,
                "sport": match.sport if hasattr(match, "sport") else args.sport,
                "strategy": rec.get("rule") or rec.get("live_rule_family") or rec.get("strategy_name") or "unknown",
                "match_date": str(match.match_date)[:10] if hasattr(match, "match_date") else "",
                "home_team": match.home_team if hasattr(match, "home_team") else "",
                "away_team": match.away_team if hasattr(match, "away_team") else "",
                "market": rec.get("market"),
                "odds": _odds_val,
                "stake": _stake_abs,
                "profit": _profit,
                "result": "won" if _is_win else "lost",
                "actual_outcome": _actual_outcome,
            })
        else:
            # Only save if valid or in backtest mode (or override in dry-run for analysis)
            if valid or any_override:
                # For overrides in dry-run, we don't actually save to DB
                if any_override:
                    override_type = "BTTS" if btts_override else "RULE" if rule_override else "EXPOSURE"
                    print(f"[{override_type}_DRY_RUN_OVERRIDE] Не сохраняем в БД, только для анализа")
                else:
                    save_recommendation(conn, match, payload, rec, valid, notes, args.bankroll, args.dry_run)

        # Count accepted bets and track rule-driven stats
        if valid and is_rule_driven:
            rule_driven_accepted += 1
            if is_btts:
                btts_accepted += 1
        elif any_override and is_rule_driven:
            rule_driven_blocked_exposure += 1
            if is_btts:
                btts_blocked_exposure += 1
            
        # Only count as bet if valid and not shadow-only (or override in dry-run)
        if (valid or any_override) and not rec.get("shadow_only", False):
            bets_made += 1

    if args.backtest:
        print_backtest_summary(backtest_results, args.bankroll)
        if getattr(args, "export_equity", False) and backtest_results:
            _save_equity(conn, backtest_results)

    conn.close()

    print(f"\n{'='*80}")
    print(f"Итог: матчей={len(matches)} | pre-flight SKIP={preflight_skipped} | "
          f"LLM вызовов={llm_called} | BET={bets_made}")
    print(f"RULE_DRIVEN: найдено={rule_driven_found} | принято={rule_driven_accepted} | "
          f"блок по экспозиции={rule_driven_blocked_exposure} | блок по MARKET_LOCK={rule_driven_blocked_market_lock}")
    print(f"BTTS: найдено={btts_found} | принято={btts_accepted} | "
          f"блок по экспозиции={btts_blocked_exposure} | блок по MARKET_LOCK={btts_blocked_market_lock}")
    print(f"HOCKEY ALL: матчей={hockey_matches_seen_all} | с фичами={hockey_features_found_all} | "
          f"defensive_wall={defensive_wall_signals_all} | underdog_live={underdog_live_signals_all} | "
          f"intersection={intersection_signals_all} | рекомендаций={hockey_recommendations_all}")
    print(f"HOCKEY KHL: матчей={hockey_matches_seen_khl} | с фичами={hockey_features_found_khl} | "
          f"defensive_wall={defensive_wall_signals_khl} | underdog_live={underdog_live_signals_khl} | "
          f"intersection={intersection_signals_khl} | рекомендаций={hockey_recommendations_khl} | "
          f"принято={hockey_bets_accepted_khl} | отклонено={hockey_bets_rejected_khl}")
    
    # Print decision statistics
    print(f"\nРЕШЕНИЯ: всего={decision_stats['total']} | "
          f"BET={decision_stats['BET']} | SMALL={decision_stats['SMALL']} | PASS={decision_stats['PASS']} | "
          f"valid={decision_stats['valid']} | invalid={decision_stats['invalid']}")
    # Print overall backtest summary with cashflow
    if args.backtest:
        all_staked = sum(r["stake_sum"] for r in strategy_stats.values())
        all_profit = sum(r["profit"] for r in strategy_stats.values())
        all_won = sum(r["won"] for r in strategy_stats.values())
        all_scored = sum(r["scored"] for r in strategy_stats.values())
        roi = all_profit / all_staked * 100 if all_staked > 0 else 0
        hit = all_won / all_scored * 100 if all_scored > 0 else 0
        start_bank = args.bankroll
        end_bank = start_bank + all_profit
        growth = (end_bank - start_bank) / start_bank * 100
        # Global lossstreak and drawdown across all strategies
        global_max_ls = max((r["max_loss_streak"] for r in strategy_stats.values()), default=0)
        global_max_ws = max((r["max_win_streak"] for r in strategy_stats.values()), default=0)
        # Simulate bank curve for global drawdown
        bank = start_bank
        peak_bank = start_bank
        max_dd_abs = 0.0
        max_dd_pct = 0.0
        # Collect all bets ordered by strategy then sequential
        # We track equity per strategy and sum them
        all_equity = sum(r["equity"] for r in strategy_stats.values())
        all_max_dd = max((r["max_drawdown_abs"] for r in strategy_stats.values()), default=0)
        all_max_dd_pct = max((r["max_drawdown_pct"] for r in strategy_stats.values()), default=0)

        # Global drawdown from pnl_log
        if pnl_log:
            _peak = 0.0; _cur = 0.0; _gdd = 0.0
            monthly = {}
            for _entry in pnl_log:
                if isinstance(_entry, tuple):
                    _month, _p = _entry
                else:
                    _month, _p = "unknown", _entry
                _cur += _p
                if _cur > _peak: _peak = _cur
                if (_peak - _cur) > _gdd: _gdd = _peak - _cur
                if _month not in monthly:
                    monthly[_month] = {"n": 0, "w": 0, "profit": 0.0}
                monthly[_month]["n"] += 1
                monthly[_month]["profit"] += _p
                if _p > 0: monthly[_month]["w"] += 1
            all_max_dd = _gdd
            all_max_dd_pct = (_gdd / args.bankroll * 100) if args.bankroll else 0
        icon = "✅" if roi >= 4 else ("⚠️" if roi >= 0 else "❌")
        print(f"\n{'='*80}")
        print(f"ОБЩИЙ ИТОГ БЭКТЕСТА")
        print(f"  Матчей проанализировано: {len(matches)}")
        print(f"  Ставок размещено: {all_scored} | W:{all_won} L:{all_scored-all_won} | Hit:{hit:.1f}%")
        print(f"  Поставлено: {all_staked:,.0f} руб")
        print(f"  Прибыль: {all_profit:+,.0f} руб")
        print(f"  {icon} ROI: {roi:+.2f}%")
        print(f"  БАНК: {start_bank:,.0f} → {end_bank:,.0f} руб ({growth:+.1f}%)")
        print(f"  Макс. серия поражений: {global_max_ls} | Макс. серия побед: {global_max_ws}")
        # Месячный отчёт
        if pnl_log and monthly:
            print(f"\n{'='*70}")
            print(f"ОТЧЁТ ПО МЕСЯЦАМ")
            print(f"{'='*70}")
            bank_m = args.bankroll
            print(f"  {'Месяц':<10} {'n':>5} {'WR':>7} {'Прибыль':>12} {'Банк':>12} {'ROI%':>8}")
            print(f"  {'-'*60}")
            total_months = 0
            total_profit_all = 0
            first_bank = args.bankroll
            for _m in sorted(monthly.keys()):
                _d = monthly[_m]
                _wr = _d['w']/_d['n']*100 if _d['n'] else 0
                # ROI = прибыль / поставлено (примерно stake*n)
                _avg_stake = abs(_d['profit']) / _d['n'] if _d['n'] and _d['profit'] != 0 else 750
                _staked_m = _d['n'] * _avg_stake * 1.5  # приближение
                _roi = _d['profit'] / bank_m * 100  # % от текущего банка
                bank_m += _d['profit']
                total_months += 1
                total_profit_all += _d['profit']
                _icon = "✅" if _d['profit'] > 0 else "❌"
                print(f"  {_icon} {_m:<10} {_d['n']:>5} {_wr:>6.1f}% {_d['profit']:>+12,.0f} {bank_m:>12,.0f} {_roi:>+7.1f}%")
            # Итоговая статистика
            if total_months > 0:
                total_years = total_months / 12
                annual_roi = ((bank_m / first_bank) ** (1 / total_years) - 1) * 100
                monthly_avg = total_profit_all / total_months
                print(f"  {'='*60}")
                print(f"  Период: {total_months} мес ({total_years:.1f} лет)")
                print(f"  Средняя прибыль/мес: {monthly_avg:+,.0f} руб")
                print(f"  Доходность годовых (CAGR): {annual_roi:+.1f}%")
                print(f"  Итоговый банк: {bank_m:,.0f} руб (+{(bank_m/first_bank-1)*100:.1f}%)")
        print(f"  Макс. просадка (по стратегии): {all_max_dd:,.0f} руб ({all_max_dd_pct:.1f}%)")
        print(f"{'='*80}\n")
    print_strategy_summary(strategy_stats, backtest=args.backtest)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
