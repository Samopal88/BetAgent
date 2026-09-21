#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_btts_model.py

Обучает LightGBM модель для предсказания BTTS.
Строгий time split: Train 2019-2023, Val 2024, Test 2025-2026.

Запуск:
  python train_btts_model.py                 # full (форма + коэф)
  python train_btts_model.py --odds-only     # только коэф (baseline)
  python train_btts_model.py --form-only     # только форма
  python train_btts_model.py --edge 0.05    # порог эджа
"""

import os, sys, sqlite3, argparse, pickle, csv
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Tuple

DB_PATH = os.getenv("BETAGENT_DB", "betagent.db")
OUT_DIR = "ml_output"

FORM_FEATURES = [
    "home_form_pts_5", "home_form_gf_5", "home_form_ga_5", "home_form_btts_5",
    "away_form_pts_5", "away_form_gf_5", "away_form_ga_5", "away_form_btts_5",
    "home_home_winrate_10", "home_home_gf_10", "home_home_ga_10",
    "away_away_winrate_10", "away_away_gf_10", "away_away_ga_10",
    "h2h_btts_rate", "h2h_avg_goals", "h2h_n",
    "form_pts_diff", "gf_diff", "home_winrate_diff",
]

ODDS_FEATURES = [
    "odds_btts_yes", "odds_btts_no",
    "odds_home", "odds_draw", "odds_away",
    "odds_total_over", "odds_total_under", "total_line",
    "margin_btts", "margin_1x2",
]

ALL_FEATURES = FORM_FEATURES + ODDS_FEATURES


def get_conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_data(conn):
    cols = ", ".join(ALL_FEATURES)
    rows = conn.execute(f"""
        SELECT match_id, competition, country, match_date,
               home_team, away_team, btts, has_odds_btts,
               {cols}
        FROM football_rolling_features
        WHERE has_odds_btts = 1
          AND odds_btts_yes IS NOT NULL
          AND odds_btts_no IS NOT NULL
          AND home_form_n_5 >= 2
          AND away_form_n_5 >= 2
        ORDER BY match_date ASC
    """).fetchall()
    return [dict(r) for r in rows]


def add_derived(data):
    for m in data:
        oby = m.get("odds_btts_yes")
        obn = m.get("odds_btts_no")
        if oby and obn:
            raw_yes = 1/oby
            raw_no = 1/obn
            total = raw_yes + raw_no
            m["fair_btts_yes"] = raw_yes / total
            m["fair_btts_no"] = raw_no / total
        else:
            m["fair_btts_yes"] = None
            m["fair_btts_no"] = None
        hgf = m.get("home_form_gf_5") or 0
        hga = m.get("home_form_ga_5") or 0
        agf = m.get("away_form_gf_5") or 0
        aga = m.get("away_form_ga_5") or 0
        m["attack_index"] = round(hgf + agf, 3)
        m["defense_index"] = round(hga + aga, 3)
        m["expected_goals"] = round((hgf + aga + agf + hga) / 2, 3)
    return data


def split_data(data):
    train, val, test = [], [], []
    for m in data:
        yr = m["match_date"][:4]
        if yr <= "2023":
            train.append(m)
        elif yr == "2024":
            val.append(m)
        else:
            test.append(m)
    return train, val, test


def to_xy(data, feature_cols):
    import numpy as np
    X, y = [], []
    for m in data:
        row = [float(m.get(f) or float("nan")) for f in feature_cols]
        X.append(row)
        y.append(int(m["btts"]))
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int32)


def train_lgbm(train_data, val_data, feature_cols):
    try:
        import lightgbm as lgb
    except ImportError:
        print("❌ Установи: pip install lightgbm --break-system-packages")
        sys.exit(1)

    X_tr, y_tr = to_xy(train_data, feature_cols)
    X_val, y_val = to_xy(val_data, feature_cols)

    dtrain = lgb.Dataset(X_tr, label=y_tr, feature_name=feature_cols)
    dval = lgb.Dataset(X_val, label=y_val, feature_name=feature_cols, reference=dtrain)

    params = {
        "objective": "binary", "metric": "binary_logloss",
        "learning_rate": 0.05, "num_leaves": 31,
        "min_child_samples": 50, "feature_fraction": 0.8,
        "bagging_fraction": 0.8, "bagging_freq": 5,
        "lambda_l1": 0.1, "lambda_l2": 0.1,
        "verbose": -1, "seed": 42,
    }

    model = lgb.train(
        params, dtrain, num_boost_round=500,
        valid_sets=[dval],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(100)],
    )
    return model


def calc_edge(p_model, m):
    oby = m.get("odds_btts_yes") or 0
    obn = m.get("odds_btts_no") or 2.0
    if not oby:
        return 0
    raw_yes = 1/oby
    raw_no = 1/obn
    total = raw_yes + raw_no
    p_bookie = raw_yes / total if total else 0
    return p_model - p_bookie


def evaluate_roi(data, probs, edge_thr=0.04, min_n=20):
    total_bets = 0
    hits = 0
    profit = 0.0
    by_league = defaultdict(lambda: {"n": 0, "profit": 0.0, "hits": 0})

    for m, p in zip(data, probs):
        edge = calc_edge(p, m)
        if edge < edge_thr:
            continue
        oby = m.get("odds_btts_yes")
        if not oby:
            continue
        won = m["btts"] == 1
        pnl = (oby - 1) if won else -1
        total_bets += 1
        profit += pnl
        if won:
            hits += 1
        key = f"{m['competition']} | {m['country']}"
        by_league[key]["n"] += 1
        by_league[key]["profit"] += pnl
        if won:
            by_league[key]["hits"] += 1

    n = total_bets
    roi = round(profit / n * 100, 2) if n else 0
    hr = round(hits / n * 100, 1) if n else 0

    leagues = {}
    for k, v in by_league.items():
        if v["n"] >= min_n:
            leagues[k] = {
                "n": v["n"],
                "roi": round(v["profit"] / v["n"] * 100, 2),
                "hit_rate": round(v["hits"] / v["n"] * 100, 1),
            }

    return {"total_bets": n, "roi": roi, "hit_rate": hr,
            "profit": profit, "by_league": leagues}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--edge", type=float, default=0.04)
    ap.add_argument("--min-n-league", type=int, default=15)
    ap.add_argument("--odds-only", action="store_true")
    ap.add_argument("--form-only", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    print(f"🚀 train_btts_model.py  edge={args.edge}")
    conn = get_conn(args.db)

    print("📥 Загружаем данные...")
    data = load_data(conn)
    conn.close()
    data = add_derived(data)
    print(f"   Загружено: {len(data):,} матчей")

    # Выбор фич
    extra = ["fair_btts_yes", "fair_btts_no", "attack_index", "defense_index", "expected_goals"]
    if args.odds_only:
        feature_cols = ODDS_FEATURES + ["fair_btts_yes", "fair_btts_no"]
        label = "odds_only"
    elif args.form_only:
        feature_cols = FORM_FEATURES + ["attack_index", "defense_index", "expected_goals"]
        label = "form_only"
    else:
        feature_cols = ALL_FEATURES + extra
        label = "full"

    print(f"   Режим: {label}, фич: {len(feature_cols)}")

    train_data, val_data, test_data = split_data(data)
    print(f"   Train: {len(train_data):,} | Val: {len(val_data):,} | Test: {len(test_data):,}")

    print("\n🔧 Обучаем LightGBM...")
    model = train_lgbm(train_data, val_data, feature_cols)
    print(f"   Best iteration: {model.best_iteration}")

    import numpy as np
    X_tr, _ = to_xy(train_data, feature_cols)
    X_val, y_val = to_xy(val_data, feature_cols)
    X_test, _ = to_xy(test_data, feature_cols)

    p_train = model.predict(X_tr)
    p_val_raw = model.predict(X_val)
    p_test_raw = model.predict(X_test)

    # Isotonic calibration
    try:
        from sklearn.isotonic import IsotonicRegression
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(p_val_raw, y_val)
        p_val = iso.predict(p_val_raw)
        p_test = iso.predict(p_test_raw)
        p_train_cal = iso.predict(p_train)
        print("   Isotonic calibration ✅")
    except Exception as e:
        iso = None
        p_val = p_val_raw
        p_test = p_test_raw
        p_train_cal = p_train
        print(f"   Calibration skip: {e}")

    # Logloss
    try:
        from sklearn.metrics import log_loss, brier_score_loss
        y_val_arr = np.array([m["btts"] for m in val_data])
        ll = log_loss(y_val_arr, p_val)
        bs = brier_score_loss(y_val_arr, p_val)
        actual_rate = y_val_arr.mean()
        print(f"\n📊 Val метрики: LogLoss={ll:.4f} | Brier={bs:.4f} | BTTS rate={actual_rate:.3f}")
    except Exception:
        pass

    # ROI
    train_res = evaluate_roi(train_data, p_train_cal, args.edge, args.min_n_league)
    val_res = evaluate_roi(val_data, p_val, args.edge, args.min_n_league)

    print(f"\n{'='*60}")
    print(f"TRAIN  bets={train_res['total_bets']:>4}  ROI={train_res['roi']:>+6.1f}%  HR={train_res['hit_rate']:.1f}%")
    print(f"VAL    bets={val_res['total_bets']:>4}  ROI={val_res['roi']:>+6.1f}%  HR={val_res['hit_rate']:.1f}%")
    print(f"{'='*60}")

    # Feature importance
    imp = sorted(zip(feature_cols, model.feature_importance("gain")), key=lambda x: -x[1])
    print("\n📈 Топ-15 фич (gain):")
    max_imp = imp[0][1] if imp else 1
    for fname, fval in imp[:15]:
        bar = "█" * int(fval / max_imp * 25)
        print(f"  {fname:<35} {bar} {fval:.0f}")

    # Лиги на валидации
    if val_res["by_league"]:
        print(f"\n🗺  Лиги на VAL (edge>{args.edge}, min {args.min_n_league} ставок):")
        for league, s in sorted(val_res["by_league"].items(), key=lambda x: -x[1]["roi"])[:20]:
            sign = "✅" if s["roi"] > 0 else "❌"
            print(f"  {sign} {league}: n={s['n']}, ROI={s['roi']:>+.1f}%, HR={s['hit_rate']:.1f}%")
    else:
        print(f"\n⚠️  Недостаточно ставок на VAL с edge>{args.edge} для разбивки по лигам")
        print(f"   Попробуй --edge 0.02 или --min-n-league 5")

    # Сохраняем модель
    model_path = os.path.join(OUT_DIR, f"btts_model_{label}.pkl")
    with open(model_path, "wb") as f:
        pickle.dump({"model": model, "feature_cols": feature_cols,
                     "calibrator": iso, "edge": args.edge,
                     "label": label, "train_roi": train_res["roi"],
                     "val_roi": val_res["roi"]}, f)
    print(f"\n💾 Модель: {model_path}")

    # Тестовые предсказания (сохраняем, не смотрим ROI)
    test_path = os.path.join(OUT_DIR, f"btts_test_{label}.csv")
    with open(test_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["match_date","competition","country","home_team","away_team",
                    "btts","p_model","odds_btts_yes","edge"])
        for m, p in zip(test_data, p_test):
            edge_val = calc_edge(p, m)
            w.writerow([m["match_date"], m["competition"], m["country"],
                        m["home_team"], m["away_team"], m["btts"],
                        round(p, 4), m.get("odds_btts_yes"), round(edge_val, 4)])
    print(f"💾 Тест (не открывать!): {test_path}")

    print(f"""
✅ Готово! Сравни три режима:
   python train_btts_model.py --odds-only    # baseline — только коэф
   python train_btts_model.py --form-only    # только форма
   python train_btts_model.py                # full

   Если full_ROI > odds_only_ROI → форма добавляет сигнал поверх рынка.
""")


if __name__ == "__main__":
    main()
