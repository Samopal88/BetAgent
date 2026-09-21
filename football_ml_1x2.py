#!/usr/bin/env python3
"""
Football 1X2 predictive model — calibrated probabilities for value betting.

Goal: predict P(home), P(draw), P(away) from market odds features,
then find positive-EV bets by comparing model probabilities vs market implied probs.

NOT optimized for accuracy — optimized for calibration + ROI after edge filter.
"""

import argparse
import json
import logging
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import LabelEncoder
import lightgbm as lgb

warnings.filterwarnings("ignore")

DB_PATH = "/root/betagent/betagent.db"
OUTPUT_DIR = Path("/root/betagent/ml_output")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 1. DATA LOADING
# ──────────────────────────────────────────────
def load_data() -> pd.DataFrame:
    """Load football_features_ml_v1 from SQLite."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM football_features_ml_v1", conn)
    conn.close()
    log.info(f"Loaded {len(df):,} matches, {df.shape[1]} columns")
    return df


# ──────────────────────────────────────────────
# 2. FEATURE ENGINEERING
# ──────────────────────────────────────────────
def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build ML-ready feature matrix from raw features."""

    # --- Target: 1X2 outcome from scores ---
    df["outcome"] = np.where(
        df["home_score"] > df["away_score"], "H",
        np.where(df["home_score"] == df["away_score"], "D", "A"),
    )

    # Drop matches without scores
    df = df.dropna(subset=["home_score", "away_score", "outcome"])

    # --- Date features ---
    df["match_date"] = pd.to_datetime(df["match_date"], errors="coerce")
    df["year"] = df["match_date"].dt.year
    df["month"] = df["match_date"].dt.month
    df["season_year"] = df["match_date"].dt.year  # for time split

    # --- League encoding (target frequency encoding) ---
    league_counts = df["league"].value_counts()
    df["league_freq"] = df["league"].map(league_counts)
    df["league_is_top"] = df["league_freq"] >= 200  # enough data

    # Hash-encode league for LightGBM (categorical)
    df["league_hash"] = pd.factorize(df["league"])[0]

    # --- Market features ---
    # 1X2 implied probabilities (fair, already in data as prob_1x2_*)
    # But we also want margin-normalized (de-biased) probabilities
    df["prob_1x2_home_fair"] = df["prob_1x2_home"] / df["overround_1x2"]
    df["prob_1x2_draw_fair"] = df["prob_1x2_draw"] / df["overround_1x2"]
    df["prob_1x2_away_fair"] = df["prob_1x2_away"] / df["overround_1x2"]

    # Odds themselves (raw market signal)
    # --- Balance / competitiveness features ---
    df["odds_home_away_ratio"] = df["odds_1x2_home"] / df["odds_1x2_away"].replace(0, np.nan)
    df["odds_draw_vs_avg"] = df["odds_1x2_draw"] / ((df["odds_1x2_home"] + df["odds_1x2_away"]) / 2)

    # Favorite strength
    min_odds = df[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].min(axis=1)
    df["min_market_odds"] = min_odds
    df["is_clear_favorite"] = min_odds <= 1.60
    df["favorite_implied_prob"] = 1.0 / min_odds

    # Balanced match: no outcome has implied prob > 40%
    max_imp = df[["prob_1x2_home", "prob_1x2_draw", "prob_1x2_away"]].max(axis=1)
    df["is_balanced"] = max_imp <= 0.40

    # No clear favorite: min odds > 2.0
    df["no_clear_favorite"] = min_odds > 2.0

    # Odds spread (how dispersed are the 3 odds)
    df["odds_spread"] = df[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].std(axis=1)
    df["odds_range"] = (
        df[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].max(axis=1)
        - df[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].min(axis=1)
    )

    # --- Total market features ---
    df["total_line_clean"] = df["total_line"].fillna(2.5)
    df["prob_over_fair"] = df["prob_total_over"] / (df["prob_total_over"] + df["prob_total_under"])
    df["prob_under_fair"] = df["prob_total_under"] / (df["prob_total_over"] + df["prob_total_under"])

    # BTTS features
    df["btts_yes_fair"] = df["prob_btts_yes"] / (df["prob_btts_yes"] + df["prob_btts_no"])

    # Cross-market consistency: does total market agree with 1X2?
    # High-scoring expectation from total should correlate with lower draw prob
    df["total_vs_draw"] = df["prob_total_over"] * df["prob_1x2_draw"]
    df["total_vs_home"] = df["prob_total_over"] * df["prob_1x2_home"]

    # --- Handicap features ---
    df["hcp_line_clean"] = df["hcp_line_home"].fillna(0)
    df["hcp_odds_diff"] = df["odds_hcp_home"] - df["odds_hcp_away"]

    # --- Corner market features ---
    df["corners_home_fair"] = df["prob_corners_home"] / (
        df["prob_corners_home"] + df["prob_corners_draw"] + df["prob_corners_away"]
    ).replace(0, np.nan)
    df["corners_away_fair"] = df["prob_corners_away"] / (
        df["prob_corners_home"] + df["prob_corners_draw"] + df["prob_corners_away"]
    ).replace(0, np.nan)

    # --- Yellow card market features ---
    df["yc_home_fair"] = df["prob_yc_home"] / (
        df["prob_yc_home"] + df["prob_yc_draw"] + df["prob_yc_away"]
    ).replace(0, np.nan)
    df["yc_away_fair"] = df["prob_yc_away"] / (
        df["prob_yc_home"] + df["prob_yc_draw"] + df["prob_yc_away"]
    ).replace(0, np.nan)

    # --- Odds ratio features (already in data, but add derived ones) ---
    df["ratio_home_corners_log"] = np.log1p(df["odds_ratio_home_vs_corners"].fillna(1))
    df["ratio_away_corners_log"] = np.log1p(df["odds_ratio_away_vs_corners"].fillna(1))

    # --- Margin features ---
    df["margin_1x2_pct"] = df["margin_1x2"] * 100
    df["is_sharp_line"] = df["margin_1x2"] < 0.05  # sharp book

    # --- Data availability flags ---
    df["n_markets_available"] = (
        df["has_1x2"] + df["has_total"] + df["has_handicap"] +
        df["has_btts"] + df["has_corners"] + df["has_yellow_cards"]
    )

    return df


# ──────────────────────────────────────────────
# 3. FEATURE SELECTION
# ──────────────────────────────────────────────
def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return list of feature columns for ML."""
    feature_cols = [
        # Raw odds
        "odds_1x2_home", "odds_1x2_draw", "odds_1x2_away",
        # Implied probabilities (raw)
        "prob_1x2_home", "prob_1x2_draw", "prob_1x2_away",
        # Margin / overround
        "margin_1x2", "overround_1x2", "margin_1x2_pct", "is_sharp_line",
        # De-biased probabilities
        "prob_1x2_home_fair", "prob_1x2_draw_fair", "prob_1x2_away_fair",
        # Total market
        "odds_total_over", "odds_total_under", "total_line_clean",
        "prob_total_over", "prob_total_under", "margin_total",
        "prob_over_fair", "prob_under_fair",
        # Handicap
        "odds_hcp_home", "odds_hcp_away", "hcp_line_clean", "hcp_odds_diff",
        # BTTS
        "odds_btts_yes", "odds_btts_no", "prob_btts_yes", "prob_btts_no", "margin_btts",
        "btts_yes_fair",
        # Balance / competitiveness
        "odds_home_away_ratio", "odds_draw_vs_avg",
        "min_market_odds", "is_clear_favorite", "favorite_implied_prob",
        "is_balanced", "no_clear_favorite",
        "odds_spread", "odds_range",
        # Cross-market
        "total_vs_draw", "total_vs_home",
        # Corners
        "odds_corners_home", "odds_corners_draw", "odds_corners_away",
        "odds_corners_over", "odds_corners_under", "corners_total_line",
        "prob_corners_home", "prob_corners_draw", "prob_corners_away",
        "margin_corners_1x2", "prob_corners_over", "prob_corners_under",
        "margin_corners_total",
        "corners_home_fair", "corners_away_fair",
        # Yellow cards
        "odds_yc_home", "odds_yc_draw", "odds_yc_away",
        "odds_yc_over", "odds_yc_under", "yc_total_line",
        "prob_yc_home", "prob_yc_draw", "prob_yc_away",
        "margin_yc_1x2", "prob_yc_over", "prob_yc_under", "margin_yc_total",
        "yc_home_fair", "yc_away_fair",
        # Odds ratios
        "odds_ratio_home_vs_corners", "odds_ratio_away_vs_corners",
        "odds_ratio_home_vs_yc", "odds_ratio_away_vs_yc",
        "odds_ratio_total_vs_corners", "odds_ratio_total_vs_yc",
        "ratio_home_corners_log", "ratio_away_corners_log",
        # League
        "league_freq", "league_is_top",
        # Time
        "month",
        # Data availability
        "n_markets_available",
        "has_btts", "has_corners", "has_yellow_cards",
    ]

    # Filter to columns that actually exist
    available = [c for c in feature_cols if c in df.columns]
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        log.info(f"Missing {len(missing)} features (OK if sparse market): {missing[:5]}...")

    return available


def get_categorical_features() -> list[str]:
    """Categorical features for LightGBM."""
    return ["league_hash", "league_is_top", "is_clear_favorite", "is_balanced",
            "no_clear_favorite", "is_sharp_line",
            "has_btts", "has_corners", "has_yellow_cards"]


# ──────────────────────────────────────────────
# 4. TIME-BASED SPLIT
# ──────────────────────────────────────────────
def time_split(df: pd.DataFrame):
    """
    Split strictly by time:
    - train: 2019-2023
    - valid: 2024
    - test: 2025-2026
    """
    train = df[df["season_year"].between(2019, 2023)].copy()
    valid = df[df["season_year"] == 2024].copy()
    test = df[df["season_year"] >= 2025].copy()

    log.info(f"Train: {len(train):,} ({train['season_year'].min()}-{train['season_year'].max()})")
    log.info(f"Valid: {len(valid):,} ({valid['season_year'].min()}-{valid['season_year'].max()})")
    log.info(f"Test:  {len(test):,} ({test['season_year'].min()}-{test['season_year'].max()})")

    return train, valid, test


# ──────────────────────────────────────────────
# 5. MODEL TRAINING
# ──────────────────────────────────────────────
def train_model(train: pd.DataFrame, valid: pd.DataFrame, feature_cols: list[str],
                cat_features: list[str]):
    """Train LightGBM with calibration focus."""

    le = LabelEncoder()
    y_train = le.fit_transform(train["outcome"])
    y_valid = le.fit_transform(valid["outcome"])

    X_train = train[feature_cols].copy()
    X_valid = valid[feature_cols].copy()

    # Fill NaN with median from train
    for col in feature_cols:
        median_val = X_train[col].median()
        X_train[col] = X_train[col].fillna(median_val)
        X_valid[col] = X_valid[col].fillna(median_val)

    # Filter cat_features to those actually in feature_cols
    cat_feats = [c for c in cat_features if c in feature_cols]

    log.info(f"Training LightGBM: {len(feature_cols)} features, {len(cat_feats)} categorical")
    log.info(f"Train: {len(X_train)}, Valid: {len(X_valid)}")
    log.info(f"Classes: {dict(zip(le.classes_, le.transform(le.classes_)))}")

    # LightGBM params — tuned for logloss (calibration), not accuracy
    params = {
        "objective": "multiclass",
        "num_class": 3,
        "metric": "multi_logloss",
        "learning_rate": 0.03,
        "num_leaves": 31,
        "max_depth": 6,
        "min_child_samples": 200,  # prevent overfitting on small segments
        "feature_fraction": 0.7,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l1": 0.5,
        "lambda_l2": 1.0,
        "verbose": -1,
        "seed": 42,
    }

    train_data = lgb.Dataset(
        X_train, label=y_train,
        categorical_feature=cat_feats,
        free_raw_data=False,
    )
    valid_data = lgb.Dataset(
        X_valid, label=y_valid,
        categorical_feature=cat_feats,
        free_raw_data=False,
        reference=train_data,
    )

    callbacks = [
        lgb.early_stopping(50),
        lgb.log_evaluation(100),
    ]

    model = lgb.train(
        params,
        train_data,
        num_boost_round=2000,
        valid_sets=[valid_data],
        valid_names=["valid"],
        callbacks=callbacks,
    )

    log.info(f"Best iteration: {model.best_iteration}")

    # Manual isotonic calibration on validation set predictions
    # Fit per-class isotonic regression: calibrated_p = isotonic(raw_p)
    log.info("Calibrating probabilities with isotonic regression on validation set...")
    from sklearn.isotonic import IsotonicRegression

    proba_valid = model.predict(X_valid)
    calibrators = []
    for i in range(3):
        ir = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        ir.fit(proba_valid[:, i], (y_valid == i).astype(float))
        calibrators.append(ir)

    def calibrated_predict(X):
        raw = model.predict(X)
        cal = np.column_stack([calibrators[i].predict(raw[:, i]) for i in range(3)])
        # Renormalize to sum to 1
        cal = cal / cal.sum(axis=1, keepdims=True)
        return cal

    return model, calibrated_predict, calibrators, le, X_train.columns.tolist()


# ──────────────────────────────────────────────
# 6. EVALUATION
# ──────────────────────────────────────────────
def evaluate_model(model, calibrated_predict, calibrators, le, feature_cols,
                   test: pd.DataFrame, valid: pd.DataFrame):
    """Full evaluation: calibration, ROI, edge analysis."""

    results = {}

    # ── Prepare test data ──
    X_test = test[feature_cols].copy()
    y_test = le.transform(test["outcome"])

    for col in feature_cols:
        median_val = test[col].median()  # use test median (should be close to train)
        X_test[col] = X_test[col].fillna(median_val)

    # ── Predictions ──
    # Raw model
    proba_raw = model.predict(X_test)
    # Calibrated model
    proba_cal = calibrated_predict(X_test)

    # Market implied probabilities (fair, de-biased)
    market_probs = test[["prob_1x2_home_fair", "prob_1x2_draw_fair", "prob_1x2_away_fair"]].values

    # ── Metrics ──
    for name, proba in [("raw", proba_raw), ("calibrated", proba_cal)]:
        ll = log_loss(y_test, proba)
        brier_per_class = {}
        brier_sum = 0
        for i, cls in enumerate(le.classes_):
            mask = y_test == i
            if mask.sum() > 0:
                brier_per_class[cls] = brier_score_loss(
                    (y_test == i).astype(int), proba[:, i]
                )
                brier_sum += brier_per_class[cls]
        brier = brier_sum / len(le.classes_)  # macro average

        # Accuracy
        preds = np.argmax(proba, axis=1)
        accuracy = (preds == y_test).mean()

        results[f"{name}_logloss"] = round(ll, 6)
        results[f"{name}_brier"] = round(brier, 6)
        results[f"{name}_accuracy"] = round(accuracy, 4)
        results[f"{name}_brier_per_class"] = {k: round(v, 6) for k, v in brier_per_class.items()}

        log.info(f"\n{'='*50}")
        log.info(f"{name.upper()} MODEL METRICS")
        log.info(f"  LogLoss:  {ll:.6f}")
        log.info(f"  Brier:    {brier:.6f}")
        log.info(f"  Accuracy: {accuracy:.4f}")
        log.info(f"  Brier/class: {brier_per_class}")

    # ── Market baseline (for comparison) ──
    # Only evaluate market baseline where all 3 odds are present
    valid_market = ~np.isnan(market_probs).any(axis=1)
    market_probs_clean = market_probs[valid_market]
    y_test_market = y_test[valid_market]

    market_preds = np.argmax(market_probs_clean, axis=1)
    market_accuracy = (market_preds == y_test_market).mean()
    market_ll = log_loss(y_test_market, market_probs_clean)
    market_brier_per_class = {}
    market_brier_sum = 0
    for i, cls in enumerate(le.classes_):
        market_brier_per_class[cls] = brier_score_loss(
            (y_test_market == i).astype(int), market_probs_clean[:, i]
        )
        market_brier_sum += market_brier_per_class[cls]
    market_brier = market_brier_sum / len(le.classes_)
    results["market_logloss"] = round(market_ll, 6)
    results["market_brier"] = round(market_brier, 6)
    results["market_accuracy"] = round(market_accuracy, 4)
    results["market_n_matches"] = int(valid_market.sum())
    log.info(f"\nMARKET BASELINE (n={valid_market.sum():,})")
    log.info(f"  LogLoss:  {market_ll:.6f}")
    log.info(f"  Brier:    {market_brier:.6f}")
    log.info(f"  Accuracy: {market_accuracy:.4f}")

    # ── Calibration analysis ──
    # Compare model probabilities vs actual frequencies in bins
    cal_analysis = {}
    for name, proba in [("raw", proba_raw), ("calibrated", proba_cal)]:
        bin_stats = {}
        for i, cls in enumerate(le.classes_):
            probs_i = proba[:, i]
            # Bin into deciles
            bins = pd.qcut(probs_i, q=10, duplicates="drop")
            bin_data = []
            for b in bins.unique():
                mask = bins == b
                avg_pred = probs_i[mask].mean()
                actual_freq = (y_test[mask] == i).mean()
                n = mask.sum()
                bin_data.append({
                    "bin_center": round(avg_pred, 4),
                    "actual_freq": round(actual_freq, 4),
                    "gap": round(actual_freq - avg_pred, 4),
                    "count": int(n),
                })
            bin_stats[cls] = bin_data
        cal_analysis[name] = bin_stats

    results["calibration_analysis"] = cal_analysis

    # ── ROI / EV analysis ──
    roi_analysis = {}

    # Fill NaN market probs with uniform (1/3) for edge computation
    market_probs_filled = np.where(np.isnan(market_probs), 1/3, market_probs)

    for name, proba in [("raw", proba_raw), ("calibrated", proba_cal)]:
        roi_data = {}

        # For each match, find the best model pick and compute EV vs market
        # Model edge = model_prob - market_implied_prob
        for i, cls in enumerate(le.classes_):
            model_p = proba[:, i]
            market_p = market_probs_filled[:, i]
            odds_col = {"H": "odds_1x2_home", "D": "odds_1x2_draw", "A": "odds_1x2_away"}[cls]
            odds = test[odds_col].values

            edge = model_p - market_p  # model edge over market

            # Overall stats for this outcome
            roi_data[cls] = {
                "n_matches": int(len(model_p)),
                "avg_model_prob": round(float(model_p.mean()), 4),
                "avg_market_prob": round(float(market_p.mean()), 4),
                "avg_edge": round(float(edge.mean()), 4),
                "pct_positive_edge": round(float((edge > 0).mean() * 100), 2),
            }

        # ── Betting simulation: bet when model edge > threshold ──
        for edge_threshold in [0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]:
            # For each match, pick the outcome with highest model probability
            # but only if edge > threshold
            best_outcome_idx = np.argmax(proba, axis=1)
            best_model_p = np.max(proba, axis=1)
            best_market_p = np.take_along_axis(market_probs_filled, best_outcome_idx[:, None], axis=1).flatten()
            best_odds = np.where(
                best_outcome_idx == 0, test["odds_1x2_home"].values,
                np.where(best_outcome_idx == 1, test["odds_1x2_draw"].values,
                         test["odds_1x2_away"].values)
            )

            # Only bet when odds are valid (not NaN)
            valid_odds_mask = ~np.isnan(best_odds)

            edge = best_model_p - best_market_p
            bet_mask = (edge >= edge_threshold) & valid_odds_mask

            n_bets = bet_mask.sum()
            if n_bets == 0:
                roi_data[f"edge>={edge_threshold}"] = {"n_bets": 0}
                continue

            # Compute ROI
            outcomes = y_test[bet_mask]
            picked = best_outcome_idx[bet_mask]
            won = (outcomes == picked).astype(float)
            odds_selected = best_odds[bet_mask]

            total_stake = n_bets  # 1 unit per bet
            total_return = (won * odds_selected).sum()
            roi = (total_return - total_stake) / total_stake
            hit_rate = won.mean()
            avg_odds = odds_selected.mean()
            avg_edge = edge[bet_mask].mean()

            roi_data[f"edge>={edge_threshold}"] = {
                "n_bets": int(n_bets),
                "hit_rate": round(float(hit_rate), 4),
                "avg_odds": round(float(avg_odds), 3),
                "roi": round(float(roi), 4),
                "total_return": round(float(total_return), 2),
                "avg_edge": round(float(avg_edge), 4),
            }

        roi_analysis[name] = roi_data

    results["roi_analysis"] = roi_analysis

    # ── Segment analysis ──
    segments = {}

    segment_defs = {
        "all_matches": np.ones(len(test), dtype=bool),
        "odds_gte_1.6": (
            test[["odds_1x2_home", "odds_1x2_draw", "odds_1x2_away"]].min(axis=1) >= 1.6
        ).values,
        "no_clear_favorite": test["no_clear_favorite"].values,
        "balanced_matches": test["is_balanced"].values,
    }

    for seg_name, seg_mask in segment_defs.items():
        if seg_mask.sum() == 0:
            continue

        seg_data = {}
        for name, proba in [("calibrated", proba_cal)]:
            X_seg = X_test.iloc[seg_mask]
            y_seg = y_test[seg_mask]
            proba_seg = proba[seg_mask]
            market_seg = market_probs[seg_mask]

            ll = log_loss(y_seg, proba_seg)
            brier_seg = 0
            for i in range(3):
                brier_seg += brier_score_loss((y_seg == i).astype(int), proba_seg[:, i])
            brier = brier_seg / 3
            preds = np.argmax(proba_seg, axis=1)
            accuracy = (preds == y_seg).mean()

            seg_data[f"{name}_metrics"] = {
                "n_matches": int(seg_mask.sum()),
                "logloss": round(ll, 6),
                "brier": round(brier, 6),
                "accuracy": round(accuracy, 4),
            }

            # ROI with edge filter
            best_idx = np.argmax(proba_seg, axis=1)
            best_p = np.max(proba_seg, axis=1)
            best_mp = np.take_along_axis(market_seg, best_idx[:, None], axis=1).flatten()
            best_odds = np.where(
                best_idx == 0, test.loc[seg_mask, "odds_1x2_home"].values,
                np.where(best_idx == 1, test.loc[seg_mask, "odds_1x2_draw"].values,
                         test.loc[seg_mask, "odds_1x2_away"].values)
            )

            edge_seg = best_p - best_mp

            for et in [0.03, 0.05, 0.08]:
                bet_m = edge_seg >= et
                n_b = bet_m.sum()
                if n_b > 0:
                    w = (y_seg[bet_m] == best_idx[bet_m]).astype(float)
                    o = best_odds[bet_m]
                    ret = (w * o).sum()
                    roi = (ret - n_b) / n_b
                    seg_data[f"edge>={et}"] = {
                        "n_bets": int(n_b),
                        "hit_rate": round(float(w.mean()), 4),
                        "avg_odds": round(float(o.mean()), 3),
                        "roi": round(float(roi), 4),
                    }
                else:
                    seg_data[f"edge>={et}"] = {"n_bets": 0}

        segments[seg_name] = seg_data

    results["segment_analysis"] = segments

    # ── Feature importance ──
    importance = model.feature_importance(importance_type="gain")
    feat_imp = sorted(
        zip(feature_cols, importance),
        key=lambda x: x[1], reverse=True
    )
    results["feature_importance"] = [
        {"feature": f, "gain": round(float(g), 2)}
        for f, g in feat_imp[:30]
    ]

    return results


# ──────────────────────────────────────────────
# 7. REPORT
# ──────────────────────────────────────────────
def print_report(results: dict):
    """Print human-readable report."""
    print("\n" + "=" * 70)
    print("  FOOTBALL 1X2 MODEL — EVALUATION REPORT")
    print("=" * 70)

    # Model metrics
    print("\n--- Model Metrics (Test Set) ---")
    for metric in ["logloss", "brier", "accuracy"]:
        print(f"\n  {metric.upper()}:")
        for key in results:
            if key.endswith(metric):
                label = key.replace(f"_{metric}", "").replace("_", " ").title()
                print(f"    {label:25s}  {results[key]}")

    # Feature importance
    print("\n--- Top 20 Features (by gain) ---")
    for i, fi in enumerate(results.get("feature_importance", [])[:20], 1):
        print(f"  {i:2d}. {fi['feature']:<40s}  {fi['gain']:>12,.0f}")

    # ROI analysis
    print("\n--- ROI Analysis (Calibrated Model) ---")
    roi_cal = results.get("roi_analysis", {}).get("calibrated", {})
    for key, val in roi_cal.items():
        if key in ["H", "D", "A"]:
            print(f"\n  Outcome {key}:")
            for k, v in val.items():
                print(f"    {k:25s}  {v}")
        else:
            print(f"\n  Edge filter {key}:")
            for k, v in val.items():
                print(f"    {k:25s}  {v}")

    # Segment analysis
    print("\n--- Segment Analysis ---")
    segments = results.get("segment_analysis", {})
    for seg_name, seg_data in segments.items():
        print(f"\n  {'='*50}")
        print(f"  SEGMENT: {seg_name}")
        print(f"  {'='*50}")
        for k, v in seg_data.items():
            if isinstance(v, dict):
                print(f"\n    {k}:")
                for kk, vv in v.items():
                    print(f"      {kk:20s}  {vv}")
            else:
                print(f"    {k:25s}  {v}")

    # Calibration
    print("\n--- Calibration Analysis (Calibrated) ---")
    cal = results.get("calibration_analysis", {}).get("calibrated", {})
    for cls, bins in cal.items():
        print(f"\n  Outcome {cls}:")
        print(f"    {'Pred':>8s}  {'Actual':>8s}  {'Gap':>8s}  {'Count':>8s}")
        for b in bins:
            print(f"    {b['bin_center']:>8.4f}  {b['actual_freq']:>8.4f}  {b['gap']:>8.4f}  {b['count']:>8d}")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--output-dir", default="/root/betagent/ml_output")
    parser.add_argument("--no-calibration", action="store_true",
                        help="Skip isotonic calibration")
    args = parser.parse_args()

    OUTPUT_DIR = Path(args.output_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load
    log.info("Loading data...")
    df = load_data()

    # 2. Feature engineering
    log.info("Engineering features...")
    df = engineer_features(df)

    # 3. Feature columns
    feature_cols = get_feature_columns(df)
    cat_features = get_categorical_features()
    log.info(f"Using {len(feature_cols)} features, {len(cat_features)} categorical")

    # 4. Time split
    log.info("Time-based split...")
    train, valid, test = time_split(df)

    # 5. Train
    log.info("Training model...")
    model, calibrated_predict, calibrators, le, final_features = train_model(
        train, valid, feature_cols, cat_features
    )

    # 6. Evaluate
    log.info("Evaluating model...")
    results = evaluate_model(model, calibrated_predict, calibrators, le, final_features, test, valid)

    # 7. Report
    print_report(results)

    # 8. Save
    report_path = OUTPUT_DIR / "ml_1x2_report.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    log.info(f"\nReport saved to {report_path}")

    # Save model metadata
    meta = {
        "feature_columns": final_features,
        "categorical_features": [c for c in cat_features if c in final_features],
        "classes": le.classes_.tolist(),
        "n_train": len(train),
        "n_valid": len(valid),
        "n_test": len(test),
    }
    meta_path = OUTPUT_DIR / "ml_1x2_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    log.info(f"Model metadata saved to {meta_path}")


if __name__ == "__main__":
    main()
