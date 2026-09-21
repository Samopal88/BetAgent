#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — validator.py

Проверка рекомендаций агента по BETAGENT v2.2.
Используется из agent_handoff.py
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

RULES_VERSION = "v2.2"

def compute_ev(probability: float, odds: float) -> float:
    return (probability * odds) - 1.0

def compute_kelly(probability: float, odds: float) -> float:
    # Kelly = (p*o - 1) / (o - 1)
    if odds <= 1.0:
        return -1.0
    return ((probability * odds) - 1.0) / (odds - 1.0)

def confidence_cap_pct(confidence: int) -> float:
    caps = {
        1: 0.00,
        2: 0.01,
        3: 0.02,
        4: 0.03,
        5: 0.04,
        6: 0.05,
        7: 0.07,
        8: 0.08,
        9: 0.09,
        10: 0.10,
    }
    return caps.get(int(confidence), 0.0)

def classify_signal(
    lineup_data_available: bool,
    confirmed_facts_count: int,
) -> str:
    if confirmed_facts_count <= 0:
        return "Pass"
    if lineup_data_available and confirmed_facts_count >= 2:
        return "Strong"
    if confirmed_facts_count >= 1:
        return "Medium"
    return "Weak"

def is_odds_allowed(
    odds: float,
    signal_type: str,
    ev: float,
) -> Tuple[bool, str]:
    if odds < 1.50:
        return False, "Коэффициент ниже 1.50: абсолютный запрет"
    if 1.50 <= odds < 1.55:
        if signal_type != "Strong" or ev <= 0.05:
            return False, "Зона 1.50–1.54 требует Strong edge + EV > 5%"
    return True, "ok"

def validate_recommendation(
    recommendation: Dict[str, Any],
    payload: Dict[str, Any],
    bankroll: float,
) -> Tuple[bool, List[str]]:
    notes: List[str] = []
    decision = recommendation.get("decision", "PASS")
    market = recommendation.get("market", "pass")

    if market == "pass" or decision == "PASS":
        notes.append("Агент сам пометил матч как PASS")
        return False, notes

    odds = float(recommendation["odds"])
    market_p = float(recommendation["market_probability"])
    our_p = float(recommendation["our_probability"])
    ev = float(recommendation["ev"])
    signal_type = str(recommendation.get("signal_type", "Pass"))
    confidence = int(recommendation.get("confidence", 0))
    lineup_data_available = bool(recommendation.get("lineup_data_available", False))
    confirmed_facts = recommendation.get("confirmed_facts", []) or []

    # EV recompute
    ev_check = compute_ev(our_p, odds)
    if abs(ev_check - ev) > 1e-4:
        notes.append(f"EV исправлен validator: {ev} -> {ev_check:.4f}")
        recommendation["ev"] = ev_check
        ev = ev_check

    # Kelly recompute
    kelly_check = compute_kelly(our_p, odds)
    recommendation["kelly"] = kelly_check
    recommendation["kelly_quarter"] = max(0.0, kelly_check * 0.25)
    recommendation["confidence_cap"] = confidence_cap_pct(confidence)
    recommendation["stake_pct"] = min(
        recommendation["kelly_quarter"],
        recommendation["confidence_cap"],
        0.10,
    )

    # Mandatory filters
    if ev < 0.03:
        notes.append("EV < 0.03")
        return False, notes

    if kelly_check <= 0:
        notes.append("Kelly <= 0")
        return False, notes

    odds_ok, odds_note = is_odds_allowed(odds, signal_type, ev)
    if not odds_ok:
        notes.append(odds_note)
        return False, notes

    if payload["open_exposure_pct"] + recommendation["stake_pct"] > 0.50:
        notes.append("Открытая экспозиция превысит 50%")
        return False, notes

    if payload["loss_streak_72h_same_sport"] >= 3:
        recommendation["stake_pct"] = recommendation["stake_pct"] / 2.0
        notes.append("Серия 3 проигрыша подряд за 72ч в этом виде спорта: размер ставки уменьшен в 2 раза")

    if not recommendation.get("market_error"):
        notes.append("Нет ответа, где ошибка рынка")
        return False, notes

    if not confirmed_facts:
        notes.append("Нет подтверждённых фактов")
        return False, notes

    if not lineup_data_available and signal_type == "Strong":
        notes.append("Без данных по составам Strong невозможен")
        return False, notes

    # Optional consistency checks
    inferred = classify_signal(lineup_data_available, len(confirmed_facts))
    if signal_type == "Pass":
        notes.append("Сигнал Pass нельзя отправлять как ставку")
        return False, notes

    if signal_type == "Strong" and inferred != "Strong":
        notes.append(f"Signal downgraded by validator: {signal_type} -> {inferred}")
        recommendation["signal_type"] = inferred

    if confidence_cap_pct(confidence) <= 0:
        notes.append("Confidence cap <= 0")
        return False, notes

    notes.append("VALID")
    return True, notes
