import sqlite3
from collections import defaultdict

DB = "/root/betagent/betagent.db"

conn = sqlite3.connect(DB)

# =====================================================================
# 1. Load all backtest_tennis_players matches (with sets_winner)
# =====================================================================
print("Loading backtest_tennis_players...")
players_rows = conn.execute("""
    SELECT id, tour, year, tourney_name, surface, tourney_level, tourney_date,
           round, winner_name, winner_rank, loser_name, loser_rank,
           sets_winner, sets_loser, straight_sets
    FROM backtest_tennis_players
    WHERE sets_winner IS NOT NULL AND winner_rank IS NOT NULL
    ORDER BY winner_name, tourney_date
""").fetchall()
print(f"Loaded {len(players_rows)} player-level matches")

# Group by player for rolling dom_pct
player_matches = defaultdict(list)
for row in players_rows:
    pid, tour, yr, tname, surf, tlevel, tdate, rnd, wname, wrank, lname, lrank, sw, sl, ss = row
    player_matches[wname].append({
        'id': pid, 'tour': tour, 'year': yr, 'tourney_name': tname,
        'surface': surf, 'tourney_level': tlevel, 'tourney_date': tdate,
        'round': rnd, 'winner_name': wname, 'winner_rank': wrank,
        'loser_name': lname, 'loser_rank': lrank,
        'sets_winner': sw, 'sets_loser': sl, 'straight_sets': ss,
        'rank_gap': (lrank - wrank) if (wrank and lrank) else None,  # positive = winner was better ranked
        'rank_diff_signed': (wrank - lrank) if (wrank and lrank) else None,
    })

print(f"Players: {len(player_matches)}")

# =====================================================================
# 2. Compute rolling dom_pct per player
# =====================================================================
print("\nComputing rolling dom_pct...")

for player, matches in player_matches.items():
    for i, m in enumerate(matches):
        prior = matches[:i]
        last10 = prior[-10:] if len(prior) >= 10 else prior
        if len(last10) >= 3:
            dom_count = sum(1 for p in last10 if p['straight_sets'] == 1)
            m['dom_pct'] = dom_count / len(last10) * 100
            m['dom_n'] = len(last10)
        else:
            m['dom_pct'] = None
            m['dom_n'] = len(last10) if prior else 0

# Flatten
all_with_dom = [m for m_list in player_matches.values() for m in m_list if m['dom_pct'] is not None]
total_no_dom = len([m for m_list in player_matches.values() for m in m_list if m['dom_pct'] is None])
print(f"Matches with dom_pct (>=3 prior): {len(all_with_dom)}")
print(f"Matches without sufficient form data: {total_no_dom}")

# Debug: show rank_gap distribution for context
wta = [m for m in all_with_dom if m['tour'] == 'WTA']
gaps = [m['rank_gap'] for m in wta if m['rank_gap'] is not None]
if gaps:
    fav_wins = [g for g in gaps if g > 0]  # winner ranked better
    upset_wins = [g for g in gaps if g < 0]  # winner ranked worse
    print(f"\nWTA rank_gap (= loser_rank - winner_rank):")
    print(f"  Favorite wins (gap>0): {len(fav_wins)}, median gap={sorted(fav_wins)[len(fav_wins)//2] if fav_wins else 'N/A'}")
    print(f"  Upset wins (gap<0): {len(upset_wins)}, median gap={sorted(upset_wins)[len(upset_wins)//2] if upset_wins else 'N/A'}")

# =====================================================================
# 3. Test filter configs
#    rank_gap = loser_rank - winner_rank (positive = winner ranked better)
# =====================================================================

CONFIGS = [
    {
        'label': 'WTA r<=15, gap 50-150, dom>=65',
        'tour': ['WTA'],
        'winner_rank_max': 15,
        'rank_gap_min': 50,     # winner ranked 50+ spots better than loser
        'rank_gap_max': 150,
        'dom_pct_min': 65,
        'tourney_levels': None,
    },
    {
        'label': 'WTA r<=10, gap>=50, dom>=60',
        'tour': ['WTA'],
        'winner_rank_max': 10,
        'rank_gap_min': 50,
        'rank_gap_max': None,
        'dom_pct_min': 60,
        'tourney_levels': None,
    },
    {
        'label': 'ATP+WTA r<=10, gap>=80, dom>=70',
        'tour': ['ATP', 'WTA'],
        'winner_rank_max': 10,
        'rank_gap_min': 80,
        'rank_gap_max': None,
        'dom_pct_min': 70,
        'tourney_levels': None,
    },
    {
        'label': 'WTA r<=20, gap>=50, dom>=75',
        'tour': ['WTA'],
        'winner_rank_max': 20,
        'rank_gap_min': 50,
        'rank_gap_max': None,
        'dom_pct_min': 75,
        'tourney_levels': None,
    },
    {
        'label': 'WTA r<=15, gap>=60, dom>=65, GS/M',
        'tour': ['WTA'],
        'winner_rank_max': 15,
        'rank_gap_min': 60,
        'rank_gap_max': None,
        'dom_pct_min': 65,
        'tourney_levels': ['G', 'M'],
    },
]

def is_straight(m):
    return m['straight_sets'] == 1

def roi(pct, odds):
    return (pct / 100.0 * odds - 1) * 100

output = []
def emit(text):
    print(text)
    output.append(text)

summary = []

for cfg in CONFIGS:
    emit(f"\n{'='*70}")
    emit(f"CONFIG: {cfg['label']}")
    emit(f"{'='*70}")

    filtered = []
    for m in all_with_dom:
        if cfg['tour'] and m['tour'] not in cfg['tour']:
            continue
        if m['winner_rank'] > cfg['winner_rank_max']:
            continue
        if m['rank_gap'] is None or m['rank_gap'] < cfg['rank_gap_min']:
            continue
        if cfg['rank_gap_max'] is not None and m['rank_gap'] > cfg['rank_gap_max']:
            continue
        if m['dom_pct'] < cfg['dom_pct_min']:
            continue
        if cfg['tourney_levels'] and m['tourney_level'] not in cfg['tourney_levels']:
            continue
        filtered.append(m)

    if not filtered:
        emit(f"  No matches found")
        summary.append((cfg['label'], 0, 0, 0, 0, 0, "---"))
        continue

    emit(f"{'Year':<6} {'N':>5} {'Straight%':>10} {'AvgGap':>7} {'AvgDom%':>8} {'AvgRank':>7}")
    emit(f"{'-'*70}")

    total_n = total_straight = 0
    pos_years = all_years = 0

    by_year = defaultdict(list)
    for m in filtered:
        by_year[m['year']].append(m)

    for yr in sorted(by_year.keys()):
        grp = by_year[yr]
        if yr == 2026:
            continue
        all_years += 1
        n = len(grp)
        straight = sum(1 for m in grp if is_straight(m))
        straight_pct = straight / n * 100
        avg_dom = sum(m['dom_pct'] for m in grp) / n
        avg_gap = sum(m['rank_gap'] for m in grp if m['rank_gap'] is not None) / max(sum(1 for m in grp if m['rank_gap'] is not None), 1)
        avg_rk = sum(m['winner_rank'] for m in grp if m['winner_rank'] is not None) / max(sum(1 for m in grp if m['winner_rank'] is not None), 1)

        total_n += n
        total_straight += straight
        if straight_pct > 60:
            pos_years += 1

        emit(f"{yr:<6} {n:>5} {straight_pct:>9.1f}% {avg_gap:>6.0f} {avg_dom:>7.1f}% {avg_rk:>6.0f}")

    overall_straight_pct = total_straight / total_n * 100 if total_n else 0
    avg_yr_n = total_n / all_years if all_years else 0

    emit(f"{'-'*70}")
    emit(f"TOTAL  {total_n:>5} {overall_straight_pct:>9.1f}%")
    emit(f"  Positive years: {pos_years}/{all_years}, avg n/year: {avg_yr_n:.0f}")

    # Per-surface
    emit(f"\n  By surface:")
    by_surf = defaultdict(list)
    for m in filtered:
        by_surf[m['surface']].append(m)
    for surf in sorted(by_surf.keys()):
        sgrp = by_surf[surf]
        sn = len(sgrp)
        ss = sum(1 for m in sgrp if is_straight(m))
        spct = ss/sn*100
        emit(f"    {surf:<7} N={sn:>4} Straight={spct:>5.1f}%")

    # Summary line — target: straight% >= 65%, stable over 4/5 years, n>=15/yr
    flag = "PASS" if (overall_straight_pct >= 65 and pos_years >= 4 and avg_yr_n >= 15) else "FAIL"
    summary.append((cfg['label'], total_n, overall_straight_pct,
                    pos_years, all_years, avg_yr_n, flag))

# =====================================================================
# 4. Summary
# =====================================================================
emit(f"\n{'='*70}")
emit(f"SUMMARY — Target: Straight%>=65%, stable 4/5 yrs, n>=15/yr")
emit(f"{'='*70}")
emit(f"{'Config':<35} {'N':>6} {'Str%':>6} {'PosYrs':>8} {'AvgN':>5} {'Result':>6}")
emit(f"{'-'*70}")
for lbl, n, spct, py, ay, avn, fl in summary:
    emit(f"{lbl:<35} {n:>6} {spct:>5.1f}% {py:>3}/{ay} {avn:>4.0f} {fl:>6}")

# Save
with open("/tmp/tennis_strict_filters.txt", "w") as f:
    f.write("\n".join(output))

emit(f"\nNOTE: ROI unavailable — backtest_tennis_players and backtest_tennis_matches")
emit(f"have ~2% match population overlap (tournament results vs Fonbet-scraped odds).")
