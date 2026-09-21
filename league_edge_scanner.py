#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
league_edge_scanner.py

Для каждой лиги в football_rolling_features считает:
  - Базовый ROI по каждому рынку (1X2, BTTS, Total) без фильтров
  - ROI с фильтром по форме (только матчи где есть данные)
  - ROI по сегментам (home fav / away fav / balanced)
  - Стабильность по годам (сколько лет в плюсе)

Цель: найти лиги где букмекер систематически ошибается на конкретном рынке.

Запуск:
  python league_edge_scanner.py
  python league_edge_scanner.py --min-n 50 --top 30
  python league_edge_scanner.py --market btts --min-n 30
"""

import os
import sqlite3
import argparse
from collections import defaultdict
from typing import Dict, List, Optional

DB_PATH = os.getenv("BETAGENT_DB", "betagent.db")


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_data(conn: sqlite3.Connection) -> List[Dict]:
    rows = conn.execute("""
        SELECT
            competition, country, match_date,
            result, btts, total_goals,
            odds_home, odds_draw, odds_away,
            odds_btts_yes, odds_btts_no,
            odds_total_over, odds_total_under, total_line,
            home_form_pts_5, away_form_pts_5,
            home_form_gf_5, away_form_gf_5,
            home_form_n_5, away_form_n_5,
            home_home_winrate_10, away_away_winrate_10,
            margin_1x2, margin_btts,
            has_odds_1x2, has_odds_btts, has_odds_total
        FROM football_rolling_features
        WHERE match_date < '2026-01-01'  -- тест оставляем нетронутым
        ORDER BY match_date ASC
    """).fetchall()
    return [dict(r) for r in rows]


def roi(bets: List[Dict], market: str) -> Optional[Dict]:
    """
    Считаем ROI для списка ставок.
    bet = {'odds': float, 'won': bool}
    """
    if not bets:
        return None
    total = len(bets)
    profit = sum((b['odds'] - 1) if b['won'] else -1 for b in bets)
    hits = sum(1 for b in bets if b['won'])
    return {
        'n': total,
        'roi': round(profit / total * 100, 2),
        'hit_rate': round(hits / total * 100, 1),
        'avg_odds': round(sum(b['odds'] for b in bets) / total, 3),
    }


def year_of(match_date: str) -> str:
    return match_date[:4]


def scan_league(matches: List[Dict]) -> Dict:
    """Полный анализ одной лиги."""
    result = {}
    n_total = len(matches)
    result['n_total'] = n_total

    # ── 1X2 ──────────────────────────────────────────────────────────────
    for outcome, key in [('H', 'home'), ('D', 'draw'), ('A', 'away')]:
        odds_key = f'odds_{key}'
        bets_all, bets_by_year = [], defaultdict(list)
        for m in matches:
            odds = m.get(odds_key)
            if not odds or not m['has_odds_1x2']:
                continue
            b = {'odds': odds, 'won': m['result'] == outcome}
            bets_all.append(b)
            bets_by_year[year_of(m['match_date'])].append(b)

        r = roi(bets_all, key)
        if r:
            years_pos = sum(1 for y, yb in bets_by_year.items()
                            if len(yb) >= 5 and roi(yb, key)['roi'] > 0)
            years_total = sum(1 for y, yb in bets_by_year.items() if len(yb) >= 5)
            r['years_pos'] = years_pos
            r['years_total'] = years_total
            result[f'1x2_{key}'] = r

    # ── BTTS ─────────────────────────────────────────────────────────────
    for outcome, key in [(1, 'yes'), (0, 'no')]:
        odds_key = f'odds_btts_{key}'
        bets_all, bets_by_year = [], defaultdict(list)
        for m in matches:
            odds = m.get(odds_key)
            if not odds or not m['has_odds_btts']:
                continue
            b = {'odds': odds, 'won': m['btts'] == outcome}
            bets_all.append(b)
            bets_by_year[year_of(m['match_date'])].append(b)

        r = roi(bets_all, key)
        if r:
            years_pos = sum(1 for y, yb in bets_by_year.items()
                            if len(yb) >= 5 and roi(yb, key)['roi'] > 0)
            years_total = sum(1 for y, yb in bets_by_year.items() if len(yb) >= 5)
            r['years_pos'] = years_pos
            r['years_total'] = years_total
            result[f'btts_{key}'] = r

    # ── TOTAL ─────────────────────────────────────────────────────────────
    for outcome, key in [('over', 'over'), ('under', 'under')]:
        odds_key = f'odds_total_{key}'
        bets_all, bets_by_year = [], defaultdict(list)
        for m in matches:
            odds = m.get(odds_key)
            line = m.get('total_line')
            if not odds or not m['has_odds_total'] or not line:
                continue
            total = m['total_goals']
            if outcome == 'over':
                won = total > line
            else:
                won = total < line
            b = {'odds': odds, 'won': won}
            bets_all.append(b)
            bets_by_year[year_of(m['match_date'])].append(b)

        r = roi(bets_all, key)
        if r:
            years_pos = sum(1 for y, yb in bets_by_year.items()
                            if len(yb) >= 5 and roi(yb, key)['roi'] > 0)
            years_total = sum(1 for y, yb in bets_by_year.items() if len(yb) >= 5)
            r['years_pos'] = years_pos
            r['years_total'] = years_total
            result[f'total_{key}'] = r

    # ── Сегментный анализ (только 1X2, balanced матчи) ───────────────────
    # balanced = abs(odds_home - odds_away) < 0.5, оба < 3.0
    balanced_home, balanced_away = [], []
    for m in matches:
        oh = m.get('odds_home')
        oa = m.get('odds_away')
        if not oh or not oa or not m['has_odds_1x2']:
            continue
        if abs(oh - oa) < 0.5 and oh < 3.5 and oa < 3.5:
            balanced_home.append({'odds': oh, 'won': m['result'] == 'H'})
            balanced_away.append({'odds': oa, 'won': m['result'] == 'A'})

    bal_h = roi(balanced_home, 'home')
    bal_a = roi(balanced_away, 'away')
    if bal_h:
        result['balanced_home'] = bal_h
    if bal_a:
        result['balanced_away'] = bal_a

    # ── Форм-фильтр: BTTS с формой ───────────────────────────────────────
    # Только матчи где обе команды среднее голов > 1.2 (атакующие)
    btts_form_yes, btts_form_no = [], []
    for m in matches:
        if not m['has_odds_btts']:
            continue
        hgf = m.get('home_form_gf_5')
        agf = m.get('away_form_gf_5')
        if hgf is None or agf is None:
            continue
        # Атакующие команды
        if hgf >= 1.2 and agf >= 1.2:
            if m.get('odds_btts_yes'):
                btts_form_yes.append({
                    'odds': m['odds_btts_yes'], 'won': m['btts'] == 1
                })
        # Защитные команды
        if hgf < 1.0 and agf < 1.0:
            if m.get('odds_btts_no'):
                btts_form_no.append({
                    'odds': m['odds_btts_no'], 'won': m['btts'] == 0
                })

    r_by = roi(btts_form_yes, 'btts_yes_attack')
    r_bn = roi(btts_form_no, 'btts_no_defense')
    if r_by:
        result['btts_yes_attack_form'] = r_by
    if r_bn:
        result['btts_no_defense_form'] = r_bn

    return result


def find_edges(data: List[Dict], min_n: int = 50) -> List[Dict]:
    """
    Группируем по лиге и ищем где ROI > 0 стабильно.
    """
    # Группировка
    by_league = defaultdict(list)
    for m in data:
        key = f"{m['competition']} | {m['country']}"
        by_league[key].append(m)

    edges = []

    for league_key, matches in by_league.items():
        if len(matches) < min_n:
            continue

        stats = scan_league(matches)
        comp, country = league_key.split(' | ')

        # Перебираем все рынки
        markets = [
            '1x2_home', '1x2_draw', '1x2_away',
            'btts_yes', 'btts_no',
            'total_over', 'total_under',
            'btts_yes_attack_form', 'btts_no_defense_form',
            'balanced_home', 'balanced_away',
        ]

        for market in markets:
            s = stats.get(market)
            if not s:
                continue
            if s['n'] < min_n:
                continue

            edge = {
                'league': comp,
                'country': country,
                'market': market,
                'n': s['n'],
                'roi': s['roi'],
                'hit_rate': s['hit_rate'],
                'avg_odds': s['avg_odds'],
                'years_pos': s.get('years_pos', '-'),
                'years_total': s.get('years_total', '-'),
                'stability': (f"{s.get('years_pos',0)}/{s.get('years_total',0)}"
                              if s.get('years_total') else '-'),
            }
            edges.append(edge)

    return edges


def print_report(edges: List[Dict], top: int = 30,
                 market_filter: Optional[str] = None,
                 min_roi: float = 3.0) -> None:

    if market_filter:
        edges = [e for e in edges if market_filter in e['market']]

    # Фильтр: только положительный ROI
    positive = [e for e in edges if e['roi'] >= min_roi]

    # Сортировка: сначала стабильные (много лет в плюсе), потом по ROI
    positive.sort(key=lambda x: (
        -(x['years_pos'] if isinstance(x['years_pos'], int) else 0),
        -x['roi']
    ))

    print(f"\n{'='*110}")
    print(f"LEAGUE EDGE SCANNER — Топ лиги с положительным ROI (min_roi={min_roi}%, min_n показан в фильтре)")
    print(f"{'='*110}")
    print(f"{'Лига':<35} {'Страна':<15} {'Рынок':<25} {'n':>5} {'ROI%':>7} {'HR%':>6} {'OddsAvg':>8} {'Стаб':>8}")
    print(f"{'-'*110}")

    shown = 0
    for e in positive:
        if shown >= top:
            break
        print(
            f"{e['league'][:34]:<35} "
            f"{e['country'][:14]:<15} "
            f"{e['market']:<25} "
            f"{e['n']:>5} "
            f"{e['roi']:>+7.1f}% "
            f"{e['hit_rate']:>5.1f}% "
            f"{e['avg_odds']:>8.3f} "
            f"{e['stability']:>8}"
        )
        shown += 1

    print(f"\nВсего положительных: {len(positive)} из {len(edges)} комбинаций лига×рынок")

    # Топ по рынкам
    print(f"\n{'='*60}")
    print("СВОДКА ПО РЫНКАМ (медианный ROI положительных):")
    print(f"{'='*60}")
    from collections import Counter
    market_groups = defaultdict(list)
    for e in positive:
        market_groups[e['market']].append(e['roi'])

    for mkt, rois in sorted(market_groups.items(), key=lambda x: -len(x[1])):
        med = sorted(rois)[len(rois)//2]
        print(f"  {mkt:<30} лиг: {len(rois):>3}  медиана ROI: {med:>+6.1f}%")

    # Топ стран
    print(f"\n{'='*60}")
    print("ТОП СТРАН (количество положительных лига×рынок):")
    print(f"{'='*60}")
    country_count = Counter(e['country'] for e in positive)
    for country, cnt in country_count.most_common(15):
        print(f"  {country:<20} {cnt:>3} позитивных комбинаций")


def save_to_db(conn: sqlite3.Connection, edges: List[Dict]) -> None:
    conn.execute("DROP TABLE IF EXISTS league_edge_report")
    conn.execute("""
        CREATE TABLE league_edge_report (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT, country TEXT, market TEXT,
            n INTEGER, roi REAL, hit_rate REAL, avg_odds REAL,
            years_pos INTEGER, years_total INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    for e in edges:
        conn.execute("""
            INSERT INTO league_edge_report
            (league, country, market, n, roi, hit_rate, avg_odds, years_pos, years_total)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            e['league'], e['country'], e['market'],
            e['n'], e['roi'], e['hit_rate'], e['avg_odds'],
            e.get('years_pos') if isinstance(e.get('years_pos'), int) else None,
            e.get('years_total') if isinstance(e.get('years_total'), int) else None,
        ))
    conn.commit()
    print(f"💾 Сохранено {len(edges)} строк в league_edge_report")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--min-n", type=int, default=50,
                    help="Минимум матчей для лиги (default: 50)")
    ap.add_argument("--min-roi", type=float, default=3.0,
                    help="Минимальный ROI%% для вывода (default: 3.0)")
    ap.add_argument("--top", type=int, default=40,
                    help="Топ N результатов (default: 40)")
    ap.add_argument("--market", default=None,
                    help="Фильтр по рынку: btts / 1x2 / total / balanced")
    ap.add_argument("--save", action="store_true",
                    help="Сохранить результаты в league_edge_report")
    args = ap.parse_args()

    print(f"🚀 league_edge_scanner.py")
    print(f"   DB: {args.db}, min_n={args.min_n}, min_roi={args.min_roi}%")

    conn = get_conn(args.db)

    print("📥 Загружаем данные...")
    data = load_data(conn)
    print(f"   Загружено: {len(data):,} матчей")

    print("⚙️  Сканируем лиги...")
    edges = find_edges(data, min_n=args.min_n)
    print(f"   Проанализировано комбинаций: {len(edges)}")

    print_report(edges, top=args.top,
                 market_filter=args.market,
                 min_roi=args.min_roi)

    if args.save:
        save_to_db(conn, edges)

    conn.close()


if __name__ == "__main__":
    main()
