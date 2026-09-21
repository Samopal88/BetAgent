#!/usr/bin/env python3
"""
Deep analysis of ALL hockey betting markets in backtest_hockey_features table.
Analyzes DRAW, HOME WIN, AWAY WIN, OVER/UNDER, Playoffs, and Team-level strategies.
Saves report to hockey_strategies_report.md
"""

import sqlite3
import os
from collections import defaultdict
from datetime import datetime

DB_PATH = "/root/betagent/betagent.db"
REPORT_PATH = os.path.join(os.path.dirname(__file__), "hockey_strategies_report.md")

LEAGUES = [
    'Хоккей. NHL. Регулярный чемпионат.',
    'Хоккей. КХЛ. Регулярный чемпионат.',
    'Хоккей. Финляндия. Liiga.',
    'Хоккей. Финляндия. Mestis.',
    'Хоккей. Швеция. SHL.',
    'Хоккей. Швейцария. National League.',
    'Хоккей. Германия. DEL.',
    'Хоккей. Чехия. Extraliga.',
    'Хоккей. NHL. Плей-офф. 1/8 финала. До 4-х побед.',
    'Хоккей. КХЛ. Плей-офф. 1/8 финала. До 4-х побед.',
]

PLAYOFF_LEAGUES = [
    'Хоккей. NHL. Плей-офф. 1/8 финала. До 4-х побед.',
    'Хоккей. КХЛ. Плей-офф. 1/8 финала. До 4-х побед.',
]

REGULAR_LEAGUES = [l for l in LEAGUES if l not in PLAYOFF_LEAGUES]

# Acceptance criteria
MIN_ROI = 10.0  # +10%
MIN_YEARS_POSITIVE = 4  # positive in 4/5 years
MIN_BETS_PER_YEAR = 20
MIN_TEAM_GAMES = 15
MIN_TEAM_SEASONS = 3


def get_conn():
    return sqlite3.connect(DB_PATH)


def extract_year(season_key):
    """Extract start year from season_key like '2022/2023' -> 2022"""
    if not season_key or '/' not in season_key:
        return None
    try:
        return int(season_key.split('/')[0])
    except:
        return None


def calc_roi(bets):
    """Calculate ROI from list of (odds, result_bool) tuples."""
    # Filter out None odds
    clean = [(o, h) for o, h in bets if o is not None and o > 1.0]
    if not clean:
        return 0, 0, 0, 0
    total_stake = len(clean)
    total_return = sum(odds for odds, hit in clean if hit)
    profit = total_return - total_stake
    roi = (profit / total_stake) * 100 if total_stake > 0 else 0
    hit_pct = sum(1 for _, hit in clean if hit) / len(clean) * 100
    avg_odds = sum(odds for odds, _ in clean) / len(clean)
    return roi, hit_pct, avg_odds, total_stake


def max_consecutive_losses(bets):
    """Calculate max consecutive losses."""
    max_loss = 0
    cur_loss = 0
    for _, hit in bets:
        if not hit:
            cur_loss += 1
            max_loss = max(max_loss, cur_loss)
        else:
            cur_loss = 0
    return max_loss


def format_short_name(league):
    """Short league name for display."""
    if 'NHL' in league:
        if 'Плей' in league:
            return 'NHL ПО'
        return 'NHL'
    if 'КХЛ' in league:
        if 'Плей' in league:
            return 'КХЛ ПО'
        return 'КХЛ'
    if 'Liiga' in league:
        return 'Liiga'
    if 'Mestis' in league:
        return 'Mestis'
    if 'SHL' in league:
        return 'SHL'
    if 'National League' in league:
        return 'NL'
    if 'DEL' in league:
        return 'DEL'
    if 'Extraliga' in league:
        return 'Czech'
    return league[:30]


def run_query(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


def run_query_df(conn, sql, params=()):
    """Return list of dicts."""
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ============================================================
# ANALYSIS FUNCTIONS
# ============================================================

def analyze_draw_odds(conn):
    """Analyze DRAW (X) betting strategies by odds ranges and filters."""
    results = []

    draw_ranges = [
        ('3.5-4.0', 3.5, 4.0),
        ('4.0-4.5', 4.0, 4.5),
        ('4.5-5.0', 4.5, 5.0),
        ('5.0-5.5', 5.0, 5.5),
    ]

    strength_filters = [
        ('all', None, None),
        ('sd<0.1', -0.1, 0.1),
        ('sd<0.2', -0.2, 0.2),
        ('sd<0.3', -0.3, 0.3),
    ]

    form_filters = [
        ('all', None),
        ('form_diff<0.15', 0.15),
        ('form_diff<0.10', 0.10),
    ]

    for league in LEAGUES:
        short = format_short_name(league)
        for range_name, lo, hi in draw_ranges:
            for sf_name, sf_lo, sf_hi in strength_filters:
                for ff_name, ff_thresh in form_filters:
                    # Build query
                    where = f"league = ? AND odds_draw IS NOT NULL AND odds_draw >= {lo} AND odds_draw < {hi}"
                    params = [league]

                    if sf_lo is not None:
                        where += " AND strength_diff_ppg >= ? AND strength_diff_ppg <= ?"
                        params.extend([sf_lo, sf_hi])

                    if ff_thresh is not None:
                        where += " AND ABS(form5_home_winrate - form5_away_winrate) <= ?"
                        params.append(ff_thresh)

                    sql = f"SELECT season_key, odds_draw, result_regulation FROM backtest_hockey_features WHERE {where}"
                    rows = run_query(conn, sql, params)

                    if len(rows) < 30:
                        continue

                    # Group by year
                    by_year = defaultdict(list)
                    for season, odds, result in rows:
                        yr = extract_year(season)
                        if yr:
                            by_year[yr].append((odds, result == 'draw'))

                    years_positive = sum(1 for yr, bets in by_year.items()
                                         if calc_roi(bets)[0] > 0 and len(bets) >= 5)
                    total_years = len(by_year)

                    all_bets = [(odds, result == 'draw') for _, odds, result in rows]
                    roi, hit_pct, avg_odds, n = calc_roi(all_bets)

                    # Check if passes criteria
                    years_with_enough = sum(1 for yr, bets in by_year.items() if len(bets) >= MIN_BETS_PER_YEAR // 3)
                    passes = (roi > MIN_ROI and
                              years_positive >= MIN_YEARS_POSITIVE and
                              years_with_enough >= 3)

                    results.append({
                        'type': 'DRAW',
                        'league': short,
                        'league_full': league,
                        'filter': f'odds {range_name}, {sf_name}, {ff_name}',
                        'n': n,
                        'roi': roi,
                        'hit_pct': hit_pct,
                        'avg_odds': avg_odds,
                        'years': total_years,
                        'years_positive': years_positive,
                        'years_with_enough': years_with_enough,
                        'passes': passes,
                        'by_year': by_year,
                        'all_bets': all_bets,
                    })

    return results


def analyze_home_win(conn):
    """Analyze HOME WIN (П1) strategies."""
    results = []

    home_ranges = [
        ('1.30-1.50', 1.30, 1.50),
        ('1.50-1.70', 1.50, 1.70),
        ('1.70-2.00', 1.70, 2.00),
        ('2.00-2.30', 2.00, 2.30),
    ]

    filter_sets = [
        ('all', None, None, None),
        ('form5>0.5', 0.5, None, None),
        ('sd>0.2', None, 0.2, None),
        ('form5>0.5+sd>0.2', 0.5, 0.2, None),
        ('form5=1.0', 1.0, None, 'form5_all_wins'),
    ]

    for league in LEAGUES:
        short = format_short_name(league)
        for range_name, lo, hi in home_ranges:
            for fs_name, form_thresh, sd_thresh, special in filter_sets:
                where = f"league = ? AND odds_home IS NOT NULL AND odds_home >= {lo} AND odds_home < {hi}"
                params = [league]

                if form_thresh is not None and special != 'form5_all_wins':
                    where += " AND form5_home_winrate >= ?"
                    params.append(form_thresh)

                if sd_thresh is not None:
                    where += " AND strength_diff_ppg >= ?"
                    params.append(sd_thresh)

                if special == 'form5_all_wins':
                    where += " AND form5_home_winrate >= 1.0"

                sql = f"SELECT season_key, odds_home, result_regulation FROM backtest_hockey_features WHERE {where}"
                rows = run_query(conn, sql, params)

                if len(rows) < 30:
                    continue

                by_year = defaultdict(list)
                for season, odds, result in rows:
                    yr = extract_year(season)
                    if yr:
                        by_year[yr].append((odds, result == 'home'))

                years_positive = sum(1 for yr, bets in by_year.items()
                                     if calc_roi(bets)[0] > 0 and len(bets) >= 5)
                total_years = len(by_year)

                all_bets = [(odds, result == 'home') for _, odds, result in rows]
                roi, hit_pct, avg_odds, n = calc_roi(all_bets)

                years_with_enough = sum(1 for yr, bets in by_year.items() if len(bets) >= MIN_BETS_PER_YEAR // 3)
                passes = (roi > MIN_ROI and
                          years_positive >= MIN_YEARS_POSITIVE and
                          years_with_enough >= 3)

                results.append({
                    'type': 'HOME_WIN',
                    'league': short,
                    'league_full': league,
                    'filter': f'odds {range_name}, {fs_name}',
                    'n': n,
                    'roi': roi,
                    'hit_pct': hit_pct,
                    'avg_odds': avg_odds,
                    'years': total_years,
                    'years_positive': years_positive,
                    'years_with_enough': years_with_enough,
                    'passes': passes,
                    'by_year': by_year,
                    'all_bets': all_bets,
                })

    return results


def analyze_away_win(conn):
    """Analyze AWAY WIN (П2) strategies."""
    results = []

    away_ranges = [
        ('1.80-2.20', 1.80, 2.20),
        ('2.20-2.60', 2.20, 2.60),
        ('2.60-3.00', 2.60, 3.00),
    ]

    filter_sets = [
        ('all', None, None),
        ('sd<-0.3', -0.3, None),
        ('form5>0.6', None, 0.6),
        ('sd<-0.3+form5>0.6', -0.3, 0.6),
    ]

    for league in LEAGUES:
        short = format_short_name(league)
        for range_name, lo, hi in away_ranges:
            for fs_name, sd_thresh, form_thresh in filter_sets:
                where = f"league = ? AND odds_away IS NOT NULL AND odds_away >= {lo} AND odds_away < {hi}"
                params = [league]

                if sd_thresh is not None:
                    where += " AND strength_diff_ppg <= ?"
                    params.append(sd_thresh)

                if form_thresh is not None:
                    where += " AND form5_away_winrate >= ?"
                    params.append(form_thresh)

                sql = f"SELECT season_key, odds_away, result_regulation FROM backtest_hockey_features WHERE {where}"
                rows = run_query(conn, sql, params)

                if len(rows) < 30:
                    continue

                by_year = defaultdict(list)
                for season, odds, result in rows:
                    yr = extract_year(season)
                    if yr:
                        by_year[yr].append((odds, result == 'away'))

                years_positive = sum(1 for yr, bets in by_year.items()
                                     if calc_roi(bets)[0] > 0 and len(bets) >= 5)
                total_years = len(by_year)

                all_bets = [(odds, result == 'away') for _, odds, result in rows]
                roi, hit_pct, avg_odds, n = calc_roi(all_bets)

                years_with_enough = sum(1 for yr, bets in by_year.items() if len(bets) >= MIN_BETS_PER_YEAR // 3)
                passes = (roi > MIN_ROI and
                          years_positive >= MIN_YEARS_POSITIVE and
                          years_with_enough >= 3)

                results.append({
                    'type': 'AWAY_WIN',
                    'league': short,
                    'league_full': league,
                    'filter': f'odds {range_name}, {fs_name}',
                    'n': n,
                    'roi': roi,
                    'hit_pct': hit_pct,
                    'avg_odds': avg_odds,
                    'years': total_years,
                    'years_positive': years_positive,
                    'years_with_enough': years_with_enough,
                    'passes': passes,
                    'by_year': by_year,
                    'all_bets': all_bets,
                })

    return results


def analyze_totals(conn):
    """Analyze OVER/UNDER total strategies."""
    results = []

    total_lines = [4.5, 5.0, 5.5, 6.0, 6.5]

    for league in LEAGUES:
        short = format_short_name(league)
        for tl in total_lines:
            for market in ['over', 'under']:
                odds_col = f'odds_total_{market}'
                where = f"league = ? AND total_line = ? AND {odds_col} IS NOT NULL AND {odds_col} > 1.0"
                params = [league, tl]

                sql = f"SELECT season_key, {odds_col}, total_goals, total_line FROM backtest_hockey_features WHERE {where}"

                # We need to compute total_goals from regulation scores
                sql = f"""
                    SELECT season_key, {odds_col},
                           (regulation_home_score + regulation_away_score) as total_goals,
                           total_line
                    FROM backtest_hockey_features
                    WHERE {where}
                      AND regulation_home_score IS NOT NULL
                      AND regulation_away_score IS NOT NULL
                """
                rows = run_query(conn, sql, params)

                if len(rows) < 30:
                    continue

                by_year = defaultdict(list)
                for season, odds, total_goals, tline in rows:
                    if total_goals is None or tline is None:
                        continue
                    yr = extract_year(season)
                    if yr:
                        if market == 'over':
                            hit = total_goals > tline
                        else:
                            hit = total_goals < tline
                        by_year[yr].append((odds, hit))

                years_positive = sum(1 for yr, bets in by_year.items()
                                     if calc_roi(bets)[0] > 0 and len(bets) >= 5)
                total_years = len(by_year)

                all_bets = []
                for season, odds, total_goals, tline in rows:
                    if total_goals is None or tline is None:
                        continue
                    if market == 'over':
                        hit = total_goals > tline
                    else:
                        hit = total_goals < tline
                    all_bets.append((odds, hit))

                roi, hit_pct, avg_odds, n = calc_roi(all_bets)

                years_with_enough = sum(1 for yr, bets in by_year.items() if len(bets) >= MIN_BETS_PER_YEAR // 3)
                passes = (roi > MIN_ROI and
                          years_positive >= MIN_YEARS_POSITIVE and
                          years_with_enough >= 3)

                results.append({
                    'type': f'TOTAL_{market.upper()}',
                    'league': short,
                    'league_full': league,
                    'filter': f'line={tl}',
                    'n': n,
                    'roi': roi,
                    'hit_pct': hit_pct,
                    'avg_odds': avg_odds,
                    'years': total_years,
                    'years_positive': years_positive,
                    'years_with_enough': years_with_enough,
                    'passes': passes,
                    'by_year': by_year,
                    'all_bets': all_bets,
                })

    return results


def analyze_team_level(conn):
    """Team-level deep dive: top teams by ROI for each market type."""
    results = []

    market_configs = [
        ('HOME_WIN', 'home', 'odds_home', 'П1'),
        ('AWAY_WIN', 'away', 'odds_away', 'П2'),
        ('DRAW', 'draw', 'odds_draw', 'X'),
    ]

    for league in LEAGUES:
        short = format_short_name(league)

        for mkt_type, result_val, odds_col, mkt_label in market_configs:
            # Get all matches for this league with valid odds
            sql = f"""
                SELECT season_key, home_team, away_team, {odds_col} as odds,
                       result_regulation
                FROM backtest_hockey_features
                WHERE league = ? AND {odds_col} IS NOT NULL AND {odds_col} > 1.0
            """
            rows = run_query(conn, sql, [league])

            if not rows:
                continue

            # Group by team
            team_bets = defaultdict(list)
            for season, home, away, odds, result in rows:
                if result_val == 'home':
                    team = home
                    hit = (result == 'home')
                elif result_val == 'away':
                    team = away
                    hit = (result == 'away')
                else:  # draw
                    # For draw, both teams are involved
                    team_bets[(home, season)].append((odds, result == 'draw'))
                    team_bets[(away, season)].append((odds, result == 'draw'))
                    continue

                team_bets[(team, season)].append((odds, hit))

            # Aggregate per team
            team_stats = defaultdict(lambda: {'bets': [], 'seasons': set()})
            for (team, season), bets in team_bets.items():
                if len(bets) < 5:
                    continue
                team_stats[team]['bets'].extend(bets)
                team_stats[team]['seasons'].add(season)

            # Filter: min games and min seasons
            qualified = {}
            for team, data in team_stats.items():
                if len(data['bets']) >= MIN_TEAM_GAMES and len(data['seasons']) >= MIN_TEAM_SEASONS:
                    roi, hit_pct, avg_odds, n = calc_roi(data['bets'])
                    by_year = defaultdict(list)
                    for (t, s), bets in team_bets.items():
                        if t == team and len(bets) >= 5:
                            yr = extract_year(s)
                            if yr:
                                by_year[yr].extend(bets)
                    years_positive = sum(1 for yr, bets in by_year.items()
                                         if calc_roi(bets)[0] > 0)
                    qualified[team] = {
                        'roi': roi,
                        'hit_pct': hit_pct,
                        'avg_odds': avg_odds,
                        'n': n,
                        'seasons': len(data['seasons']),
                        'years_positive': years_positive,
                        'total_years': len(by_year),
                        'by_year': by_year,
                        'bets': data['bets'],
                    }

            # Sort by ROI descending
            sorted_teams = sorted(qualified.items(), key=lambda x: x[1]['roi'], reverse=True)

            for team, stats in sorted_teams[:10]:
                passes = (stats['roi'] > MIN_ROI and
                          stats['years_positive'] >= MIN_YEARS_POSITIVE and
                          stats['n'] >= MIN_TEAM_GAMES)

                results.append({
                    'type': f'TEAM_{mkt_type}',
                    'league': short,
                    'league_full': league,
                    'filter': f'team={team}, {mkt_label}',
                    'n': stats['n'],
                    'roi': stats['roi'],
                    'hit_pct': stats['hit_pct'],
                    'avg_odds': stats['avg_odds'],
                    'years': stats['total_years'],
                    'years_positive': stats['years_positive'],
                    'years_with_enough': stats['total_years'],
                    'passes': passes,
                    'by_year': stats['by_year'],
                    'all_bets': stats['bets'],
                    'team': team,
                })

    return results


def analyze_playoffs_vs_regular(conn):
    """Compare regular season vs playoffs metrics."""
    results = []

    # Find leagues that have both regular and playoff versions
    regular_map = {
        'Хоккей. NHL. Плей-офф. 1/8 финала. До 4-х побед.': 'Хоккей. NHL. Регулярный чемпионат.',
        'Хоккей. КХЛ. Плей-офф. 1/8 финала. До 4-х побед.': 'Хоккей. КХЛ. Регулярный чемпионат.',
    }

    for playoff_league, regular_league in regular_map.items():
        p_short = format_short_name(playoff_league)
        r_short = format_short_name(regular_league)

        # Home win rate comparison
        for label, league, short in [('Regular', regular_league, r_short),
                                      ('Playoff', playoff_league, p_short)]:
            sql = """
                SELECT season_key, odds_home, result_regulation,
                       home_advantage_ppg, strength_diff_ppg,
                       form5_home_winrate
                FROM backtest_hockey_features
                WHERE league = ? AND odds_home IS NOT NULL
            """
            rows = run_query(conn, sql, [league])

            if not rows:
                continue

            by_year = defaultdict(list)
            for season, odds, result, ha, sd, f5 in rows:
                yr = extract_year(season)
                if yr:
                    by_year[yr].append((odds, result == 'home'))

            all_bets = [(odds, result == 'home') for _, odds, result, _, _, _ in rows]
            roi, hit_pct, avg_odds, n = calc_roi(all_bets)

            results.append({
                'type': 'PLAYOFF_COMPARISON',
                'league': short,
                'league_full': league,
                'filter': f'{label} - HOME WIN all odds',
                'n': n,
                'roi': roi,
                'hit_pct': hit_pct,
                'avg_odds': avg_odds,
                'years': len(by_year),
                'years_positive': sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0),
                'years_with_enough': len(by_year),
                'passes': False,  # informational only
                'by_year': by_year,
                'all_bets': all_bets,
            })

        # Draw rate comparison
        for label, league, short in [('Regular', regular_league, r_short),
                                      ('Playoff', playoff_league, p_short)]:
            sql = """
                SELECT season_key, odds_draw, result_regulation
                FROM backtest_hockey_features
                WHERE league = ? AND odds_draw IS NOT NULL
            """
            rows = run_query(conn, sql, [league])

            if not rows:
                continue

            by_year = defaultdict(list)
            for season, odds, result in rows:
                yr = extract_year(season)
                if yr:
                    by_year[yr].append((odds, result == 'draw'))

            all_bets = [(odds, result == 'draw') for _, odds, result in rows]
            roi, hit_pct, avg_odds, n = calc_roi(all_bets)

            results.append({
                'type': 'PLAYOFF_COMPARISON',
                'league': short,
                'league_full': league,
                'filter': f'{label} - DRAW all odds',
                'n': n,
                'roi': roi,
                'hit_pct': hit_pct,
                'avg_odds': avg_odds,
                'years': len(by_year),
                'years_positive': sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0),
                'years_with_enough': len(by_year),
                'passes': False,
                'by_year': by_year,
                'all_bets': all_bets,
            })

        # Totals comparison
        for label, league, short in [('Regular', regular_league, r_short),
                                      ('Playoff', playoff_league, p_short)]:
            sql = """
                SELECT season_key, odds_total_over, total_line,
                       (regulation_home_score + regulation_away_score) as total_goals
                FROM backtest_hockey_features
                WHERE league = ? AND odds_total_over IS NOT NULL AND total_line IS NOT NULL
                  AND regulation_home_score IS NOT NULL AND regulation_away_score IS NOT NULL
            """
            rows = run_query(conn, sql, [league])

            if not rows:
                continue

            by_year = defaultdict(list)
            for season, odds, tline, total_goals in rows:
                if total_goals is None or tline is None:
                    continue
                yr = extract_year(season)
                if yr:
                    hit = total_goals > tline
                    by_year[yr].append((odds, hit))

            all_bets = []
            for _, odds, tline, total_goals in rows:
                if total_goals is None or tline is None:
                    continue
                all_bets.append((odds, total_goals > tline))

            roi, hit_pct, avg_odds, n = calc_roi(all_bets)

            results.append({
                'type': 'PLAYOFF_COMPARISON',
                'league': short,
                'league_full': league,
                'filter': f'{label} - OVER all lines',
                'n': n,
                'roi': roi,
                'hit_pct': hit_pct,
                'avg_odds': avg_odds,
                'years': len(by_year),
                'years_positive': sum(1 for yr, bets in by_year.items() if calc_roi(bets)[0] > 0),
                'years_with_enough': len(by_year),
                'passes': False,
                'by_year': by_year,
                'all_bets': all_bets,
            })

    return results


# ============================================================
# REPORT GENERATION
# ============================================================

def generate_report(all_results):
    """Generate markdown report."""
    lines = []
    lines.append("# Hockey Betting Strategies — Deep Analysis Report\n")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"Database: {DB_PATH}\n")
    lines.append(f"Table: backtest_hockey_features\n")
    lines.append(f"Leagues analyzed: {len(LEAGUES)}\n")
    lines.append("")

    # Acceptance criteria
    lines.append("## Acceptance Criteria\n")
    lines.append(f"- ROI > +{MIN_ROI}%")
    lines.append(f"- Positive ROI in {MIN_YEARS_POSITIVE}/{5} years minimum")
    lines.append(f"- n >= {MIN_BETS_PER_YEAR} bets per year")
    lines.append(f"- Team-specific: n >= {MIN_TEAM_GAMES} games, {MIN_TEAM_SEASONS}+ seasons")
    lines.append("")

    # Summary
    passed = [r for r in all_results if r.get('passes', False)]
    total = len(all_results)

    lines.append("## Summary\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total strategies tested | {total} |")
    lines.append(f"| **PASSED** criteria | **{len(passed)}** |")
    lines.append(f"| Failed | {total - len(passed)} |")
    lines.append("")

    if passed:
        lines.append("### PASSED Strategies\n")
        lines.append("| # | Type | League | Filter | ROI% | n | Hit% | AvgOdds | Years+ |")
        lines.append("|---|------|--------|--------|------|---|------|---------|--------|")
        for i, r in enumerate(passed, 1):
            lines.append(f"| {i} | {r['type']} | {r['league']} | {r['filter']} | {r['roi']:+.1f}% | {r['n']} | {r['hit_pct']:.1f}% | {r['avg_odds']:.2f} | {r['years_positive']}/{r['years']} |")
        lines.append("")

    # Top 20 by ROI (even if not passing)
    lines.append("## Top 20 Strategies by ROI\n")
    sorted_results = sorted(all_results, key=lambda x: x['roi'], reverse=True)
    lines.append("| # | Type | League | Filter | ROI% | n | Hit% | AvgOdds | Pass? |")
    lines.append("|---|------|--------|--------|------|---|------|---------|-------|")
    for i, r in enumerate(sorted_results[:20], 1):
        pass_mark = "✅" if r.get('passes') else "❌"
        lines.append(f"| {i} | {r['type']} | {r['league']} | {r['filter']} | {r['roi']:+.1f}% | {r['n']} | {r['hit_pct']:.1f}% | {r['avg_odds']:.2f} | {pass_mark} |")
    lines.append("")

    # Detailed sections by type
    sections = {
        'DRAW': [r for r in all_results if r['type'] == 'DRAW'],
        'HOME_WIN': [r for r in all_results if r['type'] == 'HOME_WIN'],
        'AWAY_WIN': [r for r in all_results if r['type'] == 'AWAY_WIN'],
        'TOTAL_OVER': [r for r in all_results if r['type'] == 'TOTAL_OVER'],
        'TOTAL_UNDER': [r for r in all_results if r['type'] == 'TOTAL_UNDER'],
        'TEAM_HOME_WIN': [r for r in all_results if r['type'] == 'TEAM_HOME_WIN'],
        'TEAM_AWAY_WIN': [r for r in all_results if r['type'] == 'TEAM_AWAY_WIN'],
        'TEAM_DRAW': [r for r in all_results if r['type'] == 'TEAM_DRAW'],
        'PLAYOFF_COMPARISON': [r for r in all_results if r['type'] == 'PLAYOFF_COMPARISON'],
    }

    section_titles = {
        'DRAW': '## 1. DRAW (X) Strategies',
        'HOME_WIN': '## 2. HOME WIN (П1) Strategies',
        'AWAY_WIN': '## 3. AWAY WIN (П2) Strategies',
        'TOTAL_OVER': '## 4. OVER Total Strategies',
        'TOTAL_UNDER': '## 5. UNDER Total Strategies',
        'TEAM_HOME_WIN': '## 6. Team-Level HOME WIN',
        'TEAM_AWAY_WIN': '## 7. Team-Level AWAY WIN',
        'TEAM_DRAW': '## 8. Team-Level DRAW',
        'PLAYOFF_COMPARISON': '## 9. Playoffs vs Regular Season Comparison',
    }

    for section_key, title in section_titles.items():
        items = sections.get(section_key, [])
        if not items:
            continue

        lines.append(f"\n{title}\n")

        # Show top items by ROI
        items_sorted = sorted(items, key=lambda x: x['roi'], reverse=True)

        # For team-level, show top 10 per league
        if section_key.startswith('TEAM_'):
            leagues_seen = set()
            shown = 0
            for r in items_sorted:
                if r['league'] not in leagues_seen:
                    leagues_seen.add(r['league'])
                    shown += 1
                if shown > 50:
                    break

                pass_mark = "✅ PASS" if r.get('passes') else ""
                lines.append(f"### {r['league']} — {r['filter']} {pass_mark}\n")
                lines.append(f"ROI: {r['roi']:+.1f}% | n={r['n']} | Hit%: {r['hit_pct']:.1f}% | AvgOdds: {r['avg_odds']:.2f}\n")

                if r.get('by_year'):
                    lines.append("| Year | n | Hit% | AvgOdds | ROI% |")
                    lines.append("|------|---|------|---------|------|")
                    for yr in sorted(r['by_year'].keys()):
                        yr_roi, yr_hit, yr_avg, yr_n = calc_roi(r['by_year'][yr])
                        lines.append(f"| {yr} | {yr_n} | {yr_hit:.1f}% | {yr_avg:.2f} | {yr_roi:+.1f}% |")
                    lines.append("")
        else:
            # For non-team strategies, show all that have ROI > 0 or pass
            shown_items = [r for r in items_sorted if r['roi'] > 0 or r.get('passes')]
            if not shown_items:
                lines.append("*No profitable strategies found.*\n")
                continue

            for r in shown_items[:100]:
                pass_mark = "✅ PASS" if r.get('passes') else ""
                lines.append(f"### {r['league']} — {r['filter']} {pass_mark}\n")
                lines.append(f"ROI: {r['roi']:+.1f}% | n={r['n']} | Hit%: {r['hit_pct']:.1f}% | AvgOdds: {r['avg_odds']:.2f}\n")

                if r.get('by_year'):
                    lines.append("| Year | n | Hit% | AvgOdds | ROI% |")
                    lines.append("|------|---|------|---------|------|")
                    for yr in sorted(r['by_year'].keys()):
                        yr_roi, yr_hit, yr_avg, yr_n = calc_roi(r['by_year'][yr])
                        lines.append(f"| {yr} | {yr_n} | {yr_hit:.1f}% | {yr_avg:.2f} | {yr_roi:+.1f}% |")
                    lines.append("")

    # Final PASSED strategies summary
    lines.append("\n---\n")
    lines.append("## PASSED STRATEGIES SUMMARY\n")

    if passed:
        for i, r in enumerate(passed, 1):
            lines.append(f"### Strategy #{i}: {r['type']} | {r['league']} | {r['filter']}\n")
            lines.append(f"- **ROI:** {r['roi']:+.1f}%")
            lines.append(f"- **Total bets:** {r['n']}")
            lines.append(f"- **Hit rate:** {r['hit_pct']:.1f}%")
            lines.append(f"- **Average odds:** {r['avg_odds']:.2f}")
            lines.append(f"- **Years positive:** {r['years_positive']}/{r['years']}")

            if r.get('all_bets'):
                mcl = max_consecutive_losses(r['all_bets'])
                lines.append(f"- **Max consecutive losses:** ~{mcl}")

            if r.get('by_year'):
                lines.append("")
                lines.append("| Year | n | Hit% | AvgOdds | ROI% |")
                lines.append("|------|---|------|---------|------|")
                for yr in sorted(r['by_year'].keys()):
                    yr_roi, yr_hit, yr_avg, yr_n = calc_roi(r['by_year'][yr])
                    lines.append(f"| {yr} | {yr_n} | {yr_hit:.1f}% | {yr_avg:.2f} | {yr_roi:+.1f}% |")

            if r.get('team'):
                lines.append(f"\n**Team:** {r['team']}")

            lines.append("")
    else:
        lines.append("*No strategies met all acceptance criteria.*\n")
        lines.append("### Near-miss strategies (ROI > 0 but didn't pass all criteria):\n")
        near_miss = [r for r in sorted(all_results, key=lambda x: x['roi'], reverse=True)
                     if r['roi'] > 0][:10]
        for r in near_miss:
            lines.append(f"- {r['type']} | {r['league']} | {r['filter']} | ROI: {r['roi']:+.1f}% | n={r['n']} | Years+: {r['years_positive']}/{r['years']}")

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("HOCKEY BETTING STRATEGIES — DEEP ANALYSIS")
    print("=" * 70)

    conn = get_conn()

    # Verify data
    total = run_query(conn, "SELECT COUNT(*) FROM backtest_hockey_features")[0][0]
    print(f"\nTotal matches in table: {total}")

    for league in LEAGUES:
        cnt = run_query(conn, "SELECT COUNT(*) FROM backtest_hockey_features WHERE league = ?", [league])[0][0]
        short = format_short_name(league)
        print(f"  {short}: {cnt} matches")

    all_results = []

    # 1. DRAW strategies
    print("\n[1/6] Analyzing DRAW strategies...")
    draw_results = analyze_draw_odds(conn)
    all_results.extend(draw_results)
    draw_pass = sum(1 for r in draw_results if r['passes'])
    print(f"  Tested: {len(draw_results)}, Passed: {draw_pass}")

    # 2. HOME WIN strategies
    print("\n[2/6] Analyzing HOME WIN strategies...")
    home_results = analyze_home_win(conn)
    all_results.extend(home_results)
    home_pass = sum(1 for r in home_results if r['passes'])
    print(f"  Tested: {len(home_results)}, Passed: {home_pass}")

    # 3. AWAY WIN strategies
    print("\n[3/6] Analyzing AWAY WIN strategies...")
    away_results = analyze_away_win(conn)
    all_results.extend(away_results)
    away_pass = sum(1 for r in away_results if r['passes'])
    print(f"  Tested: {len(away_results)}, Passed: {away_pass}")

    # 4. OVER/UNDER strategies
    print("\n[4/6] Analyzing OVER/UNDER strategies...")
    totals_results = analyze_totals(conn)
    all_results.extend(totals_results)
    totals_pass = sum(1 for r in totals_results if r['passes'])
    print(f"  Tested: {len(totals_results)}, Passed: {totals_pass}")

    # 5. Team-level analysis
    print("\n[5/6] Analyzing team-level strategies...")
    team_results = analyze_team_level(conn)
    all_results.extend(team_results)
    team_pass = sum(1 for r in team_results if r['passes'])
    print(f"  Tested: {len(team_results)}, Passed: {team_pass}")

    # 6. Playoffs vs Regular
    print("\n[6/6] Analyzing playoffs vs regular season...")
    playoff_results = analyze_playoffs_vs_regular(conn)
    all_results.extend(playoff_results)
    playoff_pass = sum(1 for r in playoff_results if r['passes'])
    print(f"  Tested: {len(playoff_results)}, Passed: {playoff_pass}")

    # Generate report
    print("\nGenerating report...")
    report = generate_report(all_results)

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\nReport saved to: {REPORT_PATH}")

    # Print summary
    passed = [r for r in all_results if r.get('passes', False)]
    print(f"\n{'=' * 70}")
    print(f"TOTAL: {len(all_results)} strategies tested, {len(passed)} PASSED")
    print(f"{'=' * 70}")

    if passed:
        print("\nPASSED STRATEGIES:")
        for i, r in enumerate(passed, 1):
            print(f"  {i}. [{r['type']}] {r['league']} | {r['filter']} | ROI: {r['roi']:+.1f}% | n={r['n']} | Years+: {r['years_positive']}/{r['years']}")
    else:
        print("\nNo strategies passed all criteria.")
        print("\nTop 10 by ROI:")
        for r in sorted(all_results, key=lambda x: x['roi'], reverse=True)[:10]:
            print(f"  [{r['type']}] {r['league']} | {r['filter']} | ROI: {r['roi']:+.1f}% | n={r['n']} | Years+: {r['years_positive']}/{r['years']}")

    conn.close()


if __name__ == '__main__':
    main()
