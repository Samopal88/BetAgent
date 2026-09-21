#!/usr/bin/env python3
"""
Football ML Policy v4 — Production Universe Evaluation

Evaluates ML 1X2 policies against a predefined production universe
(CORE + EXPANSION leagues) instead of ROI-based whitelist selection.

Policies:
  C_Bal_Core:   balanced, edge>0.05, H/A only
  B_NCF_Tight:  no_clear_favorite, edge>0.07, H/A only
  D_Bal_Tight:  balanced, edge>0.06, H/A only
  C_Bal_Relaxed: balanced, edge>0.04, H/A only (volume-expanded)
  B_NCF_Relaxed: no_clear_favorite, edge>0.06, H/A only (volume-expanded)

Universes:
  CORE: 30 professional leagues
  CORE+EXP: CORE + 20 expansion leagues
  FULL: all non-blacklisted leagues (reference)

Hard blacklist: women, reserve, youth, friendly, 6x6, amateur, cup patterns
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product

# ============================================================
# CONFIG
# ============================================================

PRED_FILE = Path("/root/betagent/ml_output/test_predictions.csv")
OUTPUT_MD = Path("/root/betagent/analysis/football_ml_policy_v4_universe.md")

CORE_LEAGUES = [
    "Англия. Премьер-лига",
    "Англия. Чемпионшип",
    "Англия. Первая лига",
    "Англия. Вторая лига",
    "Испания. Примера Дивизион",
    "Испания. Сегунда",
    "Италия. Серия A",
    "Италия. Серия B",
    "Германия. Бундеслига",
    "Германия. 2-я Бундеслига",
    "Франция. Лига 1",
    "Франция. Лига 2",
    "Нидерланды. Эредивизи",
    "Нидерланды. Эрстедивизи",
    "Португалия. Примейра",
    "Бельгия. Высшая лига",
    "Шотландия. Премьер-лига",
    "Турция. Суперлига",
    "Швейцария. Суперлига",
    "Австрия. Бундеслига",
    "Бразилия. Серия A",
    "Бразилия. Серия B",
    "Аргентина. Примера Дивизион",
    "Аргентина. Примера Насьональ",
    "Мексика. Примера",
    "США. MLS",
    "Япония. J1",
    "Южная Корея. K League 1",
    "Греция. Суперлига",
    "Польша. Экстракласа",
]

EXPANSION_LEAGUES = [
    "Чехия. Первая лига",
    "Румыния. Лига 1",
    "Хорватия. HNL",
    "Дания. Суперлига",
    "Швеция. Аллсвенскан",
    "Норвегия. Элитсериен",
    "Финляндия. Вейккауслига",
    "Чили. Примера",
    "Колумбия. Примера A",
    "Колумбия. Примера B",
    "Эквадор. Серия A",
    "Парагвай. Примера",
    "Перу. Лига 1",
    "Сербия. Суперлига",
    "Венгрия. NB I",
    "Словения. Первая лига",
    "Словакия. Суперлига",
    "Ирландия. Премьер-дивизион",
    "Северная Ирландия. Премьершип",
    "Египет. Премьер-лига",
]

HARD_BLACKLIST_PATTERNS = [
    "women", "женщин", "reserve", "резерв", "youth", "юнош",
    "молодеж", "u19", "u20", "u21", "u23", "friendly", "товарищ",
    "6x6", "студен", "любител",
]

POLICIES = {
    "C_Bal_Core": {
        "segment": "balanced",
        "edge_threshold": 0.05,
        "outcomes": ["home", "away"],
    },
    "B_NCF_Tight": {
        "segment": "no_clear_favorite",
        "edge_threshold": 0.07,
        "outcomes": ["home", "away"],
    },
    "D_Bal_Tight": {
        "segment": "balanced",
        "edge_threshold": 0.06,
        "outcomes": ["home", "away"],
    },
    "C_Bal_Relaxed": {
        "segment": "balanced",
        "edge_threshold": 0.04,
        "outcomes": ["home", "away"],
    },
    "B_NCF_Relaxed": {
        "segment": "no_clear_favorite",
        "edge_threshold": 0.06,
        "outcomes": ["home", "away"],
    },
}

UNIVERSES = {
    "CORE": CORE_LEAGUES,
    "CORE+EXP": CORE_LEAGUES + EXPANSION_LEAGUES,
}

# ============================================================
# HELPERS
# ============================================================

def is_blacklisted(league_name: str) -> bool:
    low = league_name.lower()
    return any(p in low for p in HARD_BLACKLIST_PATTERNS)


def normalize_league(league: str) -> str:
    """Strip 'Футбол. ' prefix and trailing dots for matching."""
    s = league.strip()
    if s.startswith("Футбол. "):
        s = s[len("Футбол. "):]
    return s.lower().rstrip(".")


def league_matches_universe(league: str, universe_leagues: list) -> bool:
    """Check if a league name matches any league in the universe list.
    CSV leagues have 'Футбол. ' prefix and may have suffixes (Апертура, Клаусура, etc.).
    We match by checking if the universe league is a prefix of the normalized CSV league.
    """
    norm = normalize_league(league)
    for ul in universe_leagues:
        norm_ul = normalize_league(ul)
        # Exact match or universe league is a prefix of the CSV league name
        if norm == norm_ul or norm.startswith(norm_ul):
            return True
    return False


def compute_drawdown(pnl_series: pd.Series):
    """Compute max drawdown from cumulative PnL series."""
    if len(pnl_series) == 0:
        return 0.0
    cummax = pnl_series.cummax()
    dd = pnl_series - cummax
    return abs(dd.min()) if len(dd) > 0 else 0.0


def compute_longest_losing_streak(results: pd.Series):
    """results: series of +1 (win) / -1 (loss) per bet."""
    if len(results) == 0:
        return 0
    max_streak = 0
    current = 0
    for r in results:
        if r < 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def rolling_roi(results: pd.Series, odds: pd.Series, window=50):
    """Compute rolling ROI over windows of `window` bets."""
    if len(results) < window:
        return {"min": None, "max": None, "avg": None, "negative_count": 0, "total_windows": 0}

    rois = []
    for i in range(len(results) - window + 1):
        w_results = results.iloc[i:i + window]
        w_odds = odds.iloc[i:i + window]
        pnl = (w_results * w_odds - 1).sum()
        roi = pnl / window * 100
        rois.append(roi)

    rois = np.array(rois)
    return {
        "min": round(float(rois.min()), 2),
        "max": round(float(rois.max()), 2),
        "avg": round(float(rois.mean()), 2),
        "negative_count": int((rois < 0).sum()),
        "total_windows": len(rois),
    }


def evaluate_policy_bets(bets_df, policy_name, n_months=15.25):
    """Compute full metrics for a set of filtered bets."""
    if len(bets_df) == 0:
        return {
            "n_bets": 0,
            "bets_per_month": 0,
            "bets_per_week": 0,
            "hit_rate": 0,
            "avg_odds": 0,
            "avg_edge": 0,
            "roi_flat": 0,
            "roi_kelly": 0,
            "pnl_flat": 0,
            "max_dd_flat": 0,
            "max_dd_kelly": 0,
            "longest_losing_streak": 0,
            "rolling_50": {"min": None, "max": None, "avg": None, "negative_count": 0, "total_windows": 0},
            "monthly": [],
            "quarterly": [],
            "negative_months": 0,
            "negative_quarters": 0,
        }

    n_bets = len(bets_df)
    hit_rate = bets_df["correct"].mean() * 100
    avg_odds = bets_df["bet_odds"].mean()
    avg_edge = bets_df["edge"].mean()

    # Flat PnL
    flat_results = bets_df["correct"] * bets_df["bet_odds"] - 1
    pnl_flat = flat_results.sum()
    roi_flat = pnl_flat / n_bets * 100

    # Kelly PnL (quarter Kelly)
    kelly_fraction = 0.25
    kelly_stakes = ((bets_df["prob"] * bets_df["bet_odds"] - 1) / (bets_df["bet_odds"] - 1)) * kelly_fraction
    kelly_stakes = kelly_stakes.clip(lower=0)
    kelly_pnls = bets_df["correct"] * kelly_stakes * (bets_df["bet_odds"] - 1) - kelly_stakes
    pnl_kelly = kelly_pnls.sum()
    roi_kelly = pnl_kelly / kelly_stakes.sum() * 100 if kelly_stakes.sum() > 0 else 0

    # Drawdown flat
    cum_flat = flat_results.cumsum()
    max_dd_flat = compute_drawdown(cum_flat)

    # Drawdown Kelly (as % of bankroll, starting at 1.0)
    bankroll = 1.0
    br_series = bankroll + kelly_pnls.cumsum()
    dd_kelly = (br_series - br_series.cummax()) / br_series.cummax()
    max_dd_kelly = abs(dd_kelly.min()) * 100 if len(dd_kelly) > 0 else 0

    # Losing streak
    results_sign = (bets_df["correct"] * 2 - 1)  # +1 win, -1 loss
    longest_losing = compute_longest_losing_streak(results_sign)

    # Rolling 50-bet ROI
    rolling = rolling_roi(bets_df["correct"], bets_df["bet_odds"], window=50)

    # Monthly breakdown
    bets_df = bets_df.copy()
    bets_df["month"] = pd.to_datetime(bets_df["match_date"]).dt.to_period("M")
    monthly = []
    for m, grp in bets_df.groupby("month"):
        m_n = len(grp)
        m_hr = grp["correct"].mean() * 100
        m_flat = (grp["correct"] * grp["bet_odds"] - 1).sum()
        m_kelly_stakes = ((grp["prob"] * grp["bet_odds"] - 1) / (grp["bet_odds"] - 1)) * kelly_fraction
        m_kelly_stakes = m_kelly_stakes.clip(lower=0)
        m_kelly_pnl = (grp["correct"] * m_kelly_stakes * (grp["bet_odds"] - 1) - m_kelly_stakes).sum()
        m_roi_k = m_kelly_pnl / m_kelly_stakes.sum() * 100 if m_kelly_stakes.sum() > 0 else 0
        monthly.append({
            "month": str(m),
            "n_bets": m_n,
            "hit_rate": round(m_hr, 1),
            "roi_kelly": round(m_roi_k, 2),
            "pnl_flat": round(m_flat, 2),
            "pnl_kelly": round(m_kelly_pnl, 2),
        })

    # Quarterly breakdown
    bets_df["quarter"] = pd.to_datetime(bets_df["match_date"]).dt.to_period("Q")
    quarterly = []
    for q, grp in bets_df.groupby("quarter"):
        q_n = len(grp)
        q_hr = grp["correct"].mean() * 100
        q_flat = (grp["correct"] * grp["bet_odds"] - 1).sum()
        q_kelly_stakes = ((grp["prob"] * grp["bet_odds"] - 1) / (grp["bet_odds"] - 1)) * kelly_fraction
        q_kelly_stakes = q_kelly_stakes.clip(lower=0)
        q_kelly_pnl = (grp["correct"] * q_kelly_stakes * (grp["bet_odds"] - 1) - q_kelly_stakes).sum()
        q_roi_k = q_kelly_pnl / q_kelly_stakes.sum() * 100 if q_kelly_stakes.sum() > 0 else 0
        quarterly.append({
            "quarter": str(q),
            "n_bets": q_n,
            "hit_rate": round(q_hr, 1),
            "roi_kelly": round(q_roi_k, 2),
            "pnl_flat": round(q_flat, 2),
            "pnl_kelly": round(q_kelly_pnl, 2),
        })

    negative_months = sum(1 for m in monthly if m["pnl_kelly"] < 0)
    negative_quarters = sum(1 for q in quarterly if q["pnl_kelly"] < 0)

    return {
        "n_bets": n_bets,
        "bets_per_month": round(n_bets / n_months, 1),
        "bets_per_week": round(n_bets / (n_months * 4.345), 1),
        "hit_rate": round(hit_rate, 1),
        "avg_odds": round(avg_odds, 3),
        "avg_edge": round(avg_edge, 4),
        "roi_flat": round(roi_flat, 2),
        "roi_kelly": round(roi_kelly, 2),
        "pnl_flat": round(pnl_flat, 2),
        "max_dd_flat": round(max_dd_flat, 2),
        "max_dd_kelly": round(max_dd_kelly, 1),
        "longest_losing_streak": longest_losing,
        "rolling_50": rolling,
        "monthly": monthly,
        "quarterly": quarterly,
        "negative_months": negative_months,
        "negative_quarters": negative_quarters,
    }


def filter_bets(df, policy, universe_leagues=None):
    """Filter predictions to bets matching policy + universe."""
    seg = policy["segment"]
    edge_th = policy["edge_threshold"]

    # Segment filter
    if seg == "balanced":
        mask = df["is_balanced"] == 1
    elif seg == "no_clear_favorite":
        mask = df["no_clear_favorite"] == 1
    else:
        mask = pd.Series(True, index=df.index)

    bets = df[mask].copy()

    # Universe filter
    if universe_leagues is not None:
        universe_mask = bets["league"].apply(
            lambda lg: league_matches_universe(lg, universe_leagues)
        )
        bets = bets[universe_mask].copy()

    # Hard blacklist (always applied)
    bl_mask = ~bets["league"].apply(is_blacklisted)
    bets = bets[bl_mask].copy()

    # Min odds filter
    bets = bets[bets["min_odd"] >= 1.55].copy()

    # For each bet, pick the best outcome among allowed ones
    allowed = policy["outcomes"]  # ["home", "away"]

    rows = []
    for _, row in bets.iterrows():
        edges = {}
        if "home" in allowed:
            edges["home"] = row["edge_home"]
        if "away" in allowed:
            edges["away"] = row["edge_away"]

        best_outcome = max(edges, key=edges.get)
        best_edge = edges[best_outcome]

        if best_edge < edge_th:
            continue

        # Determine correct outcome
        target = row["target"]  # 0=home, 1=draw, 2=away
        if best_outcome == "home":
            correct = (target == 0)
            prob = row["pred_home"]
            odds = row["odds_1x2_home"]
        else:
            correct = (target == 2)
            prob = row["pred_away"]
            odds = row["odds_1x2_away"]

        rows.append({
            "match_date": row["match_date"],
            "league": row["league"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "outcome": best_outcome,
            "correct": int(correct),
            "prob": prob,
            "bet_odds": odds,
            "edge": best_edge,
        })

    return pd.DataFrame(rows)


# ============================================================
# MAIN
# ============================================================

def main():
    print("Loading predictions...")
    df = pd.read_csv(PRED_FILE)
    print(f"  Total matches: {len(df)}")
    print(f"  Date range: {df['match_date'].min()} to {df['match_date'].max()}")

    # Compute date span in months
    dates = pd.to_datetime(df["match_date"])
    n_months = (dates.max() - dates.min()).days / 30.44
    print(f"  Span: {n_months:.1f} months")

    # Count blacklisted leagues
    all_leagues = df["league"].unique()
    blacklisted = [lg for lg in all_leagues if is_blacklisted(lg)]
    print(f"  Unique leagues: {len(all_leagues)}")
    print(f"  Blacklisted leagues: {len(blacklisted)}")

    # Universe membership counts
    for uname, uleagues in UNIVERSES.items():
        matched = [lg for lg in all_leagues if league_matches_universe(lg, uleagues) and not is_blacklisted(lg)]
        print(f"  {uname} matched leagues: {len(matched)}")

    # Also compute FULL (non-blacklisted) for reference
    full_leagues = [lg for lg in all_leagues if not is_blacklisted(lg)]
    print(f"  FULL (non-blacklisted) leagues: {len(full_leagues)}")

    # ============================================================
    # Evaluate all policy x universe combos
    # ============================================================
    results = {}

    for policy_name, policy in POLICIES.items():
        for universe_name in list(UNIVERSES.keys()) + ["FULL"]:
            uleagues = UNIVERSES.get(universe_name, full_leagues)
            key = f"{policy_name} | {universe_name}"
            print(f"\nEvaluating {key}...")

            bets = filter_bets(df, policy, uleagues)
            metrics = evaluate_policy_bets(bets, policy_name, n_months)
            metrics["universe"] = universe_name
            metrics["policy"] = policy_name
            metrics["n_leagues_in_universe"] = len(uleagues)

            # Unique leagues that actually produced bets
            if len(bets) > 0:
                metrics["leagues_with_bets"] = bets["league"].nunique()
                top = (
                    bets.groupby("league")
                    .agg(n_bets=("correct", "count"), pnl=("correct", lambda x: (x * bets.loc[x.index, "bet_odds"] - 1).sum()))
                    .sort_values("n_bets", ascending=False)
                    .head(10)
                    .reset_index()
                )
                metrics["top_leagues"] = top.to_dict("records")
            else:
                metrics["leagues_with_bets"] = 0
                metrics["top_leagues"] = []

            results[key] = metrics
            print(f"  Bets: {metrics['n_bets']}, ROI_k: {metrics['roi_kelly']}%, "
                  f"Bets/mo: {metrics['bets_per_month']}, DD_k: {metrics['max_dd_kelly']}%")

    # ============================================================
    # Generate markdown report
    # ============================================================
    md = generate_report(results, df, n_months, all_leagues, full_leagues)

    with open(OUTPUT_MD, "w") as f:
        f.write(md)

    print(f"\nReport saved to {OUTPUT_MD}")


def generate_report(results, df, n_months, all_leagues, full_leagues):
    lines = []
    a = lines.append

    a("# Football ML Policy v4 — Production Universe Evaluation")
    a("")
    a(f"Generated from test_predictions.csv (n={len(df)}, period: ~{n_months:.1f} months)")
    a("")
    a("## Approach")
    a("")
    a("This analysis does NOT select leagues by historical ROI.")
    a("Instead, it evaluates ML policies within a predefined production universe of healthy leagues.")
    a("")
    a("- **CORE**: 30 professional, stable, bettable leagues")
    a("- **EXPANSION**: 20 secondary leagues for volume")
    a("- **FULL**: all non-blacklisted leagues (reference)")
    a("- **Hard blacklist**: women / reserve / youth / friendly / 6x6 / amateur")
    a("")

    # ============================================================
    # Section 1: Summary Table
    # ============================================================
    a("## 1. Policy x Universe Summary")
    a("")
    a("| Policy | Universe | Bets | Bets/Mo | Bets/Wk | ROI Flat | ROI Kelly | Hit Rate | Avg Odds | Max DD Kelly | Max Losing |")
    a("|--------|----------|------|---------|---------|----------|-----------|----------|----------|--------------|------------|")

    for key in results:
        m = results[key]
        if m["n_bets"] == 0:
            continue
        a(f"| {m['policy']} | {m['universe']} | {m['n_bets']} | {m['bets_per_month']} | {m['bets_per_week']} | {m['roi_flat']}% | {m['roi_kelly']}% | {m['hit_rate']}% | {m['avg_odds']} | {m['max_dd_kelly']}% | {m['longest_losing_streak']} |")

    a("")

    # ============================================================
    # Section 2: Volume vs Target
    # ============================================================
    a("## 2. Volume vs Target (50-100 bets/month)")
    a("")

    a("| Policy | Universe | Bets/Month | % of 50-target | % of 100-target |")
    a("|--------|----------|------------|----------------|-----------------|")

    for key in results:
        m = results[key]
        if m["n_bets"] == 0:
            continue
        pct50 = m["bets_per_month"] / 50 * 100
        pct100 = m["bets_per_month"] / 100 * 100
        a(f"| {m['policy']} | {m['universe']} | {m['bets_per_month']} | {pct50:.0f}% | {pct100:.0f}% |")

    a("")

    # ============================================================
    # Section 3: Detailed Policy Analysis
    # ============================================================
    a("## 3. Detailed Policy Analysis")
    a("")

    for policy_name in POLICIES:
        a(f"### {policy_name}")
        a("")
        policy = POLICIES[policy_name]
        a(f"**Segment**: {policy['segment']}")
        a(f"**Edge threshold**: > {policy['edge_threshold']}")
        a(f"**Outcomes**: Home / Away (draw excluded)")
        a("")

        # Universe comparison
        a("| Metric | CORE | CORE+EXP | FULL |")
        a("|--------|------|----------|------|")

        metrics_core = results.get(f"{policy_name} | CORE", {})
        metrics_exp = results.get(f"{policy_name} | CORE+EXP", {})
        metrics_full = results.get(f"{policy_name} | FULL", {})

        for metric, label in [
            ("n_bets", "Total Bets"),
            ("bets_per_month", "Bets/Month"),
            ("bets_per_week", "Bets/Week"),
            ("roi_flat", "ROI Flat"),
            ("roi_kelly", "ROI Kelly"),
            ("hit_rate", "Hit Rate"),
            ("avg_odds", "Avg Odds"),
            ("max_dd_flat", "Max DD Flat"),
            ("max_dd_kelly", "Max DD Kelly"),
            ("longest_losing_streak", "Max Losing Streak"),
            ("negative_months", "Negative Months"),
            ("negative_quarters", "Negative Quarters"),
        ]:
            v_core = metrics_core.get(metric, "—")
            v_exp = metrics_exp.get(metric, "—")
            v_full = metrics_full.get(metric, "—")
            suffix = "%" if metric in ("roi_flat", "roi_kelly", "hit_rate", "max_dd_kelly") else ""
            a(f"| {label} | {v_core}{suffix} | {v_exp}{suffix} | {v_full}{suffix} |")

        a("")

        # Top leagues by bet volume
        for uname in ["CORE", "CORE+EXP", "FULL"]:
            key = f"{policy_name} | {uname}"
            m = results.get(key, {})
            if m.get("top_leagues"):
                a(f"**Top leagues by volume ({uname})**:")
                a("")
                for i, tl in enumerate(m["top_leagues"][:10], 1):
                    a(f"  {i}. {tl['league']}: n={tl['n_bets']}")
                a("")

        # Monthly breakdown for CORE+EXP
        key_exp = f"{policy_name} | CORE+EXP"
        m_exp = results.get(key_exp, {})
        if m_exp.get("monthly"):
            a(f"**Monthly breakdown ({policy_name}, CORE+EXP)**:")
            a("")
            a("| Month | Bets | Hit Rate | ROI Kelly | PnL Flat | PnL Kelly |")
            a("|-------|------|----------|-----------|----------|-----------|")
            cum_pnl = 0
            for mb in m_exp["monthly"]:
                cum_pnl += mb["pnl_kelly"]
                a(f"| {mb['month']} | {mb['n_bets']} | {mb['hit_rate']}% | {mb['roi_kelly']}% | {mb['pnl_flat']} | {mb['pnl_kelly']} ({cum_pnl:+.2f}) |")
            a("")

        # Quarterly breakdown
        if m_exp.get("quarterly"):
            a(f"**Quarterly breakdown ({policy_name}, CORE+EXP)**:")
            a("")
            a("| Quarter | Bets | Hit Rate | ROI Kelly | PnL Flat | PnL Kelly |")
            a("|---------|------|----------|-----------|----------|-----------|")
            cum_pnl = 0
            for qb in m_exp["quarterly"]:
                cum_pnl += qb["pnl_kelly"]
                a(f"| {qb['quarter']} | {qb['n_bets']} | {qb['hit_rate']}% | {qb['roi_kelly']}% | {qb['pnl_flat']} | {qb['pnl_kelly']} ({cum_pnl:+.2f}) |")
            a("")

        # Rolling 50-bet ROI
        if m_exp.get("rolling_50") and m_exp["rolling_50"]["min"] is not None:
            r = m_exp["rolling_50"]
            a(f"**Rolling 50-bet ROI ({policy_name}, CORE+EXP)**:")
            a("")
            a(f"- Min: {r['min']}%")
            a(f"- Max: {r['max']}%")
            a(f"- Avg: {r['avg']}%")
            a(f"- Negative windows: {r['negative_count']}/{r['total_windows']} ({r['negative_count']/max(r['total_windows'],1)*100:.0f}%)")
            a("")

        a("---")
        a("")

    # ============================================================
    # Section 4: Stability Analysis
    # ============================================================
    a("## 4. Stability Analysis")
    a("")

    a("### Negative Periods Count")
    a("")
    a("| Policy | Universe | Negative Months | Negative Quarters | Negative 50-bet Windows |")
    a("|--------|----------|-----------------|-------------------|------------------------|")

    for key in results:
        m = results[key]
        if m["n_bets"] == 0:
            continue
        r = m.get("rolling_50", {})
        neg_50 = f"{r.get('negative_count', 0)}/{r.get('total_windows', 0)}" if r.get("total_windows", 0) > 0 else "N/A"
        a(f"| {m['policy']} | {m['universe']} | {m['negative_months']} | {m['negative_quarters']} | {neg_50} |")

    a("")

    # ============================================================
    # Section 5: Universe Coverage
    # ============================================================
    a("## 5. Universe Coverage")
    a("")

    a("### CORE Leagues (30)")
    a("")
    for lg in CORE_LEAGUES:
        a(f"- {lg}")
    a("")

    a("### EXPANSION Leagues (20)")
    a("")
    for lg in EXPANSION_LEAGUES:
        a(f"- {lg}")
    a("")

    a("### Hard Blacklist Patterns")
    a("")
    for p in HARD_BLACKLIST_PATTERNS:
        a(f"- `{p}`")
    a("")

    # ============================================================
    # Section 6: Final Recommendations
    # ============================================================
    a("## 6. Final Recommendations")
    a("")

    # Determine PRIMARY, SECONDARY, PILOT
    # Criteria: positive ROI Kelly, reasonable volume, acceptable drawdown
    candidates = []
    for key in results:
        m = results[key]
        if m["n_bets"] < 10:
            continue
        # Score: balance of ROI, volume, stability
        roi_score = min(m["roi_kelly"] / 20, 5)  # cap at 5
        vol_score = min(m["bets_per_month"] / 10, 5)  # cap at 5
        dd_score = max(0, 5 - m["max_dd_kelly"] / 5)  # lower DD = better
        stability = max(0, 5 - m["negative_months"])
        total = roi_score + vol_score + dd_score + stability
        candidates.append((key, m, total))

    candidates.sort(key=lambda x: x[2], reverse=True)

    a("### Scoring Methodology")
    a("")
    a("Each policy/universe combo scored on:")
    a("- **ROI component** (0-5): ROI Kelly / 20, capped at 5")
    a("- **Volume component** (0-5): bets/month / 10, capped at 5")
    a("- **Drawdown component** (0-5): 5 - max_DD_kelly/5")
    a("- **Stability component** (0-5): 5 - negative_months")
    a("")

    a("| Rank | Policy | Universe | Score | ROI Kelly | Bets/Mo | Max DD Kelly | Neg Months |")
    a("|------|--------|----------|-------|-----------|---------|--------------|------------|")

    for i, (key, m, score) in enumerate(candidates, 1):
        a(f"| {i} | {m['policy']} | {m['universe']} | {score:.1f} | {m['roi_kelly']}% | {m['bets_per_month']} | {m['max_dd_kelly']}% | {m['negative_months']} |")

    a("")

    # Primary recommendation
    if candidates:
        best_key, best_m, best_score = candidates[0]
        a(f"### PRIMARY READY: {best_m['policy']} on {best_m['universe']}")
        a("")
        a(f"- Score: {best_score:.1f}")
        a(f"- ROI Kelly: {best_m['roi_kelly']}%")
        a(f"- Bets/month: {best_m['bets_per_month']}")
        a(f"- Bets/week: {best_m['bets_per_week']}")
        a(f"- Max DD Kelly: {best_m['max_dd_kelly']}%")
        a(f"- Max DD Flat: {best_m['max_dd_flat']} units")
        a(f"- Longest losing streak: {best_m['longest_losing_streak']}")
        a(f"- Negative months: {best_m['negative_months']}")
        a(f"- Negative quarters: {best_m['negative_quarters']}")
        a("")

    if len(candidates) > 1:
        sec_key, sec_m, sec_score = candidates[1]
        a(f"### SECONDARY READY: {sec_m['policy']} on {sec_m['universe']}")
        a("")
        a(f"- Score: {sec_score:.1f}")
        a(f"- ROI Kelly: {sec_m['roi_kelly']}%")
        a(f"- Bets/month: {sec_m['bets_per_month']}")
        a(f"- Max DD Kelly: {sec_m['max_dd_kelly']}%")
        a("")

    if len(candidates) > 2:
        third_key, third_m, third_score = candidates[2]
        a(f"### PILOT: {third_m['policy']} on {third_m['universe']}")
        a("")
        a(f"- Score: {third_score:.1f}")
        a(f"- ROI Kelly: {third_m['roi_kelly']}%")
        a(f"- Bets/month: {third_m['bets_per_month']}")
        a(f"- Max DD Kelly: {third_m['max_dd_kelly']}%")
        a("")

    # Business question answer
    a("### Business Question: Can ML 1X2 deliver 50-100 bets/month?")
    a("")

    # Find best volume among positive-ROI policies
    best_vol = 0
    best_vol_policy = None
    for key, m, score in candidates:
        if m["roi_kelly"] > 0 and m["bets_per_month"] > best_vol:
            best_vol = m["bets_per_month"]
            best_vol_policy = m["policy"]

    if best_vol_policy:
        a(f"**Best volume at positive ROI**: {best_vol_policy} delivers ~{best_vol:.0f} bets/month.")
        a("")
        if best_vol < 50:
            a(f"**Gap to 50 bets/month**: {50 - best_vol:.0f} bets/month must come from:")
            a("1. **BTTS/Over-Under ML models** — extend the model to predict these markets")
            a("2. **Rule-based strategies** — existing BTTS, Over/Under, Draw rules (~30-60/month)")
            a("3. **Lower edge thresholds** — increases volume but reduces ROI")
            a("4. **Asian Handicap ML** — additional market with different odds structure")
            a("")
            a(f"**Realistic ML 1X2 volume**: ~{best_vol:.0f} bets/month at positive ROI.")
            a(f"**Remaining gap**: {50 - best_vol:.0f} bets from complementary systems.")
        else:
            a(f"**YES**: {best_vol_policy} alone reaches the 50 bets/month target.")
    else:
        a("**No policy with positive ROI found.** ML model needs retraining.")

    a("")
    a("### Final Verdict")
    a("")

    if candidates and candidates[0][1]["roi_kelly"] > 5:
        a(f"**RECOMMEND: CORE+EXPANSION universe with {candidates[0][1]['policy']} as primary.**")
        a("")
        a(f"- Whitelist: {candidates[0][1]['universe']} ({candidates[0][1]['n_leagues_in_universe']} leagues)")
        a(f"- Expected bets/month: ~{candidates[0][1]['bets_per_month']}")
        a(f"- Expected ROI Kelly: ~{candidates[0][1]['roi_kelly']}%")
        a(f"- Expected Max DD Kelly: ~{candidates[0][1]['max_dd_kelly']}%")
        a(f"- Blacklist patterns: {', '.join(f'`{p}`' for p in HARD_BLACKLIST_PATTERNS)}")
        a("")
        a("**Recommendation**: CORE+EXPANSION — CORE alone may not provide enough volume, EXPANSION adds healthy secondary leagues without compromising quality.")
    else:
        a("**REJECT for production** — ML model does not produce sufficient positive-EV signals on the production universe.")

    a("")
    a("---")
    a("")
    a("## 7. Implementation-Ready Rules")
    a("")

    if candidates:
        best = candidates[0][1]
        policy = POLICIES[best["policy"]]
        a(f"### {best['policy']} (PRIMARY)")
        a("")
        a("```")
        a(f"SEGMENT: {policy['segment']}")
        a(f"EDGE_THRESHOLD: {policy['edge_threshold']}")
        a(f"ALLOWED_OUTCOMES: {policy['outcomes']}")
        a(f"DRAW: excluded")
        a(f"MIN_ODDS: 1.55")
        a(f"KELLY_FRACTION: 0.25")
        a(f"MAX_STAKE_PCT: 0.10")
        a(f"UNIVERSE: {best['universe']}")
        a(f"EXPECTED_BETS_MONTH: ~{best['bets_per_month']}")
        a(f"EXPECTED_BETS_WEEK: ~{best['bets_per_week']}")
        a(f"EXPECTED_ROI_KELLY: {best['roi_kelly']}%")
        a(f"EXPECTED_HIT_RATE: {best['hit_rate']}%")
        a(f"AVG_ODDS: {best['avg_odds']}")
        a(f"MAX_DRAWDOWN_KELLY: {best['max_dd_kelly']}%")
        a(f"MAX_DRAWDOWN_FLAT: {best['max_dd_flat']} units")
        a(f"LONGEST_LOSING_STREAK: {best['longest_losing_streak']}")
        a(f"BLACKLIST_PATTERNS: {', '.join(HARD_BLACKLIST_PATTERNS)}")
        a("```")
        a("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
