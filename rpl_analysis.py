#!/usr/bin/env python3
"""Анализ стратегий для РПЛ"""
import sqlite3

conn = sqlite3.connect("betagent.db")
conn.row_factory = sqlite3.Row

print("="*70)
print("РПЛ — БАЗОВАЯ СТАТИСТИКА")
print("="*70)

r = conn.execute("""
    SELECT COUNT(*) as n,
           AVG(home_score+away_score) as avg_goals,
           AVG(CASE WHEN home_score>away_score THEN 1.0 ELSE 0.0 END) as home_wr,
           AVG(CASE WHEN home_score=away_score THEN 1.0 ELSE 0.0 END) as draw_rate,
           AVG(CASE WHEN away_score>home_score THEN 1.0 ELSE 0.0 END) as away_wr,
           AVG(CASE WHEN home_score>0 AND away_score>0 THEN 1.0 ELSE 0.0 END) as btts_rate,
           AVG(CASE WHEN home_score+away_score>2 THEN 1.0 ELSE 0.0 END) as over25_rate,
           AVG(CASE WHEN home_score+away_score<=1 THEN 1.0 ELSE 0.0 END) as under15_rate
    FROM backtest_matches
    WHERE league='RPL' AND home_score IS NOT NULL
""").fetchone()

print(f"Матчей: {r['n']}")
print(f"Средние голы: {r['avg_goals']:.2f}")
print(f"Хозяева: {r['home_wr']:.1%} | Ничья: {r['draw_rate']:.1%} | Гость: {r['away_wr']:.1%}")
print(f"BTTS: {r['btts_rate']:.1%} | Over2.5: {r['over25_rate']:.1%} | Under1.5: {r['under15_rate']:.1%}")

print("\n" + "="*70)
print("ПО СЕЗОНАМ")
print("="*70)
rows = conn.execute("""
    SELECT season,
           COUNT(*) as n,
           AVG(home_score+away_score) as avg_goals,
           AVG(CASE WHEN home_score>0 AND away_score>0 THEN 1.0 ELSE 0.0 END) as btts,
           AVG(CASE WHEN home_score+away_score>2 THEN 1.0 ELSE 0.0 END) as over25,
           AVG(CASE WHEN home_score+away_score<=1 THEN 1.0 ELSE 0.0 END) as under15,
           AVG(CASE WHEN home_score=away_score THEN 1.0 ELSE 0.0 END) as draws
    FROM backtest_matches
    WHERE league='RPL' AND home_score IS NOT NULL
    GROUP BY season ORDER BY season
""").fetchall()
print(f"{'Сезон':<8} {'n':>5} {'Голы':>6} {'BTTS':>7} {'O2.5':>7} {'U1.5':>7} {'Ничья':>7}")
print("-"*55)
for r in rows:
    print(f"{r['season']:<8} {r['n']:>5} {r['avg_goals']:>6.2f} {r['btts']:>7.1%} {r['over25']:>7.1%} {r['under15']:>7.1%} {r['draws']:>7.1%}")

print("\n" + "="*70)
print("ТЕСТ СТРАТЕГИЙ")
print("="*70)

strategies = [
    ("BTTS да 1.85-2.10", "odds_btts_yes BETWEEN 1.85 AND 2.10", "home_score>0 AND away_score>0", "odds_btts_yes"),
    ("BTTS да 1.90-2.10", "odds_btts_yes BETWEEN 1.90 AND 2.10", "home_score>0 AND away_score>0", "odds_btts_yes"),
    ("BTTS да 2.00-2.20", "odds_btts_yes BETWEEN 2.00 AND 2.20", "home_score>0 AND away_score>0", "odds_btts_yes"),
    ("Over 1.5 (1.5-2.5)", "odds_over_1_5 BETWEEN 1.5 AND 2.5", "home_score+away_score>1", "odds_over_1_5"),
    ("Over 1.5 (2.0-3.0)", "odds_over_1_5 BETWEEN 2.0 AND 3.0", "home_score+away_score>1", "odds_over_1_5"),
    ("Under 1.5 (3.0+)", "odds_under_1_5 >= 3.0", "home_score+away_score<=1", "odds_under_1_5"),
    ("Under 2.5 (1.4-1.8)", "odds_under_2_5 BETWEEN 1.4 AND 1.8", "home_score+away_score<=2", "odds_under_2_5"),
    ("Over 2.5 (1.8-2.5)", "odds_over_2_5 BETWEEN 1.8 AND 2.5", "home_score+away_score>2", "odds_over_2_5"),
    ("Draw (2.8-3.8)", "odds_draw BETWEEN 2.8 AND 3.8", "home_score=away_score", "odds_draw"),
    ("Draw (3.0-4.0)", "odds_draw BETWEEN 3.0 AND 4.0", "home_score=away_score", "odds_draw"),
    ("Away dog (3.0-5.0)", "odds_away BETWEEN 3.0 AND 5.0", "away_score>home_score", "odds_away"),
    ("Home fav (1.4-1.8)", "odds_home BETWEEN 1.4 AND 1.8", "home_score>away_score", "odds_home"),
    ("Home fav (1.5-2.0)", "odds_home BETWEEN 1.5 AND 2.0", "home_score>away_score", "odds_home"),
]

print(f"{'Стратегия':<25} {'n':>5} {'WR':>7} {'avg_odds':>9} {'ROI':>8}")
print("-"*60)
for name, cond, win, odds_col in strategies:
    r = conn.execute(f"""
        SELECT COUNT(*) as n,
               SUM(CASE WHEN {win} THEN 1 ELSE 0 END) as wins,
               AVG({odds_col}) as avg_odds,
               SUM(CASE WHEN {win} THEN {odds_col}-1 ELSE -1 END) as profit
        FROM backtest_matches
        WHERE league='RPL' AND home_score IS NOT NULL AND {cond}
    """).fetchone()
    if not r['n'] or r['n'] < 20: continue
    roi = r['profit']/r['n']*100
    wr = r['wins']/r['n']
    icon = "✅" if roi > 5 else ("⚡" if roi > 0 else "❌")
    print(f"{icon} {name:<23} {r['n']:>5} {wr:>7.1%} {r['avg_odds']:>9.2f} {roi:>8.1f}%")

conn.close()
