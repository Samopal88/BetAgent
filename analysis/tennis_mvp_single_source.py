#!/usr/bin/env python3
"""
Tennis ML MVP — Single-Source Baseline
=======================================
Source: tennis_data_odds table only (betagent.db)
No Betz, no mapping files, no multi-source joins.
Only English names, only this table.

Goal: answer "can single-source tennis winner ML work?"
"""

import sqlite3
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, brier_score_loss, accuracy_score
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import LabelEncoder
import lightgbm as lgb

warnings.filterwarnings("ignore")

DB_PATH = Path(__file__).resolve().parent.parent / "betagent.db"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ANALYSIS_DIR = Path(__file__).resolve().parent

DATA_DIR.mkdir(exist_ok=True)

# ============================================================
# 1. LOAD DATA
# ============================================================

def load_data():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql("SELECT * FROM tennis_data_odds", conn)
    conn.close()
    print(f"Loaded {len(df)} rows from tennis_data_odds")
    return df


# ============================================================
# 2. FEATURE ENGINEERING
# ============================================================

def build_features(df):
    """Build features from raw tennis_data_odds columns."""

    # --- Target: did the winner win? (always 1 for the winner row) ---
    # We need to restructure to match-level: each match = 1 row
    # with features for both players, target = 1 if player1 wins

    # Drop rows with no odds at all
    df = df.dropna(subset=["b365_winner", "b365_loser", "ps_winner", "ps_loser"], how="all")

    # Use b365 as primary, ps as fallback
    df["odds_winner"] = df["b365_winner"].fillna(df["ps_winner"])
    df["odds_loser"] = df["b365_loser"].fillna(df["ps_loser"])

    # Drop rows still missing odds
    mask = df["odds_winner"].notna() & df["odds_loser"].notna()
    df = df[mask].copy()
    print(f"After dropping no-odds rows: {len(df)}")

    # Implied probabilities (raw, before overround adjustment)
    df["imp_winner"] = 1.0 / df["odds_winner"]
    df["imp_loser"] = 1.0 / df["odds_loser"]
    df["overround"] = df["imp_winner"] + df["imp_loser"]

    # Fair probabilities (overround-adjusted)
    df["fair_winner"] = df["imp_winner"] / df["overround"]
    df["fair_loser"] = df["imp_loser"] / df["overround"]

    # Favorite flag: winner is favorite if fair_winner > 0.5
    df["winner_is_favorite"] = (df["fair_winner"] > 0.5).astype(int)

    # Rank difference (positive = winner had better rank i.e. lower number)
    df["rank_diff"] = df["l_rank"] - df["w_rank"]  # positive means winner ranked better
    df["abs_rank_diff"] = df["rank_diff"].abs()

    # Log rank (ranks are heavy-tailed)
    df["log_w_rank"] = np.log1p(df["w_rank"])
    df["log_l_rank"] = np.log1p(df["l_rank"])

    # Rank points proxy: use inverse rank
    df["w_rank_inv"] = 1.0 / (df["w_rank"] + 1)
    df["l_rank_inv"] = 1.0 / (df["l_rank"] + 1)

    # Odds ratio
    df["odds_ratio"] = df["odds_loser"] / df["odds_winner"]
    df["log_odds_ratio"] = np.log(df["odds_ratio"])

    # Surface encoding
    surface_map = {"Hard": 0, "Clay": 1, "Grass": 2}
    df["surface_code"] = df["surface"].map(surface_map).fillna(-1).astype(int)

    # Round encoding (progressive)
    round_order = [
        "Round Robin", "1st Round", "2nd Round", "3rd Round",
        "4th Round", "Quarterfinals", "Semifinals", "The Final"
    ]
    round_map = {r: i for i, r in enumerate(round_order)}
    df["round_code"] = df["round"].map(round_map).fillna(-1).astype(int)

    # Best of
    df["best_of"] = df["best_of"].fillna(3).astype(int)

    # Tour encoding
    df["is_atp"] = (df["tour"] == "ATP").astype(int)

    # Tournament frequency (how often does this tournament appear?)
    tour_freq = df["tournament"].value_counts()
    df["tournament_freq"] = df["tournament"].map(tour_freq)

    # Year as feature
    df["year"] = df["year"].astype(int)

    # NOTE: set_gap is EXCLUDED — it's post-match and leaks the outcome.
    # We keep has_score as a data-quality flag only.

    return df


def build_match_rows(df):
    """
    Convert winner-centric rows to match-centric rows.
    Each match becomes 2 rows: one from winner perspective, one from loser perspective.
    Target = 1 if the focal player wins.
    This is the standard format for binary classification in sports ML.
    """
    # Row for the winner (target=1)
    winner_rows = pd.DataFrame({
        "match_key": df.index,
        "year": df["year"],
        "tour": df["tour"],
        "tournament": df["tournament"],
        "surface": df["surface"],
        "surface_code": df["surface_code"],
        "round": df["round"],
        "round_code": df["round_code"],
        "best_of": df["best_of"],
        "player_rank": df["w_rank"],
        "opponent_rank": df["l_rank"],
        "log_player_rank": np.log1p(df["w_rank"]),
        "log_opponent_rank": np.log1p(df["l_rank"]),
        "rank_diff": df["l_rank"] - df["w_rank"],  # positive = player ranked better
        "player_rank_inv": 1.0 / (df["w_rank"] + 1),
        "opponent_rank_inv": 1.0 / (df["l_rank"] + 1),
        "odds_player": df["odds_winner"],
        "odds_opponent": df["odds_loser"],
        "imp_player": df["imp_winner"],
        "imp_opponent": df["imp_loser"],
        "overround": df["overround"],
        "fair_player": df["fair_winner"],
        "fair_opponent": df["fair_loser"],
        "odds_ratio": df["odds_loser"] / df["odds_winner"],
        "log_odds_ratio": np.log(df["odds_ratio"] / 1.0),
        "is_atp": df["is_atp"],
        "tournament_freq": df["tournament_freq"],
        "target": 1,
    })

    # Row for the loser (target=0)
    loser_rows = pd.DataFrame({
        "match_key": df.index,
        "year": df["year"],
        "tour": df["tour"],
        "tournament": df["tournament"],
        "surface": df["surface"],
        "surface_code": df["surface_code"],
        "round": df["round"],
        "round_code": df["round_code"],
        "best_of": df["best_of"],
        "player_rank": df["l_rank"],
        "opponent_rank": df["w_rank"],
        "log_player_rank": np.log1p(df["l_rank"]),
        "log_opponent_rank": np.log1p(df["w_rank"]),
        "rank_diff": df["w_rank"] - df["l_rank"],  # negative = player ranked worse
        "player_rank_inv": 1.0 / (df["l_rank"] + 1),
        "opponent_rank_inv": 1.0 / (df["w_rank"] + 1),
        "odds_player": df["odds_loser"],
        "odds_opponent": df["odds_winner"],
        "imp_player": df["imp_loser"],
        "imp_opponent": df["imp_winner"],
        "overround": df["overround"],
        "fair_player": df["fair_loser"],
        "fair_opponent": df["fair_winner"],
        "odds_ratio": df["odds_winner"] / df["odds_loser"],
        "log_odds_ratio": np.log(df["odds_winner"] / df["odds_loser"]),
        "is_atp": df["is_atp"],
        "tournament_freq": df["tournament_freq"],
        "target": 0,
    })

    match_df = pd.concat([winner_rows, loser_rows], ignore_index=True)
    # Shuffle to mix winner/loser rows
    match_df = match_df.sample(frac=1, random_state=42).reset_index(drop=True)
    print(f"Match-level rows: {len(match_df)} ({match_df['target'].mean():.3f} win rate)")
    return match_df


# ============================================================
# 3. TIME SPLIT
# ============================================================

def time_split(df):
    """Split by year: train=2021-2023, val=2024, test=2025, ood=2026."""
    train = df[df["year"].isin([2021, 2022, 2023])].copy()
    val = df[df["year"] == 2024].copy()
    test = df[df["year"] == 2025].copy()
    ood = df[df["year"] == 2026].copy()

    print(f"\nTime split:")
    print(f"  Train (2021-2023): {len(train)}")
    print(f"  Val   (2024):      {len(val)}")
    print(f"  Test  (2025):      {len(test)}")
    print(f"  OOD   (2026):      {len(ood)}")

    return train, val, test, ood


# ============================================================
# 4. MODEL TRAINING
# ============================================================

FEATURE_COLS = [
    "surface_code", "round_code", "best_of",
    "log_player_rank", "log_opponent_rank",
    "rank_diff", "player_rank_inv", "opponent_rank_inv",
    "odds_player", "odds_opponent",
    "imp_player", "imp_opponent",
    "overround", "fair_player", "fair_opponent",
    "odds_ratio", "log_odds_ratio",
    "is_atp", "tournament_freq",
]

TARGET_COL = "target"


def train_lgbm(train, val):
    """Train LightGBM with early stopping on validation set."""
    X_train = train[FEATURE_COLS].values
    y_train = train[TARGET_COL].values
    X_val = val[FEATURE_COLS].values
    y_val = val[TARGET_COL].values

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "seed": 42,
        "min_child_samples": 50,
        "reg_alpha": 0.1,
        "reg_lambda": 0.1,
    }

    train_data = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_COLS)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data, feature_name=FEATURE_COLS)

    model = lgb.train(
        params,
        train_data,
        num_boost_round=2000,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(100)],
    )

    return model


def train_calibrated(model, train, val):
    """Wrap model with isotonic calibration on validation set."""
    # Use a subset for calibration to avoid overfitting
    X_val = val[FEATURE_COLS].values
    y_val = val[TARGET_COL].values

    # LightGBM doesn't support sklearn calibration directly via CalibratedClassifierCV
    # So we'll do manual Platt scaling (sigmoid calibration)
    val_probs = model.predict(X_val)

    # Simple sigmoid calibration: fit logistic on val predictions
    from sklearn.linear_model import LogisticRegression
    calibrator = LogisticRegression(C=1.0, solver="lbfgs")
    calibrator.fit(val_probs.reshape(-1, 1), y_val)

    return calibrator


def predict_with_calibration(model, calibrator, X):
    """Predict with calibration."""
    raw_probs = model.predict(X)
    cal_probs = calibrator.predict_proba(raw_probs.reshape(-1, 1))[:, 1]
    return raw_probs, cal_probs


# ============================================================
# 5. EVALUATION
# ============================================================

def evaluate(model, calibrator, df, label=""):
    """Evaluate model on a dataset."""
    if len(df) == 0:
        print(f"  {label}: empty")
        return {}

    X = df[FEATURE_COLS].values
    y = df[TARGET_COL].values

    raw_probs, cal_probs = predict_with_calibration(model, calibrator, X)

    # Accuracy at 0.5 threshold
    raw_acc = accuracy_score(y, (raw_probs >= 0.5).astype(int))
    cal_acc = accuracy_score(y, (cal_probs >= 0.5).astype(int))

    # Log loss
    raw_ll = log_loss(y, raw_probs)
    cal_ll = log_loss(y, cal_probs)

    # Brier score
    raw_brier = brier_score_loss(y, raw_probs)
    cal_brier = brier_score_loss(y, cal_probs)

    print(f"\n  {label} (n={len(df)}):")
    print(f"    Raw:  acc={raw_acc:.4f}  logloss={raw_ll:.4f}  brier={raw_brier:.4f}")
    print(f"    Cal:  acc={cal_acc:.4f}  logloss={cal_ll:.4f}  brier={cal_brier:.4f}")

    return {
        "label": label,
        "n": len(df),
        "raw_accuracy": round(raw_acc, 4),
        "raw_logloss": round(raw_ll, 4),
        "raw_brier": round(raw_brier, 4),
        "cal_accuracy": round(cal_acc, 4),
        "cal_logloss": round(cal_ll, 4),
        "cal_brier": round(cal_brier, 4),
    }


def calibration_report(df, model, calibrator, label=""):
    """Check calibration quality by decile bins."""
    if len(df) == 0:
        return

    X = df[FEATURE_COLS].values
    y = df[TARGET_COL].values
    _, cal_probs = predict_with_calibration(model, calibrator, X)

    df_check = df[["target"]].copy()
    df_check["pred"] = cal_probs
    df_check["bin"] = pd.qcut(df_check["pred"], q=10, duplicates="drop")

    bins = df_check.groupby("bin").agg(
        count=("target", "size"),
        avg_pred=("pred", "mean"),
        avg_actual=("target", "mean"),
    ).reset_index()

    print(f"\n  Calibration bins ({label}):")
    for _, row in bins.iterrows():
        print(f"    bin {str(row['bin']):30s}  n={row['count']:5d}  pred={row['avg_pred']:.3f}  actual={row['avg_actual']:.3f}")


# ============================================================
# 6. BETTING BACKTEST
# ============================================================

def backtest_betting(df, model, calibrator, label="", ev_threshold=0.03, stake_type="flat"):
    """
    Simulate betting on model predictions.

    stake_type: 'flat' (1 unit per bet) or 'kelly_quarter'
    ev_threshold: minimum EV to place bet
    """
    if len(df) == 0:
        print(f"  {label} backtest: empty")
        return {}

    X = df[FEATURE_COLS].values
    y = df[TARGET_COL].values
    odds = df["odds_player"].values
    _, cal_probs = predict_with_calibration(model, calibrator, X)

    # EV = p * odds - 1
    ev = cal_probs * odds - 1

    # Filter by EV threshold
    mask = ev >= ev_threshold
    n_bets = mask.sum()

    if n_bets == 0:
        print(f"  {label} backtest (EV>={ev_threshold}, {stake_type}): 0 bets")
        return {"label": label, "n_bets": 0, "ev_threshold": ev_threshold, "stake_type": stake_type}

    bet_outcomes = y[mask]
    bet_odds = odds[mask]
    bet_ev = ev[mask]
    bet_probs = cal_probs[mask]

    if stake_type == "flat":
        stakes = np.ones(n_bets)
    else:
        # Kelly quarter: k = (p*o - 1) / (o - 1) * 0.25
        kelly = (bet_probs * bet_odds - 1) / (bet_odds - 1) * 0.25
        kelly = np.clip(kelly, 0.01, 0.10)  # cap at 10%
        stakes = kelly

    # P&L: win = stake * (odds - 1), loss = -stake
    pnl = np.where(bet_outcomes == 1, stakes * (bet_odds - 1), -stakes)
    total_pnl = pnl.sum()
    roi = total_pnl / stakes.sum() if stakes.sum() > 0 else 0

    wins = (bet_outcomes == 1).sum()
    hit_rate = wins / n_bets

    # Max drawdown
    cum_pnl = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum_pnl)
    drawdown = cum_pnl - peak
    max_dd = drawdown.min()

    print(f"  {label} backtest (EV>={ev_threshold}, {stake_type}):")
    print(f"    Bets: {n_bets}  Hit rate: {hit_rate:.3f}  ROI: {roi:.4f}  PnL: {total_pnl:.2f}  MaxDD: {max_dd:.2f}")

    return {
        "label": label,
        "n_bets": int(n_bets),
        "ev_threshold": ev_threshold,
        "stake_type": stake_type,
        "hit_rate": round(hit_rate, 4),
        "roi": round(roi, 4),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "avg_odds": round(bet_odds.mean(), 3),
        "avg_ev": round(bet_ev.mean(), 4),
    }


def backtest_ev_grid(df, model, calibrator, label=""):
    """Run backtest across EV threshold grid."""
    results = []
    for ev_thresh in [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10]:
        for stake in ["flat", "kelly_quarter"]:
            r = backtest_betting(df, model, calibrator,
                                 label=f"{label}",
                                 ev_threshold=ev_thresh,
                                 stake_type=stake)
            r["ev_threshold"] = ev_thresh
            r["stake_type"] = stake
            results.append(r)
    return results


# ============================================================
# 7. FEATURE IMPORTANCE
# ============================================================

def feature_importance(model):
    """Get feature importance from LightGBM."""
    imp = model.feature_importance(importance_type="gain")
    fi = pd.DataFrame({
        "feature": FEATURE_COLS,
        "importance": imp,
    }).sort_values("importance", ascending=False)
    return fi


# ============================================================
# 8. REPORT
# ============================================================

def generate_report(eval_results, backtest_results, fi_df, cal_results, ood_results):
    """Generate markdown report."""
    lines = []
    lines.append("# Tennis ML MVP — Single-Source Baseline Report")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append("- **Source**: `tennis_data_odds` table only (betagent.db)")
    lines.append("- **No Betz, no mapping files, no multi-source joins**")
    lines.append("- **Target**: match winner (binary classification)")
    lines.append("- **Model**: LightGBM + logistic calibration")
    lines.append("- **Split**: train=2021-2023, val=2024, test=2025, OOD=2026")
    lines.append("")

    lines.append("## Data Summary")
    lines.append("")
    for r in eval_results:
        lines.append(f"- {r['label']}: {r['n']} rows")
    lines.append("")

    lines.append("## Model Performance")
    lines.append("")
    lines.append("| Split | Accuracy | LogLoss | Brier |")
    lines.append("|-------|----------|---------|-------|")
    for r in eval_results:
        lines.append(
            f"| {r['label']} | {r['cal_accuracy']:.4f} | {r['cal_logloss']:.4f} | {r['cal_brier']:.4f} |"
        )
    lines.append("")

    lines.append("## Calibration Check (Test Set)")
    lines.append("")
    if cal_results:
        lines.append("| Bin | Count | Avg Pred | Avg Actual |")
        lines.append("|-----|-------|----------|------------|")
        for row in cal_results:
            lines.append(
                f"| {row['bin']} | {row['count']} | {row['avg_pred']:.3f} | {row['avg_actual']:.3f} |"
            )
    lines.append("")

    lines.append("## Feature Importance (Top 15)")
    lines.append("")
    lines.append("| Feature | Importance |")
    lines.append("|---------|------------|")
    for _, row in fi_df.head(15).iterrows():
        lines.append(f"| {row['feature']} | {row['importance']:.1f} |")
    lines.append("")

    lines.append("## Betting Backtest — Test Set (2025)")
    lines.append("")
    lines.append("| EV Thresh | Stake | Bets | Hit Rate | ROI | PnL | MaxDD | Avg Odds |")
    lines.append("|-----------|-------|------|----------|-----|-----|-------|----------|")
    test_bt = [r for r in backtest_results if r.get("label", "").startswith("Test")]
    for r in test_bt:
        lines.append(
            f"| {r['ev_threshold']:.2f} | {r['stake_type']} | {r['n_bets']} | "
            f"{r.get('hit_rate', 0):.3f} | {r.get('roi', 0):.4f} | "
            f"{r.get('total_pnl', 0):.2f} | {r.get('max_drawdown', 0):.2f} | "
            f"{r.get('avg_odds', 0):.3f} |"
        )
    lines.append("")

    lines.append("## Betting Backtest — OOD (2026)")
    lines.append("")
    lines.append("| EV Thresh | Stake | Bets | Hit Rate | ROI | PnL | MaxDD | Avg Odds |")
    lines.append("|-----------|-------|------|----------|-----|-----|-------|----------|")
    ood_bt = [r for r in backtest_results if r.get("label", "").startswith("OOD")]
    for r in ood_bt:
        lines.append(
            f"| {r['ev_threshold']:.2f} | {r['stake_type']} | {r['n_bets']} | "
            f"{r.get('hit_rate', 0):.3f} | {r.get('roi', 0):.4f} | "
            f"{r.get('total_pnl', 0):.2f} | {r.get('max_drawdown', 0):.2f} | "
            f"{r.get('avg_odds', 0):.3f} |"
        )
    lines.append("")

    lines.append("## Conclusion")
    lines.append("")

    # Determine conclusion from results
    test_roi = max([r.get("roi", -1) for r in test_bt if r.get("n_bets", 0) > 50], default=-1)
    ood_roi = max([r.get("roi", -1) for r in ood_bt if r.get("n_bets", 0) > 20], default=-1)
    test_acc = next((r["cal_accuracy"] for r in eval_results if r["label"] == "Test (2025)"), 0)

    lines.append(f"- **Test accuracy**: {test_acc:.4f}")
    lines.append(f"- **Best test ROI** (EV-filtered): {test_roi:.4f}")
    lines.append(f"- **Best OOD ROI**: {ood_roi:.4f}")
    lines.append("")

    if test_roi > 0.03 and ood_roi > 0:
        lines.append("### Verdict: PROMISING")
        lines.append("")
        lines.append("Single-source tennis ML shows positive ROI even on a simplified dataset.")
        lines.append("The model finds edge in the odds market using only rank, surface, round, and odds features.")
        lines.append("Further enrichment (form, H2H, injuries) could improve results.")
    elif test_roi > 0:
        lines.append("### Verdict: MARGINAL")
        lines.append("")
        lines.append("Single-source tennis ML shows some edge but ROI is thin.")
        lines.append("The market is efficient; rank + odds alone give limited advantage.")
        lines.append("Adding form data, serve/return stats, and fatigue metrics would be needed for robust edge.")
    else:
        lines.append("### Verdict: NOT VIABLE (single-source only)")
        lines.append("")
        lines.append("Single-source tennis ML does not produce positive ROI.")
        lines.append("The bookmaker odds already fully incorporate rank and surface information.")
        lines.append("A competitive model would need richer features: serve/return stats, fatigue, weather, H2H.")
    lines.append("")

    report = "\n".join(lines)

    report_path = ANALYSIS_DIR / "tennis_mvp_single_source_report.md"
    report_path.write_text(report)
    print(f"\nReport saved: {report_path}")

    return report


# ============================================================
# 9. MAIN
# ============================================================

def main():
    print("=" * 60)
    print("Tennis ML MVP — Single-Source Baseline")
    print("=" * 60)

    # 1. Load
    df = load_data()

    # 2. Features
    df = build_features(df)

    # 3. Match-level rows
    df = build_match_rows(df)

    # 4. Save dataset
    csv_path = DATA_DIR / "tennis_mvp_single_source.csv"
    df.to_csv(str(csv_path), index=False)
    print(f"\nDataset saved: {csv_path} ({len(df)} rows, {len(FEATURE_COLS)} features)")

    # 5. Time split
    train, val, test, ood = time_split(df)

    # 6. Train
    print("\n--- Training LightGBM ---")
    model = train_lgbm(train, val)

    # 7. Calibrate
    print("\n--- Calibrating ---")
    calibrator = train_calibrated(model, train, val)

    # 8. Evaluate
    print("\n--- Evaluation ---")
    eval_results = []
    for split, label in [(train, "Train (2021-2023)"), (val, "Val (2024)"),
                          (test, "Test (2025)"), (ood, "OOD (2026)")]:
        r = evaluate(model, calibrator, split, label=label)
        if r:
            eval_results.append(r)

    # 9. Calibration report for test
    print("\n--- Calibration Report (Test) ---")
    if len(test) > 0:
        X_test = test[FEATURE_COLS].values
        y_test = test[TARGET_COL].values
        _, cal_probs = predict_with_calibration(model, calibrator, X_test)
        df_check = test[["target"]].copy()
        df_check["pred"] = cal_probs
        try:
            df_check["bin"] = pd.qcut(df_check["pred"], q=10, duplicates="drop")
        except ValueError:
            df_check["bin"] = pd.cut(df_check["pred"], bins=10)
        cal_bins = df_check.groupby("bin").agg(
            count=("target", "size"),
            avg_pred=("pred", "mean"),
            avg_actual=("target", "mean"),
        ).reset_index()
        cal_results = cal_bins.to_dict("records")
        for row in cal_results:
            print(f"    {str(row['bin']):30s}  n={row['count']:5d}  pred={row['avg_pred']:.3f}  actual={row['avg_actual']:.3f}")
    else:
        cal_results = []

    # 10. Feature importance
    fi_df = feature_importance(model)
    print("\n--- Feature Importance (Top 10) ---")
    for _, row in fi_df.head(10).iterrows():
        print(f"  {row['feature']:25s}  {row['importance']:.1f}")

    # 11. Betting backtest — EV grid
    print("\n--- Betting Backtest (Test) ---")
    backtest_results = []
    bt_test = backtest_ev_grid(test, model, calibrator, label="Test (2025)")
    backtest_results.extend(bt_test)

    if len(ood) > 0:
        print("\n--- Betting Backtest (OOD 2026) ---")
        bt_ood = backtest_ev_grid(ood, model, calibrator, label="OOD (2026)")
        backtest_results.extend(bt_ood)

    # 12. Report
    report = generate_report(eval_results, backtest_results, fi_df, cal_results, {})

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)

    return model, calibrator, df


if __name__ == "__main__":
    main()
