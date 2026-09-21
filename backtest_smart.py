#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — backtest_smart.py

Умный бэктест — симулирует логику агента:
- Форма команд (последние 5 матчей)
- Разница в голах
- Мотивация (позиция в таблице)
- EV + Kelly калибровка

Запуск:
  python backtest_smart.py
  python backtest_smart.py --league EPL --season 2024
  python backtest_smart.py --all --verbose
"""

import os, sqlite3, argparse
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
BANK    = float(os.getenv("BETAGENT_BANK", "100000"))

MIN_EV         = 0.03
MIN_ODDS       = 1.55
MAX_ODDS       = 4.5
MAX_STAKE_PCT  = 0.05
KELLY_FRACTION = 0.25


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def build_form(matches: list, team: str, before_date: str, n: int = 5) -> list:
    """Форма команды за последние N матчей до указанной даты."""
    results = []
    for m in sorted(matches, key=lambda x: x["match_date"], reverse=True):
        if m["match_date"] >= before_date:
            continue
        if m["home_team"] == team:
            if m["result"] == "H": results.append("W")
            elif m["result"] == "D": results.append("D")
            else: results.append("L")
        elif m["away_team"] == team:
            if m["result"] == "A": results.append("W")
            elif m["result"] == "D": results.append("D")
            else: results.append("L")
        if len(results) >= n:
            break
    return results


def build_goals_avg(matches: list, team: str, before_date: str, n: int = 5):
    """Средние голы за/против за последние N матчей."""
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
    return round(scored/count, 2), round(conceded/count, 2)


def build_table(matches: list, before_date: str) -> dict:
    """Строим таблицу из результатов до указанной даты."""
    table = defaultdict(lambda: {"pts": 0, "played": 0, "gf": 0, "ga": 0})
    for m in matches:
        if m["match_date"] >= before_date:
            continue
        h, a = m["home_team"], m["away_team"]
        hg = m["home_score"] or 0
        ag = m["away_score"] or 0
        table[h]["played"] += 1
        table[a]["played"] += 1
        table[h]["gf"] += hg
        table[h]["ga"] += ag
        table[a]["gf"] += ag
        table[a]["ga"] += hg
        if m["result"] == "H":
            table[h]["pts"] += 3
        elif m["result"] == "A":
            table[a]["pts"] += 3
        else:
            table[h]["pts"] += 1
            table[a]["pts"] += 1

    # Позиции
    sorted_teams = sorted(table.keys(),
                          key=lambda t: (-table[t]["pts"],
                                         -(table[t]["gf"]-table[t]["ga"])))
    positions = {team: pos+1 for pos, team in enumerate(sorted_teams)}
    return table, positions


def wins_count(form: list) -> int:
    return sum(1 for r in form if r == "W")


def analyze_match(home: str, away: str, oh: float, od: float, oa: float,
                  home_form: list, away_form: list,
                  home_scored: float, home_conceded: float,
                  away_scored: float, away_conceded: float,
                  home_pos: int, away_pos: int,
                  total_teams: int) -> dict | None:
    """
    Симулирует логику агента без LLM.
    Возвращает сигнал или None.
    """
    if len(home_form) < 3 or len(away_form) < 3:
        return None
    if not home_scored or not away_scored:
        return None

    home_wins = wins_count(home_form)
    away_wins = wins_count(away_form)
    table_diff = abs(home_pos - away_pos) if home_pos and away_pos else 99

    # Рыночные вероятности
    margin = 1/oh + 1/od + 1/oa
    ph = (1/oh) / margin
    pd = (1/od) / margin
    pa = (1/oa) / margin

    # ── СИГНАЛ П1 ──────────────────────────────────────────────
    # Хозяева в хорошей форме + слабая защита гостей + разница в таблице
    if (home_wins >= 3
            and away_wins <= 1
            and home_scored > 1.2
            and away_conceded > 1.4
            and table_diff >= 3
            and home_pos < away_pos
            and MIN_ODDS <= oh <= MAX_ODDS):
        our_p = ph + 0.07
        our_p = min(our_p, 0.75)
        ev = our_p * oh - 1
        if ev >= MIN_EV:
            return {"market": "home", "odds": oh, "our_p": our_p,
                    "ev": ev, "reason": f"Форма {home_wins}/5 vs {away_wins}/5"}

    # ── СИГНАЛ П2 ──────────────────────────────────────────────
    # Гости в хорошей форме + слабая защита хозяев + разница в таблице
    if (away_wins >= 3
            and home_wins <= 1
            and away_scored > 1.2
            and home_conceded > 1.4
            and table_diff >= 3
            and away_pos < home_pos
            and MIN_ODDS <= oa <= MAX_ODDS):
        our_p = pa + 0.07
        our_p = min(our_p, 0.65)
        ev = our_p * oa - 1
        if ev >= MIN_EV:
            return {"market": "away", "odds": oa, "our_p": our_p,
                    "ev": ev, "reason": f"Форма {away_wins}/5 vs {home_wins}/5 в гостях"}

    # ── СИГНАЛ X ───────────────────────────────────────────────
    # Равные команды + закрытая игра + коэф в диапазоне
    if (abs(home_wins - away_wins) <= 1
            and home_scored < 1.5
            and away_scored < 1.5
            and table_diff <= 5
            and 3.0 <= od <= 4.5):
        our_p = pd + 0.06
        our_p = min(our_p, 0.40)
        ev = our_p * od - 1
        if ev >= MIN_EV:
            return {"market": "draw", "odds": od, "our_p": our_p,
                    "ev": ev, "reason": f"Равные команды, закрытая игра"}

    return None


def run_smart_backtest(rows: list, bank: float) -> dict:
    """Запускает умный бэктест с динамической формой и таблицей."""
    all_matches = [dict(r) for r in rows]
    current_bank = bank
    bets = []

    for i, match in enumerate(sorted(all_matches, key=lambda m: m["match_date"])):
        date = match["match_date"]
        home = match["home_team"]
        away = match["away_team"]
        oh = float(match["odds_home"])
        od = float(match["odds_draw"])
        oa = float(match["odds_away"])

        # Строим контекст из матчей до этой даты в этой лиге
        league_matches = [m for m in all_matches
                          if m["league"] == match["league"]
                          and m["season"] == match["season"]]

        home_form     = build_form(league_matches, home, date)
        away_form     = build_form(league_matches, away, date)
        home_s, home_c = build_goals_avg(league_matches, home, date)
        away_s, away_c = build_goals_avg(league_matches, away, date)
        table, positions = build_table(league_matches, date)
        home_pos = positions.get(home, 99)
        away_pos = positions.get(away, 99)
        total_teams = len(positions)

        if not home_s or not away_s:
            continue

        signal = analyze_match(
            home, away, oh, od, oa,
            home_form, away_form,
            home_s, home_c, away_s, away_c,
            home_pos, away_pos, total_teams
        )

        if not signal:
            continue

        odds = signal["odds"]
        our_p = signal["our_p"]
        kelly = max(0, (our_p * odds - 1) / (odds - 1))
        stake_pct = min(kelly * KELLY_FRACTION, MAX_STAKE_PCT)
        stake = current_bank * stake_pct

        if stake < 200:
            continue

        # Результат
        result_map = {"H": "home", "D": "draw", "A": "away"}
        actual = result_map.get(match["result"])
        won = actual == signal["market"]
        profit = stake * (odds - 1) if won else -stake
        current_bank += profit

        bets.append({
            "date": date,
            "league": match["league"],
            "home": home,
            "away": away,
            "market": signal["market"],
            "odds": odds,
            "stake": stake,
            "stake_pct": stake_pct,
            "won": won,
            "profit": profit,
            "bank_after": current_bank,
            "ev": signal["ev"],
            "reason": signal["reason"],
            "home_form": "".join(home_form[:5]),
            "away_form": "".join(away_form[:5]),
        })

        if current_bank < bank * 0.2:
            break  # стоп-лосс 80%

    if not bets:
        return {"bets": 0}

    wins = sum(1 for b in bets if b["won"])
    total_staked = sum(b["stake"] for b in bets)
    total_profit = sum(b["profit"] for b in bets)
    roi = total_profit / total_staked * 100 if total_staked > 0 else 0

    return {
        "bets": len(bets),
        "wins": wins,
        "losses": len(bets) - wins,
        "winrate": wins / len(bets) * 100,
        "total_staked": total_staked,
        "total_profit": total_profit,
        "roi": roi,
        "final_bank": current_bank,
        "bank_growth": (current_bank - bank) / bank * 100,
        "bets_list": bets,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league",  default=None)
    ap.add_argument("--season",  default=None)
    ap.add_argument("--all",     action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--top",     type=int, default=5)
    args = ap.parse_args()

    conn = get_conn()

    count = conn.execute("SELECT COUNT(*) FROM backtest_matches").fetchone()[0]
    if count == 0:
        print("❌ Нет данных. Запусти: python backtest_downloader.py")
        conn.close()
        return

    where = ["result IS NOT NULL", "result != ''",
             "home_score IS NOT NULL", "odds_home > 0"]
    params = []
    if args.league and not args.all:
        where.append("league = ?")
        params.append(args.league)
    if args.season and not args.all:
        where.append("season = ?")
        params.append(args.season)

    rows = conn.execute(f"""
        SELECT * FROM backtest_matches
        WHERE {' AND '.join(where)}
        ORDER BY match_date ASC
    """, params).fetchall()
    conn.close()

    print(f"\n{'='*60}")
    print(f"  BETAGENT — УМНЫЙ БЭКТЕСТ")
    print(f"  Матчей в выборке: {len(rows)}")
    print(f"  Банк: {BANK:,.0f} руб | Kelly×{KELLY_FRACTION} | Max stake: {MAX_STAKE_PCT*100:.0f}%")
    print(f"  Фильтры: EV≥{MIN_EV} | Коэф {MIN_ODDS}-{MAX_ODDS}")
    print(f"{'='*60}")

    r = run_smart_backtest(rows, BANK)

    if r["bets"] == 0:
        print("❌ Нет ставок по критериям")
        return

    roi_icon = "✅" if r["roi"] >= 4 else ("⚠️" if r["roi"] >= 0 else "❌")

    print(f"\n  Ставок: {r['bets']} | W:{r['wins']} L:{r['losses']}")
    print(f"  Винрейт: {r['winrate']:.1f}%")
    print(f"  Поставлено: {r['total_staked']:,.0f} руб")
    print(f"  Прибыль: {r['total_profit']:+,.0f} руб")
    print(f"  {roi_icon} ROI: {r['roi']:+.2f}%")
    print(f"  Банк: {BANK:,.0f} → {r['final_bank']:,.0f} руб ({r['bank_growth']:+.1f}%)")

    # По лигам
    if args.all or args.verbose:
        by_league = defaultdict(lambda: {"bets": 0, "wins": 0, "staked": 0, "profit": 0})
        for b in r["bets_list"]:
            by_league[b["league"]]["bets"] += 1
            by_league[b["league"]]["wins"] += int(b["won"])
            by_league[b["league"]]["staked"] += b["stake"]
            by_league[b["league"]]["profit"] += b["profit"]

        print(f"\n  По лигам:")
        for league, s in sorted(by_league.items(),
                                  key=lambda x: x[1]["profit"], reverse=True):
            roi_l = s["profit"] / s["staked"] * 100 if s["staked"] > 0 else 0
            icon = "✅" if roi_l >= 4 else ("⚠️" if roi_l >= 0 else "❌")
            print(f"  {icon} {league:5s} | {s['bets']:3d} ставок | "
                  f"W:{s['wins']} | ROI:{roi_l:+.1f}% | {s['profit']:+,.0f} руб")

    # По рынкам
    by_market = defaultdict(lambda: {"bets": 0, "wins": 0, "staked": 0, "profit": 0})
    for b in r["bets_list"]:
        by_market[b["market"]]["bets"] += 1
        by_market[b["market"]]["wins"] += int(b["won"])
        by_market[b["market"]]["staked"] += b["stake"]
        by_market[b["market"]]["profit"] += b["profit"]

    print(f"\n  По рынкам:")
    for market, s in by_market.items():
        roi_m = s["profit"] / s["staked"] * 100 if s["staked"] > 0 else 0
        icon = "✅" if roi_m >= 4 else ("⚠️" if roi_m >= 0 else "❌")
        label = {"home": "П1", "draw": "X", "away": "П2"}.get(market, market)
        print(f"  {icon} {label:3s} | {s['bets']:3d} ставок | "
              f"W:{s['wins']} | ROI:{roi_m:+.1f}% | {s['profit']:+,.0f} руб")

    if args.verbose:
        bets_sorted = sorted(r["bets_list"], key=lambda b: b["profit"], reverse=True)
        print(f"\n  ТОП-{args.top} лучших:")
        for b in bets_sorted[:args.top]:
            label = {"home": "П1", "draw": "X", "away": "П2"}.get(b["market"])
            print(f"  ✅ {b['date']} | {b['league']} | "
                  f"{b['home']} — {b['away']} | "
                  f"{label} @ {b['odds']:.2f} | "
                  f"+{b['profit']:,.0f} руб | "
                  f"Форма: {b['home_form']} vs {b['away_form']}")

        print(f"\n  ТОП-{args.top} худших:")
        for b in bets_sorted[-args.top:]:
            label = {"home": "П1", "draw": "X", "away": "П2"}.get(b["market"])
            print(f"  ❌ {b['date']} | {b['league']} | "
                  f"{b['home']} — {b['away']} | "
                  f"{label} @ {b['odds']:.2f} | "
                  f"{b['profit']:,.0f} руб | "
                  f"Форма: {b['home_form']} vs {b['away_form']}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
