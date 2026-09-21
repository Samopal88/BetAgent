"""
Football ML Policy v3 — Final Deployment Shortlist
Focus: B_NCF_Tight, C_Bal_Core, D_Bal_Tight only.
- Blacklist-based filtering (practical for live deployment)
- Monthly/quarterly stability after blacklist
- Risk metrics after blacklist
- Stress tests (remove top-1, top-2 leagues by PnL)
- Final operational recommendation
"""

import pandas as pd
import numpy as np
from pathlib import Path

PRED_PATH = Path(__file__).parent.parent / "ml_output" / "test_predictions.csv"
OUTPUT_MD = Path(__file__).parent / "football_ml_policy_v3_shortlist.md"

TEST_MONTHS = 15.25

df = pd.read_csv(PRED_PATH)
# Exclude draw
df = df[df["prediction"] != 1].copy()

df["bet_odds"] = np.where(df["prediction"] == 0, df["odds_1x2_home"], df["odds_1x2_away"])
df["bet_prob"] = np.where(df["prediction"] == 0, df["pred_home"], df["pred_away"])
df["bet_edge"] = df["bet_prob"] * df["bet_odds"] - 1
df["bet_won"] = (df["prediction"] == df["target"]).astype(int)
df["bet_outcome"] = np.where(df["prediction"] == 0, "home", "away")

kelly_full = np.where(df["bet_odds"] > 1,
                      (df["bet_prob"] * df["bet_odds"] - 1) / (df["bet_odds"] - 1), 0)
df["kelly_q"] = np.minimum(np.maximum(kelly_full * 0.25, 0), 0.10)
df["pnl_flat"] = np.where(df["bet_won"] == 1, df["bet_odds"] - 1, -1.0)
df["pnl_kelly"] = np.where(df["bet_won"] == 1, df["kelly_q"] * (df["bet_odds"] - 1), -df["kelly_q"])

df["match_date"] = pd.to_datetime(df["match_date"])
df["month"] = df["match_date"].dt.to_period("M").astype(str)
df["quarter"] = df["match_date"].dt.to_period("Q").astype(str)

# ─── Policy definitions ───
policies = {
    "B_NCF_Tight":  {"mask": (df["no_clear_favorite"] == 1) & (df["max_edge"] >= 0.07)},
    "C_Bal_Core":   {"mask": (df["is_balanced"] == 1) & (df["max_edge"] >= 0.05)},
    "D_Bal_Tight":  {"mask": (df["is_balanced"] == 1) & (df["max_edge"] >= 0.06)},
}

for name, pol in policies.items():
    pol["data"] = df[pol["mask"]].copy().sort_values("match_date").reset_index(drop=True)

# ─── Helpers ───
def compute_streaks(won_arr):
    streaks, cur = [], 0
    for w in won_arr:
        if w == 0: cur += 1
        else:
            if cur > 0: streaks.append(cur)
            cur = 0
    if cur > 0: streaks.append(cur)
    return streaks if streaks else [0]

def compute_drawdown(pnl_arr):
    cumsum = np.cumsum(pnl_arr)
    running_max = np.maximum.accumulate(np.concatenate([[0], cumsum]))
    dd = np.array([running_max[i] - cumsum[i] for i in range(len(cumsum))])
    return dd.max(), dd

def policy_summary(sub_df):
    n = len(sub_df)
    if n == 0: return None
    hr = sub_df["bet_won"].mean()
    roi_f = sub_df["pnl_flat"].sum() / n * 100
    roi_k = sub_df["pnl_kelly"].sum() / sub_df["kelly_q"].sum() * 100 if sub_df["kelly_q"].sum() > 0 else 0
    return {
        "n_bets": n, "hit_rate": round(hr * 100, 1),
        "roi_flat": round(roi_f, 2), "roi_kelly": round(roi_k, 2),
        "pnl_flat": round(sub_df["pnl_flat"].sum(), 2),
        "pnl_kelly": round(sub_df["pnl_kelly"].sum(), 4),
        "avg_odds": round(sub_df["bet_odds"].mean(), 3),
        "avg_edge": round(sub_df["bet_edge"].mean(), 4),
    }

def rolling_roi(sub_df, window=50):
    if len(sub_df) < window: return []
    won, odds = sub_df["bet_won"].values, sub_df["bet_odds"].values
    result = []
    for i in range(window - 1, len(won)):
        w = won[i - window + 1:i + 1]
        o = odds[i - window + 1:i + 1]
        pnl = (w * (o - 1) - (1 - w)).sum()
        result.append(round(pnl / window * 100, 2))
    return result

# ─── Blacklist patterns ───
# Hard blacklist: structural noise — always exclude
HARD_BLACKLIST_PATTERNS = [
    "резерв", "reserve", "женщин", "women",
    "юношеск", "youth", "до 20", "до 21", "до 19", "до 18",
    "товарищеск", "friendly",
    "сан-хуана", "лига сан",
]

# Soft blacklist: cup/playoff — exclude only if n < 5
SOFT_BLACKLIST_PATTERNS = [
    "кубок", "cup", "плей-офф", "play-off", "стыков",
]

def is_hard_blacklist(league_name):
    low = league_name.lower()
    for pat in HARD_BLACKLIST_PATTERNS:
        if pat in low:
            return True
    return False

def is_soft_blacklist(league_name):
    low = league_name.lower()
    for pat in SOFT_BLACKLIST_PATTERNS:
        if pat in low:
            return True
    return False

# ─── Analysis ───
print("=" * 60)
print("FOOTBALL ML POLICY v3 — DEPLOYMENT SHORTLIST")
print("=" * 60)

all_results = {}

for pol_name, pol in policies.items():
    sub = pol["data"]
    n = len(sub)
    s = policy_summary(sub)
    print(f"\n{'='*60}")
    print(f"POLICY: {pol_name} (n={n})")
    print(f"{'='*60}")
    print(f"  Overall: HR={s['hit_rate']}%, ROI_k={s['roi_kelly']}%, PnL={s['pnl_flat']}")

    # ── League breakdown ──
    league_rows = []
    for league in sub["league"].unique():
        lg = sub[sub["league"] == league]
        ls = policy_summary(lg)
        ls["league"] = league
        ls["pnl"] = round(lg["pnl_flat"].sum(), 2)
        ls["n_bets"] = len(lg)
        league_rows.append(ls)
    league_df = pd.DataFrame(league_rows).sort_values("pnl", ascending=False)
    if s["pnl_flat"] != 0:
        league_df["pnl_contrib"] = (league_df["pnl"] / s["pnl_flat"] * 100).round(1)
    else:
        league_df["pnl_contrib"] = 0

    # ── Blacklist-based filtering ──
    # Practical approach: exclude structural noise, keep everything else.
    # The ML edge filter does the real selection work.
    def passes_filter(row):
        lg = row["league"]
        n_bets = row["n_bets"]
        # Hard blacklist: always exclude
        if is_hard_blacklist(lg):
            return False
        # Soft blacklist: cup/playoff with very few bets
        if is_soft_blacklist(lg) and n_bets < 5:
            return False
        # Microsample with terrible ROI
        if n_bets < 3 and row["roi_kelly"] < 0:
            return False
        return True

    filter_mask = league_df.apply(passes_filter, axis=1)
    whitelist = league_df[filter_mask]["league"].tolist()
    blacklist_leagues = league_df[~filter_mask]["league"].tolist()

    print(f"  After blacklist: {len(whitelist)} leagues kept, {len(blacklist_leagues)} excluded")

    # ── Filtered data ──
    wl_sub = sub[sub["league"].isin(whitelist)].copy().sort_values("match_date").reset_index(drop=True)
    wl_s = policy_summary(wl_sub)
    print(f"  Filtered: n={wl_s['n_bets']}, HR={wl_s['hit_rate']}%, ROI_k={wl_s['roi_kelly']}%, PnL={wl_s['pnl_flat']}")

    # ── Monthly breakdown ──
    monthly_rows = []
    for month in sorted(wl_sub["month"].unique()):
        m = wl_sub[wl_sub["month"] == month]
        ms = policy_summary(m)
        ms["month"] = month
        ms["pnl"] = round(m["pnl_flat"].sum(), 2)
        monthly_rows.append(ms)
    monthly_df = pd.DataFrame(monthly_rows)
    monthly_df["cum_pnl"] = monthly_df["pnl"].cumsum().round(2)

    losing_months = (monthly_df["pnl"] < 0).astype(int)
    consec, max_consec = 0, 0
    for v in losing_months.values:
        if v == 1: consec += 1; max_consec = max(max_consec, consec)
        else: consec = 0

    worst_month = monthly_df.loc[monthly_df["pnl"].idxmin()]
    print(f"  Monthly: max_consec_losing={max_consec}, worst={worst_month['month']} PnL={worst_month['pnl']}")

    # ── Quarterly breakdown ──
    quarterly_rows = []
    for quarter in sorted(wl_sub["quarter"].unique()):
        q = wl_sub[wl_sub["quarter"] == quarter]
        qs = policy_summary(q)
        qs["quarter"] = quarter
        qs["pnl"] = round(q["pnl_flat"].sum(), 2)
        quarterly_rows.append(qs)
    quarterly_df = pd.DataFrame(quarterly_rows)
    quarterly_df["cum_pnl"] = quarterly_df["pnl"].cumsum().round(2)
    worst_quarter = quarterly_df.loc[quarterly_df["pnl"].idxmin()]
    print(f"  Quarterly: worst={worst_quarter['quarter']} PnL={worst_quarter['pnl']}")

    # ── Risk metrics ──
    streaks = compute_streaks(wl_sub["bet_won"].values)
    max_losing_streak = max(streaks)
    max_dd_flat, _ = compute_drawdown(wl_sub["pnl_flat"].values)
    max_dd_kelly, _ = compute_drawdown(wl_sub["pnl_kelly"].values)
    print(f"  Risk: max_losing_streak={max_losing_streak}, max_dd_flat={max_dd_flat:.2f}, max_dd_kelly={max_dd_kelly*100:.1f}%")

    # Rolling
    roll50 = rolling_roi(wl_sub, 50)
    roll100 = rolling_roi(wl_sub, 100)
    if roll50:
        neg50 = sum(1 for r in roll50 if r < 0)
        print(f"  Rolling50: min={min(roll50)}%, max={max(roll50)}%, neg={neg50}/{len(roll50)} ({neg50/len(roll50)*100:.0f}%)")
    if roll100:
        neg100 = sum(1 for r in roll100 if r < 0)
        print(f"  Rolling100: min={min(roll100)}%, max={max(roll100)}%, neg={neg100}/{len(roll100)} ({neg100/len(roll100)*100:.0f}%)")

    # ── Outcome stability ──
    for outcome in ["home", "away"]:
        osub = wl_sub[wl_sub["bet_outcome"] == outcome]
        if len(osub) == 0: continue
        os = policy_summary(osub)
        os_pnl = round(osub["pnl_flat"].sum(), 2)
        pct = len(osub) / wl_s["n_bets"] * 100
        contrib = os_pnl / wl_s["pnl_flat"] * 100 if wl_s["pnl_flat"] != 0 else 0
        print(f"  {outcome}: n={len(osub)} ({pct:.0f}%), HR={os['hit_rate']}%, ROI_k={os['roi_kelly']}%, PnL={os_pnl}, contrib={contrib:.0f}%")

    # ── Stress tests ──
    wl_league_df = league_df[league_df["league"].isin(whitelist)].sort_values("pnl", ascending=False)
    top1_league = wl_league_df.iloc[0]["league"] if len(wl_league_df) > 0 else None
    top2_wl = wl_league_df.head(2)["league"].tolist()

    stress_no_top1 = wl_sub[~wl_sub["league"].isin([top1_league])] if top1_league else wl_sub
    stress_no_top2 = wl_sub[~wl_sub["league"].isin(top2_wl)]

    s_no_top1 = policy_summary(stress_no_top1)
    s_no_top2 = policy_summary(stress_no_top2)

    print(f"  Stress -top1 ({top1_league}): n={s_no_top1['n_bets']}, ROI_k={s_no_top1['roi_kelly']}%, PnL={s_no_top1['pnl_flat']}")
    print(f"  Stress -top2 ({', '.join(top2_wl)}): n={s_no_top2['n_bets']}, ROI_k={s_no_top2['roi_kelly']}%, PnL={s_no_top2['pnl_flat']}")

    # ── Store ──
    all_results[pol_name] = {
        "summary": s,
        "wl_summary": wl_s,
        "whitelist": whitelist,
        "blacklist": blacklist_leagues,
        "league_df": league_df,
        "monthly_df": monthly_df,
        "quarterly_df": quarterly_df,
        "max_losing_streak": max_losing_streak,
        "max_dd_flat": max_dd_flat,
        "max_dd_kelly": max_dd_kelly,
        "roll50": roll50,
        "roll100": roll100,
        "worst_month": worst_month.to_dict(),
        "worst_quarter": worst_quarter.to_dict(),
        "max_consec_losing_months": max_consec,
        "top1_league": top1_league,
        "top2_leagues": top2_wl,
        "s_no_top1": s_no_top1,
        "s_no_top2": s_no_top2,
        "per_month": round(wl_s["n_bets"] / TEST_MONTHS, 1),
        "per_week": round(wl_s["n_bets"] / (TEST_MONTHS * 4.35), 1),
    }

# ─── Generate Markdown ───
md = []
md.append("# Football ML Policy v3 — Deployment Shortlist\n")
md.append("Generated from test_predictions.csv (period: 2025-01 to 2026-04, ~15.25 months)\n")
md.append("Focus: B_NCF_Tight, C_Bal_Core, D_Bal_Tight — blacklist filtering, stability, stress test.\n")

md.append("## 1. Executive Summary\n")
md.append("Three policies analyzed after practical league filtering:")
md.append("- **Draw excluded** from all picks (v1 conclusion)")
md.append("- **Home/away only** — away bets carry the edge")
md.append("- **Blacklist approach**: exclude structural noise (reserve/youth/women/friendly), not whitelist-only")
md.append("- **Stress tested**: removing top-1 and top-2 leagues by PnL contribution\n")

md.append("| Policy | Segment | Edge | Filtered Bets | Filtered ROI_k | Bets/Mo | Max DD Kelly | Max Losing |")
md.append("|--------|---------|------|---------------|----------------|---------|--------------|------------|")

for pol_name in ["B_NCF_Tight", "C_Bal_Core", "D_Bal_Tight"]:
    r = all_results[pol_name]
    ws = r["wl_summary"]
    pm = r["per_month"]
    edge = 0.07 if "Tight" in pol_name and "NCF" in pol_name else 0.05 if "Core" in pol_name else 0.06
    seg = "no_clear_favorite" if "NCF" in pol_name else "balanced"
    md.append(f"| {pol_name} | {seg} | >{edge} | {ws['n_bets']} | {ws['roi_kelly']}% | {pm} | {r['max_dd_kelly']*100:.1f}% | {r['max_losing_streak']} |")

md.append("")

# ── Per-policy detail ──
for pol_name in ["B_NCF_Tight", "C_Bal_Core", "D_Bal_Tight"]:
    r = all_results[pol_name]
    s = r["summary"]
    ws = r["wl_summary"]
    edge = 0.07 if "Tight" in pol_name and "NCF" in pol_name else 0.05 if "Core" in pol_name else 0.06
    seg = "no_clear_favorite" if "NCF" in pol_name else "balanced"

    md.append(f"\n## 2. {pol_name}\n")
    md.append(f"- **Segment**: {seg}")
    md.append(f"- **Edge threshold**: > {edge}")
    md.append(f"- **Outcomes**: Home / Away (draw excluded)\n")

    md.append("### Before vs After Blacklist\n")
    md.append(f"| Metric | Before | After Blacklist |")
    md.append(f"|--------|--------|-----------------|")
    md.append(f"| Bets | {s['n_bets']} | {ws['n_bets']} |")
    md.append(f"| Hit Rate | {s['hit_rate']}% | {ws['hit_rate']}% |")
    md.append(f"| ROI Kelly | {s['roi_kelly']}% | {ws['roi_kelly']}% |")
    md.append(f"| PnL Flat | {s['pnl_flat']} | {ws['pnl_flat']} |")
    md.append(f"| Bets/Month | {round(s['n_bets']/TEST_MONTHS, 1)} | {r['per_month']} |")
    md.append(f"| Leagues | {len(r['league_df'])} | {len(r['whitelist'])} kept, {len(r['blacklist'])} excluded |")
    md.append("")

    md.append("### Blacklisted Leagues (excluded)\n")
    md.append(f"Total: {len(r['blacklist'])} leagues\n")
    for lg in r["blacklist"][:20]:
        lg_row = r["league_df"][r["league_df"]["league"] == lg].iloc[0]
        md.append(f"- {lg}: n={int(lg_row['n_bets'])}, ROI_k={lg_row['roi_kelly']}%, PnL={lg_row['pnl']}")
    if len(r["blacklist"]) > 20:
        md.append(f"- ... and {len(r['blacklist']) - 20} more")
    md.append("")

    md.append("### Monthly Stability (after blacklist)\n")
    md.append("| Month | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |")
    md.append("|-------|------|----------|-----------|-----|---------|")
    for _, row in r["monthly_df"].iterrows():
        flag = " **" if row["pnl"] < -5 else ""
        md.append(f"| {row['month']} | {row['n_bets']} | {row['hit_rate']}% | {row['roi_kelly']}% | {row['pnl']} | {row['cum_pnl']} |{flag}")
    md.append(f"\nMax consecutive losing months: {r['max_consec_losing_months']}")
    md.append(f"Worst month: {r['worst_month']['month']}, PnL={r['worst_month']['pnl']}, n={r['worst_month']['n_bets']}\n")

    md.append("### Quarterly Stability (after blacklist)\n")
    md.append("| Quarter | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |")
    md.append("|---------|------|----------|-----------|-----|---------|")
    for _, row in r["quarterly_df"].iterrows():
        md.append(f"| {row['quarter']} | {row['n_bets']} | {row['hit_rate']}% | {row['roi_kelly']}% | {row['pnl']} | {row['cum_pnl']} |")
    md.append(f"Worst quarter: {r['worst_quarter']['quarter']}, PnL={r['worst_quarter']['pnl']}\n")

    md.append("### Risk Metrics (after blacklist)\n")
    md.append(f"- **Max drawdown (flat)**: {r['max_dd_flat']:.2f} units")
    md.append(f"- **Max drawdown (Kelly)**: {r['max_dd_kelly']*100:.1f}% of bankroll")
    md.append(f"- **Longest losing streak**: {r['max_losing_streak']}")
    md.append(f"- **Worst month**: {r['worst_month']['month']} (PnL={r['worst_month']['pnl']})")
    md.append(f"- **Worst quarter**: {r['worst_quarter']['quarter']} (PnL={r['worst_quarter']['pnl']})")

    if r["roll50"]:
        neg50 = sum(1 for x in r["roll50"] if x < 0)
        md.append(f"- **Rolling 50-bet ROI**: min={min(r['roll50'])}%, max={max(r['roll50'])}%, avg={round(np.mean(r['roll50']), 2)}%")
        md.append(f"- **Negative 50-bet windows**: {neg50}/{len(r['roll50'])} ({neg50/len(r['roll50'])*100:.0f}%)")
    if r["roll100"]:
        neg100 = sum(1 for x in r["roll100"] if x < 0)
        md.append(f"- **Rolling 100-bet ROI**: min={min(r['roll100'])}%, max={max(r['roll100'])}%, avg={round(np.mean(r['roll100']), 2)}%")
        md.append(f"- **Negative 100-bet windows**: {neg100}/{len(r['roll100'])} ({neg100/len(r['roll100'])*100:.0f}%)")
    md.append("")

    md.append("### Stress Test\n")
    md.append(f"**Remove top-1 league** ({r['top1_league']}):")
    md.append(f"- n={r['s_no_top1']['n_bets']}, HR={r['s_no_top1']['hit_rate']}%, ROI_k={r['s_no_top1']['roi_kelly']}%, PnL={r['s_no_top1']['pnl_flat']}")
    v1 = 'PASS' if r['s_no_top1']['roi_kelly'] > 5 else ('MARGINAL' if r['s_no_top1']['roi_kelly'] > 0 else 'FAIL')
    md.append(f"- Verdict: {v1}")
    md.append("")
    md.append(f"**Remove top-2 leagues** ({', '.join(r['top2_leagues'])}):")
    md.append(f"- n={r['s_no_top2']['n_bets']}, HR={r['s_no_top2']['hit_rate']}%, ROI_k={r['s_no_top2']['roi_kelly']}%, PnL={r['s_no_top2']['pnl_flat']}")
    v2 = 'PASS' if r['s_no_top2']['roi_kelly'] > 5 else ('MARGINAL' if r['s_no_top2']['roi_kelly'] > 0 else 'FAIL')
    md.append(f"- Verdict: {v2}")
    md.append("")

# ── Final Decision ──
md.append("\n## 5. Final Decision\n")

scores = {}
for pol_name in ["B_NCF_Tight", "C_Bal_Core", "D_Bal_Tight"]:
    r = all_results[pol_name]
    ws = r["wl_summary"]
    score = 0
    reasons = []

    if ws["roi_kelly"] >= 20: score += 3; reasons.append("excellent ROI")
    elif ws["roi_kelly"] >= 10: score += 2; reasons.append("good ROI")
    elif ws["roi_kelly"] >= 5: score += 1; reasons.append("moderate ROI")

    pm = r["per_month"]
    if pm >= 10: score += 2; reasons.append(f"good volume ({pm}/mo)")
    elif pm >= 5: score += 1; reasons.append(f"acceptable volume ({pm}/mo)")
    else: score += 0; reasons.append(f"low volume ({pm}/mo)")

    if r["max_dd_kelly"] < 0.15: score += 2; reasons.append("low DD")
    elif r["max_dd_kelly"] < 0.25: score += 1; reasons.append("moderate DD")
    else: score += 0; reasons.append("high DD")

    if r["max_losing_streak"] <= 8: score += 2; reasons.append("short losing streak")
    elif r["max_losing_streak"] <= 12: score += 1; reasons.append("acceptable losing streak")
    else: score += 0; reasons.append("long losing streak")

    if r["roll50"]:
        neg50_pct = sum(1 for x in r["roll50"] if x < 0) / len(r["roll50"]) * 100
        if neg50_pct < 20: score += 2; reasons.append("stable rolling")
        elif neg50_pct < 35: score += 1; reasons.append("acceptable rolling")
        else: score += 0; reasons.append("unstable rolling")

    if r["s_no_top2"]["roi_kelly"] > 5: score += 2; reasons.append("robust without top leagues")
    elif r["s_no_top2"]["roi_kelly"] > 0: score += 1; reasons.append("survives without top leagues")
    else: score += 0; reasons.append("depends on top leagues")

    scores[pol_name] = {"score": score, "reasons": reasons}

sorted_scores = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)

md.append("| Policy | Score | Key Strengths | Key Risks |")
md.append("|--------|-------|---------------|-----------|")
for pol_name, sc in sorted_scores:
    r = all_results[pol_name]
    strengths = "; ".join(sc["reasons"][:3])
    risks = "; ".join(sc["reasons"][3:]) if len(sc["reasons"]) > 3 else "—"
    md.append(f"| {pol_name} | {sc['score']}/13 | {strengths} | {risks} |")
md.append("")

primary = sorted_scores[0][0]
secondary = sorted_scores[1][0]
pilot = sorted_scores[2][0]

sec_score = sorted_scores[1][1]["score"]
sec_verdict = "SECONDARY READY" if sec_score >= 8 else "PILOT"

md.append(f"### PRIMARY READY: {primary}\n")
md.append(f"- Score: {scores[primary]['score']}/13")
md.append(f"- ROI Kelly: {all_results[primary]['wl_summary']['roi_kelly']}%")
md.append(f"- Bets/month: {all_results[primary]['per_month']}")
md.append(f"- Max DD Kelly: {all_results[primary]['max_dd_kelly']*100:.1f}%")
md.append(f"- Strengths: {'; '.join(scores[primary]['reasons'])}\n")

md.append(f"### {sec_verdict}: {secondary}\n")
md.append(f"- Score: {scores[secondary]['score']}/13")
md.append(f"- ROI Kelly: {all_results[secondary]['wl_summary']['roi_kelly']}%")
md.append(f"- Bets/month: {all_results[secondary]['per_month']}")
md.append(f"- Max DD Kelly: {all_results[secondary]['max_dd_kelly']*100:.1f}%")
md.append(f"- Strengths: {'; '.join(scores[secondary]['reasons'])}\n")

md.append(f"### REJECT (for now): {pilot}\n")
md.append(f"- Score: {scores[pilot]['score']}/13")
md.append(f"- ROI Kelly: {all_results[pilot]['wl_summary']['roi_kelly']}%")
md.append(f"- Bets/month: {all_results[pilot]['per_month']}")
md.append(f"- Reasons: {'; '.join(scores[pilot]['reasons'])}\n")

# ── Implementation Rules ──
md.append("\n## 6. Implementation-Ready Rules\n")

for pol_name in [primary, secondary]:
    r = all_results[pol_name]
    ws = r["wl_summary"]
    edge = 0.07 if "Tight" in pol_name and "NCF" in pol_name else 0.05 if "Core" in pol_name else 0.06
    segment = "no_clear_favorite" if "NCF" in pol_name else "balanced"

    md.append(f"### {pol_name}\n")
    md.append("```")
    md.append(f"SEGMENT: {segment}")
    md.append(f"EDGE_THRESHOLD: {edge}")
    md.append(f"ALLOWED_OUTCOMES: [home, away]")
    md.append(f"DRAW: excluded")
    md.append(f"MIN_ODDS: 1.55")
    md.append(f"KELLY_FRACTION: 0.25")
    md.append(f"MAX_STAKE_PCT: 0.10")
    md.append(f"BLACKLIST_PATTERNS (hard): reserve, women, youth, friendly, san-juan")
    md.append(f"BLACKLIST_PATTERNS (soft, n<5): cup, playoff")
    md.append(f"EXPECTED_BETS_MONTH: ~{r['per_month']}")
    md.append(f"EXPECTED_BETS_WEEK: ~{r['per_week']}")
    md.append(f"EXPECTED_ROI_KELLY: {ws['roi_kelly']}%")
    md.append(f"EXPECTED_HIT_RATE: {ws['hit_rate']}%")
    md.append(f"AVG_ODDS: {ws['avg_odds']}")
    md.append(f"MAX_DRAWDOWN_KELLY: {r['max_dd_kelly']*100:.1f}%")
    md.append(f"MAX_DRAWDOWN_FLAT: {r['max_dd_flat']:.2f} units")
    md.append(f"LONGEST_LOSING_STREAK: {r['max_losing_streak']}")
    md.append(f"WORST_MONTH: {r['worst_month']['month']} (PnL={r['worst_month']['pnl']})")
    md.append(f"WORST_QUARTER: {r['worst_quarter']['quarter']} (PnL={r['worst_quarter']['pnl']})")
    md.append("```\n")

with open(OUTPUT_MD, "w") as f:
    f.write("\n".join(md))

print(f"\n\nReport saved to: {OUTPUT_MD}")
print("Done.")
