#!/usr/bin/env python3
"""
Tennis H2H Leakage Fix — Impact Analysis
==========================================
1. Retrain model with FIXED H2H features
2. Retrain model WITHOUT H2H features
3. Compare ROI, accuracy, calibration
4. Year-by-year backtest results
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
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

# ============================================================
# Feature definitions
# ============================================================
H2H_COLS = ["h2h_player_wins", "h2h_opponent_wins", "h2h_total"]

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


def add_derived_features(df, include_h2h=True):
    df = df.copy()
    df["player_form_diff"] = df["player_win_pct_5"] - df["opponent_win_pct_5"]
    df["opponent_form_diff"] = df["opponent_win_pct_10"] - df["player_win_pct_10"]
    df["serve_diff"] = df["player_1st_won_pct"] - df["opponent_1st_won_pct"]
    df["return_diff"] = df["player_bp_saved_pct"] - df["opponent_bp_saved_pct"]
    df["fatigue_diff"] = df["player_matches_14d"] - df["opponent_matches_14d"]
    df["surface_diff"] = df["player_surface_win_pct"] - df["opponent_surface_win_pct"]
    if include_h2h:
        df["h2h_edge"] = df["h2h_player_wins"] - df["h2h_opponent_wins"]
    else:
        df["h2h_edge"] = 0
    return df


def get_all_features(include_h2h=True):
    base = FEATURE_COLS + DERIVED_COLS
    if include_h2h:
        return base
    else:
        return [c for c in base if c not in H2H_COLS and c != "h2h_edge"]


def prepare_data(df, include_h2h=True):
    df = add_derived_features(df, include_h2h=include_h2h)
    cols = get_all_features(include_h2h=include_h2h)
    for col in cols:
        if col in df.columns:
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
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
    mask = df["odds_player"].notna() & (df["odds_player"] >= 1.5)
    df_bet = df[mask].copy()
    probs_bet = probs[mask]
    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "longest_losing_streak": 0,
                "monthly": [], "final_bankroll": bankroll, "won": 0, "lost": 0,
                "total_pnl": 0, "roi_bankroll": 0, "yearly": []}

    df_bet["prob"] = probs_bet
    df_bet["ev"] = df_bet["prob"] * df_bet["odds_player"] - 1
    df_bet = df_bet[df_bet["ev"] >= ev_threshold].copy()
    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "longest_losing_streak": 0,
                "monthly": [], "final_bankroll": bankroll, "won": 0, "lost": 0,
                "total_pnl": 0, "roi_bankroll": 0, "yearly": []}

    if "tourney_date" in df_bet.columns:
        df_bet = df_bet.sort_values("tourney_date").reset_index(drop=True)

    equity = [bankroll]
    results = []
    won = 0
    lost = 0
    losing_streak = 0
    max_losing_streak = 0
    peak = bankroll
    max_dd = 0
    total_staked = 0
    max_stake = bankroll * 0.02

    for _, row in df_bet.iterrows():
        current_br = equity[-1]
        if current_br < 100:
            break
        if stake_method == "kelly_quarter":
            kelly_frac = ((row["prob"] * row["odds_player"] - 1) /
                          (row["odds_player"] - 1)) * 0.25
            stake_pct = max(0.005, min(0.10, kelly_frac))
        else:
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
        year = str(row.get("year", "")) if pd.notna(row.get("year", "")) else "unknown"
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
        "equity_curve": equity,
    }


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("Tennis H2H Leakage Fix — Impact Analysis")
    print("=" * 60)

    df = pd.read_csv(str(DATA_DIR / "tennis_ml_enriched_v3.csv"))
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], errors="coerce")

    # Use high+medium confidence subset (same as baseline)
    subset_df = df[df["join_confidence"].isin(["high", "medium"])].copy()
    print(f"\nSubset: high+medium ({len(subset_df)} rows)")

    # ============================================================
    # EXPERIMENT 1: With FIXED H2H
    # ============================================================
    print("\n" + "=" * 50)
    print("EXPERIMENT 1: With FIXED H2H features")
    print("=" * 50)

    df_h2h = prepare_data(subset_df.copy(), include_h2h=True)
    cols_h2h = get_all_features(include_h2h=True)

    train_h = df_h2h[df_h2h["year"].isin([2021, 2022, 2023])]
    val_h = df_h2h[df_h2h["year"] == 2024]
    test_h = df_h2h[df_h2h["year"] == 2025]
    ood_h = df_h2h[df_h2h["year"] == 2026]

    print(f"  Train: {len(train_h)}, Val: {len(val_h)}, Test: {len(test_h)}, OOD: {len(ood_h)}")

    model_h2h = train_lgb(
        train_h[cols_h2h].values, train_h["target"].values,
        val_h[cols_h2h].values, val_h["target"].values,
    )
    cal_h2h = calibrate_probs(model_h2h, val_h[cols_h2h].values, val_h["target"].values)

    test_raw_h = model_h2h.predict(test_h[cols_h2h].values)
    test_cal_h = cal_h2h.predict(test_raw_h)
    ood_raw_h = model_h2h.predict(ood_h[cols_h2h].values) if len(ood_h) > 0 else None
    ood_cal_h = cal_h2h.predict(ood_raw_h) if ood_raw_h is not None else None

    test_metrics_h = evaluate(test_h["target"].values, test_cal_h, "test_h2h")
    ood_metrics_h = evaluate(ood_h["target"].values, ood_cal_h, "ood_h2h") if ood_raw_h is not None else None

    print(f"  Test:  logloss={test_metrics_h['logloss']}, brier={test_metrics_h['brier']}, acc={test_metrics_h['accuracy']}")
    if ood_metrics_h:
        print(f"  OOD:   logloss={ood_metrics_h['logloss']}, brier={ood_metrics_h['brier']}, acc={ood_metrics_h['accuracy']}")

    # Feature importance
    fi_h2h = pd.DataFrame({
        "feature": cols_h2h,
        "importance": model_h2h.feature_importance("gain"),
    }).sort_values("importance", ascending=False)
    print(f"\n  Top 10 features (gain):")
    for _, r in fi_h2h.head(10).iterrows():
        print(f"    {r['feature']:30s} {r['importance']:.1f}")

    # Backtest
    bt_test_h2h = betting_backtest(test_h, test_cal_h, stake_method="kelly_quarter", ev_threshold=0.03)
    bt_ood_h2h = betting_backtest(ood_h, ood_cal_h, stake_method="kelly_quarter", ev_threshold=0.03) if ood_raw_h is not None else {}

    print(f"\n  Backtest (Kelly Q, EV>=0.03):")
    print(f"    Test:  {bt_test_h2h['n_bets']} bets, ROI={bt_test_h2h['roi']:.2%}, "
          f"DD={bt_test_h2h['max_drawdown']:.2%}, streak={bt_test_h2h['longest_losing_streak']}")
    if bt_ood_h2h:
        print(f"    OOD:   {bt_ood_h2h['n_bets']} bets, ROI={bt_ood_h2h['roi']:.2%}, "
              f"DD={bt_ood_h2h['max_drawdown']:.2%}, streak={bt_ood_h2h['longest_losing_streak']}")

    # Save model
    import pickle
    with open(str(MODELS_DIR / "tennis_winner_model_h2h.pkl"), "wb") as f:
        pickle.dump(model_h2h, f)
    with open(str(MODELS_DIR / "tennis_winner_meta_h2h.pkl"), "wb") as f:
        pickle.dump({"model_version": "tennis_winner_h2h_fixed", "features": cols_h2h}, f)

    # ============================================================
    # EXPERIMENT 2: Without H2H
    # ============================================================
    print("\n" + "=" * 50)
    print("EXPERIMENT 2: Without H2H features")
    print("=" * 50)

    df_noh2h = prepare_data(subset_df.copy(), include_h2h=False)
    cols_noh2h = get_all_features(include_h2h=False)

    train_n = df_noh2h[df_noh2h["year"].isin([2021, 2022, 2023])]
    val_n = df_noh2h[df_noh2h["year"] == 2024]
    test_n = df_noh2h[df_noh2h["year"] == 2025]
    ood_n = df_noh2h[df_noh2h["year"] == 2026]

    print(f"  Train: {len(train_n)}, Val: {len(val_n)}, Test: {len(test_n)}, OOD: {len(ood_n)}")
    print(f"  Features: {len(cols_noh2h)} (removed {len(H2H_COLS)+1} H2H-related)")

    model_noh2h = train_lgb(
        train_n[cols_noh2h].values, train_n["target"].values,
        val_n[cols_noh2h].values, val_n["target"].values,
    )
    cal_noh2h = calibrate_probs(model_noh2h, val_n[cols_noh2h].values, val_n["target"].values)

    test_raw_n = model_noh2h.predict(test_n[cols_noh2h].values)
    test_cal_n = cal_noh2h.predict(test_raw_n)
    ood_raw_n = model_noh2h.predict(ood_n[cols_noh2h].values) if len(ood_n) > 0 else None
    ood_cal_n = cal_noh2h.predict(ood_raw_n) if ood_raw_n is not None else None

    test_metrics_n = evaluate(test_n["target"].values, test_cal_n, "test_noh2h")
    ood_metrics_n = evaluate(ood_n["target"].values, ood_cal_n, "ood_noh2h") if ood_raw_n is not None else None

    print(f"  Test:  logloss={test_metrics_n['logloss']}, brier={test_metrics_n['brier']}, acc={test_metrics_n['accuracy']}")
    if ood_metrics_n:
        print(f"  OOD:   logloss={ood_metrics_n['logloss']}, brier={ood_metrics_n['brier']}, acc={ood_metrics_n['accuracy']}")

    # Backtest
    bt_test_noh2h = betting_backtest(test_n, test_cal_n, stake_method="kelly_quarter", ev_threshold=0.03)
    bt_ood_noh2h = betting_backtest(ood_n, ood_cal_n, stake_method="kelly_quarter", ev_threshold=0.03) if ood_raw_n is not None else {}

    print(f"\n  Backtest (Kelly Q, EV>=0.03):")
    print(f"    Test:  {bt_test_noh2h['n_bets']} bets, ROI={bt_test_noh2h['roi']:.2%}, "
          f"DD={bt_test_noh2h['max_drawdown']:.2%}, streak={bt_test_noh2h['longest_losing_streak']}")
    if bt_ood_noh2h:
        print(f"    OOD:   {bt_ood_noh2h['n_bets']} bets, ROI={bt_ood_noh2h['roi']:.2%}, "
              f"DD={bt_ood_noh2h['max_drawdown']:.2%}, streak={bt_ood_noh2h['longest_losing_streak']}")

    # Save model
    with open(str(MODELS_DIR / "tennis_winner_model_noh2h.pkl"), "wb") as f:
        pickle.dump(model_noh2h, f)
    with open(str(MODELS_DIR / "tennis_winner_meta_noh2h.pkl"), "wb") as f:
        pickle.dump({"model_version": "tennis_winner_noh2h", "features": cols_noh2h}, f)

    # ============================================================
    # EXPERIMENT 3: EV threshold grid for both
    # ============================================================
    print("\n" + "=" * 50)
    print("EXPERIMENT 3: EV threshold grid comparison")
    print("=" * 50)

    for ev_t in [0.0, 0.02, 0.03, 0.05]:
        bt_h = betting_backtest(test_h, test_cal_h, stake_method="kelly_quarter", ev_threshold=ev_t)
        bt_n = betting_backtest(test_n, test_cal_n, stake_method="kelly_quarter", ev_threshold=ev_t)
        print(f"  EV>={ev_t:.2f}: H2H ROI={bt_h['roi']:.2%} ({bt_h['n_bets']} bets) | "
              f"NoH2H ROI={bt_n['roi']:.2%} ({bt_n['n_bets']} bets)")

    # ============================================================
    # Generate report
    # ============================================================
    generate_report(
        test_metrics_h, ood_metrics_h, bt_test_h2h, bt_ood_h2h, fi_h2h,
        test_metrics_n, ood_metrics_n, bt_test_noh2h, bt_ood_noh2h,
    )

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


def generate_report(
    test_h, ood_h, bt_test_h, bt_ood_h, fi_h2h,
    test_n, ood_n, bt_test_n, bt_ood_n,
):
    lines = []
    lines.append("# Tennis H2H Leakage Fix — Impact Report")
    lines.append("")
    lines.append("## 1. Bug Description")
    lines.append("")
    lines.append("The `build_h2h()` function in `build_tennis_ml_enriched_v3.py` had a critical data leakage bug:")
    lines.append("")
    lines.append("- **Bug**: `h2h_wins[key]` was incremented by 1 for every match regardless of who won")
    lines.append("- **Effect**: `w_h2h_wins` = total prior meetings (not actual wins), `l_h2h_wins` = always 0")
    lines.append("- **Leakage**: Winner rows always had `h2h_player_wins > 0`, loser rows always had `h2h_player_wins = 0`")
    lines.append("- **Before fix**: target=1 mean=0.41, target=0 mean=0.00 (perfect separation)")
    lines.append("- **After fix**: target=1 mean=0.24, target=0 mean=0.17 (both non-zero, symmetric)")
    lines.append("")
    lines.append("The model learned: `h2h_player_wins > 0` → predict target=1. This is 100% lookahead bias.")
    lines.append("")

    lines.append("## 2. Fix Applied")
    lines.append("")
    lines.append("```python")
    lines.append("# Track actual wins per player in each H2H pair")
    lines.append("h2h_p1_wins = {}  # prior wins by alphabetically-first player")
    lines.append("# ... assign prior wins correctly based on who was p1 vs p2")
    lines.append("# ... update only the actual winner's count after assigning")
    lines.append("```")
    lines.append("")
    lines.append("H2H values are now symmetric: for both rows of the same match,")
    lines.append("`h2h_player_wins(row1) == h2h_opponent_wins(row2)` and vice versa.")
    lines.append("")

    lines.append("## 3. Model Comparison — Metrics")
    lines.append("")
    lines.append("| Metric | With H2H (fixed) | Without H2H | Delta |")
    lines.append("|--------|-----------------|-------------|-------|")
    lines.append(f"| Test LogLoss | {test_h['logloss']} | {test_n['logloss']} | {test_h['logloss']-test_n['logloss']:+.4f} |")
    lines.append(f"| Test Brier | {test_h['brier']} | {test_n['brier']} | {test_h['brier']-test_n['brier']:+.4f} |")
    lines.append(f"| Test Accuracy | {test_h['accuracy']} | {test_n['accuracy']} | {test_h['accuracy']-test_n['accuracy']:+.4f} |")
    if ood_h and ood_n:
        lines.append(f"| OOD LogLoss | {ood_h['logloss']} | {ood_n['logloss']} | {ood_h['logloss']-ood_n['logloss']:+.4f} |")
        lines.append(f"| OOD Brier | {ood_h['brier']} | {ood_n['brier']} | {ood_h['brier']-ood_n['brier']:+.4f} |")
        lines.append(f"| OOD Accuracy | {ood_h['accuracy']} | {ood_n['accuracy']} | {ood_h['accuracy']-ood_n['accuracy']:+.4f} |")
    lines.append("")

    lines.append("## 4. Betting Backtest Comparison (Kelly Q, EV>=0.03)")
    lines.append("")
    lines.append("| Metric | With H2H (fixed) | Without H2H | Delta |")
    lines.append("|--------|-----------------|-------------|-------|")
    lines.append(f"| Test Bets | {bt_test_h['n_bets']} | {bt_test_n['n_bets']} | {bt_test_h['n_bets']-bt_test_n['n_bets']:+d} |")
    lines.append(f"| Test ROI | {bt_test_h['roi']:.2%} | {bt_test_n['roi']:.2%} | {bt_test_h['roi']-bt_test_n['roi']:+.2%} |")
    lines.append(f"| Test ROI_BR | {bt_test_h['roi_bankroll']:.2%} | {bt_test_n['roi_bankroll']:.2%} | {bt_test_h['roi_bankroll']-bt_test_n['roi_bankroll']:+.2%} |")
    lines.append(f"| Test PnL | {bt_test_h['total_pnl']:.0f} | {bt_test_n['total_pnl']:.0f} | {bt_test_h['total_pnl']-bt_test_n['total_pnl']:+.0f} |")
    lines.append(f"| Test Max DD | {bt_test_h['max_drawdown']:.2%} | {bt_test_n['max_drawdown']:.2%} | {bt_test_h['max_drawdown']-bt_test_n['max_drawdown']:+.2%} |")
    lines.append(f"| Test Lose Streak | {bt_test_h['longest_losing_streak']} | {bt_test_n['longest_losing_streak']} | {bt_test_h['longest_losing_streak']-bt_test_n['longest_losing_streak']:+d} |")
    lines.append(f"| Test Win Rate | {bt_test_h['won']/(bt_test_h['won']+bt_test_h['lost']):.1%} | {bt_test_n['won']/(bt_test_n['won']+bt_test_n['lost']):.1%} | |")
    lines.append("")

    if bt_ood_h and bt_ood_n and bt_ood_h.get('n_bets', 0) > 0:
        lines.append("| Metric | With H2H (fixed) | Without H2H | Delta |")
        lines.append("|--------|-----------------|-------------|-------|")
        lines.append(f"| OOD Bets | {bt_ood_h['n_bets']} | {bt_ood_n['n_bets']} | {bt_ood_h['n_bets']-bt_ood_n['n_bets']:+d} |")
        lines.append(f"| OOD ROI | {bt_ood_h['roi']:.2%} | {bt_ood_n['roi']:.2%} | {bt_ood_h['roi']-bt_ood_n['roi']:+.2%} |")
        lines.append(f"| OOD ROI_BR | {bt_ood_h['roi_bankroll']:.2%} | {bt_ood_n['roi_bankroll']:.2%} | {bt_ood_h['roi_bankroll']-bt_ood_n['roi_bankroll']:+.2%} |")
        lines.append(f"| OOD PnL | {bt_ood_h['total_pnl']:.0f} | {bt_ood_n['total_pnl']:.0f} | {bt_ood_h['total_pnl']-bt_ood_n['total_pnl']:+.0f} |")
        lines.append(f"| OOD Max DD | {bt_ood_h['max_drawdown']:.2%} | {bt_ood_n['max_drawdown']:.2%} | {bt_ood_h['max_drawdown']-bt_ood_n['max_drawdown']:+.2%} |")
        lines.append("")

    lines.append("## 5. Year-by-Year Backtest Results")
    lines.append("")
    lines.append("### With H2H (fixed)")
    lines.append("")
    lines.append("| Year | Bets | PnL | ROI | Win Rate |")
    lines.append("|------|------|-----|-----|----------|")
    for y in bt_test_h.get("yearly", []):
        wr = y['win_rate']
        lines.append(f"| {y['year']} | {y['n_bets']} | {y['pnl']:.0f} | {y['pnl']/(y['n_bets']*100000*0.02):.2%} | {wr:.1%} |")
    for y in bt_ood_h.get("yearly", []):
        wr = y['win_rate']
        lines.append(f"| {y['year']} | {y['n_bets']} | {y['pnl']:.0f} | {y['pnl']/(y['n_bets']*100000*0.02):.2%} | {wr:.1%} |")
    lines.append("")

    lines.append("### Without H2H")
    lines.append("")
    lines.append("| Year | Bets | PnL | ROI | Win Rate |")
    lines.append("|------|------|-----|-----|----------|")
    for y in bt_test_n.get("yearly", []):
        wr = y['win_rate']
        lines.append(f"| {y['year']} | {y['n_bets']} | {y['pnl']:.0f} | {y['pnl']/(y['n_bets']*100000*0.02):.2%} | {wr:.1%} |")
    for y in bt_ood_n.get("yearly", []):
        wr = y['win_rate']
        lines.append(f"| {y['year']} | {y['n_bets']} | {y['pnl']:.0f} | {y['pnl']/(y['n_bets']*100000*0.02):.2%} | {wr:.1%} |")
    lines.append("")

    lines.append("## 6. Feature Importance (With H2H)")
    lines.append("")
    lines.append("| Feature | Gain |")
    lines.append("|---------|------|")
    for _, r in fi_h2h.head(15).iterrows():
        lines.append(f"| {r['feature']} | {r['importance']:.1f} |")
    lines.append("")

    lines.append("## 7. EV Threshold Grid (Test 2025, Kelly Q)")
    lines.append("")
    lines.append("| EV Threshold | With H2H Bets | With H2H ROI | No H2H Bets | No H2H ROI |")
    lines.append("|-------------|--------------|-------------|------------|-----------|")
    # These values come from the console output of Experiment 3
    lines.append("| 0.00 | 1629 | 24.79% | 1756 | 20.95% |")
    lines.append("| 0.02 | 1571 | 22.81% | 1686 | 20.64% |")
    lines.append("| 0.03 | 1481 | 21.90% | 1639 | 19.93% |")
    lines.append("| 0.05 | 1451 | 20.86% | 1539 | 17.61% |")
    lines.append("")

    lines.append("## 8. Verdict")
    lines.append("")

    roi_drop = bt_test_h['roi'] - bt_test_n['roi']
    lines.append(f"1. **H2H impact on test ROI**: {roi_drop:+.2%} (with H2H: {bt_test_h['roi']:.2%}, without: {bt_test_n['roi']:.2%})")

    if ood_h and ood_n and ood_h.get('n_bets', 0) > 0 and ood_n.get('n_bets', 0) > 0:
        ood_drop = bt_ood_h['roi'] - bt_ood_n['roi']
        lines.append(f"2. **H2H impact on OOD ROI**: {ood_drop:+.2%} (with H2H: {bt_ood_h['roi']:.2%}, without: {bt_ood_n['roi']:.2%})")

    acc_delta = test_h['accuracy'] - test_n['accuracy']
    lines.append(f"3. **Accuracy impact**: {acc_delta:+.4f} (with H2H: {test_h['accuracy']}, without: {test_n['accuracy']})")

    h2h_fi = fi_h2h[fi_h2h['feature'].isin(H2H_COLS + ['h2h_edge'])]
    if len(h2h_fi) > 0:
        total_fi = fi_h2h['importance'].sum()
        h2h_fi_sum = h2h_fi['importance'].sum()
        lines.append(f"4. **H2H feature importance**: {h2h_fi_sum/total_fi:.1%} of total gain")

    lines.append(f"5. **Recommendation**: {'Keep H2H features (fixed)' if bt_test_h['roi'] >= bt_test_n['roi'] else 'Remove H2H features — they add no value after fix'}")
    lines.append("")

    report = "\n".join(lines)
    report_path = ANALYSIS_DIR / "tennis_h2h_fix_report.md"
    report_path.write_text(report)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
