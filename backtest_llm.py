#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — backtest_llm.py

LLM бэктест — прогоняет исторические матчи через реального агента.
Форма и таблица строятся динамически на момент каждого матча.

Запуск:
  python3 backtest_llm.py --league SA --season 2024 --limit 50
  python3 backtest_llm.py --league BL1 --season 2024 --limit 50
  python3 backtest_llm.py --league SA BL1 --season 2024 --limit 100
"""

import os, sys, sqlite3, json, time, argparse, requests
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

DB_PATH   = Path(os.getenv("BETAGENT_DB", "betagent.db"))
API_URL   = os.getenv("LLM_API_URL")
API_KEY   = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-haiku-4-5")

BANK           = 100_000.0
KELLY_FRACTION = 0.25
MAX_STAKE_PCT  = 0.05
MIN_ODDS       = 1.55
MAX_ODDS       = 4.5
MIN_EV         = 0.025

# ── ДИНАМИЧЕСКАЯ ФОРМА И ТАБЛИЦА ──────────────────────────────
def build_form(matches, team, before_date, n=5):
    results = []
    for m in sorted(matches, key=lambda x: x["match_date"], reverse=True):
        if m["match_date"] >= before_date:
            continue
        if m["home_team"] == team:
            r = "W" if m["result"] == "H" else ("D" if m["result"] == "D" else "L")
        elif m["away_team"] == team:
            r = "W" if m["result"] == "A" else ("D" if m["result"] == "D" else "L")
        else:
            continue
        results.append(r)
        if len(results) >= n:
            break
    return results

def build_goals(matches, team, before_date, n=5):
    scored, conceded, count = 0, 0, 0
    for m in sorted(matches, key=lambda x: x["match_date"], reverse=True):
        if m["match_date"] >= before_date:
            continue
        if m["home_team"] == team:
            scored   += m["home_score"] or 0
            conceded += m["away_score"] or 0
            count    += 1
        elif m["away_team"] == team:
            scored   += m["away_score"] or 0
            conceded += m["home_score"] or 0
            count    += 1
        if count >= n:
            break
    if count == 0:
        return None, None
    return round(scored/count, 2), round(conceded/count, 2)

def build_table(matches, before_date):
    table = defaultdict(lambda: {"pts": 0, "played": 0, "gf": 0, "ga": 0})
    for m in matches:
        if m["match_date"] >= before_date:
            continue
        h, a = m["home_team"], m["away_team"]
        hg = m["home_score"] or 0
        ag = m["away_score"] or 0
        table[h]["played"] += 1
        table[a]["played"] += 1
        table[h]["gf"] += hg; table[h]["ga"] += ag
        table[a]["gf"] += ag; table[a]["ga"] += hg
        if m["result"] == "H":
            table[h]["pts"] += 3
        elif m["result"] == "A":
            table[a]["pts"] += 3
        else:
            table[h]["pts"] += 1
            table[a]["pts"] += 1
    sorted_teams = sorted(table.keys(),
                          key=lambda t: (-table[t]["pts"],
                                         -(table[t]["gf"]-table[t]["ga"])))
    positions = {t: i+1 for i, t in enumerate(sorted_teams)}
    return table, positions

def build_h2h(matches, home, away, before_date, n=3):
    h2h = []
    for m in sorted(matches, key=lambda x: x["match_date"], reverse=True):
        if m["match_date"] >= before_date:
            continue
        if set([m["home_team"], m["away_team"]]) == set([home, away]):
            h2h.append(m)
            if len(h2h) >= n:
                break
    if not h2h:
        return "Нет H2H данных"
    parts = []
    for m in h2h:
        parts.append(f"{m['home_team']} {m['home_score']}:{m['away_score']} {m['away_team']}")
    return " | ".join(parts)

# ── LLM ВЫЗОВ ─────────────────────────────────────────────────
SYSTEM_PROMPT = """Ты профессиональный бетторский аналитик. Анализируй футбольные матчи и ищи ценные ставки.

ПРАВИЛА АНАЛИЗА:
- Ищи конкретную ошибку рынка — место где букмекер недооценивает команду
- Опирайся только на факты из данных: форма, таблица, голы, H2H
- Базовое качество команды: минимум 2W из 5 + голы > 1.0 + таблица топ-15
- Травмы и мотивация дают edge ТОЛЬКО если есть базовое качество
- Ничья (X): разница таблицы ≤ 5 мест, атака < 1.7 г/матч у обеих, коэф 3.0-4.5

ФИЛЬТРЫ (обязательные):
- Коэф < 1.55 → PASS
- Форма выбранной команды < 2W из 5 без других сильных факторов → PASS
- Рынок адекватен → PASS

Ответ ТОЛЬКО в JSON:
{
  "market": "home|draw|away|pass",
  "our_probability": 0.0-1.0,
  "confidence": 1-10,
  "signal_type": "Strong|Medium|Weak|Pass",
  "decision": "BET|PASS",
  "reasoning": "кратко почему",
  "confirmed_facts": ["факт1", "факт2"],
  "market_error": "описание ошибки рынка или null"
}"""

def call_llm(payload_text):
    if not API_URL or not API_KEY:
        raise RuntimeError("Нужны LLM_API_URL и LLM_API_KEY")
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    body = {
        "model": LLM_MODEL,
        "temperature": 0.1,
        "max_tokens": 1000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": payload_text},
        ],
    }
    for attempt in range(5):
        try:
            r = requests.post(API_URL, headers=headers, json=body, timeout=60, verify=False)
            if r.status_code in (429, 500, 502, 503):
                wait = 20 * (attempt + 1)
                print(f"  ⏳ HTTP {r.status_code}, retry {attempt+1}/5 через {wait} сек...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"].strip()
            if not content:
                print(f"  ⏳ Пустой ответ, retry {attempt+1}/5 через 10 сек...")
                time.sleep(10)
                continue
            # Убираем markdown обёртку если есть
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()
            return json.loads(content)
        except json.JSONDecodeError:
            print(f"  ⏳ JSON ошибка, retry {attempt+1}/5 через 10 сек...")
            time.sleep(10)
        except Exception as e:
            if attempt < 4:
                time.sleep(15)
            else:
                raise
    raise RuntimeError("Все попытки LLM исчерпаны")

def build_payload_text(match, home_form, away_form, home_s, home_c,
                       away_s, away_c, home_pos, away_pos, h2h_str,
                       total_teams):
    oh = float(match["odds_home"])
    od = float(match["odds_draw"])
    oa = float(match["odds_away"])
    margin = 1/oh + 1/od + 1/oa
    ph = round((1/oh) / margin, 3)
    pd = round((1/od) / margin, 3)
    pa = round((1/oa) / margin, 3)

    return f"""Матч: {match['home_team']} — {match['away_team']}
Лига: {match['league_name']} | Дата: {match['match_date']}

КОЭФФИЦИЕНТЫ:
П1: {oh} (вер. {ph}) | X: {od} (вер. {pd}) | П2: {oa} (вер. {pa})

ФОРМА (последние 5):
{match['home_team']}: {' '.join(home_form) if home_form else 'нет данных'}
{match['away_team']}: {' '.join(away_form) if away_form else 'нет данных'}

ГОЛЫ (ср. за матч):
{match['home_team']}: забивает {home_s or '?'} | пропускает {home_c or '?'}
{match['away_team']}: забивает {away_s or '?'} | пропускает {away_c or '?'}

ТАБЛИЦА:
{match['home_team']}: {home_pos or '?'}/{total_teams} место
{match['away_team']}: {away_pos or '?'}/{total_teams} место

H2H: {h2h_str}

Составы: недоступны | Травмы: недоступны
"""

# ── МАТЕМАТИЧЕСКИЕ ФИЛЬТРЫ ────────────────────────────────────
def math_filter(rec, odds_home, odds_draw, odds_away, profile):
    market = rec.get("market", "pass")
    if market == "pass":
        return rec, "LLM PASS"

    odds_map = {"home": odds_home, "draw": odds_draw, "away": odds_away}
    odds = odds_map.get(market)
    if not odds or odds < MIN_ODDS or odds > MAX_ODDS:
        rec["decision"] = "PASS"
        return rec, f"Коэф {odds} вне диапазона {MIN_ODDS}-{MAX_ODDS}"

    market_p = 1.0 / odds
    our_p    = float(rec.get("our_probability", market_p))
    min_edge = 0.025

    # Cap без составов
    if our_p > 0.57:
        our_p = 0.57
    rec["our_probability"] = our_p

    ev = our_p * odds - 1.0
    rec["ev"] = round(ev, 4)

    if our_p <= market_p + min_edge:
        rec["decision"] = "PASS"
        return rec, f"Нет edge: {our_p:.3f} ≤ {market_p+min_edge:.3f}"

    if ev < MIN_EV:
        rec["decision"] = "PASS"
        return rec, f"EV {ev:.3f} < {MIN_EV}"

    # Ничья фильтры
    if market == "draw" and odds > 4.5:
        rec["decision"] = "PASS"
        return rec, "X @ > 4.5 — PASS"

    rec["decision"] = "BET"
    kelly = max(0, (our_p * odds - 1) / (odds - 1))
    stake_pct = min(kelly * KELLY_FRACTION, MAX_STAKE_PCT)
    rec["stake_pct"] = round(stake_pct, 4)
    return rec, "OK"

# ── ОСНОВНОЙ ЦИКЛ ─────────────────────────────────────────────
def run_backtest_llm(rows, limit, verbose=False):
    all_matches = [dict(r) for r in rows]
    current_bank = BANK
    bets = []
    errors = []
    total = 0
    llm_calls = 0

    for match in sorted(all_matches, key=lambda m: m["match_date"]):
        if total >= limit:
            break

        # Нужно минимум 5 предыдущих матчей для обеих команд
        league_matches = [m for m in all_matches
                          if m["league"] == match["league"]
                          and m["season"] == match["season"]]

        home_form = build_form(league_matches, match["home_team"], match["match_date"])
        away_form = build_form(league_matches, match["away_team"], match["match_date"])

        if len(home_form) < 3 or len(away_form) < 3:
            continue  # Недостаточно данных

        home_s, home_c = build_goals(league_matches, match["home_team"], match["match_date"])
        away_s, away_c = build_goals(league_matches, match["away_team"], match["match_date"])
        table, positions = build_table(league_matches, match["match_date"])
        home_pos = positions.get(match["home_team"])
        away_pos = positions.get(match["away_team"])
        h2h = build_h2h(league_matches, match["home_team"], match["away_team"], match["match_date"])

        payload_text = build_payload_text(
            match, home_form, away_form,
            home_s, home_c, away_s, away_c,
            home_pos, away_pos, h2h,
            len(positions)
        )

        total += 1
        llm_calls += 1

        try:
            rec = call_llm(payload_text)
            time.sleep(2)  # пауза между запросами
        except Exception as e:
            errors.append(str(e))
            print(f"  ❌ LLM ошибка: {e}")
            continue

        oh = float(match["odds_home"])
        od = float(match["odds_draw"])
        oa = float(match["odds_away"])

        rec, reason = math_filter(rec, oh, od, oa, {})

        if verbose:
            decision = rec.get("decision", "PASS")
            market   = rec.get("market", "pass")
            print(f"  [{total:3d}] {match['home_team']} — {match['away_team']} | "
                  f"{decision} {market} | {reason[:50]}")

        if rec.get("decision") != "BET":
            continue

        market   = rec["market"]
        odds_map = {"home": oh, "draw": od, "away": oa}
        odds     = odds_map[market]
        our_p    = rec["our_probability"]
        stake_pct = rec.get("stake_pct", 0.02)
        stake    = current_bank * stake_pct

        if stake < 200:
            continue

        # Реальный результат
        result_map = {"H": "home", "D": "draw", "A": "away"}
        actual = result_map.get(match["result"])
        won    = actual == market
        profit = stake * (odds - 1) if won else -stake
        current_bank += profit

        bets.append({
            "date":     match["match_date"],
            "league":   match["league"],
            "home":     match["home_team"],
            "away":     match["away_team"],
            "market":   market,
            "odds":     odds,
            "stake":    stake,
            "stake_pct": stake_pct,
            "won":      won,
            "profit":   profit,
            "bank":     current_bank,
            "ev":       rec.get("ev", 0),
            "our_p":    our_p,
            "confidence": rec.get("confidence", 0),
            "reasoning": rec.get("reasoning", ""),
        })

        status = "✅" if won else "❌"
        print(f"  {status} BET: {match['home_team']} — {match['away_team']} | "
              f"{market} @ {odds} | {stake:.0f} руб | {profit:+.0f} руб | "
              f"Банк: {current_bank:.0f}")

        if current_bank < BANK * 0.3:
            print("  ⛔ Стоп-лосс 70%!")
            break

    return {
        "total_analyzed": total,
        "llm_calls": llm_calls,
        "bets": len(bets),
        "wins": sum(1 for b in bets if b["won"]),
        "losses": sum(1 for b in bets if not b["won"]),
        "total_staked": sum(b["stake"] for b in bets),
        "total_profit": sum(b["profit"] for b in bets),
        "final_bank": current_bank,
        "errors": len(errors),
        "bets_list": bets,
    }

# ── MAIN ──────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league",   nargs="+", default=["SA"])
    ap.add_argument("--season",   default="2024")
    ap.add_argument("--limit",    type=int, default=50)
    ap.add_argument("--verbose",  action="store_true")
    ap.add_argument("--save",     default="backtest_llm_results.json")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Проверяем данные
    count = conn.execute("SELECT COUNT(*) FROM backtest_matches").fetchone()[0]
    if count == 0:
        print("❌ Нет исторических данных. Запусти: python3 backtest_downloader.py")
        return

    where = ["result IS NOT NULL", "result != ''",
             "home_score IS NOT NULL", "odds_home > 0",
             f"season = '{args.season}'",
             f"league IN ({','.join(['?' for _ in args.league])})"]

    rows = conn.execute(f"""
        SELECT * FROM backtest_matches
        WHERE {' AND '.join(where)}
        ORDER BY match_date ASC
    """, args.league).fetchall()
    conn.close()

    print(f"\n{'='*65}")
    print(f"  BETAGENT — LLM БЭКТЕСТ")
    print(f"  Лиги: {', '.join(args.league)} | Сезон: {args.season}")
    print(f"  Матчей в выборке: {len(rows)} | Лимит анализа: {args.limit}")
    print(f"  Модель: {LLM_MODEL}")
    print(f"  Банк: {BANK:,.0f} руб | Kelly×{KELLY_FRACTION} | Max: {MAX_STAKE_PCT*100:.0f}%")
    print(f"{'='*65}\n")

    start = time.time()
    results = run_backtest_llm(rows, args.limit, verbose=args.verbose)
    elapsed = time.time() - start

    # Итоги
    r = results
    closed = r["wins"] + r["losses"]
    winrate = r["wins"] / closed * 100 if closed > 0 else 0
    roi = r["total_profit"] / r["total_staked"] * 100 if r["total_staked"] > 0 else 0
    roi_icon = "✅" if roi >= 4 else ("⚠️" if roi >= 0 else "❌")

    print(f"\n{'='*65}")
    print(f"  ИТОГИ")
    print(f"  Проанализировано: {r['total_analyzed']} матчей")
    print(f"  LLM вызовов: {r['llm_calls']} | Ошибок: {r['errors']}")
    print(f"  Ставок: {r['bets']} | W:{r['wins']} L:{r['losses']}")
    if closed > 0:
        print(f"  Винрейт: {winrate:.1f}%")
    print(f"  Поставлено: {r['total_staked']:,.0f} руб")
    print(f"  Прибыль: {r['total_profit']:+,.0f} руб")
    print(f"  {roi_icon} ROI: {roi:+.2f}%")
    print(f"  Банк: {BANK:,.0f} → {r['final_bank']:,.0f} руб")
    print(f"  Время: {elapsed/60:.1f} мин")

    # По лигам
    by_league = defaultdict(lambda: {"bets":0,"wins":0,"staked":0,"profit":0})
    for b in r["bets_list"]:
        by_league[b["league"]]["bets"]   += 1
        by_league[b["league"]]["wins"]   += int(b["won"])
        by_league[b["league"]]["staked"] += b["stake"]
        by_league[b["league"]]["profit"] += b["profit"]

    if by_league:
        print(f"\n  По лигам:")
        for league, s in sorted(by_league.items(), key=lambda x: x[1]["profit"], reverse=True):
            roi_l = s["profit"] / s["staked"] * 100 if s["staked"] > 0 else 0
            icon  = "✅" if roi_l >= 4 else ("⚠️" if roi_l >= 0 else "❌")
            print(f"  {icon} {league:5s} | {s['bets']:3d} ставок | "
                  f"W:{s['wins']} | ROI:{roi_l:+.1f}% | {s['profit']:+,.0f} руб")

    # Лучшие/худшие
    if r["bets_list"]:
        bets_sorted = sorted(r["bets_list"], key=lambda b: b["profit"], reverse=True)
        print(f"\n  Топ-3 лучших:")
        for b in bets_sorted[:3]:
            print(f"    ✅ {b['date'][:10]} | {b['home']} — {b['away']} | "
                  f"{b['market']} @ {b['odds']} | +{b['profit']:,.0f} руб | {b['reasoning'][:60]}")
        print(f"\n  Топ-3 худших:")
        for b in bets_sorted[-3:]:
            print(f"    ❌ {b['date'][:10]} | {b['home']} — {b['away']} | "
                  f"{b['market']} @ {b['odds']} | {b['profit']:,.0f} руб | {b['reasoning'][:60]}")

    # Сохраняем результаты
    save_path = Path(args.save)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  Результаты сохранены: {save_path}")
    print(f"{'='*65}\n")

if __name__ == "__main__":
    main()
