#!/usr/bin/env python3
"""
football_ml_predictive_1x2.py — Predictive 1X2 model + value betting evaluation.

Goal: calibrated probabilities + positive ROI after edge filter.
NOT accuracy maximization.

Pipeline:
  1. Load football_features_ml_v1 from SQLite
  2. Feature engineering (odds, margins, cross-market ratios, league/season)
  3. 3-class target (home/draw/away)
  4. Time-based split: train 2019-2023, valid 2024, test 2025-2026
  5. LightGBM with logloss objective
  6. Calibration (isotonic on valid set)
  7. Evaluation: logloss, brier, calibration, ROI with edge filter
  8. Segment reports: all, odds>=1.6, no favorite, balanced
"""

from __future__ import annotations

import json
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).parent / "betagent.db"
OUT_DIR = Path(__file__).parent / "ml_output"
OUT_DIR.mkdir(exist_ok=True)

TRAIN_YEARS = range(2019, 2024)   # 2019-2023
VALID_YEARS = [2024]
TEST_YEARS = [2025, 2026]

# Edge thresholds to sweep
EDGE_THRESHOLDS = [0.00, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10]

# Kelly fraction
KELLY_FRAC = 0.25
BANKROLL = 100_000

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    con = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql("SELECT * FROM football_features_ml_v1", con)
    con.close()
    print(f"Loaded {len(df)} rows, {len(df.columns)} columns")
    return df


# ---------------------------------------------------------------------------
# 2. Feature engineering
# ---------------------------------------------------------------------------

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create ML features from raw odds/probabilities."""
    df = df.copy()

    # --- Target: derive from score ---
    df["target"] = np.where(
        df["home_score"] > df["away_score"], 0,
        np.where(df["home_score"] == df["away_score"], 1, 2)
    )
    df = df.dropna(subset=["target"])
    df["target"] = df["target"].astype(int)

    # --- Date parsing ---
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    df["year"] = df["match_date"].dt.year
    df["month"] = df["match_date"].dt.month
    df = df.dropna(subset=["match_date", "year"])

    # --- Filter: must have 1X2 odds ---
    df = df[df["has_1x2"] == 1].copy()

    # Remove matches where any 1X2 odds is missing or <= 1.0
    for col in ["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]:
        df = df[df[col].notna() & (df[col] > 1.0)]

    print(f"After 1X2 filter: {len(df)} rows")

    # --- Implied probabilities (already in data, but recompute clean) ---
    for suffix in ["home", "draw", "away"]:
        col = f"odds_1x2_{suffix}"
        df[f"imp_{suffix}"] = 1.0 / df[col]

    df["overround"] = df["imp_home"] + df["imp_draw"] + df["imp_away"]
    df["margin"] = df["overround"] - 1.0

    # Fair probabilities (remove margin proportionally)
    df["fair_home"] = df["imp_home"] / df["overround"]
    df["fair_draw"] = df["imp_draw"] / df["overround"]
    df["fair_away"] = df["imp_away"] / df["overround"]

    # --- Market-derived features ---
    # Odds ratios
    df["odds_home_draw_ratio"] = df["odds_1x2_home"] / df["odds_1x2_draw"]
    df["odds_away_draw_ratio"] = df["odds_1x2_away"] / df["odds_1x2_draw"]
    df["odds_home_away_ratio"] = df["odds_1x2_home"] / df["odds_1x2_away"]

    # Favorite strength
    df["min_odd"] = df[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].min(axis=1)
    df["max_odd"] = df[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].max(axis=1)
    df["odd_spread"] = df["max_odd"] - df["min_odd"]
    df["odd_range_ratio"] = df["max_odd"] / df["min_odd"]

    # No clear favorite: min_odd > 2.0
    df["no_clear_favorite"] = (df["min_odd"] > 2.0).astype(int)

    # Balanced match: odd_spread < 1.0
    df["is_balanced"] = (df["odd_spread"] < 1.0).astype(int)

    # --- Total market features ---
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

    # --- BTTS features ---
    mask_btts = df["has_btts"] == 1
    df["btts_yes_odds"] = np.nan
    df["btts_imp_yes"] = np.nan
    df["btts_margin"] = np.nan

    mask_b = mask_btts & df["odds_btts_yes"].notna() & (df["odds_btts_yes"] > 1.0)
    df.loc[mask_b, "btts_yes_odds"] = df.loc[mask_b, "odds_btts_yes"]
    df.loc[mask_b, "btts_imp_yes"] = 1.0 / df.loc[mask_b, "odds_btts_yes"]
    btts_sum = df.loc[mask_b, "btts_imp_yes"] + 1.0 / df.loc[mask_b, "odds_btts_no"]
    df.loc[mask_b, "btts_margin"] = btts_sum - 1.0

    # --- Handicap features ---
    mask_hcp = df["has_handicap"] == 1
    df["hcp_line"] = np.nan
    df["hcp_odds_home"] = np.nan
    df["hcp_odds_away"] = np.nan

    mask_h = mask_hcp & df["odds_hcp_home"].notna() & (df["odds_hcp_home"] > 1.0)
    df.loc[mask_h, "hcp_line"] = df.loc[mask_h, "hcp_line_home"]
    df.loc[mask_h, "hcp_odds_home"] = df.loc[mask_h, "odds_hcp_home"]
    df.loc[mask_h, "hcp_odds_away"] = df.loc[mask_h, "odds_hcp_away"]

    # --- Corners features ---
    mask_cor = df["has_corners"] == 1
    df["corners_imp_home"] = np.nan
    df["corners_imp_draw"] = np.nan
    df["corners_imp_away"] = np.nan
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

    # --- Yellow Cards features ---
    mask_yc = df["has_yellow_cards"] == 1
    df["yc_imp_home"] = np.nan
    df["yc_imp_draw"] = np.nan
    df["yc_imp_away"] = np.nan
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

    # --- Cross-market odds ratios (from report) ---
    for col in ["odds_ratio_home_vs_corners", "odds_ratio_away_vs_corners",
                "odds_ratio_home_vs_yc", "odds_ratio_away_vs_yc",
                "odds_ratio_total_vs_corners", "odds_ratio_total_vs_yc"]:
        if col in df.columns:
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)

    # --- League encoding ---
    df["league"] = df["league"].fillna("Unknown")
    # Top leagues by frequency
    league_counts = df["league"].value_counts()
    top_leagues = set(league_counts[league_counts >= 50].index)
    df["league_encoded"] = df["league"].apply(lambda x: x if x in top_leagues else "Other")
    league_map = {l: i for i, l in enumerate(sorted(df["league_encoded"].unique()))}
    df["league_id"] = df["league_encoded"].map(league_map)

    # Season encoding
    df["season"] = df["season"].fillna("Unknown")
    season_map = {s: i for i, s in enumerate(sorted(df["season"].unique()))}
    df["season_id"] = df["season"].map(season_map)

    # --- Time features ---
    df["day_of_week"] = df["match_date"].dt.dayofweek
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

    print(f"Feature engineering done: {len(df)} rows")
    return df


# ---------------------------------------------------------------------------
# 3. Feature selection
# ---------------------------------------------------------------------------

def get_feature_cols(df: pd.DataFrame) -> list[str]:
    """Select features for the model."""
    base_features = [
        # Core 1X2 odds
        "odds_1x2_home", "odds_1x2_draw", "odds_1x2_away",
        "imp_home", "imp_draw", "imp_away",
        "fair_home", "fair_draw", "fair_away",
        "margin", "overround",

        # Odds ratios
        "odds_home_draw_ratio", "odds_away_draw_ratio", "odds_home_away_ratio",

        # Spread features
        "min_odd", "max_odd", "odd_spread", "odd_range_ratio",
        "no_clear_favorite", "is_balanced",

        # Total market
        "total_odds", "total_line_val", "total_imp_over", "total_imp_under", "total_margin",

        # BTTS
        "btts_yes_odds", "btts_imp_yes", "btts_margin",

        # Handicap
        "hcp_line", "hcp_odds_home", "hcp_odds_away",

        # Corners
        "corners_imp_home", "corners_imp_draw", "corners_imp_away",
        "corners_margin", "corners_total_line_val", "corners_imp_over",

        # Yellow cards
        "yc_imp_home", "yc_imp_draw", "yc_imp_away",
        "yc_margin", "yc_total_line_val", "yc_imp_over",

        # Cross-market ratios
        "odds_ratio_home_vs_corners", "odds_ratio_away_vs_corners",
        "odds_ratio_home_vs_yc", "odds_ratio_away_vs_yc",
        "odds_ratio_total_vs_corners", "odds_ratio_total_vs_yc",

        # League / season
        "league_id", "season_id",

        # Time
        "month", "day_of_week", "is_weekend",
    ]

    # Only keep features that exist and have enough non-null values
    valid = []
    for col in base_features:
        if col in df.columns:
            non_null = df[col].notna().sum()
            if non_null > 100:
                valid.append(col)
            else:
                print(f"  Skipping {col}: only {non_null} non-null values")

    print(f"Using {len(valid)} features: {valid}")
    return valid


# ---------------------------------------------------------------------------
# 4. Train / valid / test split (time-based)
# ---------------------------------------------------------------------------

def time_split(df: pd.DataFrame):
    train = df[df["year"].isin(TRAIN_YEARS)].copy()
    valid = df[df["year"].isin(VALID_YEARS)].copy()
    test = df[df["year"].isin(TEST_YEARS)].copy()

    print(f"Train: {len(train)} ({train['year'].min()}-{train['year'].max()})")
    print(f"Valid: {len(valid)} ({valid['year'].min()}-{valid['year'].max()})")
    print(f"Test:  {len(test)} ({test['year'].min()}-{test['year'].max()})")

    # Check target distribution
    for name, split in [("train", train), ("valid", valid), ("test", test)]:
        dist = split["target"].value_counts().sort_index()
        dist_pct = (dist / len(split) * 100).round(1)
        print(f"  {name} target dist: H={dist_pct.get(0,0)}% D={dist_pct.get(1,0)}% A={dist_pct.get(2,0)}%")

    return train, valid, test


# ---------------------------------------------------------------------------
# 5. Train LightGBM
# ---------------------------------------------------------------------------

def train_model(train: pd.DataFrame, valid: pd.DataFrame, feature_cols: list[str]):
    import lightgbm as lgb

    X_train = train[feature_cols].fillna(-999)
    y_train = train["target"].values
    X_valid = valid[feature_cols].fillna(-999)
    y_valid = valid["target"].values

    # Class weights to handle imbalance
    from sklearn.utils.class_weight import compute_class_weight
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

    print("Training LightGBM...")
    model = lgb.train(
        params,
        train_data,
        num_boost_round=2000,
        valid_sets=[valid_data],
        callbacks=[
            lgb.early_stopping(100),
            lgb.log_evaluation(200),
        ],
    )

    # Feature importance
    importance = pd.DataFrame({
        "feature": feature_cols,
        "importance": model.feature_importance("gain"),
    }).sort_values("importance", ascending=False)
    print("\nTop 15 features by gain:")
    print(importance.head(15).to_string(index=False))

    return model, importance


# ---------------------------------------------------------------------------
# 6. Calibration
# ---------------------------------------------------------------------------

def calibrate_model(model, train: pd.DataFrame, valid: pd.DataFrame, feature_cols: list[str]):
    """Fit isotonic calibration on validation set predictions (per-class Platt scaling)."""
    from sklearn.isotonic import IsotonicRegression

    X_valid = valid[feature_cols].fillna(-999)
    y_valid = valid["target"].values

    # Get raw predictions from model
    raw_preds = model.predict(X_valid)

    # Check if already well-calibrated
    print("\nCalibration check (valid set):")
    for i, name in enumerate(["home", "draw", "away"]):
        brier_before = brier_score_loss((y_valid == i).astype(int), raw_preds[:, i])
        print(f"  {name}: brier={brier_before:.4f}, mean_pred={raw_preds[:, i].mean():.3f}, mean_actual={(y_valid == i).mean():.3f}")

    # Per-class isotonic regression calibration
    calibrators = []
    for i in range(3):
        ir = IsotonicRegression(out_of_bounds="clip")
        ir.fit(raw_preds[:, i], (y_valid == i).astype(float))
        calibrators.append(ir)

    # Verify calibration
    cal_preds = np.column_stack([calibrators[i].predict(raw_preds[:, i]) for i in range(3)])
    # Renormalize
    cal_preds = cal_preds / cal_preds.sum(axis=1, keepdims=True)

    print("\nAfter calibration (valid set):")
    for i, name in enumerate(["home", "draw", "away"]):
        brier_after = brier_score_loss((y_valid == i).astype(int), cal_preds[:, i])
        print(f"  {name}: brier={brier_after:.4f}, mean_pred={cal_preds[:, i].mean():.3f}, mean_actual={(y_valid == i).mean():.3f}")

    return model, calibrators


def predict_calibrated(model, calibrators, X: pd.DataFrame):
    """Get calibrated predictions."""
    raw = model.predict(X)
    cal_preds = np.column_stack([calibrators[i].predict(raw[:, i]) for i in range(3)])
    cal_preds = cal_preds / cal_preds.sum(axis=1, keepdims=True)
    return cal_preds


# ---------------------------------------------------------------------------
# 7. Evaluation
# ---------------------------------------------------------------------------

def evaluate_model(model, calibrators, test: pd.DataFrame, feature_cols: list[str]):
    """Full evaluation on test set."""
    X_test = test[feature_cols].fillna(-999)
    y_test = test["target"].values

    # Predictions
    probs = predict_calibrated(model, calibrators, X_test)
    preds = np.argmax(probs, axis=1)

    # Overall metrics
    logloss = log_loss(y_test, probs)
    print(f"\n{'='*60}")
    print(f"TEST SET EVALUATION")
    print(f"{'='*60}")
    print(f"Matches: {len(test)}")
    print(f"Log Loss: {logloss:.4f}")

    # Brier per class
    for i, name in enumerate(["home", "draw", "away"]):
        brier = brier_score_loss((y_test == i).astype(int), probs[:, i])
        print(f"  Brier {name}: {brier:.4f}")

    # Accuracy
    accuracy = (preds == y_test).mean()
    print(f"Accuracy (argmax): {accuracy:.3f}")

    # Per-class accuracy
    for i, name in enumerate(["home", "draw", "away"]):
        mask = y_test == i
        if mask.sum() > 0:
            acc = (preds[mask] == i).mean()
            print(f"  Accuracy {name}: {acc:.3f} ({mask.sum()} matches)")

    # --- ROI analysis with edge filter ---
    results = analyze_roi(test, probs, feature_cols)

    return {
        "logloss": logloss,
        "accuracy": accuracy,
        "probs": probs,
        "preds": preds,
        "results": results,
    }


def analyze_roi(test: pd.DataFrame, probs: np.ndarray, feature_cols: list[str]):
    """Analyze ROI for different edge thresholds and segments."""
    y_test = test["target"].values
    odds_cols = ["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]
    odds = test[odds_cols].values

    # Market implied probabilities
    imp = 1.0 / odds
    overround = imp.sum(axis=1, keepdims=True)
    fair_market = imp / overround

    # Model edge = model_prob - fair_market_prob
    edges = probs - fair_market

    all_results = {}

    # Segment definitions
    segments = {
        "all_matches": np.ones(len(test), dtype=bool),
        "odds_gte_1.6": np.min(odds, axis=1) >= 1.6,
        "no_clear_favorite": test["min_odd"].values > 2.0,
        "balanced_matches": test["odd_spread"].values < 1.0,
    }

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
            # Bet when model edge > threshold for any outcome
            best_edge = np.max(seg_edges, axis=1)
            bet_mask = best_edge > threshold

            n_bets = bet_mask.sum()
            if n_bets == 0:
                seg_results[f"edge>{threshold:.2f}"] = {
                    "n_bets": 0, "roi": None, "pnl": 0, "hit_rate": None,
                    "avg_odds": None, "avg_edge": None, "kelly_stake_avg": None,
                }
                continue

            # For each bet, pick the outcome with highest edge
            bet_outcomes = np.argmax(seg_edges[bet_mask], axis=1)  # 0,1,2
            bet_odds = seg_odds[bet_mask, bet_outcomes]
            bet_probs = seg_probs[bet_mask, bet_outcomes]
            bet_actual = seg_y[bet_mask]

            # Win/loss
            wins = (bet_outcomes == bet_actual).astype(float)

            # Flat stake ROI
            pnl_flat = (wins * (bet_odds - 1) - (1 - wins)).sum()
            roi_flat = pnl_flat / n_bets * 100
            hit_rate = wins.mean() * 100

            # Kelly quarter stake ROI
            kelly_stakes = np.maximum(0, (bet_probs * bet_odds - 1) / (bet_odds - 1)) * KELLY_FRAC
            kelly_stakes = np.clip(kelly_stakes, 0, 0.10)  # max 10%
            total_staked = kelly_stakes.sum()
            if total_staked > 0:
                pnl_kelly = (wins * kelly_stakes * (bet_odds - 1) - (1 - wins) * kelly_stakes).sum()
                roi_kelly = pnl_kelly / total_staked * 100
            else:
                roi_kelly = 0

            seg_results[f"edge>{threshold:.2f}"] = {
                "n_bets": int(n_bets),
                "roi_flat": round(roi_flat, 2),
                "roi_kelly": round(roi_kelly, 2),
                "pnl_flat": round(pnl_flat, 2),
                "hit_rate": round(hit_rate, 1),
                "avg_odds": round(bet_odds.mean(), 3),
                "avg_edge": round(seg_edges[bet_mask].max(axis=1).mean(), 4),
                "kelly_stake_avg": round(kelly_stakes.mean(), 4),
            }

        all_results[seg_name] = {
            "n_matches": int(n_seg),
            "bets": seg_results,
        }

    return all_results


# ---------------------------------------------------------------------------
# 8. Print reports
# ---------------------------------------------------------------------------

def print_reports(eval_results: dict):
    """Print formatted reports."""
    results = eval_results["results"]

    seg_labels = {
        "all_matches": "ALL MATCHES",
        "odds_gte_1.6": "ODDS >= 1.6",
        "no_clear_favorite": "NO CLEAR FAVORITE",
        "balanced_matches": "BALANCED MATCHES",
    }

    for seg_key, seg_data in results.items():
        label = seg_labels.get(seg_key, seg_key)
        print(f"\n{'='*70}")
        print(f"  SEGMENT: {label}  ({seg_data['n_matches']} matches)")
        print(f"{'='*70}")
        print(f"{'Edge':>8} | {'Bets':>5} | {'ROI_flat':>8} | {'ROI_kelly':>9} | {'Hit%':>6} | {'AvgOdds':>7} | {'AvgEdge':>7} | {'Kelly%':>6}")
        print(f"{'-'*8}-+-{'-'*5}-+-{'-'*8}-+-{'-'*9}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}-+-{'-'*6}")

        for edge_key, bd in seg_data["bets"].items():
            edge_str = edge_key.replace("edge>", "")
            roi_f = f"{bd['roi_flat']:+.1f}%" if bd['roi_flat'] is not None else "N/A"
            roi_k = f"{bd['roi_kelly']:+.1f}%" if bd['roi_kelly'] is not None else "N/A"
            hr = f"{bd['hit_rate']:.1f}" if bd['hit_rate'] is not None else "N/A"
            ao = f"{bd['avg_odds']:.3f}" if bd['avg_odds'] is not None else "N/A"
            ae = f"{bd['avg_edge']:.4f}" if bd['avg_edge'] is not None else "N/A"
            ka = f"{bd['kelly_stake_avg']:.3f}" if bd['kelly_stake_avg'] is not None else "N/A"
            print(f"{edge_str:>8} | {bd['n_bets']:>5} | {roi_f:>8} | {roi_k:>9} | {hr:>6} | {ao:>7} | {ae:>7} | {ka:>6}")


def save_outputs(model, calibrators, importance, test: pd.DataFrame, feature_cols: list[str], eval_results: dict):
    """Save model, predictions, and report to files."""
    import pickle

    # Save model
    with open(OUT_DIR / "model.pkl", "wb") as f:
        pickle.dump({"model": model, "calibrators": calibrators, "feature_cols": feature_cols}, f)

    # Save feature importance
    importance.to_csv(OUT_DIR / "feature_importance.csv", index=False)

    # Save predictions on test set
    X_test = test[feature_cols].fillna(-999)
    probs = predict_calibrated(model, calibrators, X_test)
    preds = np.argmax(probs, axis=1)

    pred_df = test[["match_id", "league", "home_team", "away_team", "match_date",
                     "odds_1x2_home", "odds_1x2_draw", "odds_1x2_away",
                     "target", "min_odd", "odd_spread", "no_clear_favorite", "is_balanced"]].copy()
    pred_df["pred_home"] = probs[:, 0]
    pred_df["pred_draw"] = probs[:, 1]
    pred_df["pred_away"] = probs[:, 2]
    pred_df["prediction"] = preds
    pred_df["correct"] = (preds == test["target"].values).astype(int)

    # Compute edges
    imp = 1.0 / test[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].values
    overround = imp.sum(axis=1, keepdims=True)
    fair = imp / overround
    pred_df["edge_home"] = probs[:, 0] - fair[:, 0]
    pred_df["edge_draw"] = probs[:, 1] - fair[:, 1]
    pred_df["edge_away"] = probs[:, 2] - fair[:, 2]
    pred_df["max_edge"] = np.max(np.column_stack([pred_df["edge_home"], pred_df["edge_draw"], pred_df["edge_away"]]), axis=1)

    pred_df.to_csv(OUT_DIR / "test_predictions.csv", index=False)

    # Save evaluation report as JSON
    report = {
        "logloss": eval_results["logloss"],
        "accuracy": eval_results["accuracy"],
        "n_test": len(test),
        "feature_cols": feature_cols,
        "roi_analysis": eval_results["results"],
    }
    with open(OUT_DIR / "evaluation_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\nSaved outputs to {OUT_DIR}/:")
    print(f"  model.pkl")
    print(f"  feature_importance.csv")
    print(f"  test_predictions.csv")
    print(f"  evaluation_report.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("BETAGENT — Predictive 1X2 ML Model")
    print("=" * 60)

    # Step 1: Load
    print("\n[1/7] Loading data...")
    df = load_data()

    # Step 2: Feature engineering
    print("\n[2/7] Engineering features...")
    df = engineer_features(df)

    # Step 3: Feature selection
    print("\n[3/7] Selecting features...")
    feature_cols = get_feature_cols(df)

    # Step 4: Time split
    print("\n[4/7] Time-based split...")
    train, valid, test = time_split(df)

    # Step 5: Train
    print("\n[5/7] Training model...")
    model, importance = train_model(train, valid, feature_cols)

    # Step 6: Calibrate
    print("\n[6/7] Calibrating...")
    model, calibrators = calibrate_model(model, train, valid, feature_cols)

    # Step 7: Evaluate
    print("\n[7/7] Evaluating on test set...")
    eval_results = evaluate_model(model, calibrators, test, feature_cols)

    # Print reports
    print_reports(eval_results)

    # Save
    save_outputs(model, calibrators, importance, test, feature_cols, eval_results)

    print("\nDone.")


if __name__ == "__main__":
    main()
