#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — backtest.py

Прогоняет логику системы на исторических данных.
Использует реальные коэффициенты из football-data.co.uk
и нашу математику (EV, Kelly, calibration).

Запуск:
  python backtest.py
  python backtest.py --league EPL --season 2024
  python backtest.py --league EPL --min-odds 1.8 --max-odds 4.0
  python backtest.py --all --report
"""

import os, sqlite3, argparse, json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
BANK = float(os.getenv("BETAGENT_BANK", "100000"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── ПРОСТАЯ КАЛИБРОВКА (без LLM) ──────────────────────────────
def simple_edge_signal(row: dict, strategy: str) -> dict | None:
    """
    Простые стратегии без LLM — проверяем edge по математике.
    Возвращает dict с market/odds/our_p или None если нет ставки.
    """
    oh = float(row["odds_home"])
    od = float(row["odds_draw"])
    oa = float(row["odds_away"])

    # Рыночные вероятности
    margin = 1/oh + 1/od + 1/oa
    ph = (1/oh) / margin  # нормализованная вероятность
    pd = (1/od) / margin
    pa = (1/oa) / margin

    if strategy == "value_home":
        # Ставим на П1 если рынок недооценивает хозяев
        # Наша модель: хозяева имеют +5% преимущество к рыночной вероятности
        our_p = ph * 1.05
        ev = our_p * oh - 1
        if ev >= 0.03 and oh >= 1.5 and oh <= 4.5:
            return {"market": "home", "odds": oh, "our_p": our_p, "ev": ev}

    elif strategy == "value_away":
        our_p = pa * 1.05
        ev = our_p * oa - 1
        if ev >= 0.03 and oa >= 1.8 and oa <= 4.5:
            return {"market": "away", "odds": oa, "our_p": our_p, "ev": ev}

    elif strategy == "low_odds_home":
        # Фавориты дома 1.5-2.0
        if 1.5 <= oh <= 2.0:
            our_p = 1/oh + 0.04
            ev = our_p * oh - 1
            if ev >= 0.02:
                return {"market": "home", "odds": oh, "our_p": our_p, "ev": ev}

    elif strategy == "draw_equal":
        # Ничья если команды равны (рыночные вероятности близки)
        if abs(ph - pa) < 0.05 and 3.0 <= od <= 4.5:
            our_p = pd * 1.08
            ev = our_p * od - 1
            if ev >= 0.03:
                return {"market": "draw", "odds": od, "our_p": our_p, "ev": ev}

    elif strategy == "away_underdog":
        # Аутсайдер в гостях 2.5-3.5
        if 2.5 <= oa <= 3.5 and pa > 0.28:
            our_p = pa + 0.05
            ev = our_p * oa - 1
            if ev >= 0.04:
                return {"market": "away", "odds": oa, "our_p": our_p, "ev": ev}

    return None


def kelly_stake(our_p: float, odds: float, fraction: float = 0.25) -> float:
    """Kelly четверть."""
    k = (our_p * odds - 1) / (odds - 1)
    return max(0, k * fraction)


def run_backtest(rows: list, strategy: str, bank: float,
                 min_odds: float = 1.0, max_odds: float = 10.0) -> dict:
    """Прогоняет стратегию на списке матчей."""
    current_bank = bank
    bets = []
    
    for row in rows:
        signal = simple_edge_signal(dict(row), strategy)
        if not signal:
            continue

        odds = signal["odds"]
        if not (min_odds <= odds <= max_odds):
            continue

        our_p = signal["our_p"]
        stake_pct = kelly_stake(our_p, odds)
        stake_pct = min(stake_pct, 0.05)  # максимум 5% банка
        stake = current_bank * stake_pct

        if stake < 100:  # минимальная ставка
            continue

        # Определяем результат
        result_map = {"H": "home", "D": "draw", "A": "away"}
        actual = result_map.get(row["result"])
        won = actual == signal["market"]
        profit = stake * (odds - 1) if won else -stake
        current_bank += profit

        bets.append({
            "date": row["match_date"],
            "home": row["home_team"],
            "away": row["away_team"],
            "market": signal["market"],
            "odds": odds,
            "stake": stake,
            "stake_pct": stake_pct,
            "won": won,
            "profit": profit,
            "bank_after": current_bank,
            "ev": signal["ev"],
        })

    if not bets:
        return {"bets": 0}

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
        "best_bet": max(bets, key=lambda b: b["profit"]),
        "worst_bet": min(bets, key=lambda b: b["profit"]),
        "bets_list": bets,
    }


def print_result(r: dict, verbose: bool = False):
    if r["bets"] == 0:
        print(f"  {r.get('strategy','?'):20s} | 0 ставок")
        return

    roi_icon = "✅" if r["roi"] >= 4 else ("⚠️" if r["roi"] >= 0 else "❌")
    print(f"\n  Стратегия: {r['strategy']}")
    print(f"  Ставок: {r['bets']} | W:{r['wins']} L:{r['losses']} | "
          f"Винрейт: {r['winrate']:.1f}%")
    print(f"  Поставлено: {r['total_staked']:,.0f} руб")
    print(f"  Прибыль: {r['total_profit']:+,.0f} руб")
    print(f"  {roi_icon} ROI: {r['roi']:+.2f}%")
    print(f"  Банк: {BANK:,.0f} → {r['final_bank']:,.0f} руб "
          f"({r['bank_growth']:+.1f}%)")

    if verbose and r["bets_list"]:
        print(f"\n  Лучшая ставка: {r['best_bet']['home']} — {r['best_bet']['away']} "
              f"| {r['best_bet']['market']} @ {r['best_bet']['odds']} "
              f"| +{r['best_bet']['profit']:,.0f} руб")
        print(f"  Худшая ставка: {r['worst_bet']['home']} — {r['worst_bet']['away']} "
              f"| {r['worst_bet']['market']} @ {r['worst_bet']['odds']} "
              f"| {r['worst_bet']['profit']:,.0f} руб")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league",    default=None, help="EPL/BL1/SA/PD/FL1/RPL")
    ap.add_argument("--season",    default=None, help="2024/2023/2022")
    ap.add_argument("--strategy",  default=None, help="Конкретная стратегия")
    ap.add_argument("--min-odds",  type=float, default=1.4)
    ap.add_argument("--max-odds",  type=float, default=5.0)
    ap.add_argument("--all",       action="store_true", help="Все лиги и сезоны")
    ap.add_argument("--verbose",   action="store_true")
    ap.add_argument("--top",       type=int, default=5, help="Топ-N лучших ставок")
    args = ap.parse_args()

    conn = get_conn()

    # Проверяем есть ли данные
    count = conn.execute("SELECT COUNT(*) FROM backtest_matches").fetchone()[0]
    if count == 0:
        print("❌ Нет исторических данных. Запусти сначала:")
        print("   python backtest_downloader.py")
        conn.close()
        return

    # Фильтруем матчи
    where = ["result IS NOT NULL", "result != ''",
             "odds_home > 0", "odds_draw > 0", "odds_away > 0"]
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

    if not rows:
        print("❌ Нет матчей для бэктеста")
        return

    print(f"\n{'='*60}")
    print(f"  BETAGENT — БЭКТЕСТ")
    print(f"  Матчей: {len(rows)}")
    if args.league:
        print(f"  Лига: {args.league}")
    if args.season:
        print(f"  Сезон: {args.season}")
    print(f"  Банк: {BANK:,.0f} руб | Kelly×0.25 | Макс ставка: 5%")
    print(f"{'='*60}")

    strategies = [args.strategy] if args.strategy else [
        "value_home",
        "value_away",
        "low_odds_home",
        "draw_equal",
        "away_underdog",
    ]

    results = []
    for strategy in strategies:
        r = run_backtest(rows, strategy, BANK, args.min_odds, args.max_odds)
        r["strategy"] = strategy
        results.append(r)
        print_result(r, verbose=args.verbose)

    # Сводка
    print(f"\n{'='*60}")
    print("  СВОДКА (по ROI):")
    valid = [r for r in results if r["bets"] > 0]
    valid.sort(key=lambda r: r["roi"], reverse=True)
    for r in valid:
        roi_icon = "✅" if r["roi"] >= 4 else ("⚠️" if r["roi"] >= 0 else "❌")
        print(f"  {roi_icon} {r['strategy']:20s} | "
              f"{r['bets']:4d} ставок | "
              f"ROI: {r['roi']:+6.2f}% | "
              f"Прибыль: {r['total_profit']:+,.0f} руб")

    # Лучшие ставки по всем стратегиям
    if args.verbose or args.top:
        all_bets = []
        for r in valid:
            for b in r.get("bets_list", []):
                b["strategy"] = r["strategy"]
                all_bets.append(b)
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

    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
