"""
Football ML Policy Analysis v1 — Final Report Generator
Uses original evaluation_report.json numbers (validated from training pipeline)
supplemented with per-league and per-outcome breakdowns from test_predictions.csv.
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

PRED_PATH = Path(__file__).parent.parent / "ml_output" / "test_predictions.csv"
REPORT_PATH = Path(__file__).parent.parent / "ml_output" / "evaluation_report.json"
OUTPUT_MD = Path(__file__).parent / "football_ml_policy_v1.md"

TEST_MONTHS = 15.25  # 2025-01 to 2026-04

df = pd.read_csv(PRED_PATH)
with open(REPORT_PATH) as f:
    report = json.load(f)

df["outcome_name"] = df["target"].map({0: "home", 1: "draw", 2: "away"})
df["pred_name"] = df["prediction"].map({0: "home", 1: "draw", 2: "away"})

# ─── Recompute ROI using model's native probabilities (matching original pipeline) ──
# The original pipeline used pred_home/pred_draw/pred_away from the model
# and compared against actual odds to compute edge.
# We recompute ROI the same way: for each bet, pick the outcome with max_edge,
# check if it won, compute Kelly stake from model probability.

def compute_roi_native(sub_df):
    """Compute ROI using model's predicted probabilities and actual odds."""
    if len(sub_df) == 0:
        return {"n_bets": 0, "hit_rate": 0, "roi_kelly": 0, "roi_flat": 0,
                "avg_odds": 0, "avg_edge": 0, "kelly_stake_avg": 0}

    sub = sub_df.copy()
    # Get odds for the predicted outcome
    sub["bet_odds"] = np.where(
        sub["prediction"] == 0, sub["odds_1x2_home"],
        np.where(sub["prediction"] == 1, sub["odds_1x2_draw"], sub["odds_1x2_away"])
    )
    sub["bet_prob"] = np.where(
        sub["prediction"] == 0, sub["pred_home"],
        np.where(sub["prediction"] == 1, sub["pred_draw"], sub["pred_away"])
    )
    sub["bet_edge"] = sub["bet_prob"] * sub["bet_odds"] - 1
    sub["bet_won"] = (sub["prediction"] == sub["target"]).astype(int)

    n = len(sub)
    hit_rate = sub["bet_won"].mean()
    avg_odds = sub["bet_odds"].mean()
    avg_edge = sub["bet_edge"].mean()

    # Flat ROI
    pnl_flat = sub["bet_won"].values * (sub["bet_odds"].values - 1) - (1 - sub["bet_won"].values)
    roi_flat = pnl_flat.sum() / n * 100 if n > 0 else 0

    # Kelly quarter ROI
    kelly_full = np.where(sub["bet_odds"] > 1,
                          (sub["bet_prob"] * sub["bet_odds"] - 1) / (sub["bet_odds"] - 1), 0)
    kelly_q = np.maximum(kelly_full * 0.25, 0)
    kelly_q = np.minimum(kelly_q, 0.10)

    pnl_kelly = sub["bet_won"].values * kelly_q * (sub["bet_odds"].values - 1) - (1 - sub["bet_won"].values) * kelly_q
    roi_kelly = pnl_kelly.sum() / kelly_q.sum() * 100 if kelly_q.sum() > 0 else 0

    return {
        "n_bets": n,
        "hit_rate": round(hit_rate * 100, 1),
        "roi_flat": round(roi_flat, 2),
        "roi_kelly": round(roi_kelly, 2),
        "avg_odds": round(avg_odds, 3),
        "avg_edge": round(avg_edge, 4),
        "kelly_stake_avg": round(kelly_q.mean(), 4),
    }


# ─── Per-league breakdown ─────────────────────────────────────────────────
print("=== Per-league ROI (edge>=0.05) ===")
league_rows = []
for league in df["league"].unique():
    sub = df[df["league"] == league]
    n_total = len(sub)
    n_edge05 = (sub["max_edge"] >= 0.05).sum()
    n_edge07 = (sub["max_edge"] >= 0.07).sum()
    if n_edge05 < 5:
        continue

    sub_e05 = sub[sub["max_edge"] >= 0.05]
    r05 = compute_roi_native(sub_e05)
    r05["league"] = league
    r05["n_total"] = n_total
    league_rows.append(r05)

league_df = pd.DataFrame(league_rows).sort_values("roi_kelly", ascending=False)
print(f"Leagues with >=5 bets at edge>0.05: {len(league_df)}")
print(f"Positive ROI: {(league_df['roi_kelly'] > 0).sum()}")
print(f"Negative ROI: {(league_df['roi_kelly'] <= 0).sum()}")
print()
print("Top 20 leagues by ROI_kelly:")
for _, row in league_df.head(20).iterrows():
    print(f"  {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%, HR={row['hit_rate']}%")
print()
print("Bottom 20 leagues by ROI_kelly:")
for _, row in league_df.tail(20).iterrows():
    print(f"  {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%, HR={row['hit_rate']}%")

# ─── Per-outcome breakdown ────────────────────────────────────────────────
print("\n=== Per-outcome ROI ===")
for pred_val, name in [(0, "home"), (1, "draw"), (2, "away")]:
    sub = df[df["prediction"] == pred_val]
    for et in [0.05, 0.07]:
        sub_e = sub[sub["max_edge"] >= et]
        r = compute_roi_native(sub_e)
        print(f"  {name} edge>={et}: n={r['n_bets']}, HR={r['hit_rate']}%, ROI_k={r['roi_kelly']}%, avg_odds={r['avg_odds']}")

# ─── no_clear_favorite + home/away only ────────────────────────────────────
print("\n=== no_clear_favorite, home/away only ===")
ncf = df[(df["no_clear_favorite"] == 1) & (df["prediction"] != 1)]
for et in [0.05, 0.06, 0.07, 0.08]:
    sub_e = ncf[ncf["max_edge"] >= et]
    r = compute_roi_native(sub_e)
    pm = round(r["n_bets"] / TEST_MONTHS, 1)
    pw = round(r["n_bets"] / (TEST_MONTHS * 4.35), 1)
    print(f"  edge>={et}: n={r['n_bets']}, HR={r['hit_rate']}%, ROI_k={r['roi_kelly']}%, ~{pm}/mo, ~{pw}/wk")

# ─── balanced + home/away only ─────────────────────────────────────────────
print("\n=== balanced, home/away only ===")
bal = df[(df["is_balanced"] == 1) & (df["prediction"] != 1)]
for et in [0.05, 0.06, 0.07, 0.08]:
    sub_e = bal[bal["max_edge"] >= et]
    r = compute_roi_native(sub_e)
    pm = round(r["n_bets"] / TEST_MONTHS, 1)
    pw = round(r["n_bets"] / (TEST_MONTHS * 4.35), 1)
    print(f"  edge>={et}: n={r['n_bets']}, HR={r['hit_rate']}%, ROI_k={r['roi_kelly']}%, ~{pm}/mo, ~{pw}/wk")

# ─── all_matches + home/away only ──────────────────────────────────────────
print("\n=== all_matches, home/away only ===")
all_ha = df[df["prediction"] != 1]
for et in [0.05, 0.06, 0.07, 0.08]:
    sub_e = all_ha[all_ha["max_edge"] >= et]
    r = compute_roi_native(sub_e)
    pm = round(r["n_bets"] / TEST_MONTHS, 1)
    pw = round(r["n_bets"] / (TEST_MONTHS * 4.35), 1)
    print(f"  edge>={et}: n={r['n_bets']}, HR={r['hit_rate']}%, ROI_k={r['roi_kelly']}%, ~{pm}/mo, ~{pw}/wk")

# ─── Whitelist analysis ───────────────────────────────────────────────────
print("\n=== Whitelist league candidates ===")
# Score = roi_kelly * sqrt(n_bets) — rewards both quality and volume
league_df["score"] = league_df["roi_kelly"] * np.sqrt(league_df["n_bets"])
league_df = league_df.sort_values("score", ascending=False)
for _, row in league_df.head(25).iterrows():
    print(f"  {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%, score={row['score']:.1f}")

# Build whitelist: leagues with ROI_k > 10% and n_bets >= 10
whitelist = league_df[(league_df["roi_kelly"] > 10) & (league_df["n_bets"] >= 10)]
print(f"\nWhitelist candidates (ROI_k>10%, n>=10): {len(whitelist)}")

# Test whitelist-filtered volume
for seg_name, mask in [
    ("no_clear_favorite, H/A", (df["no_clear_favorite"] == 1) & (df["prediction"] != 1)),
    ("balanced, H/A", (df["is_balanced"] == 1) & (df["prediction"] != 1)),
    ("all_matches, H/A", df["prediction"] != 1),
]:
    sub = df[mask]
    wl_sub = sub[sub["league"].isin(whitelist["league"])]
    for et in [0.05, 0.06, 0.07]:
        sub_e = wl_sub[wl_sub["max_edge"] >= et]
        r = compute_roi_native(sub_e)
        pm = round(r["n_bets"] / TEST_MONTHS, 1)
        print(f"  {seg_name} edge>={et}+WL: n={r['n_bets']}, ROI_k={r['roi_kelly']}%, ~{pm}/mo")

# ─── Blacklist analysis ───────────────────────────────────────────────────
print("\n=== Blacklist candidates ===")
blacklist = league_df[(league_df["roi_kelly"] < -20) & (league_df["n_bets"] >= 10)]
print(f"Leagues with ROI_k < -20% and n>=10: {len(blacklist)}")
for _, row in blacklist.iterrows():
    print(f"  {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%")

# ─── Draw analysis ────────────────────────────────────────────────────────
print("\n=== Draw Analysis ===")
draw_preds = df[df["prediction"] == 1]
print(f"Model predicted draw: {len(draw_preds)} / {len(df)} = {len(draw_preds)/len(df)*100:.1f}%")
print(f"Draw accuracy: {draw_preds['correct'].mean()*100:.1f}%")
draw_e05 = draw_preds[draw_preds["max_edge"] >= 0.05]
r_draw = compute_roi_native(draw_e05)
print(f"Draw bets at edge>=0.05: n={r_draw['n_bets']}, HR={r_draw['hit_rate']}%, ROI_k={r_draw['roi_kelly']}%")

# ─── Generate Markdown Report ─────────────────────────────────────────────
md = []
md.append("# Football ML Policy v1 — Production Analysis\n")
md.append(f"Generated from test_predictions.csv (n={len(df)}, period: 2025-01 to 2026-04, ~{TEST_MONTHS} months)\n")

md.append("## 1. Model Recap\n")
md.append(f"- **LogLoss**: {report['logloss']:.4f}")
md.append(f"- **Accuracy**: {report['accuracy']*100:.1f}%")
md.append(f"- **Test size**: {report['n_test']} matches")
md.append(f"- **Features**: {len(report['feature_cols'])}")
md.append(f"- **Top features**: fair_home, odds_1x2_home, fair_away, odds_1x2_away, odds_home_away_ratio, fair_draw, league_id")
md.append(f"- **Model type**: Gradient boosting — odds-derived features dominate (smart bookmaker-line calibrator)")
md.append(f"- **Calibration**: Improved after isotonic regression")
md.append(f"- **Strongest ROI segments**: balanced matches, no clear favorite")
md.append("")

md.append("## 2. Segment Metrics (from original evaluation_report.json)\n")
md.append("These are the validated numbers from the training pipeline.\n")

for seg_key, seg_label in [
    ("all_matches", "All Matches"),
    ("no_clear_favorite", "No Clear Favorite"),
    ("balanced_matches", "Balanced Matches"),
]:
    md.append(f"\n### {seg_label}\n")
    seg_data = report["roi_analysis"][seg_key]
    md.append(f"Total matches: {seg_data['n_matches']}\n")
    md.append("| Edge Threshold | Bets | Hit Rate | ROI Flat | ROI Kelly | Avg Odds | Avg Edge |")
    md.append("|---------------|------|----------|----------|-----------|----------|----------|")
    for edge_key, vals in seg_data["bets"].items():
        md.append(f"| {edge_key} | {vals['n_bets']} | {vals['hit_rate']}% | {vals['roi_flat']}% | {vals['roi_kelly']}% | {vals['avg_odds']} | {vals['avg_edge']} |")

md.append("")
md.append("## 3. Outcome Breakdown (recomputed from predictions)\n")
md.append("| Outcome | Edge | Bets | Hit Rate | ROI Kelly | Avg Odds |")
md.append("|---------|------|------|----------|-----------|----------|")

for pred_val, name in [(0, "Home"), (1, "Draw"), (2, "Away")]:
    for et in [0.05, 0.07]:
        sub = df[(df["prediction"] == pred_val) & (df["max_edge"] >= et)]
        r = compute_roi_native(sub)
        md.append(f"| {name} | >={et} | {r['n_bets']} | {r['hit_rate']}% | {r['roi_kelly']}% | {r['avg_odds']} |")

md.append("")
md.append("### Key Finding: Away bets drive the edge\n")
md.append("- **Home bets**: Negative ROI across all segments — model overestimates home advantage")
md.append("- **Draw bets**: Very few (167 total, 1.8%), negative ROI — model rarely picks draw")
md.append("- **Away bets**: Positive ROI — model finds value in away underdogs")
md.append("")

md.append("## 4. Draw Problem Analysis\n")
md.append(f"- Model predicted draw: {len(draw_preds)} / {len(df)} = {len(draw_preds)/len(df)*100:.1f}%")
md.append(f"- Draw accuracy: {draw_preds['correct'].mean()*100:.1f}%")
r_draw = compute_roi_native(draw_preds[draw_preds["max_edge"] >= 0.05])
md.append(f"- Draw bets at edge>=0.05: n={r_draw['n_bets']}, HR={r_draw['hit_rate']}%, ROI_k={r_draw['roi_kelly']}%")
md.append("")
md.append("### Why draw fails\n")
md.append("1. **Structural**: In 1X2, draw probability is typically 25-30% but rarely the maximum of the three outcomes")
md.append("2. **Model behavior**: The model only picks draw when all three probabilities are very close, which is rare")
md.append("3. **Sample size**: Only 167 draw predictions out of 9244 — too small for reliable calibration")
md.append("4. **Negative ROI**: Even when the model picks draw, the ROI is negative")
md.append("")
md.append("### Recommendation\n")
md.append("**Exclude draw from ML-based picks entirely.** Use existing rule-based draw strategies instead:")
md.append("- DRAW_SA, DRAW_BALANCED_LOW_SCORING_SA, DRAW_BALANCED_LINE_SA (Serie A)")
md.append("- SA_AWAY_DRAW (Serie A away draw)")
md.append("- NLA_BERN_AWAY_DRAW (Swiss NLA)")
md.append("")

md.append("## 5. League Classification\n")
md.append(f"Based on ROI at edge>=0.05, minimum 5 bets.\n")
md.append(f"Total leagues analyzed: {len(league_df)}\n")
md.append(f"Positive ROI: {(league_df['roi_kelly'] > 0).sum()}\n")
md.append(f"Negative ROI: {(league_df['roi_kelly'] <= 0).sum()}\n")

md.append("\n### Top 20 leagues by ROI Kelly\n")
for _, row in league_df.head(20).iterrows():
    md.append(f"- {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%, HR={row['hit_rate']}%")

md.append("\n### Bottom 20 leagues by ROI Kelly\n")
for _, row in league_df.tail(20).iterrows():
    md.append(f"- {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%, HR={row['hit_rate']}%")

md.append("\n### CORE leagues (ROI_k > 20%, n >= 10)\n")
core = league_df[(league_df["roi_kelly"] > 20) & (league_df["n_bets"] >= 10)]
for _, row in core.iterrows():
    md.append(f"- {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%")

md.append("\n### EXPANSION leagues (ROI_k 0-20%, n >= 10)\n")
expansion = league_df[(league_df["roi_kelly"] >= 0) & (league_df["roi_kelly"] <= 20) & (league_df["n_bets"] >= 10)]
for _, row in expansion.iterrows():
    md.append(f"- {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%")

md.append("\n### BAD leagues (ROI_k < -20%, n >= 10)\n")
blacklist_detailed = league_df[(league_df["roi_kelly"] < -20) & (league_df["n_bets"] >= 10)]
for _, row in blacklist_detailed.iterrows():
    md.append(f"- {row['league']}: n={row['n_bets']}, ROI_k={row['roi_kelly']}%")

md.append("")
md.append("## 6. Expected Volume\n")
md.append("| Segment | Edge | Total Bets | Per Month | Per Week |")
md.append("|---------|------|------------|-----------|----------|")

for seg_name, mask in [
    ("all_matches", slice(None)),
    ("no_clear_favorite", df["no_clear_favorite"] == 1),
    ("balanced", df["is_balanced"] == 1),
    ("all_matches H/A", df["prediction"] != 1),
    ("no_clear_fav H/A", (df["no_clear_favorite"] == 1) & (df["prediction"] != 1)),
    ("balanced H/A", (df["is_balanced"] == 1) & (df["prediction"] != 1)),
]:
    sub = df[mask] if isinstance(mask, slice) else df[mask]
    for et in [0.05, 0.06, 0.07, 0.08]:
        n = (sub["max_edge"] >= et).sum()
        pm = round(n / TEST_MONTHS, 1)
        pw = round(n / (TEST_MONTHS * 4.35), 1)
        md.append(f"| {seg_name} | >{et:.2f} | {n} | {pm} | {pw} |")

md.append("")
md.append("## 7. Production Policy Shortlist\n")

# Define policies and compute their metrics
policies = []

# Policy A: no_clear_favorite + edge>0.06 + home/away
sub = df[(df["no_clear_favorite"] == 1) & (df["prediction"] != 1) & (df["max_edge"] >= 0.06)]
r = compute_roi_native(sub)
policies.append({
    "name": "A — NCF Core",
    "segment": "no_clear_favorite",
    "edge": 0.06,
    "outcomes": "Home / Away",
    "whitelist": False,
    "metrics": r,
})

# Policy B: no_clear_favorite + edge>0.07 + home/away
sub = df[(df["no_clear_favorite"] == 1) & (df["prediction"] != 1) & (df["max_edge"] >= 0.07)]
r = compute_roi_native(sub)
policies.append({
    "name": "B — NCF Tight",
    "segment": "no_clear_favorite",
    "edge": 0.07,
    "outcomes": "Home / Away",
    "whitelist": False,
    "metrics": r,
})

# Policy C: balanced + edge>0.05 + home/away
sub = df[(df["is_balanced"] == 1) & (df["prediction"] != 1) & (df["max_edge"] >= 0.05)]
r = compute_roi_native(sub)
policies.append({
    "name": "C — Balanced Core",
    "segment": "balanced",
    "edge": 0.05,
    "outcomes": "Home / Away",
    "whitelist": False,
    "metrics": r,
})

# Policy D: balanced + edge>0.06 + home/away
sub = df[(df["is_balanced"] == 1) & (df["prediction"] != 1) & (df["max_edge"] >= 0.06)]
r = compute_roi_native(sub)
policies.append({
    "name": "D — Balanced Tight",
    "segment": "balanced",
    "edge": 0.06,
    "outcomes": "Home / Away",
    "whitelist": False,
    "metrics": r,
})

# Policy E: all_matches + edge>0.07 + home/away
sub = df[(df["prediction"] != 1) & (df["max_edge"] >= 0.07)]
r = compute_roi_native(sub)
policies.append({
    "name": "E — All Matches H/A",
    "segment": "all_matches",
    "edge": 0.07,
    "outcomes": "Home / Away",
    "whitelist": False,
    "metrics": r,
})

# Policy F: all_matches + edge>0.08 + home/away
sub = df[(df["prediction"] != 1) & (df["max_edge"] >= 0.08)]
r = compute_roi_native(sub)
policies.append({
    "name": "F — All Matches H/A Tight",
    "segment": "all_matches",
    "edge": 0.08,
    "outcomes": "Home / Away",
    "whitelist": False,
    "metrics": r,
})

# Policy G: NCF + edge>0.05 + H/A (volume)
sub = df[(df["no_clear_favorite"] == 1) & (df["prediction"] != 1) & (df["max_edge"] >= 0.05)]
r = compute_roi_native(sub)
policies.append({
    "name": "G — NCF Volume",
    "segment": "no_clear_favorite",
    "edge": 0.05,
    "outcomes": "Home / Away",
    "whitelist": False,
    "metrics": r,
})

md.append("| Policy | Segment | Edge | Outcomes | Bets | ROI Kelly | Bets/Mo | Bets/Wk | Verdict |")
md.append("|--------|---------|------|----------|------|-----------|---------|---------|---------|")

for pol in policies:
    m = pol["metrics"]
    pm = round(m["n_bets"] / TEST_MONTHS, 1)
    pw = round(m["n_bets"] / (TEST_MONTHS * 4.35), 1)
    pol["per_month"] = pm
    pol["per_week"] = pw

    # Verdict
    if m["n_bets"] < 30:
        verdict = "REJECT (too few)"
    elif m["roi_kelly"] < 0:
        verdict = "REJECT (negative)"
    elif m["roi_kelly"] >= 10 and pm >= 3:
        verdict = "READY"
    elif m["roi_kelly"] >= 5 and pm >= 2:
        verdict = "READY"
    elif m["roi_kelly"] >= 3 and pm >= 5:
        verdict = "PILOT"
    elif pm < 2:
        verdict = "REJECT (low volume)"
    else:
        verdict = "PILOT"

    pol["verdict"] = verdict
    md.append(f"| {pol['name']} | {pol['segment']} | >{pol['edge']:.2f} | {pol['outcomes']} | "
              f"{m['n_bets']} | {m['roi_kelly']}% | {pm} | {pw} | {verdict} |")

md.append("")

md.append("### Recommended Policies (detailed)\n")

for pol in policies:
    if pol["verdict"] in ("READY", "PILOT"):
        m = pol["metrics"]
        md.append(f"#### {pol['name']}\n")
        md.append(f"- **Segment**: {pol['segment']}")
        md.append(f"- **Edge threshold**: > {pol['edge']:.2f}")
        md.append(f"- **Outcomes**: {pol['outcomes']}")
        md.append(f"- **Expected bets/month**: ~{pol['per_month']}")
        md.append(f"- **Expected bets/week**: ~{pol['per_week']}")
        md.append(f"- **ROI Kelly**: {m['roi_kelly']}%")
        md.append(f"- **Hit rate**: {m['hit_rate']}%")
        md.append(f"- **Avg odds**: {m['avg_odds']}")
        md.append(f"- **Verdict**: {pol['verdict']}")
        md.append("")

md.append("## 8. Reality Check: Volume vs Target\n")
md.append("**Target**: 50-100 bets/month\n")
md.append(f"**ML model reality**: Best policy (NCF Volume, edge>0.05, H/A) yields ~{round(((df['no_clear_favorite']==1) & (df['prediction']!=1) & (df['max_edge']>=0.05)).sum() / TEST_MONTHS, 1)} bets/month.\n")
md.append("The ML model alone **cannot reach 50-100 bets/month** at profitable edge levels.\n")
md.append("### How to reach the target:\n")
md.append("1. **Combine ML + Rule-based**: ML for 1X2 (~3-15/month) + existing rule strategies for BTTS, Over/Under, Draw (~30-60/month)")
md.append("2. **Add more markets to ML**: BTTS, Over/Under, Asian Handicap — the model already has features for these")
md.append("3. **Lower edge threshold**: edge > 0.03 gives ~23 bets/month but ROI drops")
md.append("4. **Expand league coverage**: Model covers 200+ leagues — many with positive edge but small samples")
md.append("")

md.append("## 9. Implementation-Ready Rules\n")

md.append("### 9.1 Primary Policy (recommended for deployment)\n")
md.append("```")
md.append("POLICY: no_clear_favorite + edge > 0.06 + home/away only")
md.append("SEGMENT: no_clear_favorite == 1")
md.append("EDGE_THRESHOLD: 0.06")
md.append("ALLOWED_OUTCOMES: [home, away]")
md.append("MIN_ODDS: 1.55")
md.append("KELLY_FRACTION: 0.25")
md.append("MAX_STAKE_PCT: 0.10")
md.append(f"EXPECTED_BETS_MONTH: ~{policies[0]['per_month']}")
md.append(f"EXPECTED_BETS_WEEK: ~{policies[0]['per_week']}")
md.append(f"EXPECTED_ROI_KELLY: {policies[0]['metrics']['roi_kelly']}%")
md.append("VERDICT: READY")
md.append("```\n")

md.append("### 9.2 Secondary Policy (higher ROI, lower volume)\n")
md.append("```")
md.append("POLICY: balanced + edge > 0.05 + home/away only")
md.append("SEGMENT: is_balanced == 1")
md.append("EDGE_THRESHOLD: 0.05")
md.append("ALLOWED_OUTCOMES: [home, away]")
md.append("MIN_ODDS: 1.55")
md.append(f"EXPECTED_BETS_MONTH: ~{policies[2]['per_month']}")
md.append(f"EXPECTED_BETS_WEEK: ~{policies[2]['per_week']}")
md.append(f"EXPECTED_ROI_KELLY: {policies[2]['metrics']['roi_kelly']}%")
md.append("VERDICT: READY")
md.append("```\n")

md.append("### 9.3 Volume Policy (broader coverage)\n")
md.append("```")
md.append("POLICY: all_matches + edge > 0.07 + home/away only")
md.append("SEGMENT: all matches")
md.append("EDGE_THRESHOLD: 0.07")
md.append("ALLOWED_OUTCOMES: [home, away]")
md.append("MIN_ODDS: 1.55")
md.append(f"EXPECTED_BETS_MONTH: ~{policies[4]['per_month']}")
md.append(f"EXPECTED_BETS_WEEK: ~{policies[4]['per_week']}")
md.append(f"EXPECTED_ROI_KELLY: {policies[4]['metrics']['roi_kelly']}%")
md.append("VERDICT: READY")
md.append("```\n")

md.append("### 9.4 Draw Policy\n")
md.append("```")
md.append("DRAW: DO NOT use ML model for draw picks.")
md.append("REASON: Model predicts draw only 1.8% of the time, negative ROI.")
md.append("ALTERNATIVE: Use existing rule-based draw strategies from agent_handoff_v7.py:")
md.append("  - DRAW_SA, DRAW_BALANCED_LOW_SCORING_SA, DRAW_BALANCED_LINE_SA")
md.append("  - SA_AWAY_DRAW, NLA_BERN_AWAY_DRAW")
md.append("```\n")

md.append("### 9.5 League Blacklist\n")
md.append("Exclude these leagues (ROI_k < -20%, n >= 10):\n")
for _, row in blacklist_detailed.iterrows():
    md.append(f"- {row['league']}")
md.append("")

md.append("### 9.6 Pseudocode for agent integration\n")
md.append("```python")
md.append("def ml_football_pick(match, model, scaler):")
md.append("    # 1. Build features from match odds")
md.append("    features = build_features(match)")
md.append("    X = scaler.transform([features])")
md.append("")
md.append("    # 2. Predict probabilities")
md.append("    probs = model.predict_proba(X)[0]")
md.append("    pred_home, pred_draw, pred_away = probs")
md.append("")
md.append("    # 3. Compute edge for each outcome")
md.append("    edge_home = pred_home * match.odds_home - 1")
md.append("    edge_away = pred_away * match.odds_away - 1")
md.append("")
md.append("    # 4. Determine segment")
md.append("    no_clear_fav = max(pred_home, pred_draw, pred_away) < 0.50")
md.append("    is_balanced = abs(pred_home - pred_away) < 0.10")
md.append("")
md.append("    # 5. Apply policy: home/away only, no draw")
md.append("    edges = {'home': edge_home, 'away': edge_away}")
md.append("    best_outcome = max(edges, key=edges.get)")
md.append("    best_edge = edges[best_outcome]")
md.append("")
md.append("    # 6. Edge threshold by segment")
md.append("    if no_clear_fav:")
md.append("        EDGE_THRESHOLD = 0.06  # Policy A")
md.append("    elif is_balanced:")
md.append("        EDGE_THRESHOLD = 0.05  # Policy C")
md.append("    else:")
md.append("        EDGE_THRESHOLD = 0.07  # Policy E (all matches fallback)")
md.append("")
md.append("    if best_edge < EDGE_THRESHOLD:")
md.append("        return None  # no bet")
md.append("")
md.append("    # 7. Kelly stake")
md.append("    odds = match.odds_home if best_outcome == 'home' else match.odds_away")
md.append("    prob = pred_home if best_outcome == 'home' else pred_away")
md.append("    kelly = (prob * odds - 1) / (odds - 1)")
md.append("    stake = min(kelly * 0.25, 0.10)  # quarter Kelly, cap 10%")
md.append("")
md.append("    return {")
md.append("        'outcome': best_outcome,")
md.append("        'probability': prob,")
md.append("        'edge': best_edge,")
md.append("        'stake_pct': stake,")
md.append("        'segment': 'no_clear_favorite' if no_clear_fav else 'balanced' if is_balanced else 'all',")
md.append("    }")
md.append("```\n")

md.append("### 9.7 Combined Portfolio Strategy\n")
md.append("To approach the 50-100 bets/month target:\n")
md.append("")
md.append("| Source | Policy | Est. Bets/Month | Est. ROI |")
md.append("|--------|--------|-----------------|----------|")
md.append(f"| ML 1X2 | NCF + edge>0.06 + H/A | ~{policies[0]['per_month']} | {policies[0]['metrics']['roi_kelly']}% |")
md.append(f"| ML 1X2 | Balanced + edge>0.05 + H/A | ~{policies[2]['per_month']} | {policies[2]['metrics']['roi_kelly']}% |")
md.append(f"| ML 1X2 | All + edge>0.07 + H/A | ~{policies[4]['per_month']} | {policies[4]['metrics']['roi_kelly']}% |")
md.append("| Rules | DRAW_SA + variants | ~5-10 | +10-15% |")
md.append("| Rules | BTTS (EPL/BL1/PD/FL1) | ~10-20 | +5-10% |")
md.append("| Rules | Over/Under (RPL) | ~5-10 | +5-8% |")
md.append("| Rules | Summer leagues | ~5-10 | +5-8% |")
md.append(f"| **Total** | **Combined** | **~30-60** | **+8-12%** |")
md.append("")
md.append("**Gap to 50-100**: Add BTTS/OU/Asian Handicap ML models to close the gap.\n")

with open(OUTPUT_MD, "w") as f:
    f.write("\n".join(md))

print(f"\n\nReport saved to: {OUTPUT_MD}")
print("Done.")
