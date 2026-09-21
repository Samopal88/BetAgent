#!/usr/bin/env python3
"""
Tennis Winner ML — Baseline v1
===============================
Train LightGBM on tennis_ml_enriched_v3.csv.
Compare high-only vs high+medium confidence subsets.
Evaluate: logloss, brier, calibration, accuracy, betting backtest.
"""

import warnings
warnings.filterwarnings("ignore")

import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import log_loss, brier_score_loss, accuracy_score
from sklearn.isotonic import IsotonicRegression
import lightgbm as lgb

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ANALYSIS_DIR = Path(__file__).resolve().parent

# ============================================================
# Feature engineering
# ============================================================
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

# Derived features
DERIVED_COLS = [
    "player_form_diff", "opponent_form_diff",
    "serve_diff", "return_diff",
    "fatigue_diff", "surface_diff",
    "h2h_edge",
]


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


ALL_FEATURES = FEATURE_COLS + DERIVED_COLS


def prepare_data(df):
    df = add_derived_features(df)
    # Fill NaNs with column medians computed from non-null values
    for col in ALL_FEATURES:
        if col in df.columns:
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
    # Drop only rows where target or odds are missing (critical)
    df = df.dropna(subset=["target"])
    return df


# ============================================================
# Model training
# ============================================================
def train_lgb(X_train, y_train, X_val, y_val):
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "min_child_samples": 50,
        "reg_alpha": 0.1,
        "reg_lambda": 0.1,
        "verbose": -1,
        "seed": 42,
    }

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    return model


def calibrate_probs(model, X_val, y_val):
    """Isotonic calibration on validation set."""
    val_probs = model.predict(X_val)
    ir = IsotonicRegression(out_of_bounds="clip")
    ir.fit(val_probs, y_val)
    return ir


def evaluate(y_true, probs, label=""):
    logloss = log_loss(y_true, probs)
    brier = brier_score_loss(y_true, probs)
    acc = accuracy_score(y_true, (probs >= 0.5).astype(int))
    return {
        "label": label,
        "logloss": round(logloss, 4),
        "brier": round(brier, 4),
        "accuracy": round(acc, 4),
        "n_samples": len(y_true),
        "pos_rate": round(y_true.mean(), 4),
        "mean_prob": round(probs.mean(), 4),
    }


# ============================================================
# Betting backtest
# ============================================================
def betting_backtest(df, probs, stake_method="kelly_quarter", ev_threshold=0.0, bankroll=100000):
    """
    Simulate betting with dynamic bankroll tracking.
    df must have 'odds_player' column.
    """
    mask = df["odds_player"].notna() & (df["odds_player"] >= 1.5)
    df_bet = df[mask].copy()
    probs_bet = probs[mask]

    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "longest_losing_streak": 0,
                "monthly": [], "final_bankroll": bankroll, "won": 0, "lost": 0,
                "total_pnl": 0, "roi_bankroll": 0}

    df_bet["prob"] = probs_bet
    df_bet["ev"] = df_bet["prob"] * df_bet["odds_player"] - 1

    # Filter by EV threshold
    df_bet = df_bet[df_bet["ev"] >= ev_threshold].copy()

    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "longest_losing_streak": 0,
                "monthly": [], "final_bankroll": bankroll, "won": 0, "lost": 0,
                "total_pnl": 0, "roi_bankroll": 0}

    # Sort by date for realistic equity curve
    if "tourney_date" in df_bet.columns:
        df_bet = df_bet.sort_values("tourney_date").reset_index(drop=True)

    # Simulate with dynamic bankroll
    equity = [bankroll]
    results = []
    won = 0
    lost = 0
    losing_streak = 0
    max_losing_streak = 0
    peak = bankroll
    max_dd = 0
    total_staked = 0
    # Realistic stake cap: 2% of initial bankroll per bet (prevents compounding explosion)
    max_stake = bankroll * 0.02

    for _, row in df_bet.iterrows():
        current_br = equity[-1]
        if current_br < 100:  # Stop if nearly bust
            break

        # Calculate stake from current bankroll
        if stake_method == "kelly_quarter":
            kelly_frac = ((row["prob"] * row["odds_player"] - 1) /
                          (row["odds_player"] - 1)) * 0.25
            stake_pct = max(0.005, min(0.10, kelly_frac))
        else:  # flat
            stake_pct = 0.02

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
        results.append({
            "month": month,
            "pnl": pnl,
            "equity": new_equity,
            "stake": stake,
            "odds": row["odds_player"],
            "prob": row["prob"],
            "ev": row["ev"],
            "won": row["target"] == 1,
        })

    res_df = pd.DataFrame(results)
    monthly = res_df.groupby("month").agg(
        n_bets=("pnl", "count"),
        pnl=("pnl", "sum"),
        win_rate=("won", "mean"),
    ).reset_index()

    total_pnl = equity[-1] - bankroll
    roi = total_pnl / total_staked if total_staked > 0 else 0
    roi_bankroll = total_pnl / bankroll

    return {
        "n_bets": len(results),
        "won": won,
        "lost": lost,
        "roi": round(roi, 4),
        "roi_bankroll": round(roi_bankroll, 4),
        "total_pnl": round(total_pnl, 2),
        "total_staked": round(total_staked, 2),
        "max_drawdown": round(max_dd, 4),
        "longest_losing_streak": max_losing_streak,
        "final_bankroll": round(equity[-1], 2),
        "monthly": monthly.to_dict("records"),
        "equity_curve": equity,
    }


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("Tennis Winner ML — Baseline v1")
    print("=" * 60)

    df = pd.read_csv(str(DATA_DIR / "tennis_ml_enriched_v3.csv"))
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], errors="coerce")

    print(f"\nTotal rows: {len(df)}")
    print(f"Confidence dist: {df['join_confidence'].value_counts().to_dict()}")

    # ============================================================
    # Prepare subsets
    # ============================================================
    subsets = {
        "high_only": df[df["join_confidence"] == "high"].copy(),
        "high_medium": df[df["join_confidence"].isin(["high", "medium"])].copy(),
    }

    results = {}

    for subset_name, subset_df in subsets.items():
        print(f"\n{'='*50}")
        print(f"Subset: {subset_name} ({len(subset_df)} rows)")
        print(f"{'='*50}")

        subset_df = prepare_data(subset_df)
        print(f"  After feature prep: {len(subset_df)} rows")

        # Time splits
        train = subset_df[subset_df["year"].isin([2021, 2022, 2023])]
        val = subset_df[subset_df["year"] == 2024]
        test = subset_df[subset_df["year"] == 2025]
        ood = subset_df[subset_df["year"] == 2026]

        print(f"  Train: {len(train)}, Val: {len(val)}, Test: {len(test)}, OOD: {len(ood)}")

        X_train = train[ALL_FEATURES].values
        y_train = train["target"].values
        X_val = val[ALL_FEATURES].values
        y_val = val["target"].values
        X_test = test[ALL_FEATURES].values
        y_test = test["target"].values
        X_ood = ood[ALL_FEATURES].values if len(ood) > 0 else None
        y_ood = ood["target"].values if len(ood) > 0 else None

        # Train model
        print(f"  Training LightGBM...")
        model = train_lgb(X_train, y_train, X_val, y_val)

        # Calibrate
        calibrator = calibrate_probs(model, X_val, y_val)

        # Predictions
        val_raw = model.predict(X_val)
        val_cal = calibrator.predict(val_raw)

        test_raw = model.predict(X_test)
        test_cal = calibrator.predict(test_raw)

        ood_raw = model.predict(X_ood) if X_ood is not None else None
        ood_cal = calibrator.predict(ood_raw) if ood_raw is not None else None

        # Evaluate
        print(f"\n  --- Evaluation ---")
        val_metrics = evaluate(y_val, val_cal, f"{subset_name}/val")
        test_metrics = evaluate(y_test, test_cal, f"{subset_name}/test")
        ood_metrics = evaluate(y_ood, ood_cal, f"{subset_name}/ood") if ood_raw is not None else None

        print(f"  Val:   logloss={val_metrics['logloss']}, brier={val_metrics['brier']}, acc={val_metrics['accuracy']}")
        print(f"  Test:  logloss={test_metrics['logloss']}, brier={test_metrics['brier']}, acc={test_metrics['accuracy']}")
        if ood_metrics:
            print(f"  OOD:   logloss={ood_metrics['logloss']}, brier={ood_metrics['brier']}, acc={ood_metrics['accuracy']}")

        # Feature importance
        importance = pd.DataFrame({
            "feature": ALL_FEATURES,
            "importance": model.feature_importance("gain"),
        }).sort_values("importance", ascending=False)

        # Betting backtest — EV threshold grid
        print(f"\n  --- Betting Backtest ---")
        ev_thresholds = [0.0, 0.02, 0.03, 0.05]
        stake_methods = ["flat", "kelly_quarter"]

        subset_results = {
            "val": val_metrics,
            "test": test_metrics,
            "ood": ood_metrics,
            "feature_importance": importance.head(15).to_dict("records"),
            "betting": {},
        }

        for sm in stake_methods:
            for ev_t in ev_thresholds:
                key = f"{sm}_ev{ev_t}"

                # Test backtest
                test_result = betting_backtest(test, test_cal, stake_method=sm, ev_threshold=ev_t)
                # OOD backtest
                ood_result = betting_backtest(ood, ood_cal, stake_method=sm, ev_threshold=ev_t) if ood_raw is not None else {}

                subset_results["betting"][key] = {
                    "test": test_result,
                    "ood": ood_result,
                }

                if ev_t == 0.03 and sm == "kelly_quarter":
                    print(f"  Kelly Q, EV>=0.03:")
                    print(f"    Test:  {test_result['n_bets']} bets, ROI={test_result['roi']:.2%}, "
                          f"DD={test_result['max_drawdown']:.2%}, streak={test_result['longest_losing_streak']}")
                    if ood_result:
                        print(f"    OOD:   {ood_result['n_bets']} bets, ROI={ood_result['roi']:.2%}, "
                              f"DD={ood_result['max_drawdown']:.2%}, streak={ood_result['longest_losing_streak']}")

        results[subset_name] = subset_results

    # ============================================================
    # Report
    # ============================================================
    generate_report(results)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


def generate_report(results):
    lines = []
    lines.append("# Tennis Winner ML — Baseline v1 Report")
    lines.append("")

    for subset_name in ["high_only", "high_medium"]:
        r = results[subset_name]
        lines.append(f"## {subset_name}")
        lines.append("")

        # Metrics
        lines.append("### Metrics")
        lines.append("")
        lines.append("| Split | LogLoss | Brier | Accuracy | N |")
        lines.append("|-------|---------|-------|----------|---|")
        for split in ["val", "test", "ood"]:
            m = r.get(split)
            if m:
                lines.append(f"| {split} | {m['logloss']} | {m['brier']} | {m['accuracy']} | {m['n_samples']} |")
        lines.append("")

        # Feature importance
        lines.append("### Top 15 Features (Gain)")
        lines.append("")
        lines.append("| Feature | Importance |")
        lines.append("|---------|-----------|")
        for fi in r["feature_importance"]:
            lines.append(f"| {fi['feature']} | {fi['importance']:.1f} |")
        lines.append("")

        # Betting results
        lines.append("### Betting Backtest — Test (2025)")
        lines.append("")
        lines.append("| Method | EV Thresh | Bets | ROI | ROI_BR | PnL | Max DD | Lose Streak |")
        lines.append("|--------|-----------|------|-----|--------|-----|--------|-------------|")
        for key, bet in r["betting"].items():
            t = bet["test"]
            if t["n_bets"] > 0:
                lines.append(f"| {key} | | {t['n_bets']} | {t['roi']:.2%} | {t['roi_bankroll']:.2%} | {t['total_pnl']:.0f} | {t['max_drawdown']:.2%} | {t['longest_losing_streak']} |")
        lines.append("")

        lines.append("### Betting Backtest — OOD (2026)")
        lines.append("")
        lines.append("| Method | EV Thresh | Bets | ROI | ROI_BR | PnL | Max DD | Lose Streak |")
        lines.append("|--------|-----------|------|-----|--------|-----|--------|-------------|")
        for key, bet in r["betting"].items():
            o = bet.get("ood", {})
            if o and o.get("n_bets", 0) > 0:
                lines.append(f"| {key} | | {o['n_bets']} | {o['roi']:.2%} | {o['roi_bankroll']:.2%} | {o['total_pnl']:.0f} | {o['max_drawdown']:.2%} | {o['longest_losing_streak']} |")
        lines.append("")

        # Monthly breakdown (test, kelly_quarter, ev=0.03)
        bk = r["betting"].get("kelly_quarter_ev0.03", {}).get("test", {})
        if bk.get("monthly"):
            lines.append("### Monthly Breakdown — Test (Kelly Q, EV>=0.03)")
            lines.append("")
            lines.append("| Month | Bets | PnL | Win Rate |")
            lines.append("|-------|------|-----|----------|")
            for m in bk["monthly"]:
                lines.append(f"| {m['month']} | {m['n_bets']} | {m['pnl']:.0f} | {m['win_rate']:.1%} |")
            lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")

    ho_test = results["high_only"]["betting"].get("kelly_quarter_ev0.03", {}).get("test", {})
    hm_test = results["high_medium"]["betting"].get("kelly_quarter_ev0.03", {}).get("test", {})
    ho_ood = results["high_only"]["betting"].get("kelly_quarter_ev0.03", {}).get("ood", {})
    hm_ood = results["high_medium"]["betting"].get("kelly_quarter_ev0.03", {}).get("ood", {})

    ho_test_roi = ho_test.get("roi", -999)
    hm_test_roi = hm_test.get("roi", -999)
    ho_ood_roi = ho_ood.get("roi", -999)
    hm_ood_roi = hm_ood.get("roi", -999)

    better = "high_only" if ho_test_roi >= hm_test_roi else "high_medium"
    lines.append(f"1. **Better subset**: {better} (test ROI: {ho_test_roi:.2%} vs {hm_test_roi:.2%}, OOD ROI: {ho_ood_roi:.2%} vs {hm_ood_roi:.2%})")

    # Viability
    viable = ho_test_roi > 0 or hm_test_roi > 0
    lines.append(f"2. **Standalone tennis ML viable**: {'yes' if viable else 'no'} — "
                 f"best test ROI={max(ho_test_roi, hm_test_roi):.2%}, best OOD ROI={max(ho_ood_roi, hm_ood_roi):.2%}")

    lines.append(f"3. **Worth moving to theory+ML intersection**: "
                 f"{'yes' if not viable else 'maybe — test positive but OOD needs confirmation'}")

    lines.append("")

    report = "\n".join(lines)
    report_path = ANALYSIS_DIR / "tennis_winner_baseline_v1_report.md"
    report_path.write_text(report)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
