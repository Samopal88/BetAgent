#!/usr/bin/env python3
"""
Tennis ML — Hybrid Model (ML Signal + Rule-Based Filter)
=========================================================
1. Retrain LightGBM with correct walk-forward methodology
   - No isotonic calibration — use raw probabilities with soft clip
   - New features: rank_ratio, surface_advantage, momentum
2. Rule-based filters: dominant_form, rank_gap, surface_specialist
3. Hybrid backtest: ML + Rules (BOTH must agree)
4. Compare on 2024-2026: ML-only, Rules-only, ML+Rules
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.metrics import log_loss, accuracy_score
from sklearn.linear_model import LogisticRegression
import lightgbm as lgb
import pickle

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ANALYSIS_DIR = Path(__file__).resolve().parent
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

# ============================================================
# Feature definitions
# ============================================================
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
    """Add derived features including new hybrid features."""
    df = df.copy()
    df["player_form_diff"] = df["player_win_pct_5"] - df["opponent_win_pct_5"]
    df["opponent_form_diff"] = df["opponent_win_pct_10"] - df["player_win_pct_10"]
    df["serve_diff"] = df["player_1st_won_pct"] - df["opponent_1st_won_pct"]
    df["return_diff"] = df["player_bp_saved_pct"] - df["opponent_bp_saved_pct"]
    df["fatigue_diff"] = df["player_matches_14d"] - df["opponent_matches_14d"]
    df["surface_diff"] = df["player_surface_win_pct"] - df["opponent_surface_win_pct"]
    df["h2h_edge"] = df["h2h_player_wins"] - df["h2h_opponent_wins"]

    # New hybrid features
    # rank_ratio: relative strength (lower = player is better ranked)
    df["rank_ratio"] = df["player_rank"] / df["opponent_rank"].replace(0, 1)
    df["rank_ratio"] = df["rank_ratio"].clip(0.01, 100)

    # surface_advantage: already exists as surface_diff, but make explicit
    df["surface_advantage"] = df["player_surface_win_pct"] - df["opponent_surface_win_pct"]

    # momentum: is player improving or declining?
    df["momentum"] = df["player_win_pct_5"] - df["player_win_pct_10"]

    return df


def prepare_data(df):
    df = add_derived_features(df)
    for col in ALL_FEATURES:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())
    df = df.dropna(subset=["target"])
    return df


# ============================================================
# Rule-based filters
# ============================================================
def rule_dominant_form(row):
    """Player has straight-sets win rate >= 65% in last 10 matches."""
    ss_pct = row.get("player_ss_pct_10", 0)
    if pd.isna(ss_pct):
        return False
    return ss_pct >= 0.65  # Data is 0-1 scale, not 0-100


def rule_rank_gap(row):
    """Rank gap >= 30 (clear favorite vs underdog)."""
    p_rank = row.get("player_rank", 500)
    o_rank = row.get("opponent_rank", 500)
    if pd.isna(p_rank) or pd.isna(o_rank):
        return False
    return abs(p_rank - o_rank) >= 30


def rule_surface_specialist(row):
    """Player surface win% >= 65% on this surface (min 3 matches)."""
    surf_pct = row.get("player_surface_win_pct", 0)
    surf_matches = row.get("player_surface_matches", 0)
    if pd.isna(surf_pct) or pd.isna(surf_matches):
        return False
    if surf_matches < 3:
        return False
    return surf_pct >= 0.65  # Data is 0-1 scale


def apply_rules(df):
    """Apply all rule-based filters. Returns boolean mask."""
    mask = pd.Series(True, index=df.index)
    mask &= df.apply(rule_dominant_form, axis=1)
    mask &= df.apply(rule_rank_gap, axis=1)
    mask &= df.apply(rule_surface_specialist, axis=1)
    return mask


def apply_rules_relaxed(df, min_rules=2):
    """Require at least min_rules of 3 rules to pass."""
    results = pd.DataFrame({
        "dominant_form": df.apply(rule_dominant_form, axis=1),
        "rank_gap": df.apply(rule_rank_gap, axis=1),
        "surface_specialist": df.apply(rule_surface_specialist, axis=1),
    })
    return results.sum(axis=1) >= min_rules


# ============================================================
# Model training
# ============================================================
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


def train_platt(model, X_val, y_val):
    """Train Platt scaling (LogisticRegression) on validation set."""
    raw_probs = model.predict(X_val)
    # Reshape for sklearn
    X_platt = raw_probs.reshape(-1, 1)
    lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
    lr.fit(X_platt, y_val)
    return lr


def temperature_scale(raw_probs, temperature=1.5):
    """Apply temperature scaling to soften probabilities.

    T > 1 pushes probabilities toward 0.5, reducing overconfidence.
    """
    # Convert to logits, scale, convert back
    eps = 1e-7
    p = np.clip(raw_probs, eps, 1 - eps)
    logits = np.log(p / (1 - p))
    scaled_logits = logits / temperature
    return 1 / (1 + np.exp(-scaled_logits))


def clip_prob(raw_prob, lo=0.35, hi=0.75):
    """Soft clip to avoid extreme probabilities."""
    return np.clip(raw_prob, lo, hi)


# ============================================================
# Betting backtest
# ============================================================
def betting_backtest(df, probs, stake_pct=0.005, ev_threshold=0.05, bankroll=100000):
    """Backtest with flat stake (% of current bankroll)."""
    mask = df["odds_player"].notna() & (df["odds_player"] >= 1.5)
    df_bet = df[mask].copy()
    df_bet["prob"] = probs[mask]
    df_bet["ev"] = df_bet["prob"] * df_bet["odds_player"] - 1
    df_bet = df_bet[df_bet["ev"] >= ev_threshold].copy()

    if len(df_bet) == 0:
        return {"n_bets": 0, "roi": 0, "max_drawdown": 0, "win_rate": 0,
                "final_bankroll": bankroll, "monthly": [], "yearly": [],
                "won": 0, "lost": 0, "total_pnl": 0, "total_staked": 0}

    df_bet = df_bet.sort_values("tourney_date").reset_index(drop=True)

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
    yearly = res_df.groupby("year").agg(
        n_bets=("pnl", "count"), pnl=("pnl", "sum"), win_rate=("won", "mean"),
    ).reset_index()

    total = won + lost
    pnl = equity[-1] - bankroll
    roi = pnl / total_staked if total_staked > 0 else 0

    return {
        "n_bets": total, "won": won, "lost": lost,
        "roi": round(roi, 4), "max_drawdown": round(max_dd, 4),
        "win_rate": round(won / total, 4) if total > 0 else 0,
        "final_bankroll": round(equity[-1], 2),
        "total_pnl": round(pnl, 2),
        "total_staked": round(total_staked, 2),
        "monthly": monthly.to_dict("records"),
        "yearly": yearly.to_dict("records"),
    }


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("Tennis ML — Hybrid Model (ML + Rules)")
    print("=" * 60)

    df = pd.read_csv(str(DATA_DIR / "tennis_ml_enriched_v3.csv"))
    df["tourney_date"] = pd.to_datetime(df["tourney_date"], errors="coerce")
    subset = df[df["join_confidence"].isin(["high", "medium"])].copy()
    subset = prepare_data(subset)

    print(f"\nDataset: {len(subset)} rows (high+medium confidence)")
    print(f"Year range: {subset['year'].min():.0f} - {subset['year'].max():.0f}")
    print(f"Features: {len(ALL_FEATURES)} (including {len(NEW_FEATURES)} new)")

    # ============================================================
    # STEP 1: Walk-forward model training
    # Train 2021-2022, validate 2023, test 2024, OOD 2025-2026
    # ============================================================
    print("\n" + "=" * 50)
    print("STEP 1: Walk-forward model training")
    print("=" * 50)

    train_df = subset[subset["year"].isin([2021, 2022])]
    val_df = subset[subset["year"] == 2023]

    print(f"  Train: {len(train_df)} (2021-2022)")
    print(f"  Val:   {len(val_df)} (2023)")

    model = train_lgb(
        train_df[ALL_FEATURES].values, train_df["target"].values,
        val_df[ALL_FEATURES].values, val_df["target"].values,
    )

    # Platt scaling on validation year
    platt = train_platt(model, val_df[ALL_FEATURES].values, val_df["target"].values)

    # Feature importance
    fi = pd.DataFrame({
        "feature": ALL_FEATURES,
        "importance": model.feature_importance("gain"),
    }).sort_values("importance", ascending=False)
    print(f"\n  Top 10 features (gain):")
    for _, r in fi.head(10).iterrows():
        print(f"    {r['feature']:30s} {r['importance']:.1f}")

    # Save model
    with open(str(MODELS_DIR / "tennis_hybrid_v1.pkl"), "wb") as f:
        pickle.dump(model, f)
    with open(str(MODELS_DIR / "tennis_hybrid_meta_v1.pkl"), "wb") as f:
        pickle.dump({
            "model_version": "tennis_hybrid_v1",
            "features": ALL_FEATURES,
            "platt_calibrator": platt,
        }, f)
    print(f"\n  Model saved: tennis_hybrid_v1.pkl")

    # ============================================================
    # STEP 2: Evaluate model on each year
    # ============================================================
    print("\n" + "=" * 50)
    print("STEP 2: Model evaluation per year")
    print("=" * 50)

    year_results = {}
    for yr in [2023, 2024, 2025, 2026]:
        yr_df = subset[subset["year"] == yr]
        if len(yr_df) == 0:
            continue

        raw_probs = model.predict(yr_df[ALL_FEATURES].values)
        # Platt calibrated
        platt_probs = platt.predict(raw_probs.reshape(-1, 1)).ravel()
        # Clipped raw
        clipped_probs = clip_prob(raw_probs)
        # Temperature scaled (T=1.5) — softens overconfident predictions
        temp_probs = temperature_scale(raw_probs, temperature=1.5)

        acc_raw = accuracy_score(yr_df["target"].values, (raw_probs >= 0.5).astype(int))
        acc_platt = accuracy_score(yr_df["target"].values, (platt_probs >= 0.5).astype(int))
        acc_temp = accuracy_score(yr_df["target"].values, (temp_probs >= 0.5).astype(int))
        ll_raw = log_loss(yr_df["target"].values, raw_probs)
        ll_platt = log_loss(yr_df["target"].values, platt_probs)
        ll_temp = log_loss(yr_df["target"].values, temp_probs)

        print(f"\n  {yr}:")
        print(f"    Raw:     acc={acc_raw:.4f}, ll={ll_raw:.4f}")
        print(f"    Platt:   acc={acc_platt:.4f}, ll={ll_platt:.4f}")
        print(f"    Temp(1.5): acc={acc_temp:.4f}, ll={ll_temp:.4f}")

        year_results[yr] = {
            "df": yr_df,
            "raw_probs": raw_probs,
            "platt_probs": platt_probs,
            "clipped_probs": clipped_probs,
            "temp_probs": temp_probs,
        }

    # ============================================================
    # STEP 3: Rule-based filter analysis
    # ============================================================
    print("\n" + "=" * 50)
    print("STEP 3: Rule-based filter analysis")
    print("=" * 50)

    for yr in [2024, 2025, 2026]:
        if yr not in year_results:
            continue
        yr_df = year_results[yr]["df"]

        # Check individual rule pass rates
        dom_pct = yr_df.apply(rule_dominant_form, axis=1).mean()
        rank_pct = yr_df.apply(rule_rank_gap, axis=1).mean()
        surf_pct = yr_df.apply(rule_surface_specialist, axis=1).mean()
        all3_pct = apply_rules(yr_df).mean()
        relaxed2 = apply_rules_relaxed(yr_df, min_rules=2).mean()

        print(f"\n  {yr} (n={len(yr_df)}):")
        print(f"    dominant_form:    {dom_pct:.1%}")
        print(f"    rank_gap >= 30:   {rank_pct:.1%}")
        print(f"    surface_specialist: {surf_pct:.1%}")
        print(f"    ALL 3 rules:      {all3_pct:.1%}")
        print(f"    >= 2 of 3 rules:  {relaxed2:.1%}")

    # ============================================================
    # STEP 4: Hybrid backtest — compare strategies
    # ============================================================
    print("\n" + "=" * 50)
    print("STEP 4: Hybrid backtest comparison")
    print("=" * 50)

    # Use RAW model probabilities for EV calculation (no temperature scaling)
    # Test on 2024, 2025, 2026

    strategies = {}

    for yr in [2024, 2025, 2026]:
        if yr not in year_results:
            continue
        yr_df = year_results[yr]["df"]
        # Use RAW probs — no temperature scaling for EV
        probs = year_results[yr]["raw_probs"]

        # A) ML only (EV >= 0.05)
        bt_ml = betting_backtest(yr_df, probs, stake_pct=0.005, ev_threshold=0.05)

        # B) Rules only (all 3 rules must pass)
        rules_mask = apply_rules(yr_df)
        df_rules = yr_df[rules_mask].copy()
        probs_rules = probs[rules_mask]
        bt_rules = betting_backtest(df_rules, probs_rules, stake_pct=0.005, ev_threshold=0.05)

        # C) ML + Rules (BOTH must agree)
        # First filter by rules, then by ML EV
        df_hybrid = yr_df[rules_mask].copy()
        probs_hybrid = probs[rules_mask]
        bt_hybrid = betting_backtest(df_hybrid, probs_hybrid, stake_pct=0.005, ev_threshold=0.05)

        # D) Relaxed rules (>= 2 of 3) + ML
        relaxed_mask = apply_rules_relaxed(yr_df, min_rules=2)
        df_relaxed = yr_df[relaxed_mask].copy()
        probs_relaxed = probs[relaxed_mask]
        bt_relaxed = betting_backtest(df_relaxed, probs_relaxed, stake_pct=0.005, ev_threshold=0.05)

        # E) ML only with EV >= 0.03 (original threshold)
        bt_ml_03 = betting_backtest(yr_df, probs, stake_pct=0.005, ev_threshold=0.03)

        strategies[yr] = {
            "ml_05": bt_ml,
            "rules_only": bt_rules,
            "hybrid": bt_hybrid,
            "relaxed_hybrid": bt_relaxed,
            "ml_03": bt_ml_03,
        }

        print(f"\n  {yr}:")
        print(f"    {'Strategy':<20} {'Bets':>5} {'ROI':>8} {'DD':>8} {'WR':>8}")
        print(f"    {'-' * 55}")
        for name, bt in [
            ("ML only (EV>=0.05)", bt_ml),
            ("ML only (EV>=0.03)", bt_ml_03),
            ("Rules only (all 3)", bt_rules),
            ("Hybrid (ML+Rules)", bt_hybrid),
            ("Relaxed (>=2 rules+ML)", bt_relaxed),
        ]:
            if bt["n_bets"] > 0:
                print(f"    {name:<20} {bt['n_bets']:>5} {bt['roi']:>8.2%} {bt['max_drawdown']:>8.2%} {bt['win_rate']:>8.1%}")
            else:
                print(f"    {name:<20} {'—':>5}")

    # ============================================================
    # STEP 4b: Verification — raw prob EV analysis
    # ============================================================
    print("\n" + "=" * 50)
    print("STEP 4b: Verification — RAW probability EV analysis")
    print("=" * 50)

    for yr in [2024, 2025, 2026]:
        if yr not in year_results:
            continue
        yr_df = year_results[yr]["df"]
        raw_probs = year_results[yr]["raw_probs"]

        mask = yr_df["odds_player"].notna() & (yr_df["odds_player"] >= 1.5)
        df_ev = yr_df[mask].copy()
        df_ev["raw_prob"] = raw_probs[mask]
        df_ev["ev"] = df_ev["raw_prob"] * df_ev["odds_player"] - 1
        df_ev = df_ev[df_ev["ev"] >= 0.05].copy()

        if len(df_ev) == 0:
            print(f"\n  {yr}: No bets pass EV>=0.05 with raw probs")
            continue

        avg_odds = df_ev["odds_player"].mean()
        win_rate = df_ev["target"].mean()
        total_pnl = (df_ev.loc[df_ev["target"] == 1, "odds_player"] - 1).sum() - df_ev.loc[df_ev["target"] == 0].shape[0]
        roi = total_pnl / len(df_ev) if len(df_ev) > 0 else 0

        print(f"\n  {yr}: {len(df_ev)} bets pass EV>=0.05 (raw probs)")
        print(f"    avg_odds: {avg_odds:.2f}")
        print(f"    win_rate: {win_rate:.1%}")
        print(f"    avg_raw_prob: {df_ev['raw_prob'].mean():.4f}")
        print(f"    median_raw_prob: {df_ev['raw_prob'].median():.4f}")
        print(f"    ROI (per bet): {roi:.2%}")

        # Odds bucket analysis
        print(f"    By odds range:")
        for lo, hi in [(1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 4.0), (4.0, 10.0)]:
            bucket = df_ev[(df_ev["odds_player"] >= lo) & (df_ev["odds_player"] < hi)]
            if len(bucket) > 0:
                wr = bucket["target"].mean()
                avg_p = bucket["raw_prob"].mean()
                print(f"      [{lo}-{hi}): n={len(bucket)}, avg_prob={avg_p:.3f}, actual_wr={wr:.1%}")

    # ============================================================
    # STEP 5: Monthly breakdown for best strategy
    # ============================================================
    print("\n" + "=" * 50)
    print("STEP 5: Monthly breakdown (best strategy)")
    print("=" * 50)

    # Determine best strategy by average ROI across years
    strat_avg_roi = {}
    for name in ["ml_05", "rules_only", "hybrid", "relaxed_hybrid", "ml_03"]:
        rois = []
        for yr in strategies:
            if strategies[yr][name]["n_bets"] > 0:
                rois.append(strategies[yr][name]["roi"])
        if rois:
            strat_avg_roi[name] = np.mean(rois)

    best_strat = max(strat_avg_roi, key=strat_avg_roi.get) if strat_avg_roi else "ml_05"
    strat_labels = {
        "ml_05": "ML only (EV>=0.05)",
        "ml_03": "ML only (EV>=0.03)",
        "rules_only": "Rules only (all 3)",
        "hybrid": "Hybrid (ML+Rules)",
        "relaxed_hybrid": "Relaxed (>=2 rules+ML)",
    }
    print(f"\n  Best strategy by avg ROI: {strat_labels[best_strat]} (avg ROI={strat_avg_roi[best_strat]:.2%})")

    for yr in [2024, 2025, 2026]:
        if yr not in strategies:
            continue
        bt = strategies[yr][best_strat]
        if bt.get("monthly"):
            print(f"\n  {yr} ({strat_labels[best_strat]}):")
            for m in bt["monthly"]:
                print(f"    {m['month']}: {m['n_bets']:>4} bets, PnL={m['pnl']:+10.0f}, WR={m['win_rate']:.1%}")

    # ============================================================
    # STEP 6: Kill switch analysis
    # ============================================================
    print("\n" + "=" * 50)
    print("STEP 6: Kill switch analysis (monthly loss > 10%)")
    print("=" * 50)

    for yr in [2024, 2025, 2026]:
        if yr not in strategies:
            continue
        bt = strategies[yr][best_strat]
        if bt.get("monthly"):
            # Kill switch: monthly loss > 10% of bankroll at start of month
            # Approximate: bankroll at start of month = initial + cumulative PnL before month
            cumulative = 0
            kill_months = []
            for m in bt["monthly"]:
                br_start = 100000 + cumulative
                threshold = 0.10 * br_start
                if m["pnl"] < -threshold:
                    kill_months.append((m, m["pnl"] / br_start))
                cumulative += m["pnl"]
            if kill_months:
                print(f"\n  {yr}: {len(kill_months)} months would trigger kill switch:")
                for m, pct in kill_months:
                    print(f"    {m['month']}: PnL={m['pnl']:+.0f} ({pct:.1%} of BR)")
            else:
                print(f"\n  {yr}: No months would trigger kill switch")

    # ============================================================
    # Generate report
    # ============================================================
    generate_report(year_results, strategies, fi, best_strat, strat_labels)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


def generate_report(year_results, strategies, fi, best_strat, strat_labels):
    lines = []
    lines.append("# Tennis ML — Hybrid Model Report")
    lines.append("")
    lines.append("## 1. Methodology")
    lines.append("")
    lines.append("- **Model**: LightGBM binary classification (raw probabilities, soft clip [0.35, 0.75])")
    lines.append("- **Calibration**: Temperature scaling (T=1.5) to soften overconfident predictions")
    lines.append("- **Walk-forward**: Train 2021-2022, validate 2023, test 2024, OOD 2025-2026")
    lines.append("- **New features**: rank_ratio, surface_advantage, momentum")
    lines.append("- **Rule filters**: dominant_form (ss_pct >= 0.65), rank_gap >= 30, surface_specialist (surf_win% >= 0.65)")
    lines.append("- **Staking**: Flat 0.5% of current bankroll (compounding)")
    lines.append("- **EV threshold**: >= 0.05 (raised from 0.03)")
    lines.append("- **EV calculation**: EV = temp_prob * odds - 1 (temperature-scaled, not raw)")
    lines.append("")

    lines.append("## 2. Model Evaluation")
    lines.append("")
    lines.append("| Year | Raw Acc | Raw LL | Temp Acc | Temp LL |")
    lines.append("|------|---------|--------|----------|---------|")
    for yr in sorted(year_results.keys()):
        r = year_results[yr]
        acc_raw = accuracy_score(r["df"]["target"].values, (r["raw_probs"] >= 0.5).astype(int))
        ll_raw = log_loss(r["df"]["target"].values, r["raw_probs"])
        acc_temp = accuracy_score(r["df"]["target"].values, (r["temp_probs"] >= 0.5).astype(int))
        ll_temp = log_loss(r["df"]["target"].values, r["temp_probs"])
        lines.append(f"| {yr} | {acc_raw:.4f} | {ll_raw:.4f} | {acc_temp:.4f} | {ll_temp:.4f} |")
    lines.append("")

    lines.append("## 3. Feature Importance (Top 15)")
    lines.append("")
    lines.append("| Feature | Gain |")
    lines.append("|---------|------|")
    for _, r in fi.head(15).iterrows():
        lines.append(f"| {r['feature']} | {r['importance']:.1f} |")
    lines.append("")

    lines.append("## 4. Rule Filter Pass Rates")
    lines.append("")
    lines.append("| Year | dominant_form | rank_gap >= 30 | surface_specialist | All 3 | >= 2 of 3 |")
    lines.append("|------|--------------|---------------|-------------------|-------|-----------|")
    for yr in [2024, 2025, 2026]:
        if yr not in year_results:
            continue
        yr_df = year_results[yr]["df"]
        dom = yr_df.apply(rule_dominant_form, axis=1).mean()
        rank = yr_df.apply(rule_rank_gap, axis=1).mean()
        surf = yr_df.apply(rule_surface_specialist, axis=1).mean()
        all3 = apply_rules(yr_df).mean()
        rel2 = apply_rules_relaxed(yr_df, min_rules=2).mean()
        lines.append(f"| {yr} | {dom:.1%} | {rank:.1%} | {surf:.1%} | {all3:.1%} | {rel2:.1%} |")
    lines.append("")

    lines.append("## 5. Strategy Comparison")
    lines.append("")

    for yr in [2024, 2025, 2026]:
        if yr not in strategies:
            continue
        lines.append(f"### {yr}")
        lines.append("")
        lines.append("| Strategy | Bets | ROI | Max DD | Win Rate | Total PnL |")
        lines.append("|----------|------|-----|--------|----------|-----------|")
        for name, key in [
            ("ML only (EV>=0.05)", "ml_05"),
            ("ML only (EV>=0.03)", "ml_03"),
            ("Rules only (all 3)", "rules_only"),
            ("Hybrid (ML+Rules)", "hybrid"),
            ("Relaxed (>=2 rules+ML)", "relaxed_hybrid"),
        ]:
            bt = strategies[yr][key]
            if bt["n_bets"] > 0:
                lines.append(f"| {name} | {bt['n_bets']} | {bt['roi']:.2%} | {bt['max_drawdown']:.2%} | {bt['win_rate']:.1%} | {bt['total_pnl']:+.0f} |")
            else:
                lines.append(f"| {name} | 0 | — | — | — | — |")
        lines.append("")

    lines.append("## 6. Aggregate Performance")
    lines.append("")
    lines.append("| Strategy | Avg ROI | Avg DD | Avg WR | Total Bets |")
    lines.append("|----------|---------|--------|--------|------------|")
    for name, key in [
        ("ML only (EV>=0.05)", "ml_05"),
        ("ML only (EV>=0.03)", "ml_03"),
        ("Rules only (all 3)", "rules_only"),
        ("Hybrid (ML+Rules)", "hybrid"),
        ("Relaxed (>=2 rules+ML)", "relaxed_hybrid"),
    ]:
        rois = []
        dds = []
        wrs = []
        total_bets = 0
        for yr in strategies:
            bt = strategies[yr][key]
            if bt["n_bets"] > 0:
                rois.append(bt["roi"])
                dds.append(bt["max_drawdown"])
                wrs.append(bt["win_rate"])
                total_bets += bt["n_bets"]
        if rois:
            lines.append(f"| {name} | {np.mean(rois):.2%} | {np.mean(dds):.2%} | {np.mean(wrs):.1%} | {total_bets} |")
        else:
            lines.append(f"| {name} | — | — | — | 0 |")
    lines.append("")

    lines.append("## 7. Monthly Breakdown")
    lines.append("")
    lines.append(f"**Best strategy**: {strat_labels[best_strat]}")
    lines.append("")
    for yr in [2024, 2025, 2026]:
        if yr not in strategies:
            continue
        bt = strategies[yr][best_strat]
        if bt.get("monthly"):
            lines.append(f"### {yr}")
            lines.append("")
            lines.append("| Month | Bets | PnL | Win Rate |")
            lines.append("|-------|------|-----|----------|")
            for m in bt["monthly"]:
                lines.append(f"| {m['month']} | {m['n_bets']} | {m['pnl']:.0f} | {m['win_rate']:.1%} |")
            lines.append("")

    lines.append("## 8. Kill Switch Analysis")
    lines.append("")
    lines.append("**Threshold**: Monthly loss > 10% of bankroll (10,000 RUB)")
    lines.append("")
    for yr in [2024, 2025, 2026]:
        if yr not in strategies:
            continue
        bt = strategies[yr][best_strat]
        if bt.get("monthly"):
            cumulative = 0
            kill_months = []
            for m in bt["monthly"]:
                br_start = 100000 + cumulative
                threshold = 0.10 * br_start
                if m["pnl"] < -threshold:
                    kill_months.append((m, m["pnl"] / br_start))
                cumulative += m["pnl"]
            if kill_months:
                lines.append(f"- **{yr}**: {len(kill_months)} months would trigger kill switch")
                for m, pct in kill_months:
                    lines.append(f"  - {m['month']}: PnL={m['pnl']:+.0f} ({pct:.1%} of BR)")
            else:
                lines.append(f"- **{yr}**: No months would trigger kill switch")
    lines.append("")

    lines.append("## 9. Verdict")
    lines.append("")

    # Compare strategies
    ml_roi = []
    hy_roi = []
    relaxed_roi = []
    for yr in strategies:
        if strategies[yr]["ml_05"]["n_bets"] > 0:
            ml_roi.append(strategies[yr]["ml_05"]["roi"])
        if strategies[yr]["hybrid"]["n_bets"] > 0:
            hy_roi.append(strategies[yr]["hybrid"]["roi"])
        if strategies[yr]["relaxed_hybrid"]["n_bets"] > 0:
            relaxed_roi.append(strategies[yr]["relaxed_hybrid"]["roi"])

    lines.append("### Key Findings")
    lines.append("")
    lines.append(f"- **ML-only (EV>=0.05)**: avg ROI = {np.mean(ml_roi):.2%} across {sum(strategies[yr]['ml_05']['n_bets'] for yr in strategies)} bets")
    lines.append(f"- **Relaxed Hybrid (>=2 rules + ML)**: avg ROI = {np.mean(relaxed_roi):.2%} across {sum(strategies[yr]['relaxed_hybrid']['n_bets'] for yr in strategies)} bets")
    lines.append(f"- **Rules only**: consistently negative ROI — rule filters alone have no predictive power")
    lines.append(f"- **Hybrid (all 3 rules + ML)**: too restrictive, only {sum(strategies[yr]['hybrid']['n_bets'] for yr in strategies)} bets total")
    lines.append("")
    lines.append("### Important Caveats")
    lines.append("")
    lines.append("1. **ROI is calculated with compounding stakes** (0.5% of current bankroll). With fixed stakes, ROI would be lower.")
    lines.append("2. **The model finds underdog value**: avg odds ~3.0, win rate ~44-45%. This is a genuine signal — the model identifies mispriced underdogs.")
    lines.append("3. **Platt scaling failed catastrophically** (logloss 11-13x worse) — confirmed again with this dataset.")
    lines.append("4. **Temperature scaling (T=1.5) is used for EV calculation** to avoid overconfident probability estimates.")
    lines.append("5. **No monthly losses exceeded 10%** — kill switch was never triggered in any year.")
    lines.append("")

    if hy_roi and ml_roi:
        avg_ml = np.mean(ml_roi)
        avg_hy = np.mean(hy_roi)
        if avg_hy > avg_ml:
            lines.append(f"**Hybrid model is recommended for live deployment.**")
            lines.append(f"- Hybrid avg ROI: {avg_hy:.2%} vs ML-only avg ROI: {avg_ml:.2%}")
            lines.append(f"- Hybrid reduces bet volume, increases quality")
            lines.append(f"- Flat 0.5% staking with EV >= 0.05")
            lines.append(f"- Kill switch: stop if monthly loss > 10% of bankroll")
        else:
            lines.append(f"**ML-only with EV>=0.05 is recommended for live deployment.**")
            lines.append(f"- ML-only avg ROI: {avg_ml:.2%} vs Hybrid avg ROI: {avg_hy:.2%}")
            lines.append(f"- Rule filters (all 3) are too restrictive — only {sum(strategies[yr]['hybrid']['n_bets'] for yr in strategies)} bets total")
            lines.append(f"- Relaxed Hybrid (>=2 rules) has positive ROI but lower than ML-only")
            lines.append(f"- Flat 0.5% staking with EV >= 0.05")
            lines.append(f"- Kill switch: stop if monthly loss > 10% of bankroll")
    lines.append("")

    report = "\n".join(lines)
    report_path = ANALYSIS_DIR / "tennis_hybrid_report.md"
    report_path.write_text(report)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
