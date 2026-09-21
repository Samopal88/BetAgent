#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
BETAGENT — DUAL AGENT SHADOW RUNNER V1

Задача:
- не ставить реальные деньги
- не слать в Telegram
- прогонять одну и ту же текущую линию через 2 агента:
  1) OLD  = текущий agent_handoff_v7
  2) NEW  = smart baseline (football safe/plus) + validator без LLM

Итог:
- оба пишут свои рекомендации в shadow_recommendations
- через 1–2 недели можно сравнить:
    * сколько сигналов дал каждый
    * какой hit rate / ROI после расчёта результатов
    * где old режет edge, а где new ловит мусор

Запуск:
  python dual_agent_shadow_runner_v1.py --sport football --limit 20 --mode safe
  python dual_agent_shadow_runner_v1.py --sport football --limit 20 --mode plus
  python dual_agent_shadow_runner_v1.py --sport hockey --limit 20 --mode safe

По умолчанию:
- old агент работает для всех спортов
- new агент пока полноценно реализован только для football
- для остальных видов спорта new пишет PASS/UNSUPPORTED
"""

from __future__ import annotations
import os
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(os.getenv("BETAGENT_DB_PATH", os.getenv("BETAGENT_DB", "betagent.db")))
DEFAULT_BANK = float(os.getenv("BETAGENT_BANK", "100000"))

import agent_handoff_v7 as old_agent
from validator import validate_recommendation


# ============================================================
# SHADOW TABLE
# ============================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_shadow_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shadow_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            mode TEXT NOT NULL,
            match_id INTEGER NOT NULL,
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
            stake_pct REAL,
            confidence INTEGER,
            signal_type TEXT,
            decision TEXT,
            valid INTEGER,
            notes TEXT,
            market_error TEXT,
            payload_json TEXT,
            recommendation_json TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_shadow_agent_match
        ON shadow_recommendations(agent_name, match_id, created_at)
    """)
    conn.commit()


def save_shadow(conn, agent_name: str, mode: str, match, payload, rec, valid: bool, notes: list[str]):
    conn.execute("""
        INSERT INTO shadow_recommendations (
            created_at, agent_name, mode, match_id, sport, league, home_team, away_team, match_date,
            market, market_label, odds, our_probability, market_probability, ev, stake_pct,
            confidence, signal_type, decision, valid, notes, market_error,
            payload_json, recommendation_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        agent_name,
        mode,
        match.id,
        match.sport,
        match.league,
        match.home_team,
        match.away_team,
        match.match_date,
        rec.get("market"),
        rec.get("market_label"),
        rec.get("odds"),
        rec.get("our_probability"),
        rec.get("market_probability"),
        rec.get("ev"),
        rec.get("stake_pct"),
        rec.get("confidence"),
        rec.get("signal_type"),
        rec.get("decision"),
        1 if valid else 0,
        " | ".join(notes or []),
        rec.get("market_error"),
        json.dumps(payload, ensure_ascii=False),
        json.dumps(rec, ensure_ascii=False),
    ))
    conn.commit()


# ============================================================
# NEW AGENT — FOOTBALL SMART BASELINE
# ============================================================

def _form_summary(form_list):
    if not form_list:
        return {"wins": 0, "draws": 0, "losses": 0, "n": 0}
    wins = sum(1 for x in form_list if str(x).upper() == "W")
    draws = sum(1 for x in form_list if str(x).upper() == "D")
    losses = sum(1 for x in form_list if str(x).upper() == "L")
    return {"wins": wins, "draws": draws, "losses": losses, "n": len(form_list)}


def build_new_agent_candidate(match, payload: dict, mode: str):
    facts = payload.get("known_facts", {}) or {}

    if match.sport != "football":
        return {
            "market": "pass",
            "market_label": "PASS",
            "decision": "PASS",
            "signal_type": "Pass",
            "confidence": 0,
            "market_error": "NEW agent пока не поддерживает этот спорт в smart baseline",
            "confirmed_facts": [],
            "unconfirmed": ["unsupported sport"],
            "lineup_data_available": bool(facts.get("lineup_data_available", False)),
        }

    league = match.league
    home_form = _form_summary(facts.get("form_last_5_home") or [])
    away_form = _form_summary(facts.get("form_last_5_away") or [])
    hp = facts.get("home_position")
    ap = facts.get("away_position")
    home_scored = facts.get("home_goals_scored_avg") or 0.0
    away_scored = facts.get("away_goals_scored_avg") or 0.0
    home_allowed = facts.get("home_goals_allowed_avg") or 0.0
    away_allowed = facts.get("away_goals_allowed_avg") or 0.0
    lineup_ok = bool(facts.get("lineup_data_available", False))
    h2h = facts.get("h2h_summary") or ""
    notes = facts.get("notes") or ""

    # SAFETY: must have some data
    if min(home_form["n"], away_form["n"]) < 3 or hp is None or ap is None:
        return {
            "market": "pass",
            "market_label": "PASS",
            "decision": "PASS",
            "signal_type": "Pass",
            "confidence": 0,
            "market_error": "Недостаточно данных для smart baseline",
            "confirmed_facts": [],
            "unconfirmed": ["short form or no table"],
            "lineup_data_available": lineup_ok,
        }

    # DRAW_SA
    if "Серия А" in league or league == "SA":
        od = float(match.odds_draw or 0)
        table_diff = abs(int(hp) - int(ap))
        if (
            3.00 <= od <= 3.85 and
            abs(home_form["wins"] - away_form["wins"]) <= 1 and
            max(home_scored, away_scored) <= 1.55 and
            max(home_allowed, away_allowed) <= 1.55 and
            table_diff <= 5
        ):
            return {
                "market": "draw",
                "market_label": "X",
                "decision": "BET",
                "signal_type": "Medium",
                "confidence": 6 if h2h else 5,
                "our_probability": round(min(0.36, (1.0 / od) + 0.05), 4),
                "market_error": "Рынок недооценивает ничью в равном низовом матче Серии А",
                "confirmed_facts": [
                    f"таблица близко: {hp} vs {ap}",
                    f"форма близко: {home_form['wins']}W vs {away_form['wins']}W",
                    f"низкая атака: {home_scored:.2f} / {away_scored:.2f}",
                ],
                "unconfirmed": [] if h2h else ["H2H summary empty"],
                "lineup_data_available": lineup_ok,
            }

        oa = float(match.odds_away or 0)
        if (
            2.05 <= oa <= 3.60 and
            away_form["wins"] >= 3 and
            away_form["wins"] - home_form["wins"] >= 2 and
            away_scored >= 1.25 and
            home_allowed >= 1.35 and
            int(ap) + 3 <= int(hp)
        ):
            inj_flag = "Травмы" in notes or "Injury" in notes
            return {
                "market": "away",
                "market_label": "П2",
                "decision": "BET",
                "signal_type": "Medium",
                "confidence": 6 if inj_flag else 5,
                "our_probability": round(min(0.52, (1.0 / oa) + 0.07), 4),
                "market_error": "Рынок недооценивает гостя с лучшей формой и таблицей",
                "confirmed_facts": [
                    f"форма: {away_form['wins']}W vs {home_form['wins']}W",
                    f"таблица: {ap} < {hp}",
                    f"хозяева много пропускают: {home_allowed:.2f}",
                ],
                "unconfirmed": [] if inj_flag else ["injury data not used"],
                "lineup_data_available": lineup_ok,
            }

    # P1_PD
    if "Примера" in league or league == "PD":
        oh = float(match.odds_home or 0)
        if (
            1.70 <= oh <= 2.20 and
            home_form["wins"] >= 3 and
            home_form["wins"] - away_form["wins"] >= 1 and
            home_scored >= 1.30 and
            away_allowed >= 1.30 and
            int(hp) + 2 <= int(ap)
        ):
            return {
                "market": "home",
                "market_label": "П1",
                "decision": "BET",
                "signal_type": "Medium",
                "confidence": 5,
                "our_probability": round(min(0.60, (1.0 / oh) + 0.06), 4),
                "market_error": "Рынок недооценивает домашнего фаворита с базовым качеством",
                "confirmed_facts": [
                    f"форма хозяев: {home_form['wins']}W",
                    f"таблица: {hp} < {ap}",
                    f"слабая оборона гостей: {away_allowed:.2f}",
                ],
                "unconfirmed": [],
                "lineup_data_available": lineup_ok,
            }

    # PLUS: BL1/FL1 draws + BL1 away
    if mode == "plus":
        od = float(match.odds_draw or 0)
        oh = float(match.odds_home or 0)
        oa = float(match.odds_away or 0)
        table_diff = abs(int(hp) - int(ap))
        if league in ("BL1", "FL1") and (
            3.05 <= od <= 3.70 and
            abs(oh - oa) <= 1.05 and
            min(oh, oa) >= 1.95 and
            abs(home_form["wins"] - away_form["wins"]) <= 1 and
            home_form["draws"] + away_form["draws"] >= 2 and
            table_diff <= 4
        ):
            return {
                "market": "draw",
                "market_label": "X",
                "decision": "BET",
                "signal_type": "Medium",
                "confidence": 5,
                "our_probability": round(min(0.34, (1.0 / od) + 0.04), 4),
                "market_error": f"Рынок недооценивает ничью в равном матче {league}",
                "confirmed_facts": [
                    f"паритет линии: {oh:.2f} vs {oa:.2f}",
                    f"форма близка: {home_form['wins']}W vs {away_form['wins']}W",
                    f"ничейный профиль: {home_form['draws']} + {away_form['draws']}",
                ],
                "unconfirmed": [],
                "lineup_data_available": lineup_ok,
            }

        if league == "BL1" and (
            2.30 <= oa <= 4.20 and
            away_form["wins"] >= 3 and
            home_form["wins"] <= 1 and
            int(ap) + 5 <= int(hp) and
            home_allowed >= 1.45
        ):
            return {
                "market": "away",
                "market_label": "П2",
                "decision": "BET",
                "signal_type": "Medium",
                "confidence": 5,
                "our_probability": round(min(0.48, (1.0 / oa) + 0.06), 4),
                "market_error": "Рынок недооценивает сильного гостя в Бундеслиге",
                "confirmed_facts": [
                    f"форма гостей: {away_form['wins']}W",
                    f"форма хозяев слабая: {home_form['wins']}W",
                    f"таблица: {ap} << {hp}",
                ],
                "unconfirmed": [],
                "lineup_data_available": lineup_ok,
            }

    return {
        "market": "pass",
        "market_label": "PASS",
        "decision": "PASS",
        "signal_type": "Pass",
        "confidence": 0,
        "market_error": "NEW agent не нашёл smart edge по своим модулям",
        "confirmed_facts": [],
        "unconfirmed": [],
        "lineup_data_available": lineup_ok,
    }


def run_old_agent(conn, match, bankroll: float):
    payload = old_agent.build_payload(conn, match, bankroll)

    skip_reason = old_agent.pre_flight_check(payload.get("known_facts", {}), match.sport)
    if skip_reason:
        rec = {
            "market": "pass",
            "market_label": "PASS",
            "decision": "PASS",
            "signal_type": "Pass",
            "confidence": 0,
            "stake_pct": 0.0,
            "market_error": skip_reason,
        }
        return payload, rec, False, [skip_reason]

    rec = old_agent.normalize_response(old_agent.call_llm(payload, bankroll))
    if rec.get("decision") == "PASS":
        return payload, rec, False, ["PASS by old agent"]

    rec = old_agent.calibrate_probability(rec, match, payload.get("known_facts", {}))
    rec = old_agent.enrich_with_math(rec, match, payload.get("known_facts", {}))
    valid, notes = validate_recommendation(rec, payload, bankroll)
    return payload, rec, valid, notes


def run_new_agent(conn, match, bankroll: float, mode: str):
    payload = old_agent.build_payload(conn, match, bankroll)
    rec = build_new_agent_candidate(match, payload, mode)

    if rec.get("decision") == "PASS":
        return payload, rec, False, ["PASS by new agent"]

    # old math + old validator, but no old LLM
    rec = old_agent.calibrate_probability(rec, match, payload.get("known_facts", {}))
    rec = old_agent.enrich_with_math(rec, match, payload.get("known_facts", {}))
    valid, notes = validate_recommendation(rec, payload, bankroll)
    return payload, rec, valid, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="football", choices=["football", "hockey", "tennis", "mma", "esports"])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--mode", default="safe", choices=["safe", "plus"])
    ap.add_argument("--bankroll", type=float, default=DEFAULT_BANK)
    args = ap.parse_args()

    conn = get_conn()
    ensure_shadow_schema(conn)

    matches = old_agent.fetch_upcoming_matches(conn, sport=args.sport, limit=args.limit)

    if not matches:
        print("Нет upcoming-матчей.")
        return 0

    print("=" * 100)
    print(f"DUAL SHADOW RUNNER | sport={args.sport} | mode={args.mode} | limit={args.limit}")
    print("=" * 100)

    old_count = new_count = 0

    for match in matches:
        try:
            payload_old, rec_old, valid_old, notes_old = run_old_agent(conn, match, args.bankroll)
            save_shadow(conn, "old_agent_v7", args.mode, match, payload_old, rec_old, valid_old, notes_old)
            if valid_old:
                old_count += 1
            print(f"OLD | {match.home_team} - {match.away_team} | {rec_old.get('market_label')} | valid={valid_old}")
        except Exception as e:
            print(f"OLD ERROR | {match.home_team} - {match.away_team} | {type(e).__name__}: {e}")

        try:
            payload_new, rec_new, valid_new, notes_new = run_new_agent(conn, match, args.bankroll, args.mode)
            save_shadow(conn, "new_smart_v1", args.mode, match, payload_new, rec_new, valid_new, notes_new)
            if valid_new:
                new_count += 1
            print(f"NEW | {match.home_team} - {match.away_team} | {rec_new.get('market_label')} | valid={valid_new}")
        except Exception as e:
            print(f"NEW ERROR | {match.home_team} - {match.away_team} | {type(e).__name__}: {e}")

        print("-" * 100)

    print(f"Saved. valid old={old_count} | valid new={new_count}")
    print("Table: shadow_recommendations")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
