"""
Football ML Policy v2 — Stability & Risk Analysis
Builds on v1 policy candidates, adds:
- League breakdown per policy
- Monthly / Quarterly breakdown
- Losing streak / drawdown
- Rolling stability
- Outcome stability (home vs away contribution)
- Final verdicts with risk-adjusted criteria
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

PRED_PATH = Path(__file__).parent.parent / "ml_output" / "test_predictions.csv"
REPORT_PATH = Path(__file__).parent.parent / "ml_output" / "evaluation_report.json"
OUTPUT_MD = Path(__file__).parent / "football_ml_policy_v2.md"

TEST_MONTHS = 15.25
df = pd.read_csv(PRED_PATH)
with open(REPORT_PATH) as f:
    report = json.load(f)

# Exclude draw predictions (v1 conclusion)
df = df[df["prediction"] != 1].copy()

# Compute bet-level metrics
df["bet_odds"] = np.where(
    df["prediction"] == 0, df["odds_1x2_home"], df["odds_1x2_away"]
)
df["bet_prob"] = np.where(
    df["prediction"] == 0, df["pred_home"], df["pred_away"]
)
df["bet_edge"] = df["bet_prob"] * df["bet_odds"] - 1
df["bet_won"] = (df["prediction"] == df["target"]).astype(int)
df["bet_outcome"] = np.where(df["prediction"] == 0, "home", "away")

# Kelly quarter stake
kelly_full = np.where(df["bet_odds"] > 1,
                      (df["bet_prob"] * df["bet_odds"] - 1) / (df["bet_odds"] - 1), 0)
df["kelly_q"] = np.minimum(np.maximum(kelly_full * 0.25, 0), 0.10)

# PnL per bet
df["pnl_flat"] = np.where(df["bet_won"] == 1, df["bet_odds"] - 1, -1.0)
df["pnl_kelly"] = np.where(df["bet_won"] == 1,
                            df["kelly_q"] * (df["bet_odds"] - 1),
                            -df["kelly_q"])

# Date parsing
df["match_date"] = pd.to_datetime(df["match_date"])
df["month"] = df["match_date"].dt.to_period("M").astype(str)
df["quarter"] = df["match_date"].dt.to_period("Q").astype(str)

# ─── Policy definitions ───────────────────────────────────────────────────
policies = {
    "A_NCF_Core":       {"mask": (df["no_clear_favorite"] == 1) & (df["max_edge"] >= 0.06)},
    "B_NCF_Tight":      {"mask": (df["no_clear_favorite"] == 1) & (df["max_edge"] >= 0.07)},
    "C_Bal_Core":       {"mask": (df["is_balanced"] == 1) & (df["max_edge"] >= 0.05)},
    "D_Bal_Tight":      {"mask": (df["is_balanced"] == 1) & (df["max_edge"] >= 0.06)},
    "E_All_HA_07":      {"mask": df["max_edge"] >= 0.07},
    "F_All_HA_08":      {"mask": df["max_edge"] >= 0.08},
    "G_NCF_Volume":     {"mask": (df["no_clear_favorite"] == 1) & (df["max_edge"] >= 0.05)},
}

for name, pol in policies.items():
    pol["data"] = df[pol["mask"]].copy().sort_values("match_date").reset_index(drop=True)

# ─── Helper functions ─────────────────────────────────────────────────────

def compute_streaks(won_arr):
    """Compute losing streaks from boolean/int won array."""
    streaks = []
    current = 0
    for w in won_arr:
        if w == 0:
            current += 1
        else:
            if current > 0:
                streaks.append(current)
            current = 0
    if current > 0:
        streaks.append(current)
    return streaks if streaks else [0]


def compute_drawdown(pnl_arr):
    """Compute max drawdown from cumulative PnL array."""
    cumsum = np.cumsum(pnl_arr)
    running_max = np.maximum.accumulate(np.concatenate([[0], cumsum]))
    # running_max[i] = max(0, cumsum[0], ..., cumsum[i-1])
    # Drawdown at step i = running_max[i] - cumsum[i-1] (if cumsum[i-1] < running_max)
    dd = np.zeros(len(cumsum))
    for i in range(len(cumsum)):
        dd[i] = running_max[i] - cumsum[i]
    return dd.max(), dd


def policy_summary(sub_df):
    """Basic summary for a policy subset."""
    n = len(sub_df)
    if n == 0:
        return None
    hr = sub_df["bet_won"].mean()
    roi_f = sub_df["pnl_flat"].sum() / n * 100
    roi_k = sub_df["pnl_kelly"].sum() / sub_df["kelly_q"].sum() * 100 if sub_df["kelly_q"].sum() > 0 else 0
    pnl_f = sub_df["pnl_flat"].sum()
    pnl_k = sub_df["pnl_kelly"].sum()
    avg_odds = sub_df["bet_odds"].mean()
    avg_edge = sub_df["bet_edge"].mean()
    return {
        "n_bets": n, "hit_rate": round(hr * 100, 1),
        "roi_flat": round(roi_f, 2), "roi_kelly": round(roi_k, 2),
        "pnl_flat": round(pnl_f, 2), "pnl_kelly": round(pnl_k, 2),
        "avg_odds": round(avg_odds, 3), "avg_edge": round(avg_edge, 4),
    }


def compute_rolling_roi(sub_df, window=50):
    """Compute rolling ROI over a window of bets."""
    if len(sub_df) < window:
        return []
    won = sub_df["bet_won"].values
    odds = sub_df["bet_odds"].values
    rolling = []
    for i in range(window - 1, len(won)):
        w = won[i - window + 1:i + 1]
        o = odds[i - window + 1:i + 1]
        pnl = (w * (o - 1) - (1 - w)).sum()
        rolling.append(round(pnl / window * 100, 2))
    return rolling


# ─── Analysis ─────────────────────────────────────────────────────────────

print("=" * 60)
print("FOOTBALL ML POLICY v2 — STABILITY & RISK ANALYSIS")
print("=" * 60)

all_results = {}

for pol_name, pol in policies.items():
    sub = pol["data"]
    n = len(sub)
    print(f"\n{'='*60}")
    print(f"POLICY: {pol_name} (n={n})")
    print(f"{'='*60}")

    s = policy_summary(sub)
    print(f"  Overall: HR={s['hit_rate']}%, ROI_k={s['roi_kelly']}%, ROI_f={s['roi_flat']}%, PnL_flat={s['pnl_flat']}")

    # ── 1. League breakdown ──
    print(f"\n  --- League Breakdown ---")
    league_rows = []
    for league in sub["league"].unique():
        lg = sub[sub["league"] == league]
        ls = policy_summary(lg)
        ls["league"] = league
        ls["pnl"] = round(lg["pnl_flat"].sum(), 2)
        league_rows.append(ls)
    league_df = pd.DataFrame(league_rows).sort_values("pnl", ascending=False)
    league_df["pnl_contrib"] = (league_df["pnl"] / s["pnl_flat"] * 100).round(1) if s["pnl_flat"] != 0 else 0
    print(f"  Top 10 leagues by PnL:")
    for _, row in league_df.head(10).iterrows():
        print(f"    {row['league']}: n={row['n_bets']}, HR={row['hit_rate']}%, ROI_k={row['roi_kelly']}%, PnL={row['pnl']}, contrib={row['pnl_contrib']}%")
    print(f"  Bottom 5 leagues by PnL:")
    for _, row in league_df.tail(5).iterrows():
        print(f"    {row['league']}: n={row['n_bets']}, HR={row['hit_rate']}%, ROI_k={row['roi_kelly']}%, PnL={row['pnl']}, contrib={row['pnl_contrib']}%")

    # Top 2 league concentration
    top2_pnl = league_df.head(2)["pnl"].sum()
    top2_contrib = top2_pnl / s["pnl_flat"] * 100 if s["pnl_flat"] != 0 else 0
    print(f"  Top 2 leagues PnL contribution: {top2_contrib:.0f}%")

    # ── 2. Monthly breakdown ──
    print(f"\n  --- Monthly Breakdown ---")
    monthly_rows = []
    for month in sorted(sub["month"].unique()):
        m = sub[sub["month"] == month]
        ms = policy_summary(m)
        ms["month"] = month
        ms["pnl"] = round(m["pnl_flat"].sum(), 2)
        monthly_rows.append(ms)
    monthly_df = pd.DataFrame(monthly_rows)
    monthly_df["cum_pnl"] = monthly_df["pnl"].cumsum().round(2)
    for _, row in monthly_df.iterrows():
        flag = " ***" if row["pnl"] < -5 else ""
        print(f"    {row['month']}: n={row['n_bets']}, HR={row['hit_rate']}%, ROI_k={row['roi_kelly']}%, PnL={row['pnl']}, CumPnL={row['cum_pnl']}{flag}")

    # Consecutive losing months
    losing_months = (monthly_df["pnl"] < 0).astype(int)
    consec_losing = 0
    max_consec_losing = 0
    for v in losing_months.values:
        if v == 1:
            consec_losing += 1
            max_consec_losing = max(max_consec_losing, consec_losing)
        else:
            consec_losing = 0
    print(f"  Max consecutive losing months: {max_consec_losing}")

    # Worst month
    worst_month = monthly_df.loc[monthly_df["pnl"].idxmin()]
    print(f"  Worst month: {worst_month['month']}, PnL={worst_month['pnl']}, n={worst_month['n_bets']}")

    # ── 3. Quarterly breakdown ──
    print(f"\n  --- Quarterly Breakdown ---")
    quarterly_rows = []
    for quarter in sorted(sub["quarter"].unique()):
        q = sub[sub["quarter"] == quarter]
        qs = policy_summary(q)
        qs["quarter"] = quarter
        qs["pnl"] = round(q["pnl_flat"].sum(), 2)
        quarterly_rows.append(qs)
    quarterly_df = pd.DataFrame(quarterly_rows)
    quarterly_df["cum_pnl"] = quarterly_df["pnl"].cumsum().round(2)
    for _, row in quarterly_df.iterrows():
        print(f"    {row['quarter']}: n={row['n_bets']}, HR={row['hit_rate']}%, ROI_k={row['roi_kelly']}%, PnL={row['pnl']}, CumPnL={row['cum_pnl']}")

    worst_quarter = quarterly_df.loc[quarterly_df["pnl"].idxmin()]
    print(f"  Worst quarter: {worst_quarter['quarter']}, PnL={worst_quarter['pnl']}")

    # ── 4. Losing streak / drawdown ──
    print(f"\n  --- Losing Streak / Drawdown ---")
    streaks = compute_streaks(sub["bet_won"].values)
    max_losing_streak = max(streaks)
    avg_losing_streak = round(np.mean(streaks), 1)
    print(f"  Longest losing streak: {max_losing_streak}")
    print(f"  Average losing streak: {avg_losing_streak}")
    print(f"  Number of losing streaks: {len(streaks)}")

    max_dd_flat, dd_flat = compute_drawdown(sub["pnl_flat"].values)
    max_dd_kelly, dd_kelly = compute_drawdown(sub["pnl_kelly"].values)
    print(f"  Max drawdown (flat): {max_dd_flat:.2f} units")
    print(f"  Max drawdown (Kelly): {max_dd_kelly:.4f} units ({max_dd_kelly*100:.2f}% of bankroll)")

    # ── 5. Rolling stability ──
    print(f"\n  --- Rolling Stability ---")
    roll50 = compute_rolling_roi(sub, 50)
    roll100 = compute_rolling_roi(sub, 100)
    if roll50:
        print(f"  Rolling 50-bet ROI: min={min(roll50)}%, max={max(roll50)}%, avg={round(np.mean(roll50), 2)}%, median={round(np.median(roll50), 2)}%")
        neg50 = sum(1 for r in roll50 if r < 0)
        print(f"  Negative 50-bet windows: {neg50}/{len(roll50)} ({neg50/len(roll50)*100:.0f}%)")
    if roll100:
        print(f"  Rolling 100-bet ROI: min={min(roll100)}%, max={max(roll100)}%, avg={round(np.mean(roll100), 2)}%, median={round(np.median(roll100), 2)}%")
        neg100 = sum(1 for r in roll100 if r < 0)
        print(f"  Negative 100-bet windows: {neg100}/{len(roll100)} ({neg100/len(roll100)*100:.0f}%)")

    # ── 6. Outcome stability ──
    print(f"\n  --- Outcome Stability ---")
    for outcome in ["home", "away"]:
        osub = sub[sub["bet_outcome"] == outcome]
        if len(osub) == 0:
            continue
        os = policy_summary(osub)
        os["pnl"] = round(osub["pnl_flat"].sum(), 2)
        pct_of_bets = len(osub) / n * 100
        pnl_contrib = os["pnl"] / s["pnl_flat"] * 100 if s["pnl_flat"] != 0 else 0
        print(f"  {outcome}: n={len(osub)} ({pct_of_bets:.0f}%), HR={os['hit_rate']}%, ROI_k={os['roi_kelly']}%, PnL={os['pnl']}, contrib={pnl_contrib:.0f}%")

    # ── 7. Without top 2 leagues ──
    top2_leagues = league_df.head(2)["league"].tolist()
    sub_no_top2 = sub[~sub["league"].isin(top2_leagues)]
    s_no_top2 = policy_summary(sub_no_top2)
    print(f"\n  --- Without Top 2 Leagues ({', '.join(top2_leagues[:2])}) ---")
    print(f"  n={s_no_top2['n_bets']}, HR={s_no_top2['hit_rate']}%, ROI_k={s_no_top2['roi_kelly']}%, PnL={s_no_top2['pnl_flat']}")

    # ── Store results ──
    all_results[pol_name] = {
        "summary": s,
        "league_df": league_df,
        "monthly_df": monthly_df,
        "quarterly_df": quarterly_df,
        "max_losing_streak": max_losing_streak,
        "avg_losing_streak": avg_losing_streak,
        "max_dd_flat": max_dd_flat,
        "max_dd_kelly": max_dd_kelly,
        "roll50": roll50,
        "roll100": roll100,
        "top2_leagues": top2_leagues,
        "top2_contrib": top2_contrib,
        "s_no_top2": s_no_top2,
        "worst_month": worst_month.to_dict(),
        "worst_quarter": worst_quarter.to_dict(),
        "max_consec_losing_months": max_consec_losing,
        "n_leagues": len(league_df),
        "n_positive_leagues": (league_df["roi_kelly"] > 0).sum(),
    }

# ─── Verdict logic ────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("FINAL VERDICTS")
print(f"{'='*60}")

for pol_name, r in all_results.items():
    s = r["summary"]
    reasons = []
    verdict = "READY"

    # Volume check
    per_month = round(s["n_bets"] / TEST_MONTHS, 1)
    if per_month < 3:
        verdict = "REJECT"
        reasons.append(f"too few bets/month ({per_month})")

    # ROI check
    if s["roi_kelly"] < 3:
        if verdict != "REJECT":
            verdict = "PILOT"
        reasons.append(f"low ROI_k ({s['roi_kelly']}%)")

    # Losing streak
    if r["max_losing_streak"] > 12:
        if verdict == "READY":
            verdict = "PILOT"
        reasons.append(f"long losing streak ({r['max_losing_streak']})")

    # Max drawdown (Kelly)
    if r["max_dd_kelly"] > 0.15:
        if verdict == "READY":
            verdict = "PILOT"
        reasons.append(f"high max DD Kelly ({r['max_dd_kelly']*100:.1f}%)")

    # Top 2 league concentration
    if r["top2_contrib"] > 60:
        if verdict == "READY":
            verdict = "PILOT"
        reasons.append(f"top 2 leagues contribute {r['top2_contrib']:.0f}% of PnL")

    # Without top 2 leagues
    if r["s_no_top2"]["roi_kelly"] < 0:
        if verdict == "READY":
            verdict = "PILOT"
        reasons.append(f"negative ROI without top 2 leagues ({r['s_no_top2']['roi_kelly']}%)")

    # Consecutive losing months
    if r["max_consec_losing_months"] > 3:
        if verdict == "READY":
            verdict = "PILOT"
        reasons.append(f"{r['max_consec_losing_months']} consecutive losing months")

    # Rolling stability
    if r["roll50"]:
        neg50_pct = sum(1 for x in r["roll50"] if x < 0) / len(r["roll50"]) * 100
        if neg50_pct > 40:
            if verdict == "READY":
                verdict = "PILOT"
            reasons.append(f"{neg50_pct:.0f}% of 50-bet windows negative")

    if not reasons:
        reasons.append("passes all risk checks")

    print(f"\n{pol_name}: {verdict}")
    print(f"  ROI_k={s['roi_kelly']}%, bets/mo={per_month}, max_losing={r['max_losing_streak']}, "
          f"max_dd_k={r['max_dd_kelly']*100:.1f}%, top2_contrib={r['top2_contrib']:.0f}%")
    for reason in reasons:
        print(f"  - {reason}")

    r["verdict"] = verdict
    r["reasons"] = reasons
    r["per_month"] = per_month

# ─── Generate Markdown Report ─────────────────────────────────────────────
md = []
md.append("# Football ML Policy v2 — Stability & Risk Analysis\n")
md.append(f"Test period: 2025-01 to 2026-04 (~{TEST_MONTHS} months), n={len(df)} bets (home/away only, draw excluded)\n")

md.append("## 1. Policy Candidates Recap\n")
md.append("| Policy | Segment | Edge | Outcomes | Bets | ROI Kelly | Bets/Mo |")
md.append("|--------|---------|------|----------|------|-----------|---------|")
for pol_name in policies:
    s = all_results[pol_name]["summary"]
    pm = all_results[pol_name]["per_month"]
    label = pol_name.replace("_", " ")
    md.append(f"| {label} | — | — | H/A | {s['n_bets']} | {s['roi_kelly']}% | {pm} |")
md.append("")

# ── 2. League Breakdown ──
for pol_name in policies:
    r = all_results[pol_name]
    s = r["summary"]
    md.append(f"\n## 2. League Breakdown — {pol_name}\n")
    md.append(f"Overall: n={s['n_bets']}, HR={s['hit_rate']}%, ROI_k={s['roi_kelly']}%, PnL_flat={s['pnl_flat']}\n")
    md.append(f"Leagues with bets: {r['n_leagues']}, positive ROI: {r['n_positive_leagues']}\n")
    md.append(f"Top 2 leagues PnL contribution: {r['top2_contrib']:.0f}%\n")

    md.append("| League | Bets | Hit Rate | ROI Kelly | PnL | PnL Contrib % |")
    md.append("|--------|------|----------|-----------|-----|---------------|")
    for _, row in r["league_df"].iterrows():
        md.append(f"| {row['league']} | {row['n_bets']} | {row['hit_rate']}% | {row['roi_kelly']}% | {row['pnl']} | {row['pnl_contrib']}% |")

    md.append(f"\n**Without top 2 leagues** ({', '.join(r['top2_leagues'][:2])}): "
              f"n={r['s_no_top2']['n_bets']}, HR={r['s_no_top2']['hit_rate']}%, "
              f"ROI_k={r['s_no_top2']['roi_kelly']}%, PnL={r['s_no_top2']['pnl_flat']}\n")

# ── 3. Monthly Breakdown ──
for pol_name in policies:
    r = all_results[pol_name]
    s = r["summary"]
    md.append(f"\n## 3. Monthly Breakdown — {pol_name}\n")
    md.append(f"Max consecutive losing months: {r['max_consec_losing_months']}\n")
    md.append(f"Worst month: {r['worst_month']['month']}, PnL={r['worst_month']['pnl']}, n={r['worst_month']['n_bets']}\n")
    md.append("| Month | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |")
    md.append("|-------|------|----------|-----------|-----|---------|")
    for _, row in r["monthly_df"].iterrows():
        flag = " **" if row["pnl"] < -5 else ""
        md.append(f"| {row['month']} | {row['n_bets']} | {row['hit_rate']}% | {row['roi_kelly']}% | {row['pnl']} | {row['cum_pnl']} |{flag}")
    md.append("\n** = losing month > 5 units\n")

# ── 4. Quarterly Breakdown ──
for pol_name in policies:
    r = all_results[pol_name]
    s = r["summary"]
    md.append(f"\n## 4. Quarterly Breakdown — {pol_name}\n")
    md.append(f"Worst quarter: {r['worst_quarter']['quarter']}, PnL={r['worst_quarter']['pnl']}\n")
    md.append("| Quarter | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |")
    md.append("|---------|------|----------|-----------|-----|---------|")
    for _, row in r["quarterly_df"].iterrows():
        md.append(f"| {row['quarter']} | {row['n_bets']} | {row['hit_rate']}% | {row['roi_kelly']}% | {row['pnl']} | {row['cum_pnl']} |")

# ── 5. Losing Streak / Drawdown ──
md.append("\n## 5. Losing Streak & Drawdown Summary\n")
md.append("| Policy | Max Losing Streak | Avg Losing Streak | Max DD (flat) | Max DD (Kelly) | Worst Month | Worst Quarter |")
md.append("|--------|-------------------|-------------------|---------------|----------------|-------------|---------------|")
for pol_name in policies:
    r = all_results[pol_name]
    md.append(f"| {pol_name} | {r['max_losing_streak']} | {r['avg_losing_streak']} | "
              f"{r['max_dd_flat']:.2f} | {r['max_dd_kelly']*100:.1f}% | "
              f"{r['worst_month']['month']} ({r['worst_month']['pnl']}) | "
              f"{r['worst_quarter']['quarter']} ({r['worst_quarter']['pnl']}) |")

md.append("")
md.append("### Interpretation\n")
md.append("- **Max Losing Streak**: Consecutive losses without a win. At 43% hit rate, expected max streak ≈ log(1-0.43)/log(0.57) ≈ 8-10 for 500 bets.")
md.append("- **Max DD (flat)**: Peak-to-trough drawdown in flat-staking units. A DD of 30 units means you'd need 30 units of bankroll buffer.")
md.append("- **Max DD (Kelly)**: Peak-to-trough as fraction of bankroll with Kelly quarter-staking. >15% is concerning for live deployment.")
md.append("")

# ── 6. Rolling Stability ──
for pol_name in policies:
    r = all_results[pol_name]
    md.append(f"\n## 6. Rolling Stability — {pol_name}\n")
    if r["roll50"]:
        neg50 = sum(1 for x in r["roll50"] if x < 0)
        md.append(f"- **Rolling 50-bet ROI**: min={min(r['roll50'])}%, max={max(r['roll50'])}%, avg={round(np.mean(r['roll50']), 2)}%, median={round(np.median(r['roll50']), 2)}%")
        md.append(f"- **Negative 50-bet windows**: {neg50}/{len(r['roll50'])} ({neg50/len(r['roll50'])*100:.0f}%)")
    if r["roll100"]:
        neg100 = sum(1 for x in r["roll100"] if x < 0)
        md.append(f"- **Rolling 100-bet ROI**: min={min(r['roll100'])}%, max={max(r['roll100'])}%, avg={round(np.mean(r['roll100']), 2)}%, median={round(np.median(r['roll100']), 2)}%")
        md.append(f"- **Negative 100-bet windows**: {neg100}/{len(r['roll100'])} ({neg100/len(r['roll100'])*100:.0f}%)")
    if not r["roll50"] and not r["roll100"]:
        md.append("- Too few bets for rolling analysis.\n")

# ── 7. Outcome Stability ──
md.append("\n## 7. Outcome Stability\n")
for pol_name in policies:
    r = all_results[pol_name]
    s = r["summary"]
    sub = policies[pol_name]["data"]
    md.append(f"\n### {pol_name}\n")
    for outcome in ["home", "away"]:
        osub = sub[sub["bet_outcome"] == outcome]
        if len(osub) == 0:
            continue
        os = policy_summary(osub)
        os_pnl = round(osub["pnl_flat"].sum(), 2)
        pct = len(osub) / s["n_bets"] * 100
        contrib = os_pnl / s["pnl_flat"] * 100 if s["pnl_flat"] != 0 else 0
        md.append(f"- **{outcome}**: n={len(osub)} ({pct:.0f}%), HR={os['hit_rate']}%, ROI_k={os['roi_kelly']}%, PnL={os_pnl}, contrib={contrib:.0f}%")

# ── 8. Final Verdicts ──
md.append("\n## 8. Final Verdicts\n")
md.append("| Policy | Verdict | ROI Kelly | Bets/Mo | Max DD Kelly | Max Losing | Top2 Contrib | Key Risk |\n")
md.append("|--------|---------|-----------|---------|--------------|------------|--------------|----------|")
for pol_name in policies:
    r = all_results[pol_name]
    s = r["summary"]
    risk = "; ".join(r["reasons"])[:80]
    md.append(f"| {pol_name} | **{r['verdict']}** | {s['roi_kelly']}% | {r['per_month']} | "
              f"{r['max_dd_kelly']*100:.1f}% | {r['max_losing_streak']} | {r['top2_contrib']:.0f}% | {risk} |")

md.append("")

# ── 9. Deployment Order ──
md.append("\n## 9. Recommended Deployment Order\n")

ready = [(k, v) for k, v in all_results.items() if v["verdict"] == "READY"]
pilot = [(k, v) for k, v in all_results.items() if v["verdict"] == "PILOT"]
reject = [(k, v) for k, v in all_results.items() if v["verdict"] == "REJECT"]

# Sort ready by ROI * volume
ready.sort(key=lambda x: x[1]["summary"]["roi_kelly"] * max(x[1]["per_month"], 1), reverse=True)

md.append("### Phase 1 — Deploy Immediately (READY)\n")
if ready:
    for i, (name, r) in enumerate(ready, 1):
        s = r["summary"]
        md.append(f"{i}. **{name}**: ROI_k={s['roi_kelly']}%, ~{r['per_month']} bets/mo, max DD={r['max_dd_kelly']*100:.1f}%")
else:
    md.append("No policies pass all risk checks.\n")

md.append("\n### Phase 2 — Monitor & Test (PILOT)\n")
if pilot:
    for i, (name, r) in enumerate(pilot, 1):
        s = r["summary"]
        md.append(f"{i}. **{name}**: ROI_k={s['roi_kelly']}%, ~{r['per_month']} bets/mo, max DD={r['max_dd_kelly']*100:.1f}%")
        md.append(f"   - Risks: {'; '.join(r['reasons'])}")
else:
    md.append("None.\n")

md.append("\n### Do Not Deploy (REJECT)\n")
if reject:
    for name, r in reject:
        s = r["summary"]
        md.append(f"- **{name}**: {'; '.join(r['reasons'])}")
else:
    md.append("None.\n")

md.append("\n### Deployment Strategy\n")
md.append("1. **Start with Phase 1 only** — run for 2-4 weeks in dry-run mode")
md.append("2. **Compare dry-run results** against backtest expectations")
md.append("3. **If dry-run matches backtest** → enable live betting with reduced stakes (Kelly × 0.125 instead of 0.25)")
md.append("4. **After 50+ live bets per policy** → evaluate actual vs expected ROI")
md.append("5. **Phase 2 policies** → add only after Phase 1 proves stable in live mode")
md.append("6. **Never deploy REJECT policies** without model retraining or feature changes")
md.append("")

with open(OUTPUT_MD, "w") as f:
    f.write("\n".join(md))

print(f"\n\nReport saved to: {OUTPUT_MD}")
print("Done.")
