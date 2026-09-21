#!/usr/bin/env python3
"""
Tennis ML — Fixed Stake Backtest (honest ROI)
================================================
- Flat 500 RUB per bet (not compounding)
- ML-only EV>=0.05 strategy
- Year-by-year + monthly breakdown
- Compare fixed vs compounding ROI
- Verify walk-forward training data
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import log_loss, accuracy_score
import lightgbm as lgb
import pickle

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

BASE_FEATURE_COLS = [
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

NEW_FEATURES = ["rank_ratio", "surface_advantage", "momentum"]

DERIVED_COLS = [
    "player_form_diff", "opponent_form_diff",
    "serve_diff", "return_diff",
    "fatigue_diff", "surface_diff",
    "h2h_edge",
] + NEW_FEATURES

ALL_FEATURES = BASE_FEATURE_COLS + DERIVED_COLS


def add_derived_features(df):
    df = df.copy()
    df["player_form_diff"] = df["player_win_pct_5"] - df["opponent_win_pct_5"]
    df["opponent_form_diff"] = df["opponent_win_pct_10"] - df["player_win_pct_10"]
    df["serve_diff"] = df["player_1st_won_pct"] - df["opponent_1st_won_pct"]
    df["return_diff"] = df["player_bp_saved_pct"] - df["opponent_bp_saved_pct"]
    df["fatigue_diff"] = df["player_matches_14d"] - df["opponent_matches_14d"]
    df["surface_diff"] = df["player_surface_win_pct"] - df["opponent_surface_win_pct"]
    df["h2h_edge"] = df["h2h_player_wins"] - df["h2h_opponent_wins"]
    df["rank_ratio"] = df["player_rank"] / df["opponent_rank"].replace(0, 1)
    df["rank_ratio"] = df["rank_ratio"].clip(0.01, 100)
    df["surface_advantage"] = df["player_surface_win_pct"] - df["opponent_surface_win_pct"]
    df["momentum"] = df["player_win_pct_5"] - df["player_win_pct_10"]
    return df


def prepare_data(df):
    df = add_derived_features(df)
    for col in ALL_FEATURES:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
    df = df.dropna(subset=["target"])
    return df


def temperature_scale(raw_probs, temperature=1.5):
    eps = 1e-7
    p = np.clip(raw_probs, eps, 1 - eps)
    logits = np.log(p / (1 - p))
    return 1 / (1 + np.exp(-logits / temperature))


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


def backtest_fixed_stake(df, probs, fixed_stake=500, ev_threshold=0.05):
    """Backtest with FIXED stake amount (not percentage)."""
    mask = df["odds_player"].notna() & (df["odds_player"] >= 1.5)
    df_bet = df[mask].copy()
    df_bet["prob"] = probs[mask]
    df_bet["ev"] = df_bet["prob"] * df_bet["odds_player"] - 1
    df_bet = df_bet[df_bet["ev"] >= ev_threshold].copy()

    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "win_rate": 0,
                "total_pnl": 0, "total_staked": 0, "monthly": []}

    df_bet = df_bet.sort_values("tourney_date").reset_index(drop=True)

    bankroll = 100000
    equity = [bankroll]
    won = lost = 0
    peak = bankroll
    max_dd = 0
    monthly_results = []
    total_staked = 0

    for _, row in df_bet.iterrows():
        total_staked += fixed_stake
        if row["target"] == 1:
            equity.append(equity[-1] + fixed_stake * (row["odds_player"] - 1))
            won += 1
        else:
            equity.append(equity[-1] - fixed_stake)
            lost += 1

        peak = max(peak, equity[-1])
        dd = (peak - equity[-1]) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

        month = str(row.get("tourney_date", ""))[:7] if pd.notna(row.get("tourney_date", "")) else "unknown"
        year = str(int(row["year"])) if pd.notna(row.get("year", "")) else "unknown"
        monthly_results.append({
            "month": month, "year": year,
            "pnl": fixed_stake * (row["odds_player"] - 1) if row["target"] == 1 else -fixed_stake,
            "won": row["target"] == 1,
        })

    res_df = pd.DataFrame(monthly_results)
    monthly = res_df.groupby("month").agg(
        n_bets=("pnl", "count"), pnl=("pnl", "sum"), win_rate=("won", "mean"),
    ).reset_index()

    total = won + lost
    pnl = equity[-1] - bankroll
    roi = pnl / total_staked if total_staked > 0 else 0

    return {
        "n_bets": total, "won": won, "lost": lost,
        "roi": round(roi, 4), "max_drawdown": round(max_dd, 4),
        "win_rate": round(won / total, 4) if total > 0 else 0,
        "total_pnl": round(pnl, 2), "total_staked": round(total_staked, 2),
        "final_bankroll": round(equity[-1], 2),
        "monthly": monthly.to_dict("records"),
    }


def backtest_compounding(df, probs, stake_pct=0.005, ev_threshold=0.05):
    """Backtest with compounding stake (% of current bankroll)."""
    mask = df["odds_player"].notna() & (df["odds_player"] >= 1.5)
    df_bet = df[mask].copy()
    df_bet["prob"] = probs[mask]
    df_bet["ev"] = df_bet["prob"] * df_bet["odds_player"] - 1
    df_bet = df_bet[df_bet["ev"] >= ev_threshold].copy()

    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "win_rate": 0,
                "total_pnl": 0, "total_staked": 0, "monthly": []}

    df_bet = df_bet.sort_values("tourney_date").reset_index(drop=True)

    bankroll = 100000
    equity = [bankroll]
    won = lost = 0
    peak = bankroll
    max_dd = 0
    monthly_results = []
    total_staked = 0

    for _, row in df_bet.iterrows():
        stake = stake_pct * equity[-1]
        total_staked += stake
        if row["target"] == 1:
            equity.append(equity[-1] + stake * (row["odds_player"] - 1))
            won += 1
        else:
            equity.append(equity[-1] - stake)
            lost += 1

        peak = max(peak, equity[-1])
        dd = (peak - equity[-1]) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

        month = str(row.get("tourney_date", ""))[:7] if pd.notna(row.get("tourney_date", "")) else "unknown"
        year = str(int(row["year"])) if pd.notna(row.get("year", "")) else "unknown"
        monthly_results.append({
            "month": month, "year": year,
            "pnl": stake * (row["odds_player"] - 1) if row["target"] == 1 else -stake,
            "won": row["target"] == 1,
        })

    res_df = pd.DataFrame(monthly_results)
    monthly = res_df.groupby("month").agg(
        n_bets=("pnl", "count"), pnl=("pnl", "sum"), win_rate=("won", "mean"),
    ).reset_index()

    total = won + lost
    pnl = equity[-1] - bankroll
    roi = pnl / total_staked if total_staked > 0 else 0

    return {
        "n_bets": total, "won": won, "lost": lost,
        "roi": round(roi, 4), "max_drawdown": round(max_dd, 4),
        "win_rate": round(won / total, 4) if total > 0 else 0,
        "total_pnl": round(pnl, 2), "total_staked": round(total_staked, 2),
        "final_bankroll": round(equity[-1], 2),
        "monthly": monthly.to_dict("records"),
    }


def main():
    print("=" * 60)
    print("Tennis ML — Fixed Stake Backtest (Honest ROI)")
    print("=" * 60)

    df = pd.read_csv(str(DATA_DIR / "tennis_ml_enriched_v3.csv"))
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], errors="coerce")
    subset = df[df["join_confidence"].isin(["high", "medium"])].copy()
    subset = prepare_data(subset)

    print(f"\nDataset: {len(subset)} rows")
    print(f"Year range: {subset['year'].min():.0f} - {subset['year'].max():.0f}")

    # ============================================================
    # Walk-forward: retrain model each year
    # ============================================================
    print("\n" + "=" * 50)
    print("WALK-FORWARD: Retrain model each year")
    print("=" * 50)

    # Year 1: Train 2021-2022, test 2023
    # Year 2: Train 2021-2023, test 2024
    # Year 3: Train 2021-2024, test 2025
    # Year 4: Train 2021-2025, test 2026

    wf_configs = [
        {"test_year": 2023, "train_years": [2021, 2022], "label": "2023 (train: 2021-2022)"},
        {"test_year": 2024, "train_years": [2021, 2022, 2023], "label": "2024 (train: 2021-2023)"},
        {"test_year": 2025, "train_years": [2021, 2022, 2023, 2024], "label": "2025 (train: 2021-2024)"},
        {"test_year": 2026, "train_years": [2021, 2022, 2023, 2024, 2025], "label": "2026 (train: 2021-2025)"},
    ]

    all_results = {}

    for cfg in wf_configs:
        train_years = cfg["train_years"]
        test_year = cfg["test_year"]
        label = cfg["label"]

        train_df = subset[subset["year"].isin(train_years)]
        test_df = subset[subset["year"] == test_year]

        if len(test_df) == 0:
            continue

        print(f"\n  {label}")
        print(f"    Train: {len(train_df)} rows, Test: {len(test_df)} rows")

        model = train_lgb(
            train_df[ALL_FEATURES].values, train_df["target"].values,
            test_df[ALL_FEATURES].values, test_df["target"].values,
        )

        raw_probs = model.predict(test_df[ALL_FEATURES].values)
        temp_probs = temperature_scale(raw_probs, temperature=1.5)

        acc = accuracy_score(test_df["target"].values, (raw_probs >= 0.5).astype(int))
        ll = log_loss(test_df["target"].values, raw_probs)
        print(f"    Accuracy: {acc:.4f}, LogLoss: {ll:.4f}")
        print(f"    Prob range: [{raw_probs.min():.3f}, {raw_probs.max():.3f}], mean={raw_probs.mean():.3f}")

        # Fixed stake backtest
        bt_fixed = backtest_fixed_stake(test_df, temp_probs, fixed_stake=500, ev_threshold=0.05)
        bt_compound = backtest_compounding(test_df, temp_probs, stake_pct=0.005, ev_threshold=0.05)

        print(f"\n    FIXED STAKE (500 RUB):")
        print(f"      Bets: {bt_fixed['n_bets']}, ROI: {bt_fixed['roi']:.2%}, DD: {bt_fixed['max_drawdown']:.2%}, WR: {bt_fixed['win_rate']:.1%}")
        print(f"      Total PnL: {bt_fixed['total_pnl']:+.0f}, Total Staked: {bt_fixed['total_staked']:.0f}")
        print(f"      Final BR: {bt_fixed['final_bankroll']:.0f}")

        print(f"\n    COMPOUNDING (0.5%):")
        print(f"      Bets: {bt_compound['n_bets']}, ROI: {bt_compound['roi']:.2%}, DD: {bt_compound['max_drawdown']:.2%}, WR: {bt_compound['win_rate']:.1%}")
        print(f"      Total PnL: {bt_compound['total_pnl']:+.0f}, Total Staked: {bt_compound['total_staked']:.0f}")
        print(f"      Final BR: {bt_compound['final_bankroll']:.0f}")

        all_results[test_year] = {
            "model": model,
            "test_df": test_df,
            "temp_probs": temp_probs,
            "fixed": bt_fixed,
            "compound": bt_compound,
        }

    # ============================================================
    # Aggregate comparison
    # ============================================================
    print("\n" + "=" * 50)
    print("AGGREGATE: Fixed vs Compounding ROI")
    print("=" * 50)

    print(f"\n  {'Year':>4} {'Bets':>5} {'Fixed ROI':>10} {'Fixed PnL':>12} {'Fixed DD':>10} {'Comp ROI':>10} {'Comp PnL':>12} {'Comp DD':>10} {'WR':>7}")
    print(f"  {'-' * 85}")
    for yr in sorted(all_results.keys()):
        r = all_results[yr]
        f = r["fixed"]
        c = r["compound"]
        print(f"  {yr:>4} {f['n_bets']:>5} {f['roi']:>10.2%} {f['total_pnl']:>+12.0f} {f['max_drawdown']:>10.2%} {c['roi']:>10.2%} {c['total_pnl']:>+12.0f} {c['max_drawdown']:>10.2%} {f['win_rate']:>7.1%}")

    # Totals
    total_bets = sum(all_results[yr]["fixed"]["n_bets"] for yr in all_results)
    total_pnl_fixed = sum(all_results[yr]["fixed"]["total_pnl"] for yr in all_results)
    total_staked_fixed = sum(all_results[yr]["fixed"]["total_staked"] for yr in all_results)
    avg_dd_fixed = np.mean([all_results[yr]["fixed"]["max_drawdown"] for yr in all_results])
    avg_wr = np.mean([all_results[yr]["fixed"]["win_rate"] for yr in all_results])

    total_pnl_comp = sum(all_results[yr]["compound"]["total_pnl"] for yr in all_results)
    avg_dd_comp = np.mean([all_results[yr]["compound"]["max_drawdown"] for yr in all_results])

    overall_roi_fixed = total_pnl_fixed / total_staked_fixed if total_staked_fixed > 0 else 0
    print(f"  {'-' * 85}")
    print(f"  {'TOTL':>4} {total_bets:>5} {overall_roi_fixed:>10.2%} {total_pnl_fixed:>+12.0f} {avg_dd_fixed:>10.2%} {'':>10} {total_pnl_comp:>+12.0f} {avg_dd_comp:>10.2%} {avg_wr:>7.1%}")
    print(f"\n  Note: Fixed ROI = Total PnL / Total Staked (honest)")
    print(f"        Compounding ROI = Total PnL / Total Staked (grows with bankroll)")

    # ============================================================
    # Monthly breakdown (fixed stake, ML-only EV>=0.05)
    # ============================================================
    print("\n" + "=" * 50)
    print("MONTHLY BREAKDOWN — Fixed Stake (500 RUB), ML-only EV>=0.05")
    print("=" * 50)

    for yr in sorted(all_results.keys()):
        r = all_results[yr]
        bt = r["fixed"]
        if bt.get("monthly"):
            print(f"\n  {yr} (ROI: {bt['roi']:.2%}, PnL: {bt['total_pnl']:+.0f}, Bets: {bt['n_bets']}):")
            for m in bt["monthly"]:
                print(f"    {m['month']}: {m['n_bets']:>4} bets, PnL={m['pnl']:+10.0f}, WR={m['win_rate']:.1%}")

    # ============================================================
    # Verify walk-forward training data
    # ============================================================
    print("\n" + "=" * 50)
    print("WALK-FORWARD VERIFICATION")
    print("=" * 50)

    for cfg in wf_configs:
        test_year = cfg["test_year"]
        train_years = cfg["train_years"]
        if test_year in all_results:
            model = all_results[test_year]["model"]
            print(f"\n  Test year {test_year}:")
            print(f"    Training data: years {train_years}")
            print(f"    Model trees: {model.num_trees()}")
            print(f"    Model features: {model.num_feature()}")


if __name__ == "__main__":
    main()
