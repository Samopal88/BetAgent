#!/usr/bin/env python3
import sqlite3, re
from collections import defaultdict

DB = "betagent.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

MAPPING = {}
exec(open('/root/betagent/tennis_player_mapping_tdo.py', encoding='utf-8', errors='ignore').read())
MAPPING = TENNIS_DATA_TO_BETZ

def count_games(score_detail):
    """Считаем суммарные геймы из '6:4, 7:6, 6:3' -> 32"""
    if not score_detail:
        return None
    nums = re.findall(r'\d+', score_detail)
    return sum(int(n) for n in nums) if nums else None

print("Загружаем данные...")
tdo = conn.execute("""
    SELECT winner, loser, year, surface, round, tournament,
           w_rank, l_rank, w_sets, l_sets, ps_winner, ps_loser, b365_winner
    FROM tennis_data_odds
    WHERE ps_winner IS NOT NULL AND w_sets IS NOT NULL
""").fetchall()

betz = conn.execute("""
    SELECT player1, player2, match_date, tour, surface, level,
           odds_total_over, odds_total_under, total_line,
           sets_winner, sets_loser, score_detail
    FROM backtest_tennis_matches
    WHERE odds_total_under IS NOT NULL AND score_detail IS NOT NULL
      AND total_line IS NOT NULL
""").fetchall()

# Индексируем betz по (player1, year)
betz_idx = defaultdict(list)
for row in betz:
    yr = row['match_date'][:4] if row['match_date'] else ''
    betz_idx[(row['player1'], yr)].append(row)

# JOIN
matched = []
for t in tdo:
    rus = MAPPING.get(t['winner'])
    if not rus:
        continue
    yr = str(t['year'])
    for b in betz_idx.get((rus, yr), []):
        games = count_games(b['score_detail'])
        if games is None:
            continue
        matched.append({
            'ps_winner': t['ps_winner'],
            'ps_loser': t['ps_loser'],
            'w_rank': t['w_rank'],
            'l_rank': t['l_rank'],
            'w_sets': t['w_sets'],
            'l_sets': t['l_sets'],
            'surface': t['surface'],
            'round': t['round'],
            'level': t['tournament'],
            'year': yr,
            'odds_under': b['odds_total_under'],
            'odds_over': b['odds_total_over'],
            'total_line': b['total_line'],
            'actual_games': games,
            'actual_sets': (b['sets_winner'] or 0) + (b['sets_loser'] or 0),
        })

print(f"Совпадений: {len(matched)}")
if not matched:
    exit()

def analyze(rows, label):
    if not rows:
        return
    n = len(rows)
    under_wins = sum(1 for r in rows if r['actual_games'] < r['total_line'])
    under_profit = sum(r['odds_under']-1 if r['actual_games'] < r['total_line'] else -1 for r in rows)
    over_wins = sum(1 for r in rows if r['actual_games'] > r['total_line'])
    over_profit = sum(r['odds_over']-1 if r['actual_games'] > r['total_line'] else -1 for r in rows)
    print(f"\n{label} (n={n})")
    print(f"  Under: hit={100*under_wins/n:.1f}% ROI={100*under_profit/n:+.1f}%")
    print(f"  Over:  hit={100*over_wins/n:.1f}% ROI={100*over_profit/n:+.1f}%")

# Анализ
analyze(matched, "ВСЕ МАТЧИ")
analyze([r for r in matched if r['ps_winner'] < 1.30], "Большой фаворит ps<1.30")
analyze([r for r in matched if r['ps_winner'] < 1.50], "Фаворит ps<1.50")
analyze([r for r in matched if r['ps_winner'] > 2.0], "Андердог ps>2.0")
analyze([r for r in matched if r['surface'] == 'Hard'], "Hard корт")
analyze([r for r in matched if r['surface'] == 'Clay'], "Clay корт")
analyze([r for r in matched if r['surface'] == 'Grass'], "Grass корт")
analyze([r for r in matched if 'Grand Slam' in (r['level'] or '') or r['level'] in ['ausopen','wimbledon','usopen','frenchopen']], "Grand Slams")

# По годам
for yr in sorted(set(r['year'] for r in matched)):
    analyze([r for r in matched if r['year'] == yr], f"Год {yr}")

conn.close()
