#!/usr/bin/env python3
"""
retrain_football_ml_clean_universe.py — A/B test: full dataset vs clean production universe.

MODEL_A_baseline: train on FULL dataset
MODEL_B_clean:    train on production_universe.core only
MODEL_C_expanded: train on production_universe.core + expansion

All models tested on the same production_universe.core test set (2025-2026).
Fixed time split: train 2019-2023, valid 2024, test 2025-2026.
"""

from __future__ import annotations

import json
import pickle
import re
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_class_weight

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent  # /root/betagent
DB_PATH = ROOT / "betagent.db"
OUT_DIR = ROOT / "ml_output"
OUT_DIR.mkdir(exist_ok=True)
ANALYSIS_DIR = Path(__file__).parent
ANALYSIS_DIR.mkdir(exist_ok=True)

UNIVERSE_PATH = ROOT / "config" / "universe.yaml"

TRAIN_YEARS = range(2019, 2024)
VALID_YEARS = [2024]
TEST_YEARS = [2025, 2026]

EDGE_THRESHOLDS = [0.04, 0.05, 0.06, 0.07, 0.08]
KELLY_FRAC = 0.25
BANKROLL = 100_000

# ---------------------------------------------------------------------------
# 1. Load universe
# ---------------------------------------------------------------------------

def load_universe():
    with open(UNIVERSE_PATH) as f:
        cfg = yaml.safe_load(f)
    core = set(cfg["production_universe"]["core"])
    expansion = set(cfg["production_universe"]["expansion"])
    blacklist = cfg.get("blacklist_patterns", [])
    return core, expansion, blacklist


def league_matches_universe(league: str, universe_set: set) -> bool:
    """Check if a league string matches any entry in the universe set.

    The DB league names may have slight variations (case, extra suffixes).
    We do a normalized containment check.
    """
    if not league:
        return False
    norm_league = league.strip().lower().rstrip(".")
    for entry in universe_set:
        norm_entry = entry.strip().lower().rstrip(".")
        # Exact match after normalization
        if norm_league == norm_entry:
            return True
        # Also try: DB league starts with the universe entry
        if norm_league.startswith(norm_entry):
            return True
    return False


def filter_core(df: pd.DataFrame, core_set: set) -> pd.DataFrame:
    return df[df["league"].apply(lambda x: league_matches_universe(x, core_set))].copy()


def filter_core_expanded(df: pd.DataFrame, core_set: set, expansion_set: set) -> pd.DataFrame:
    combined = core_set | expansion_set
    return df[df["league"].apply(lambda x: league_matches_universe(x, combined))].copy()


# ---------------------------------------------------------------------------
# 2. Load data
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    con = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql("SELECT * FROM football_features_ml_v1", con)
    con.close()
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns")
    return df


# ---------------------------------------------------------------------------
# 3. Feature engineering (same as original)
# ---------------------------------------------------------------------------

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["target"] = np.where(
        df["home_score"] > df["away_score"], 0,
        np.where(df["home_score"] == df["away_score"], 1, 2)
    )
    df = df.dropna(subset=["target"])
    df["target"] = df["target"].astype(int)

    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    df["year"] = df["match_date"].dt.year
    df["month"] = df["match_date"].dt.month
    df = df.dropna(subset=["match_date", "year"])

    df = df[df["has_1x2"] == 1].copy()
    for col in ["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]:
        df = df[df[col].notna() & (df[col] > 1.0)]

    print(f"After 1X2 filter: {len(df)} rows")

    for suffix in ["home", "draw", "away"]:
        col = f"odds_1x2_{suffix}"
        df[f"imp_{suffix}"] = 1.0 / df[col]

    df["overround"] = df["imp_home"] + df["imp_draw"] + df["imp_away"]
    df["margin"] = df["overround"] - 1.0
    df["fair_home"] = df["imp_home"] / df["overround"]
    df["fair_draw"] = df["imp_draw"] / df["overround"]
    df["fair_away"] = df["imp_away"] / df["overround"]

    df["odds_home_draw_ratio"] = df["odds_1x2_home"] / df["odds_1x2_draw"]
    df["odds_away_draw_ratio"] = df["odds_1x2_away"] / df["odds_1x2_draw"]
    df["odds_home_away_ratio"] = df["odds_1x2_home"] / df["odds_1x2_away"]

    df["min_odd"] = df[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].min(axis=1)
    df["max_odd"] = df[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].max(axis=1)
    df["odd_spread"] = df["max_odd"] - df["min_odd"]
    df["odd_range_ratio"] = df["max_odd"] / df["min_odd"]
    df["no_clear_favorite"] = (df["min_odd"] > 2.0).astype(int)
    df["is_balanced"] = (df["odd_spread"] < 1.0).astype(int)

    # Total market
    has_total = df["has_total"] == 1
    df["total_odds"] = np.nan
    df["total_line_val"] = np.nan
    df["total_imp_over"] = np.nan
    df["total_imp_under"] = np.nan
    df["total_margin"] = np.nan
    mask = has_total & df["odds_total_over"].notna() & (df["odds_total_over"] > 1.0)
    df.loc[mask, "total_odds"] = df.loc[mask, "odds_total_over"]
    df.loc[mask, "total_line_val"] = df.loc[mask, "total_line"]
    df.loc[mask, "total_imp_over"] = 1.0 / df.loc[mask, "odds_total_over"]
    df.loc[mask, "total_imp_under"] = 1.0 / df.loc[mask, "odds_total_under"]
    tot_sum = df.loc[mask, "total_imp_over"] + df.loc[mask, "total_imp_under"]
    df.loc[mask, "total_margin"] = tot_sum - 1.0

    # BTTS
    mask_btts = df["has_btts"] == 1
    df["btts_yes_odds"] = np.nan
    df["btts_imp_yes"] = np.nan
    df["btts_margin"] = np.nan
    mask_b = mask_btts & df["odds_btts_yes"].notna() & (df["odds_btts_yes"] > 1.0)
    df.loc[mask_b, "btts_yes_odds"] = df.loc[mask_b, "odds_btts_yes"]
    df.loc[mask_b, "btts_imp_yes"] = 1.0 / df.loc[mask_b, "odds_btts_yes"]
    btts_sum = df.loc[mask_b, "btts_imp_yes"] + 1.0 / df.loc[mask_b, "odds_btts_no"]
    df.loc[mask_b, "btts_margin"] = btts_sum - 1.0

    # Handicap
    mask_hcp = df["has_handicap"] == 1
    df["hcp_line"] = np.nan
    df["hcp_odds_home"] = np.nan
    df["hcp_odds_away"] = np.nan
    mask_h = mask_hcp & df["odds_hcp_home"].notna() & (df["odds_hcp_home"] > 1.0)
    df.loc[mask_h, "hcp_line"] = df.loc[mask_h, "hcp_line_home"]
    df.loc[mask_h, "hcp_odds_home"] = df.loc[mask_h, "odds_hcp_home"]
    df.loc[mask_h, "hcp_odds_away"] = df.loc[mask_h, "odds_hcp_away"]

    # Corners
    mask_cor = df["has_corners"] == 1
    for sfx, col in [("home", "odds_corners_home"), ("draw", "odds_corners_draw"), ("away", "odds_corners_away")]:
        df[f"corners_imp_{sfx}"] = np.nan
    df["corners_margin"] = np.nan
    df["corners_total_line_val"] = np.nan
    df["corners_imp_over"] = np.nan
    mask_c = mask_cor & df["odds_corners_home"].notna() & (df["odds_corners_home"] > 1.0)
    for sfx, col in [("home", "odds_corners_home"), ("draw", "odds_corners_draw"), ("away", "odds_corners_away")]:
        m = mask_c & df[col].notna() & (df[col] > 1.0)
        df.loc[m, f"corners_imp_{sfx}"] = 1.0 / df.loc[m, col]
    c_sum = df.loc[mask_c, "corners_imp_home"] + df.loc[mask_c, "corners_imp_draw"] + df.loc[mask_c, "corners_imp_away"]
    df.loc[mask_c, "corners_margin"] = c_sum - 1.0
    df.loc[mask_c, "corners_total_line_val"] = df.loc[mask_c, "corners_total_line"]
    df.loc[mask_c, "corners_imp_over"] = np.where(
        df.loc[mask_c, "odds_corners_over"].notna() & (df.loc[mask_c, "odds_corners_over"] > 1.0),
        1.0 / df.loc[mask_c, "odds_corners_over"], np.nan)

    # Yellow cards
    mask_yc = df["has_yellow_cards"] == 1
    for sfx, col in [("home", "odds_yc_home"), ("draw", "odds_yc_draw"), ("away", "odds_yc_away")]:
        df[f"yc_imp_{sfx}"] = np.nan
    df["yc_margin"] = np.nan
    df["yc_total_line_val"] = np.nan
    df["yc_imp_over"] = np.nan
    mask_y = mask_yc & df["odds_yc_home"].notna() & (df["odds_yc_home"] > 1.0)
    for sfx, col in [("home", "odds_yc_home"), ("draw", "odds_yc_draw"), ("away", "odds_yc_away")]:
        m = mask_y & df[col].notna() & (df[col] > 1.0)
        df.loc[m, f"yc_imp_{sfx}"] = 1.0 / df.loc[m, col]
    y_sum = df.loc[mask_y, "yc_imp_home"] + df.loc[mask_y, "yc_imp_draw"] + df.loc[mask_y, "yc_imp_away"]
    df.loc[mask_y, "yc_margin"] = y_sum - 1.0
    df.loc[mask_y, "yc_total_line_val"] = df.loc[mask_y, "yc_total_line"]
    df.loc[mask_y, "yc_imp_over"] = np.where(
        df.loc[mask_y, "odds_yc_over"].notna() & (df.loc[mask_y, "odds_yc_over"] > 1.0),
        1.0 / df.loc[mask_y, "odds_yc_over"], np.nan)

    # Cross-market ratios
    for col in ["odds_ratio_home_vs_corners", "odds_ratio_away_vs_corners",
                "odds_ratio_home_vs_yc", "odds_ratio_away_vs_yc",
                "odds_ratio_total_vs_corners", "odds_ratio_total_vs_yc"]:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)

    # League encoding — use ALL data for encoding to avoid mismatch
    df["league"] = df["league"].fillna("Unknown")
    league_counts = df["league"].value_counts()
    top_leagues = set(league_counts[league_counts >= 50].index)
    df["league_encoded"] = df["league"].apply(lambda x: x if x in top_leagues else "Other")
    league_map = {l: i for i, l in enumerate(sorted(df["league_encoded"].unique()))}
    df["league_id"] = df["league_encoded"].map(league_map)

    df["season"] = df["season"].fillna("Unknown")
    season_map = {s: i for i, s in enumerate(sorted(df["season"].unique()))}
    df["season_id"] = df["season"].map(season_map)

    df["day_of_week"] = df["match_date"].dt.dayofweek
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

    print(f"Feature engineering done: {len(df)} rows")
    return df


# ---------------------------------------------------------------------------
# 4. Feature selection
# ---------------------------------------------------------------------------

def get_feature_cols(df: pd.DataFrame) -> list[str]:
    base_features = [
        "odds_1x2_home", "odds_1x2_draw", "odds_1x2_away",
        "imp_home", "imp_draw", "imp_away",
        "fair_home", "fair_draw", "fair_away",
        "margin", "overround",
        "odds_home_draw_ratio", "odds_away_draw_ratio", "odds_home_away_ratio",
        "min_odd", "max_odd", "odd_spread", "odd_range_ratio",
        "no_clear_favorite", "is_balanced",
        "total_odds", "total_line_val", "total_imp_over", "total_imp_under", "total_margin",
        "btts_yes_odds", "btts_imp_yes", "btts_margin",
        "hcp_line", "hcp_odds_home", "hcp_odds_away",
        "corners_imp_home", "corners_imp_draw", "corners_imp_away",
        "corners_margin", "corners_total_line_val", "corners_imp_over",
        "yc_imp_home", "yc_imp_draw", "yc_imp_away",
        "yc_margin", "yc_total_line_val", "yc_imp_over",
        "odds_ratio_home_vs_corners", "odds_ratio_away_vs_corners",
        "odds_ratio_home_vs_yc", "odds_ratio_away_vs_yc",
        "odds_ratio_total_vs_corners", "odds_ratio_total_vs_yc",
        "league_id", "season_id",
        "month", "day_of_week", "is_weekend",
    ]
    valid = []
    for col in base_features:
        if col in df.columns:
            non_null = df[col].notna().sum()
            if non_null > 100:
                valid.append(col)
    print(f"Using {len(valid)} features")
    return valid


# ---------------------------------------------------------------------------
# 5. Time split
# ---------------------------------------------------------------------------

def time_split(df: pd.DataFrame):
    train = df[df["year"].isin(TRAIN_YEARS)].copy()
    valid = df[df["year"].isin(VALID_YEARS)].copy()
    test = df[df["year"].isin(TEST_YEARS)].copy()
    print(f"  Train: {len(train)} ({train['year'].min()}-{train['year'].max()})")
    print(f"  Valid: {len(valid)} ({valid['year'].min()}-{valid['year'].max()})")
    print(f"  Test:  {len(test)} ({test['year'].min()}-{test['year'].max()})")
    return train, valid, test


# ---------------------------------------------------------------------------
# 6. Train LightGBM
# ---------------------------------------------------------------------------

def train_model(train: pd.DataFrame, valid: pd.DataFrame, feature_cols: list[str], label: str):
    import lightgbm as lgb

    X_train = train[feature_cols].fillna(-999)
    y_train = train["target"].values
    X_valid = valid[feature_cols].fillna(-999)
    y_valid = valid["target"].values

    cw = compute_class_weight("balanced", classes=np.array([0, 1, 2]), y=y_train)
    sample_weights = np.array([cw[int(y)] for y in y_train])

    train_data = lgb.Dataset(X_train, label=y_train, weight=sample_weights)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)

    params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "learning_rate": 0.03,
        "num_leaves": 63,
        "max_depth": 8,
        "min_child_samples": 200,
        "feature_fraction": 0.7,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l1": 0.5,
        "lambda_l2": 1.0,
        "verbose": -1,
        "seed": 42,
    }

    print(f"\n  Training {label}...")
    model = lgb.train(
        params, train_data, num_boost_round=2000,
        valid_sets=[valid_data],
        callbacks=[lgb.early_stopping(100), lgb.log_evaluation(0)],
    )

    importance = pd.DataFrame({
        "feature": feature_cols,
        "importance": model.feature_importance("gain"),
    }).sort_values("importance", ascending=False)

    n_rounds = model.best_iteration or 2000
    print(f"  Best iteration: {n_rounds}")
    return model, importance


# ---------------------------------------------------------------------------
# 7. Calibration
# ---------------------------------------------------------------------------

def calibrate_model(model, valid: pd.DataFrame, feature_cols: list[str]):
    X_valid = valid[feature_cols].fillna(-999)
    y_valid = valid["target"].values
    raw_preds = model.predict(X_valid)

    calibrators = []
    for i in range(3):
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(raw_preds[:, i], (y_valid == i).astype(float))
        calibrators.append(ir)

    cal_preds = np.column_stack([calibrators[i].predict(raw_preds[:, i]) for i in range(3)])
    cal_preds = cal_preds / cal_preds.sum(axis=1, keepdims=True)

    return model, calibrators


def predict_calibrated(model, calibrators, X: pd.DataFrame):
    raw = model.predict(X)
    cal_preds = np.column_stack([calibrators[i].predict(raw[:, i]) for i in range(3)])
    cal_preds = cal_preds / cal_preds.sum(axis=1, keepdims=True)
    return cal_preds


# ---------------------------------------------------------------------------
# 8. Evaluation
# ---------------------------------------------------------------------------

def evaluate_model(model, calibrators, test: pd.DataFrame, feature_cols: list[str], label: str):
    X_test = test[feature_cols].fillna(-999)
    y_test = test["target"].values
    probs = predict_calibrated(model, calibrators, X_test)
    preds = np.argmax(probs, axis=1)

    logloss = log_loss(y_test, probs)
    accuracy = (preds == y_test).mean()

    per_class = {}
    for i, name in enumerate(["home", "draw", "away"]):
        brier = brier_score_loss((y_test == i).astype(int), probs[:, i])
        acc = (preds[y_test == i] == i).mean() if (y_test == i).sum() > 0 else 0
        per_class[name] = {
            "brier": round(brier, 4),
            "accuracy": round(acc, 4),
            "n_matches": int((y_test == i).sum()),
            "avg_pred": round(probs[:, i].mean(), 4),
            "actual_freq": round((y_test == i).mean(), 4),
        }

    pred_dist = {
        "home_pct": round(probs[:, 0].mean(), 4),
        "draw_pct": round(probs[:, 1].mean(), 4),
        "away_pct": round(probs[:, 2].mean(), 4),
    }

    # Betting analysis
    betting = analyze_betting(test, probs, feature_cols)

    return {
        "label": label,
        "logloss": round(logloss, 4),
        "accuracy": round(accuracy, 4),
        "n_test": len(test),
        "per_class": per_class,
        "pred_dist": pred_dist,
        "betting": betting,
    }


def analyze_betting(test: pd.DataFrame, probs: np.ndarray, feature_cols: list[str]):
    """Betting evaluation with segments and edge thresholds."""
    y_test = test["target"].values
    odds_cols = ["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]
    odds = test[odds_cols].values

    imp = 1.0 / odds
    overround = imp.sum(axis=1, keepdims=True)
    fair_market = imp / overround
    edges = probs - fair_market

    # Segments: balanced, no_clear_favorite (draw excluded)
    segments = {
        "balanced": test["odd_spread"].values < 1.0,
        "no_clear_favorite": test["min_odd"].values > 2.0,
    }

    results = {}
    for seg_name, seg_mask in segments.items():
        n_seg = seg_mask.sum()
        if n_seg < 10:
            continue

        seg_edges = edges[seg_mask]
        seg_odds = odds[seg_mask]
        seg_y = y_test[seg_mask]
        seg_probs = probs[seg_mask]

        seg_results = {}
        for threshold in EDGE_THRESHOLDS:
            best_edge = np.max(seg_edges, axis=1)
            bet_mask = best_edge > threshold

            n_bets = bet_mask.sum()
            if n_bets == 0:
                seg_results[f"edge>{threshold:.2f}"] = {"n_bets": 0}
                continue

            bet_outcomes = np.argmax(seg_edges[bet_mask], axis=1)
            bet_odds = seg_odds[bet_mask, bet_outcomes]
            bet_probs = seg_probs[bet_mask, bet_outcomes]
            bet_actual = seg_y[bet_mask]

            # Exclude draw picks
            no_draw = bet_outcomes != 1
            bet_outcomes = bet_outcomes[no_draw]
            bet_odds = bet_odds[no_draw]
            bet_probs = bet_probs[no_draw]
            bet_actual = bet_actual[no_draw]
            n_bets = len(bet_outcomes)

            if n_bets == 0:
                seg_results[f"edge>{threshold:.2f}"] = {"n_bets": 0}
                continue

            wins = (bet_outcomes == bet_actual).astype(float)

            # Flat ROI
            pnl_flat = (wins * (bet_odds - 1) - (1 - wins)).sum()
            roi_flat = pnl_flat / n_bets * 100
            hit_rate = wins.mean() * 100

            # Kelly
            kelly_stakes = np.maximum(0, (bet_probs * bet_odds - 1) / (bet_odds - 1)) * KELLY_FRAC
            kelly_stakes = np.clip(kelly_stakes, 0, 0.10)
            total_staked = kelly_stakes.sum()
            if total_staked > 0:
                pnl_kelly = (wins * kelly_stakes * (bet_odds - 1) - (1 - wins) * kelly_stakes).sum()
                roi_kelly = pnl_kelly / total_staked * 100
            else:
                roi_kelly = 0
                pnl_kelly = 0

            # Drawdown (cumulative PnL)
            cum_pnl_flat = np.cumsum(wins * (bet_odds - 1) - (1 - wins))
            cum_pnl_kelly = np.cumsum(wins * kelly_stakes * (bet_odds - 1) - (1 - wins) * kelly_stakes)
            max_dd_flat = float(np.max(np.maximum.accumulate(cum_pnl_flat) - cum_pnl_flat)) if len(cum_pnl_flat) > 0 else 0
            max_dd_kelly = float(np.max(np.maximum.accumulate(cum_pnl_kelly) - cum_pnl_kelly)) if len(cum_pnl_kelly) > 0 else 0

            # Losing streak
            losses = (wins == 0).astype(int)
            longest_losing = 0
            cur = 0
            for l in losses:
                if l:
                    cur += 1
                    longest_losing = max(longest_losing, cur)
                else:
                    cur = 0

            seg_results[f"edge>{threshold:.2f}"] = {
                "n_bets": int(n_bets),
                "bets_per_month": round(n_bets / 15.2, 1),
                "roi_flat": round(roi_flat, 2),
                "roi_kelly": round(roi_kelly, 2),
                "hit_rate": round(hit_rate, 1),
                "avg_odds": round(float(bet_odds.mean()), 3),
                "avg_edge": round(float(seg_edges[bet_mask][no_draw].max(axis=1).mean()), 4),
                "max_dd_flat": round(max_dd_flat, 2),
                "max_dd_kelly": round(max_dd_kelly, 2),
                "longest_losing_streak": longest_losing,
            }

        results[seg_name] = {"n_matches": int(n_seg), "bets": seg_results}

    return results


# ---------------------------------------------------------------------------
# 9. Calibration analysis
# ---------------------------------------------------------------------------

def calibration_analysis(test: pd.DataFrame, probs: np.ndarray, label: str):
    """Detailed calibration: avg predicted prob vs actual frequency by decile."""
    y_test = test["target"].values
    results = {}
    for i, name in enumerate(["home", "draw", "away"]):
        actual = (y_test == i).astype(int)
        pred = probs[:, i]

        # Overall
        results[name] = {
            "avg_pred": round(float(pred.mean()), 4),
            "actual_freq": round(float(actual.mean()), 4),
            "calibration_gap": round(float(pred.mean() - actual.mean()), 4),
        }

        # By decile
        deciles = pd.qcut(pred, q=10, labels=False, duplicates="drop")
        by_decile = []
        for d in sorted(set(deciles)):
            mask = deciles == d
            by_decile.append({
                "decile": int(d),
                "avg_pred": round(float(pred[mask].mean()), 4),
                "actual_freq": round(float(actual[mask].mean()), 4),
                "n": int(mask.sum()),
            })
        results[f"{name}_deciles"] = by_decile

    return results


# ---------------------------------------------------------------------------
# 10. Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("BETAGENT — Clean Universe Retraining A/B Test")
    print("=" * 60)

    # Load universe
    core_set, expansion_set, blacklist = load_universe()
    print(f"\nUniverse: {len(core_set)} core, {len(expansion_set)} expansion")

    # Step 1: Load + engineer features (once, on full data)
    print("\n[1/4] Loading and engineering features...")
    df = load_data()
    df = engineer_features(df)
    feature_cols = get_feature_cols(df)

    # Step 2: Create filtered datasets
    print("\n[2/4] Filtering datasets...")
    df_core = filter_core(df, core_set)
    df_expanded = filter_core_expanded(df, core_set, expansion_set)

    print(f"  Full dataset: {len(df)} rows")
    print(f"  Core only:    {len(df_core)} rows")
    print(f"  Core+Expanded: {len(df_expanded)} rows")

    # Step 3: Train 3 models
    print("\n[3/4] Training models...")

    # --- MODEL A: baseline (full data) ---
    train_a, valid_a, test_a = time_split(df)
    model_a, imp_a = train_model(train_a, valid_a, feature_cols, "MODEL_A_baseline (full)")
    model_a, cal_a = calibrate_model(model_a, valid_a, feature_cols)

    # --- MODEL B: clean (core only) ---
    train_b, valid_b, test_b = time_split(df_core)
    model_b, imp_b = train_model(train_b, valid_b, feature_cols, "MODEL_B_clean (core)")
    model_b, cal_b = calibrate_model(model_b, valid_b, feature_cols)

    # --- MODEL C: expanded (core + expansion) ---
    train_c, valid_c, test_c = time_split(df_expanded)
    model_c, imp_c = train_model(train_c, valid_c, feature_cols, "MODEL_C_expanded (core+exp)")
    model_c, cal_c = calibrate_model(model_c, valid_c, feature_cols)

    # Step 4: Evaluate all models on CORE test set
    print("\n[4/4] Evaluating on CORE test set...")

    # For fair comparison, evaluate all models on the SAME test set (core only)
    test_core = test_b.copy()  # core test set

    eval_a = evaluate_model(model_a, cal_a, test_core, feature_cols, "MODEL_A_baseline")
    eval_b = evaluate_model(model_b, cal_b, test_core, feature_cols, "MODEL_B_clean")
    eval_c = evaluate_model(model_c, cal_c, test_core, feature_cols, "MODEL_C_expanded")

    # Also evaluate B and C on their own test sets for reference
    eval_b_own = evaluate_model(model_b, cal_b, test_b, feature_cols, "MODEL_B_clean (own test)")
    eval_c_own = evaluate_model(model_c, cal_c, test_c, feature_cols, "MODEL_C_expanded (own test)")

    # Calibration analysis
    cal_analysis_a = calibration_analysis(test_core, predict_calibrated(model_a, cal_a, test_core[feature_cols].fillna(-999)), "MODEL_A")
    cal_analysis_b = calibration_analysis(test_core, predict_calibrated(model_b, cal_b, test_core[feature_cols].fillna(-999)), "MODEL_B")
    cal_analysis_c = calibration_analysis(test_core, predict_calibrated(model_c, cal_c, test_core[feature_cols].fillna(-999)), "MODEL_C")

    # -----------------------------------------------------------------------
    # Save outputs
    # -----------------------------------------------------------------------

    # Save models
    for name, model, cal in [
        ("model_a_baseline", model_a, cal_a),
        ("model_b_clean", model_b, cal_b),
        ("model_c_expanded", model_c, cal_c),
    ]:
        with open(OUT_DIR / f"{name}.pkl", "wb") as f:
            pickle.dump({"model": model, "calibrators": cal, "feature_cols": feature_cols}, f)

    # Save feature importance
    for name, imp in [("model_a", imp_a), ("model_b", imp_b), ("model_c", imp_c)]:
        imp.to_csv(OUT_DIR / f"{name}_feature_importance.csv", index=False)

    # Save evaluation results
    all_results = {
        "MODEL_A_baseline": eval_a,
        "MODEL_B_clean": eval_b,
        "MODEL_C_expanded": eval_c,
        "MODEL_B_clean_own_test": eval_b_own,
        "MODEL_C_expanded_own_test": eval_c_own,
        "calibration": {
            "MODEL_A": cal_analysis_a,
            "MODEL_B": cal_analysis_b,
            "MODEL_C": cal_analysis_c,
        },
        "train_sizes": {
            "MODEL_A": len(train_a),
            "MODEL_B": len(train_b),
            "MODEL_C": len(train_c),
        },
        "test_sizes": {
            "MODEL_A_on_core": len(test_core),
            "MODEL_B_own": len(test_b),
            "MODEL_C_own": len(test_c),
        },
    }

    with open(OUT_DIR / "clean_retrain_comparison.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # -----------------------------------------------------------------------
    # Print comparison summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY (all evaluated on CORE test set)")
    print("=" * 70)

    print(f"\n{'Metric':<25} | {'MODEL_A (full)':>15} | {'MODEL_B (core)':>15} | {'MODEL_C (core+exp)':>18}")
    print("-" * 85)

    for key in ["logloss", "accuracy"]:
        print(f"{key:<25} | {eval_a[key]:>15} | {eval_b[key]:>15} | {eval_c[key]:>18}")

    print()
    for outcome in ["home", "draw", "away"]:
        for metric in ["brier", "accuracy", "avg_pred", "actual_freq"]:
            val_a = eval_a["per_class"][outcome][metric]
            val_b = eval_b["per_class"][outcome][metric]
            val_c = eval_c["per_class"][outcome][metric]
            print(f"{outcome}.{metric:<20} | {val_a:>15} | {val_b:>15} | {val_c:>18}")

    print()
    # Calibration gaps from calibration analysis
    for outcome in ["home", "draw", "away"]:
        gap_a = cal_analysis_a[outcome]["calibration_gap"]
        gap_b = cal_analysis_b[outcome]["calibration_gap"]
        gap_c = cal_analysis_c[outcome]["calibration_gap"]
        print(f"{outcome}.calibration_gap  | {gap_a:>15} | {gap_b:>15} | {val_c:>18}" if False else f"{outcome}.calibration_gap  | {gap_a:>15} | {gap_b:>15} | {gap_c:>18}")

    print()
    print(f"{'Pred dist':<25} | {eval_a['pred_dist']['home_pct']:.1%}H/{eval_a['pred_dist']['draw_pct']:.1%}D/{eval_a['pred_dist']['away_pct']:.1%}A | {eval_b['pred_dist']['home_pct']:.1%}H/{eval_b['pred_dist']['draw_pct']:.1%}D/{eval_b['pred_dist']['away_pct']:.1%}A | {eval_c['pred_dist']['home_pct']:.1%}H/{eval_c['pred_dist']['draw_pct']:.1%}D/{eval_c['pred_dist']['away_pct']:.1%}A")

    # Betting comparison
    print("\n" + "=" * 70)
    print("BETTING COMPARISON (CORE test set, draw excluded)")
    print("=" * 70)

    for seg_name in ["balanced", "no_clear_favorite"]:
        print(f"\n--- {seg_name.upper()} ---")
        print(f"{'Threshold':>10} | {'Bets':>5} | {'ROI_F%':>7} | {'ROI_K%':>7} | {'HR%':>5} | {'AvgOdds':>7} | {'MaxDD_K%':>8} | {'LoseStrk':>9} | {'Bets/Mo':>7}")
        print("-" * 85)

        for model_label, eval_data in [("A", eval_a), ("B", eval_b), ("C", eval_c)]:
            if seg_name not in eval_data["betting"]:
                continue
            bets = eval_data["betting"][seg_name]["bets"]
            for edge_key, bd in bets.items():
                if bd.get("n_bets", 0) == 0:
                    continue
                edge_str = edge_key.replace("edge>", "")
                print(f"{model_label:>4} {edge_str:>5} | {bd['n_bets']:>5} | {bd['roi_flat']:>+7.1f} | {bd['roi_kelly']:>+7.1f} | {bd['hit_rate']:>5.1f} | {bd['avg_odds']:>7.3f} | {bd['max_dd_kelly']:>8.1f} | {bd['longest_losing_streak']:>9} | {bd['bets_per_month']:>7.1f}")

    print("\nDone. Results saved to ml_output/ and analysis/")


if __name__ == "__main__":
    main()
