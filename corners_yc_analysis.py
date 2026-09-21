#!/usr/bin/env python3
"""
Analyze backtest_football_stats for profitable corners/YC/cards strategies.
Correct column indices:
  0:id 1:league 2:match_date 3:home_team 4:away_team
  5:corners_home 6:corners_away 7:corners_total 8:corners_h1_home 9:corners_h1_away
  10:corners_odds_over 11:corners_odds_under 12:corners_line
  13:yc_home 14:yc_away 15:yc_total 16:yc_first_minute 17:yc_last_minute
  18:yc_odds_over 19:yc_odds_under 20:yc_line
  21:shots_home 22:shots_away 23:shots_odds_over 24:shots_odds_under 25:shots_line
"""

import sqlite3
from collections import defaultdict

DB = "/root/betagent/betagent.db"
SEASONS = ["2021", "2022", "2023", "2024", "2025"]

LEAGUES = {
    "BL1": "Футбол. Германия. Бундеслига.",
    "EPL": "Футбол. Англия. Премьер-лига.",
    "PD":  "Футбол. Испания. Примера Дивизион.",
    "FL1": "Футбол. Франция. Лига 1.",
    "RPL": ["Футбол. Россия. Премьер-Лига.", "Футбол. Россия. Премьер-лига."],
}

def get_season(match_date):
    if not match_date:
        return None
    parts = match_date.split("-")
    if len(parts) < 2:
        return None
    year, month = int(parts[0]), int(parts[1])
    return str(year) if month >= 8 else str(year - 1)

def max_losing_streak(results_list):
    max_streak = 0
    current = 0
    for row in results_list:
        if not row["won"]:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak

def analyze_segments(segments_data, seg_name="segment"):
    """Print per-segment per-year analysis.
    segments_data: list of {season, segment, won, odds}
    """
    year_seg = defaultdict(lambda: defaultdict(lambda: {"n": 0, "wins": 0, "win_odds_sum": 0.0, "results": []}))
    all_results = defaultdict(lambda: {"n": 0, "wins": 0, "win_odds_sum": 0.0, "results": []})

    for d in segments_data:
        odds_val = d.get("odds")
        if odds_val is None:
            odds_val = 0.0
        else:
            odds_val = float(odds_val)

        ys = year_seg[d["season"]][d["segment"]]
        ys["n"] += 1
        if d["won"]:
            ys["wins"] += 1
            ys["win_odds_sum"] += odds_val
        ys["results"].append({"won": d["won"], "odds": odds_val})

        ar = all_results[d["segment"]]
        ar["n"] += 1
        if d["won"]:
            ar["wins"] += 1
            ar["win_odds_sum"] += odds_val
        ar["results"].append({"won": d["won"], "odds": odds_val})

    all_segments_sorted = sorted(all_results.keys())

    print(f"\n{'Year':<7} | {seg_name:<35} | {'N':>5} | {'Hit%':>7} | {'ROI%':>7}")
    print("-" * 75)
    for season in SEASONS:
        if season not in year_seg:
            continue
        for seg in all_segments_sorted:
            ys = year_seg[season].get(seg)
            if not ys or ys["n"] == 0:
                continue
            pct = ys["wins"] / ys["n"] * 100
            roi = (ys["win_odds_sum"] / ys["n"] - 1) * 100
            print(f"{season:<7} | {seg:<35} | {ys['n']:>5} | {pct:>6.1f}% | {roi:>6.1f}%")

    # Overall by segment
    print(f"\n{'--- Overall ---'}")
    best_segments = []
    for seg in sorted(all_results, key=lambda s: all_results[s]["n"], reverse=True):
        ar = all_results[seg]
        if ar["n"] == 0:
            continue
        pct = ar["wins"] / ar["n"] * 100
        roi = (ar["win_odds_sum"] / ar["n"] - 1) * 100
        ml = max_losing_streak(ar["results"])
        print(f"{seg:<35} | N={ar['n']:>5} | Hit%={pct:>6.1f}% | ROI={roi:>6.1f}% | MaxLS={ml}")
        best_segments.append((seg, ar["n"], pct, roi, ml, ar["results"]))

    # Top 5 by ROI
    top = sorted(best_segments, key=lambda x: x[3], reverse=True)[:5]
    print(f"\n--- Top 5 by ROI — per-year breakdown ---")
    for seg, n, pct, roi, ml, results in top:
        print(f"\n  {seg} (N={n}, Hit%={pct:.1f}%, ROI={roi:.1f}%, MaxLS={ml}):")
        for season in SEASONS:
            ys = year_seg[season].get(seg)
            if ys and ys["n"] > 0:
                ypct = ys["wins"] / ys["n"] * 100
                yroi = (ys["win_odds_sum"] / ys["n"] - 1) * 100
                yml = max_losing_streak(ys["results"])
                print(f"    {season}: N={ys['n']:>3}, Hit%={ypct:>6.1f}%, ROI={yroi:>6.1f}%, MaxLS={yml}")

    return top


def safe_odds(val):
    return float(val) if val is not None else 0.0


# ==========================================
# 1. CORNERS OVER/UNDER by league
# ==========================================
print("="*80)
print("1. CORNERS OVER by league — which leagues beat the line")
print("="*80)

conn = sqlite3.connect(DB)

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND corners_line IS NOT NULL
          AND corners_total IS NOT NULL
          AND corners_odds_over IS NOT NULL
          AND corners_odds_over > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    results = []
    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue
        won = r[7] > r[12]  # corners_total > corners_line
        results.append({
            "season": season,
            "segment": "OVER",
            "won": won,
            "odds": r[10],  # corners_odds_over
            "home_team": r[3],
            "away_team": r[4],
        })

    # UNDER
    rows2 = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND corners_line IS NOT NULL
          AND corners_total IS NOT NULL
          AND corners_odds_under IS NOT NULL
          AND corners_odds_under > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    results2 = []
    for r in rows2:
        season = get_season(r[2])
        if season not in SEASONS:
            continue
        won = r[7] < r[12]  # corners_total < corners_line
        results2.append({
            "season": season,
            "segment": "UNDER",
            "won": won,
            "odds": r[11],  # corners_odds_under
        })

    print(f"\n--- {league_key}: Corners OVER ---")
    analyze_segments(results, "Corners")
    print(f"\n--- {league_key}: Corners UNDER ---")
    analyze_segments(results2, "Corners")


# ==========================================
# 2. CORNERS OVER by line bracket
# ==========================================
print("\n\n" + "="*80)
print("2. CORNERS OVER broken down by line value")
print("="*80)

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND corners_line IS NOT NULL
          AND corners_total IS NOT NULL
          AND corners_odds_over IS NOT NULL
          AND corners_odds_over > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    results = []
    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue
        line = r[12]  # corners_line
        if line <= 8.5:
            seg = "line<=8.5"
        elif line <= 9.5:
            seg = "line=9.0-9.5"
        elif line <= 10.5:
            seg = "line=10.0-10.5"
        elif line <= 11.5:
            seg = "line=11.0-11.5"
        else:
            seg = "line>11.5"

        won = r[7] > r[12]
        results.append({
            "season": season,
            "segment": seg,
            "won": won,
            "odds": r[10],
        })

    print(f"\n--- {league_key}: Corners OVER by line bracket ---")
    analyze_segments(results, "Line bracket")


# ==========================================
# 3. High-corner teams
# ==========================================
print("\n\n" + "="*80)
print("3. CORNERS OVER for specific high-corner teams")
print("="*80)

HIGH_CORNER_TEAMS = {
    "Манчестер Сити",
    "Байер", "Байер 04",
    "Бавария", "Бавария М",
    "Барселона",
    "Реал М",
    "Ливерпуль",
    "Арсенал",
    "Манчестер Юнайтед",
    "Челси",
    "Тоттенхэм",
    "ПСЖ",
    "Марсель",
}

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND corners_line IS NOT NULL
          AND corners_total IS NOT NULL
          AND corners_odds_over IS NOT NULL
          AND corners_odds_over > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    results = []
    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue

        won = r[7] > r[12]
        ht = r[3]
        at = r[4]

        if ht in HIGH_CORNER_TEAMS:
            results.append({
                "season": season,
                "segment": f"{ht} HOME OVER",
                "won": won,
                "odds": r[10],
            })

        if at in HIGH_CORNER_TEAMS:
            results.append({
                "season": season,
                "segment": f"{at} AWAY OVER",
                "won": won,
                "odds": r[10],
            })

    if results:
        print(f"\n--- {league_key}: High-corner teams corners OVER ---")
        analyze_segments(results, "Team")


# ==========================================
# 4. YC OVER by league
# ==========================================
print("\n\n" + "="*80)
print("4. YELLOW CARDS OVER by league")
print("="*80)

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND yc_line IS NOT NULL
          AND yc_total IS NOT NULL
          AND yc_odds_over IS NOT NULL
          AND yc_odds_over > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    results = []
    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue

        won = r[15] > r[20]  # yc_total > yc_line
        odds = r[18]  # yc_odds_over
        line = r[20]

        # Line bracket
        if line <= 3.5:
            line_seg = f"yc_line={line}"
        elif line <= 4.5:
            line_seg = "yc_line=4.0-4.5"
        elif line <= 5.5:
            line_seg = "yc_line=5.0-5.5"
        else:
            line_seg = f"yc_line>{5.5}"

        results.append({
            "season": season,
            "segment": line_seg,
            "won": won,
            "odds": odds,
            "yc_total": r[15],
            "yc_line": line,
        })

    if results:
        print(f"\n--- {league_key}: YC OVER by line bracket ---")
        analyze_segments(results, "YC Line bracket")


# ==========================================
# 5. YC OVER per league overall
# ==========================================
print("\n\n" + "="*80)
print("5. YC OVER — league comparison")
print("="*80)

all_yc_results = []
for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND yc_line IS NOT NULL
          AND yc_total IS NOT NULL
          AND yc_odds_over IS NOT NULL
          AND yc_odds_over > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    results = []
    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue
        won = r[15] > r[20]
        results.append({
            "season": season,
            "segment": league_key,
            "won": won,
            "odds": r[18],
            "yc_total": r[15],
            "yc_line": r[20],
        })

    if results:
        pct = sum(1 for x in results if x["won"]) / len(results) * 100
        roi = (sum(safe_odds(x["odds"]) for x in results if x["won"]) / len(results) - 1) * 100
        print(f"  {league_key}: N={len(results)}, Hit%={pct:.1f}%, ROI={roi:.1f}%")
        all_yc_results.extend(results)


# ==========================================
# 6. Shots OVER correlation with corners OVER
# ==========================================
print("\n\n" + "="*80)
print("6a. SHOTS OVER by league")
print("="*80)

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND shots_line IS NOT NULL
          AND shots_odds_over IS NOT NULL
          AND shots_odds_over > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    results = []
    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue
        shots_t = (r[21] or 0) + (r[22] or 0)
        if r[21] is None and r[22] is None:
            continue
        won = shots_t > r[25]
        corners_over = (r[7] > r[12]) if (r[7] is not None and r[12] is not None) else None
        results.append({
            "season": season,
            "segment": "SHOTS_OVER",
            "won": won,
            "odds": r[23],
            "shots_total": shots_t,
            "shots_line": r[25],
            "corners_total": r[7],
            "corners_line": r[12],
            "corners_over": corners_over,
        })

    if results:
        print(f"\n--- {league_key}: Shots OVER ---")
        analyze_segments(results, "Shots")


# 6b. Corners over hit rate WHEN shots over
print("\n\n" + "="*80)
print("6b. Corners OVER hit rate WHEN Shots OVER")
print("="*80)

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND shots_line IS NOT NULL
          AND corners_line IS NOT NULL
          AND corners_total IS NOT NULL
          AND corners_odds_over IS NOT NULL
          AND corners_odds_over > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    given_shots_over = []  # only when shots over
    both_over = []  # when both over

    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue
        shots_t = (r[21] or 0) + (r[22] or 0)
        if r[21] is None and r[22] is None:
            continue
        if r[7] is None or r[12] is None:
            continue
        shots_over = shots_t > r[25]
        corners_over = r[7] > r[12]

        if shots_over:
            given_shots_over.append({
                "season": season,
                "segment": "shots_over=>corners_over" if corners_over else "shots_over=>corners_under",
                "won": corners_over,
                "odds": r[10],
            })

        if shots_over and corners_over:
            both_over.append({
                "season": season,
                "segment": "both_over",
                "won": True,
                "odds": r[10],
            })

    if given_shots_over:
        print(f"\n--- {league_key}: Corners outcome GIVEN Shots OVER ---")
        analyze_segments(given_shots_over, "Outcome")

    if both_over:
        print(f"\n--- {league_key}: Matches where BOTH shots OVER and corners OVER ---")
        analyze_segments(both_over, "Match")


# ==========================================
# 7. Home vs away corners imbalance
# ==========================================
print("\n\n" + "="*80)
print("7. HOME vs AWAY corners imbalance → OVER/UNDER performance")
print("="*80)

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND corners_home IS NOT NULL
          AND corners_away IS NOT NULL
          AND corners_line IS NOT NULL
          AND corners_total IS NOT NULL
          AND corners_odds_over IS NOT NULL
          AND corners_odds_over > 0
          AND match_date < date('now', '-2 days')
        ORDER BY match_date ASC
    """, params).fetchall()

    results_over = []
    results_under = []
    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue

        ch = r[5]  # corners_home
        ca = r[6]  # corners_away
        diff = ch - ca
        over = r[7] > r[12]

        # Categorize by imbalance
        if diff >= 4:
            seg = "home_dominates(+4+)"
        elif diff >= 2:
            seg = "home_slightly(+2to+3)"
        elif diff >= -1:
            seg = "balanced(-1to+1)"
        elif diff >= -3:
            seg = "away_slightly(-3to-2)"
        else:
            seg = "away_dominates(-4-)"

        results_over.append({
            "season": season,
            "segment": seg,
            "won": over,
            "odds": r[10],
        })

        under_odds = r[11]
        if under_odds is not None and under_odds > 0:
            results_under.append({
                "season": season,
                "segment": seg,
                "won": not over,
                "odds": under_odds,
            })

    if results_over:
        print(f"\n--- {league_key}: Corners OVER by home/away imbalance ---")
        analyze_segments(results_over, "Imbalance")
    if results_under:
        print(f"\n--- {league_key}: Corners UNDER by home/away imbalance ---")
        analyze_segments(results_under, "Imbalance")


# ==========================================
# 8. Combined: corners + YC — are high-YC matches also high-corners?
# ==========================================
print("\n\n" + "="*80)
print("8. YC avg by league")
print("="*80)

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT AVG(yc_total), MIN(yc_total), MAX(yc_total), AVG(yc_line)
        FROM backtest_football_stats
        WHERE {where_clause}
          AND yc_total IS NOT NULL
    """, params).fetchone()

    if rows[0] is not None:
        print(f"  {league_key}: avg_yc={rows[0]:.1f}, min={rows[1]:.0f}, max={rows[2]:.0f}, avg_yc_line={rows[3]:.1f}")


# ==========================================
# 9. Shots line brackets
# ==========================================
print("\n\n" + "="*80)
print("9. SHOTS OVER by line bracket")
print("="*80)

for league_key, league_name in LEAGUES.items():
    where_clause = f"({' OR '.join(['league = ?' for _ in league_name])})" if isinstance(league_name, list) else "league = ?"
    params = league_name if isinstance(league_name, list) else [league_name]

    rows = conn.execute(f"""
        SELECT * FROM backtest_football_stats
        WHERE {where_clause}
          AND shots_line IS NOT NULL
          AND shots_total IS NOT NULL
          AND shots_odds_over IS NOT NULL
          AND shots_odds_over > 0
        ORDER BY match_date ASC
    """, params).fetchall()

    results = []
    for r in rows:
        season = get_season(r[2])
        if season not in SEASONS:
            continue
        shots_t = (r[21] or 0) + (r[22] or 0)
        line = r[25]
        if line <= 8.5:
            seg = "shots<=8.5"
        elif line <= 9.5:
            seg = "shots=9.0-9.5"
        elif line <= 10.5:
            seg = "shots=10.0-10.5"
        elif line <= 11.5:
            seg = "shots=11.0-11.5"
        elif line <= 12.5:
            seg = "shots=12.0-12.5"
        else:
            seg = "shots>12.5"

        won = shots_t > line
        results.append({
            "season": season,
            "segment": seg,
            "won": won,
            "odds": r[23],
        })

    if results:
        print(f"\n--- {league_key}: Shots OVER by line bracket ---")
        analyze_segments(results, "Shots line bracket")


print("\n\n" + "="*80)
print("ANALYSIS COMPLETE")
print("="*80)

conn.close()
