#!/usr/bin/env python3
"""
Tennis ML — Out-of-Time Validation
====================================
Tests model on 2023-2024 data (not used in original train/val/test split).
Checks for overfitting, compares Kelly vs flat staking, monthly breakdown.
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import log_loss, brier_score_loss, accuracy_score
from sklearn.isotonic import IsotonicRegression
import lightgbm as lgb
import pickle

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ANALYSIS_DIR = Path(__file__).resolve().parent
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

FEATURE_COLS = [
    "rank_diff", "rank_pts_diff",
    "player_win_pct_5", "player_win_pct_10",
    "player_ss_pct_5", "player_ss_pct_10",
    "opponent_win_pct_5", "opponent_win_pct_10",
    "opponent_ss_pct_5", "opponent_ss_pct_10",
    "player_ace_avg", "player_df_avg", "player_1st_in_avg",
    "player_1st_won_pct", "player_bp_saved_pct", "player_minutes_avg",
    "opponent_ace_avg", "opponent_df_avg", "opponent_1st_in_avg",
    "opponent_1st_won_pct", "opponent_bp_saved_pct", "opponent_minutes_avg",
    "player_surface_win_pct", "player_surface_matches",
    "player_surface_ace_avg", "player_surface_1st_won_pct", "player_surface_bp_saved_pct",
    "opponent_surface_win_pct", "opponent_surface_matches",
    "opponent_surface_ace_avg", "opponent_surface_1st_won_pct", "opponent_surface_bp_saved_pct",
    "player_days_rest", "player_matches_7d", "player_matches_14d", "player_minutes_14d",
    "opponent_days_rest", "opponent_matches_7d", "opponent_matches_14d", "opponent_minutes_14d",
    "h2h_player_wins", "h2h_opponent_wins", "h2h_total",
]

DERIVED_COLS = [
    "player_form_diff", "opponent_form_diff",
    "serve_diff", "return_diff",
    "fatigue_diff", "surface_diff",
    "h2h_edge",
]

ALL_FEATURES = FEATURE_COLS + DERIVED_COLS


def add_derived_features(df):
    df = df.copy()
    df["player_form_diff"] = df["player_win_pct_5"] - df["opponent_win_pct_5"]
    df["opponent_form_diff"] = df["opponent_win_pct_10"] - df["player_win_pct_10"]
    df["serve_diff"] = df["player_1st_won_pct"] - df["opponent_1st_won_pct"]
    df["return_diff"] = df["player_bp_saved_pct"] - df["opponent_bp_saved_pct"]
    df["fatigue_diff"] = df["player_matches_14d"] - df["opponent_matches_14d"]
    df["surface_diff"] = df["player_surface_win_pct"] - df["opponent_surface_win_pct"]
    df["h2h_edge"] = df["h2h_player_wins"] - df["h2h_opponent_wins"]
    return df


def prepare_data(df):
    df = add_derived_features(df)
    for col in ALL_FEATURES:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
    df = df.dropna(subset=["target"])
    return df


def train_lgb(X_train, y_train, X_val, y_val):
    params = {
        "objective": "binary", "metric": "binary_logloss",
        "boosting_type": "gbdt", "num_leaves": 31,
        "learning_rate": 0.05, "feature_fraction": 0.8,
        "bagging_fraction": 0.8, "bagging_freq": 5,
        "min_child_samples": 50, "reg_alpha": 0.1,
        "reg_lambda": 0.1, "verbose": -1, "seed": 42,
    }
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    model = lgb.train(
        params, train_data, num_boost_round=1000,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    return model


def calibrate_probs(model, X_val, y_val):
    val_probs = model.predict(X_val)
    ir = IsotonicRegression(out_of_bounds="clip")
    ir.fit(val_probs, y_val)
    return ir


def betting_backtest(df, probs, stake_method="kelly_quarter", ev_threshold=0.03, bankroll=100000):
    mask = df["odds_player"].notna() & (df["odds_player"] >= 1.5)
    df_bet = df[mask].copy()
    probs_bet = probs[mask]
    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "longest_losing_streak": 0,
                "monthly": [], "yearly": [], "final_bankroll": bankroll,
                "won": 0, "lost": 0, "total_pnl": 0, "roi_bankroll": 0}

    df_bet["prob"] = probs_bet
    df_bet["ev"] = df_bet["prob"] * df_bet["odds_player"] - 1
    df_bet = df_bet[df_bet["ev"] >= ev_threshold].copy()
    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "longest_losing_streak": 0,
                "monthly": [], "yearly": [], "final_bankroll": bankroll,
                "won": 0, "lost": 0, "total_pnl": 0, "roi_bankroll": 0}

    df_bet = df_bet.sort_values("tourney_date").reset_index(drop=True)

    equity = [bankroll]
    results = []
    won = lost = 0
    losing_streak = max_losing_streak = 0
    peak = bankroll
    max_dd = 0
    total_staked = 0
    max_stake = bankroll * 0.02

    for _, row in df_bet.iterrows():
        current_br = equity[-1]
        if current_br < 100:
            break

        if stake_method == "kelly_quarter":
            kelly_frac = ((row["prob"] * row["odds_player"] - 1) / (row["odds_player"] - 1)) * 0.25
            stake_pct = max(0.005, min(0.10, kelly_frac))
        else:
            stake_pct = 0.01

        stake = min(stake_pct * current_br, max_stake)

        if row["target"] == 1:
            pnl = stake * (row["odds_player"] - 1)
            won += 1
            losing_streak = 0
        else:
            pnl = -stake
            lost += 1
            losing_streak += 1
            max_losing_streak = max(max_losing_streak, losing_streak)

        new_equity = equity[-1] + pnl
        equity.append(new_equity)
        total_staked += stake
        peak = max(peak, new_equity)
        dd = (peak - new_equity) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

        month = str(row.get("tourney_date", ""))[:7] if pd.notna(row.get("tourney_date", "")) else "unknown"
        year = str(int(row["year"])) if pd.notna(row.get("year", "")) else "unknown"
        results.append({
            "month": month, "year": year,
            "pnl": pnl, "equity": new_equity, "stake": stake,
            "odds": row["odds_player"], "prob": row["prob"], "ev": row["ev"],
            "won": row["target"] == 1,
        })

    res_df = pd.DataFrame(results)
    monthly = res_df.groupby("month").agg(
        n_bets=("pnl", "count"), pnl=("pnl", "sum"), win_rate=("won", "mean"),
    ).reset_index()
    yearly = res_df.groupby("year").agg(
        n_bets=("pnl", "count"), pnl=("pnl", "sum"), win_rate=("won", "mean"),
    ).reset_index()

    total_pnl = equity[-1] - bankroll
    roi = total_pnl / total_staked if total_staked > 0 else 0
    roi_bankroll = total_pnl / bankroll

    return {
        "n_bets": len(results), "won": won, "lost": lost,
        "roi": round(roi, 4), "roi_bankroll": round(roi_bankroll, 4),
        "total_pnl": round(total_pnl, 2), "total_staked": round(total_staked, 2),
        "max_drawdown": round(max_dd, 4),
        "longest_losing_streak": max_losing_streak,
        "final_bankroll": round(equity[-1], 2),
        "monthly": monthly.to_dict("records"),
        "yearly": yearly.to_dict("records"),
    }


def main():
    print("=" * 60)
    print("Tennis ML — Out-of-Time Validation")
    print("=" * 60)

    df = pd.read_csv(str(DATA_DIR / "tennis_ml_enriched_v3.csv"))
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], errors="coerce")
    subset = df[df["join_confidence"].isin(["high", "medium"])].copy()
    subset = prepare_data(subset)

    print(f"\nDataset: {len(subset)} rows (high+medium confidence)")
    print(f"Year range: {subset['year'].min():.0f} - {subset['year'].max():.0f}")

    # ============================================================
    # EXPERIMENT 1: Rolling out-of-time test
    # Train on 2021-2022, test on 2023, 2024, 2025, 2026
    # ============================================================
    print("\n" + "=" * 50)
    print("EXPERIMENT 1: Rolling out-of-time validation")
    print("  Train: 2021-2022, Test each year separately")
    print("=" * 50)

    train_2122 = subset[subset["year"].isin([2021, 2022])]
    val_2122 = subset[subset["year"] == 2022]  # use 2022 as val for early stopping

    model_1 = train_lgb(
        train_2122[ALL_FEATURES].values, train_2122["target"].values,
        val_2122[ALL_FEATURES].values, val_2122["target"].values,
    )
    cal_1 = calibrate_probs(model_1, val_2122[ALL_FEATURES].values, val_2122["target"].values)

    rolling_results = {}
    for yr in [2023, 2024, 2025, 2026]:
        yr_df = subset[subset["year"] == yr]
        if len(yr_df) == 0:
            continue
        raw = model_1.predict(yr_df[ALL_FEATURES].values)
        cal_probs = cal_1.predict(raw)
        acc = accuracy_score(yr_df["target"].values, (cal_probs >= 0.5).astype(int))
        ll = log_loss(yr_df["target"].values, cal_probs)
        bt = betting_backtest(yr_df, cal_probs, stake_method="kelly_quarter", ev_threshold=0.03)
        bt_flat = betting_backtest(yr_df, cal_probs, stake_method="flat_1pct", ev_threshold=0.03)

        rolling_results[yr] = {
            "n_samples": len(yr_df),
            "accuracy": round(acc, 4),
            "logloss": round(ll, 4),
            "kelly": bt,
            "flat": bt_flat,
        }
        print(f"\n  {yr}: acc={acc:.4f}, logloss={ll:.4f}")
        print(f"    Kelly Q: {bt['n_bets']} bets, ROI={bt['roi']:.2%}, DD={bt['max_drawdown']:.2%}, WR={bt['won']/(bt['won']+bt['lost']):.1%}" if bt['n_bets'] > 0 else "    Kelly Q: no bets")
        print(f"    Flat 1%: {bt_flat['n_bets']} bets, ROI={bt_flat['roi']:.2%}, DD={bt_flat['max_drawdown']:.2%}, WR={bt_flat['won']/(bt_flat['won']+bt_flat['lost']):.1%}" if bt_flat['n_bets'] > 0 else "    Flat 1%: no bets")

    # ============================================================
    # EXPERIMENT 2: Train on 2021-2023, test on 2024-2026
    # ============================================================
    print("\n" + "=" * 50)
    print("EXPERIMENT 2: Train 2021-2023, test 2024-2026")
    print("=" * 50)

    train_2123 = subset[subset["year"].isin([2021, 2022, 2023])]
    val_23 = subset[subset["year"] == 2023]

    model_2 = train_lgb(
        train_2123[ALL_FEATURES].values, train_2123["target"].values,
        val_23[ALL_FEATURES].values, val_23["target"].values,
    )
    cal_2 = calibrate_probs(model_2, val_23[ALL_FEATURES].values, val_23["target"].values)

    exp2_results = {}
    for yr in [2024, 2025, 2026]:
        yr_df = subset[subset["year"] == yr]
        if len(yr_df) == 0:
            continue
        raw = model_2.predict(yr_df[ALL_FEATURES].values)
        cal_probs = cal_2.predict(raw)
        acc = accuracy_score(yr_df["target"].values, (cal_probs >= 0.5).astype(int))
        ll = log_loss(yr_df["target"].values, cal_probs)
        bt = betting_backtest(yr_df, cal_probs, stake_method="kelly_quarter", ev_threshold=0.03)
        bt_flat = betting_backtest(yr_df, cal_probs, stake_method="flat_1pct", ev_threshold=0.03)

        exp2_results[yr] = {
            "n_samples": len(yr_df),
            "accuracy": round(acc, 4),
            "logloss": round(ll, 4),
            "kelly": bt,
            "flat": bt_flat,
        }
        print(f"\n  {yr}: acc={acc:.4f}, logloss={ll:.4f}")
        print(f"    Kelly Q: {bt['n_bets']} bets, ROI={bt['roi']:.2%}, DD={bt['max_drawdown']:.2%}, WR={bt['won']/(bt['won']+bt['lost']):.1%}" if bt['n_bets'] > 0 else "    Kelly Q: no bets")
        print(f"    Flat 1%: {bt_flat['n_bets']} bets, ROI={bt_flat['roi']:.2%}, DD={bt_flat['max_drawdown']:.2%}, WR={bt_flat['won']/(bt_flat['won']+bt_flat['lost']):.1%}" if bt_flat['n_bets'] > 0 else "    Flat 1%: no bets")

    # ============================================================
    # EXPERIMENT 3: Full walk-forward (train on all prior, test each year)
    # ============================================================
    print("\n" + "=" * 50)
    print("EXPERIMENT 3: Walk-forward validation")
    print("  Train on all prior years, test each year independently")
    print("=" * 50)

    walkforward_results = {}
    for test_year in [2023, 2024, 2025, 2026]:
        train_years = [y for y in range(2021, test_year) if y <= 2025]
        if not train_years:
            continue

        train_wf = subset[subset["year"].isin(train_years)]
        val_wf = subset[subset["year"] == train_years[-1]]
        test_wf = subset[subset["year"] == test_year]

        if len(train_wf) == 0 or len(test_wf) == 0:
            continue

        model_wf = train_lgb(
            train_wf[ALL_FEATURES].values, train_wf["target"].values,
            val_wf[ALL_FEATURES].values, val_wf["target"].values,
        )
        cal_wf = calibrate_probs(model_wf, val_wf[ALL_FEATURES].values, val_wf["target"].values)

        raw = model_wf.predict(test_wf[ALL_FEATURES].values)
        cal_probs = cal_wf.predict(raw)
        acc = accuracy_score(test_wf["target"].values, (cal_probs >= 0.5).astype(int))
        ll = log_loss(test_wf["target"].values, cal_probs)
        bt = betting_backtest(test_wf, cal_probs, stake_method="kelly_quarter", ev_threshold=0.03)
        bt_flat = betting_backtest(test_wf, cal_probs, stake_method="flat_1pct", ev_threshold=0.03)

        walkforward_results[test_year] = {
            "train_years": train_years,
            "n_samples": len(test_wf),
            "accuracy": round(acc, 4),
            "logloss": round(ll, 4),
            "kelly": bt,
            "flat": bt_flat,
        }
        print(f"\n  {test_year} (train={train_years}): acc={acc:.4f}, logloss={ll:.4f}")
        print(f"    Kelly Q: {bt['n_bets']} bets, ROI={bt['roi']:.2%}, DD={bt['max_drawdown']:.2%}, WR={bt['won']/(bt['won']+bt['lost']):.1%}" if bt['n_bets'] > 0 else "    Kelly Q: no bets")
        print(f"    Flat 1%: {bt_flat['n_bets']} bets, ROI={bt_flat['roi']:.2%}, DD={bt_flat['max_drawdown']:.2%}, WR={bt_flat['won']/(bt_flat['won']+bt_flat['lost']):.1%}" if bt_flat['n_bets'] > 0 else "    Flat 1%: no bets")

    # ============================================================
    # EXPERIMENT 4: Kelly vs Flat comparison (aggregate)
    # ============================================================
    print("\n" + "=" * 50)
    print("EXPERIMENT 4: Kelly vs Flat stake comparison")
    print("=" * 50)

    print(f"\n  {'Year':<6} {'Kelly Bets':>10} {'Kelly ROI':>10} {'Kelly DD':>10} {'Kelly WR':>10} | {'Flat Bets':>10} {'Flat ROI':>10} {'Flat DD':>10} {'Flat WR':>10}")
    print("  " + "-" * 110)
    for yr in [2023, 2024, 2025, 2026]:
        wf = walkforward_results.get(yr, {})
        k = wf.get("kelly", {})
        f = wf.get("flat", {})
        k_wr = f"{k['won']/(k['won']+k['lost']):.1%}" if k.get("n_bets", 0) > 0 else "—"
        f_wr = f"{f['won']/(f['won']+f['lost']):.1%}" if f.get("n_bets", 0) > 0 else "—"
        print(f"  {yr:<6} {k.get('n_bets', 0):>10} {k.get('roi', 0):>10.2%} {k.get('max_drawdown', 0):>10.2%} {k_wr:>10} | {f.get('n_bets', 0):>10} {f.get('roi', 0):>10.2%} {f.get('max_drawdown', 0):>10.2%} {f_wr:>10}")

    # ============================================================
    # EXPERIMENT 5: Monthly breakdown 2023-2025
    # ============================================================
    print("\n" + "=" * 50)
    print("EXPERIMENT 5: Monthly breakdown (walk-forward, Kelly Q)")
    print("=" * 50)

    monthly_all = {}
    for yr in [2023, 2024, 2025]:
        wf = walkforward_results.get(yr, {})
        bt = wf.get("kelly", {})
        if bt.get("monthly"):
            monthly_all[yr] = bt["monthly"]
            print(f"\n  {yr}:")
            for m in bt["monthly"]:
                print(f"    {m['month']}: {m['n_bets']:>4} bets, PnL={m['pnl']:+>8.0f}, WR={m['win_rate']:.1%}")

    # ============================================================
    # Generate report
    # ============================================================
    generate_report(rolling_results, exp2_results, walkforward_results, monthly_all)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


def generate_report(rolling, exp2, walkforward, monthly):
    lines = []
    lines.append("# Tennis ML — Out-of-Time Validation Report")
    lines.append("")
    lines.append("## 1. Dataset Overview")
    lines.append("")
    lines.append("| Year | Rows | High | Medium |")
    lines.append("|------|------|------|--------|")
    df = pd.read_csv(str(DATA_DIR / "tennis_ml_enriched_v3.csv"))
    sub = df[df["join_confidence"].isin(["high", "medium"])]
    for yr in sorted(sub["year"].unique()):
        yr_sub = sub[sub["year"] == yr]
        lines.append(f"| {yr:.0f} | {len(yr_sub)} | {(yr_sub['join_confidence']=='high').sum()} | {(yr_sub['join_confidence']=='medium').sum()} |")
    lines.append("")

    lines.append("## 2. Experiment 1: Train 2021-2022, Test Each Year")
    lines.append("")
    lines.append("| Year | Accuracy | LogLoss | Kelly Bets | Kelly ROI | Kelly DD | Kelly WR | Flat Bets | Flat ROI | Flat DD |")
    lines.append("|------|----------|---------|-----------|-----------|----------|----------|----------|----------|---------|")
    for yr in sorted(rolling.keys()):
        r = rolling[yr]
        k = r["kelly"]
        f = r["flat"]
        k_wr = f"{k['won']/(k['won']+k['lost']):.1%}" if k["n_bets"] > 0 else "—"
        lines.append(f"| {yr} | {r['accuracy']} | {r['logloss']} | {k['n_bets']} | {k['roi']:.2%} | {k['max_drawdown']:.2%} | {k_wr} | {f['n_bets']} | {f['roi']:.2%} | {f['max_drawdown']:.2%} |")
    lines.append("")

    lines.append("## 3. Experiment 2: Train 2021-2023, Test 2024-2026")
    lines.append("")
    lines.append("| Year | Accuracy | LogLoss | Kelly Bets | Kelly ROI | Kelly DD | Kelly WR | Flat Bets | Flat ROI | Flat DD |")
    lines.append("|------|----------|---------|-----------|-----------|----------|----------|----------|----------|---------|")
    for yr in sorted(exp2.keys()):
        r = exp2[yr]
        k = r["kelly"]
        f = r["flat"]
        k_wr = f"{k['won']/(k['won']+k['lost']):.1%}" if k["n_bets"] > 0 else "—"
        lines.append(f"| {yr} | {r['accuracy']} | {r['logloss']} | {k['n_bets']} | {k['roi']:.2%} | {k['max_drawdown']:.2%} | {k_wr} | {f['n_bets']} | {f['roi']:.2%} | {f['max_drawdown']:.2%} |")
    lines.append("")

    lines.append("## 4. Experiment 3: Walk-Forward (Train All Prior, Test Each Year)")
    lines.append("")
    lines.append("**This is the most realistic simulation of live deployment.**")
    lines.append("")
    lines.append("| Year | Train Years | Accuracy | LogLoss | Kelly Bets | Kelly ROI | Kelly DD | Kelly WR | Flat Bets | Flat ROI | Flat DD |")
    lines.append("|------|------------|----------|---------|-----------|-----------|----------|----------|----------|----------|---------|")
    for yr in sorted(walkforward.keys()):
        r = walkforward[yr]
        k = r["kelly"]
        f = r["flat"]
        k_wr = f"{k['won']/(k['won']+k['lost']):.1%}" if k["n_bets"] > 0 else "—"
        f_wr = f"{f['won']/(f['won']+f['lost']):.1%}" if f["n_bets"] > 0 else "—"
        train_str = ", ".join(str(y) for y in r["train_years"])
        lines.append(f"| {yr} | {train_str} | {r['accuracy']} | {r['logloss']} | {k['n_bets']} | {k['roi']:.2%} | {k['max_drawdown']:.2%} | {k_wr} | {f['n_bets']} | {f['roi']:.2%} | {f['max_drawdown']:.2%} |")
    lines.append("")

    lines.append("## 5. Kelly vs Flat Stake Comparison (Walk-Forward)")
    lines.append("")
    lines.append("| Year | Method | Bets | ROI | Max DD | Win Rate | Final Bankroll |")
    lines.append("|------|--------|------|-----|--------|----------|---------------|")
    for yr in sorted(walkforward.keys()):
        r = walkforward[yr]
        k = r["kelly"]
        f = r["flat"]
        if k["n_bets"] > 0:
            k_wr = f"{k['won']/(k['won']+k['lost']):.1%}"
            lines.append(f"| {yr} | Kelly Q | {k['n_bets']} | {k['roi']:.2%} | {k['max_drawdown']:.2%} | {k_wr} | {k['final_bankroll']:.0f} |")
        if f["n_bets"] > 0:
            f_wr = f"{f['won']/(f['won']+f['lost']):.1%}"
            lines.append(f"| {yr} | Flat 1% | {f['n_bets']} | {f['roi']:.2%} | {f['max_drawdown']:.2%} | {f_wr} | {f['final_bankroll']:.0f} |")
    lines.append("")

    lines.append("## 6. Monthly Breakdown (Walk-Forward, Kelly Q)")
    lines.append("")
    for yr in sorted(monthly.keys()):
        lines.append(f"### {yr}")
        lines.append("")
        lines.append("| Month | Bets | PnL | Win Rate |")
        lines.append("|-------|------|-----|----------|")
        for m in monthly[yr]:
            lines.append(f"| {m['month']} | {m['n_bets']} | {m['pnl']:.0f} | {m['win_rate']:.1%} |")
        lines.append("")

    # Summary stats
    lines.append("## 7. Overfitting Assessment")
    lines.append("")

    # Count positive ROI years
    wf_positive_kelly = sum(1 for yr in walkforward.values() if yr["kelly"]["roi"] > 0)
    wf_positive_flat = sum(1 for yr in walkforward.values() if yr["flat"]["roi"] > 0)
    wf_total = len(walkforward)

    wf_avg_roi_kelly = np.mean([r["kelly"]["roi"] for r in walkforward.values()])
    wf_avg_roi_flat = np.mean([r["flat"]["roi"] for r in walkforward.values()])
    wf_avg_dd_kelly = np.mean([r["kelly"]["max_drawdown"] for r in walkforward.values()])
    wf_avg_dd_flat = np.mean([r["flat"]["max_drawdown"] for r in walkforward.values()])
    wf_avg_acc = np.mean([r["accuracy"] for r in walkforward.values()])

    lines.append(f"- **Years with positive Kelly ROI**: {wf_positive_kelly}/{wf_total}")
    lines.append(f"- **Years with positive Flat ROI**: {wf_positive_flat}/{wf_total}")
    lines.append(f"- **Average Kelly ROI**: {wf_avg_roi_kelly:.2%}")
    lines.append(f"- **Average Flat ROI**: {wf_avg_roi_flat:.2%}")
    lines.append(f"- **Average Kelly DD**: {wf_avg_dd_kelly:.2%}")
    lines.append(f"- **Average Flat DD**: {wf_avg_dd_flat:.2%}")
    lines.append(f"- **Average Accuracy**: {wf_avg_acc:.4f}")
    lines.append("")

    # Overfitting verdict
    lines.append("### Verdict")
    lines.append("")
    if wf_positive_kelly >= wf_total * 0.75:
        lines.append(f"**Model appears robust**: {wf_positive_kelly}/{wf_total} out-of-time years show positive ROI with Kelly staking.")
        lines.append("The model is likely not overfitting to a specific time period.")
    elif wf_positive_kelly >= wf_total * 0.5:
        lines.append(f"**Model shows mixed signals**: {wf_positive_kelly}/{wf_total} years positive with Kelly.")
        lines.append("Some years work well, others don't. This is typical for sports betting models.")
        lines.append("Recommendation: use flat staking and strict EV thresholds for live deployment.")
    else:
        lines.append(f"**Model likely overfit**: only {wf_positive_kelly}/{wf_total} years positive.")
        lines.append("The model does not generalize well to unseen time periods.")
    lines.append("")

    lines.append("## 8. Recommendation for Live Deployment")
    lines.append("")
    if wf_avg_roi_flat > 0 and wf_positive_flat >= wf_total * 0.5:
        lines.append("- **Staking**: Flat 1% (safer, more consistent than Kelly)")
        lines.append("- **EV threshold**: >= 0.03")
        lines.append("- **Expected ROI**: ~{:.0%} per bet (flat)".format(wf_avg_roi_flat))
        lines.append("- **Expected max DD**: ~{:.0%}".format(wf_avg_dd_flat))
        lines.append("- **Kill switch**: Stop if 3 consecutive losing months or DD > 25%")
    else:
        lines.append("- **NOT recommended for live deployment** based on out-of-time validation")
        lines.append("- Model shows inconsistent performance across years")
    lines.append("")

    report = "\n".join(lines)
    report_path = ANALYSIS_DIR / "tennis_validation_report.md"
    report_path.write_text(report)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
