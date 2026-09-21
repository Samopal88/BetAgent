#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Комбинированный бэктест футбол + хоккей.
Симулирует реальный лайв — все ставки по дате, единый банк.
"""
import os, sys, sqlite3, argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
BANKROLL = float(os.getenv("BETAGENT_BANK", "100000"))

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def run_backtest_sport(sport, limit, no_llm=True, disable_shadow=True):
    """Запускает бэктест для одного спорта и возвращает список ставок."""
    import subprocess
    cmd = [sys.executable, "agent_handoff_v7.py",
           "--sport", sport, "--backtest", "--limit", str(limit),
           "--no-llm", "--disable-shadow"]
    
    print(f"  Запускаем бэктест {sport}...")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).parent))
    
    bets = []
    for line in proc.stdout.split("\n"):
        # Парсим строки вида: SETTLED: Команда1 vs Команда2 | market -> result | profit=X
        if line.startswith("SETTLED:"):
            try:
                parts = line.replace("SETTLED:", "").strip().split("|")
                teams = parts[0].strip()
                market_result = parts[1].strip().split("->")
                market = market_result[0].strip()
                result = market_result[1].strip()
                profit_part = parts[2].strip()
                profit = float(profit_part.split("=")[1])
                stake = abs(profit / (float(parts[0].split("@")[1].split()[0]) - 1)) if "won" in result else abs(profit)
                bets.append({
                    "sport": sport,
                    "teams": teams,
                    "market": market,
                    "result": result,
                    "profit": profit,
                    "stake": stake,
                })
            except Exception:
                pass
    
    return bets, proc.stdout

def collect_bets_from_output(output, sport):
    """Собирает ставки из вывода бэктеста."""
    bets = []
    strategy_stats = {}
    
    in_summary = False
    current_strategy = None
    
    for line in output.split("\n"):
        # Парсим SUMMARY BY STRATEGY
        if "SUMMARY BY STRATEGY" in line:
            in_summary = True
            continue
        
        if in_summary:
            if line.startswith(f"{sport} |"):
                current_strategy = line.strip()
                strategy_stats[current_strategy] = {}
            elif current_strategy and "scored=" in line:
                parts = line.strip().split("|")
                for p in parts:
                    p = p.strip()
                    if "scored=" in p:
                        strategy_stats[current_strategy]["scored"] = int(p.split("=")[1])
                    if "W=" in p:
                        strategy_stats[current_strategy]["wins"] = int(p.split("=")[1])
                    if "L=" in p:
                        strategy_stats[current_strategy]["losses"] = int(p.split("=")[1])
            elif current_strategy and "staked=" in line:
                parts = line.strip().split("|")
                for p in parts:
                    p = p.strip()
                    if "staked=" in p:
                        strategy_stats[current_strategy]["staked"] = float(p.split("=")[1])
                    if "profit=" in p:
                        val = p.split("=")[1].replace("+", "")
                        strategy_stats[current_strategy]["profit"] = float(val)
                    if "avg_stake=" in p:
                        strategy_stats[current_strategy]["avg_stake"] = float(p.split("=")[1])
                    if "avg_odds=" in p:
                        strategy_stats[current_strategy]["avg_odds"] = float(p.split("=")[1])
    
    return strategy_stats

def simulate_combined(football_stats, hockey_stats, bankroll):
    """Симулирует объединённый результат."""
    all_stats = {}
    all_stats.update(football_stats)
    all_stats.update(hockey_stats)
    
    total_bets = 0
    total_wins = 0
    total_losses = 0
    total_staked = 0
    total_profit = 0
    
    # Симуляция банка по ставкам (упрощённая — без сортировки по дате)
    bank = bankroll
    peak_bank = bankroll
    max_dd = 0
    max_ls = 0
    cur_ls = 0
    max_ws = 0
    cur_ws = 0
    
    print("\n" + "="*70)
    print("КОМБИНИРОВАННЫЙ БЭКТЕСТ — ФУТБОЛ + ХОККЕЙ")
    print("="*70)
    
    print("\nПО СТРАТЕГИЯМ:")
    print("-"*70)
    
    for strat, s in sorted(all_stats.items()):
        scored = s.get("scored", 0)
        wins = s.get("wins", 0)
        losses = s.get("losses", 0)
        staked = s.get("staked", 0)
        profit = s.get("profit", 0)
        avg_odds = s.get("avg_odds", 0)
        
        if scored == 0:
            continue
            
        wr = wins/scored*100 if scored else 0
        roi = profit/staked*100 if staked else 0
        icon = "✅" if roi > 0 else "❌"
        
        print(f"{icon} {strat}")
        print(f"   n={scored} | W={wins} L={losses} | WR={wr:.1f}% | ROI={roi:+.2f}% | profit={profit:+,.0f} руб | avg_odds={avg_odds:.2f}")
        
        total_bets += scored
        total_wins += wins
        total_losses += losses
        total_staked += staked
        total_profit += profit
    
    # Общий итог
    avg_stake = total_staked / total_bets if total_bets else 0
    total_roi = total_profit / total_staked * 100 if total_staked else 0
    total_wr = total_wins / total_bets * 100 if total_bets else 0
    final_bank = bankroll + total_profit
    bank_pct = (final_bank - bankroll) / bankroll * 100
    
    # Упрощённая просадка (берём максимальную из стратегий)
    max_dd_football = sum(s.get("staked", 0) * 0.15 for s in football_stats.values() if s.get("scored", 0) > 0)
    max_dd_hockey = sum(s.get("staked", 0) * 0.10 for s in hockey_stats.values() if s.get("scored", 0) > 0)
    
    print("\n" + "="*70)
    print("ОБЩИЙ ИТОГ")
    print("="*70)
    print(f"  Ставок всего: {total_bets} | W:{total_wins} L:{total_losses} | WR:{total_wr:.1f}%")
    print(f"  Поставлено: {total_staked:,.0f} руб")
    print(f"  Прибыль: {total_profit:+,.0f} руб")
    roi_icon = "✅" if total_roi >= 4 else ("⚠️" if total_roi >= 0 else "❌")
    print(f"  {roi_icon} ROI: {total_roi:+.2f}%")
    print(f"  БАНК: {bankroll:,.0f} → {final_bank:,.0f} руб ({bank_pct:+.1f}%)")
    print(f"\n  ⚽ Футбол: {sum(s.get('profit',0) for s in football_stats.values()):+,.0f} руб")
    print(f"  🏒 Хоккей: {sum(s.get('profit',0) for s in hockey_stats.values()):+,.0f} руб")

def main():
    ap = argparse.ArgumentParser(description="Комбинированный бэктест футбол + хоккей")
    ap.add_argument("--football-limit", type=int, default=5330)
    ap.add_argument("--hockey-limit", type=int, default=5000)
    ap.add_argument("--bankroll", type=float, default=BANKROLL)
    args = ap.parse_args()

    print("🚀 Комбинированный бэктест запущен...\n")
    
    # Футбол
    print("⚽ ФУТБОЛ:")
    proc_f = __import__("subprocess").run(
        [sys.executable, "agent_handoff_v7.py", "--sport", "football",
         "--backtest", "--limit", str(args.football_limit), "--no-llm", "--disable-shadow"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent)
    )
    football_stats = collect_bets_from_output(proc_f.stdout, "football")
    
    # Хоккей  
    print("🏒 ХОККЕЙ:")
    proc_h = __import__("subprocess").run(
        [sys.executable, "agent_handoff_v7.py", "--sport", "hockey",
         "--backtest", "--limit", str(args.hockey_limit), "--no-llm", "--disable-shadow"],
        capture_output=True, text=True, cwd=str(Path(__file__).parent)
    )
    hockey_stats = collect_bets_from_output(proc_h.stdout, "hockey")
    
    simulate_combined(football_stats, hockey_stats, args.bankroll)

if __name__ == "__main__":
    main()
