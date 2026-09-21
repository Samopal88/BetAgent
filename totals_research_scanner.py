#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
totals_research_scanner.py

Purpose:
- check whether totals odds exist in the DB
- if they do: run basic ROI backtests for O/U markets
- if they do not: still compute hit-rate research for O/U 2.5 and 3.5
  using final scores + historical snapshots

Usage:
  cd /root/betagent
  source .venv/bin/activate
  python3 totals_research_scanner.py --db /root/betagent/betagent.db
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_form_points(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        try:
            arr = json.loads(raw)
            mp = {"W": 3, "D": 1, "L": 0}
            return sum(mp.get(str(x).upper(), 0) for x in arr)
        except Exception:
            return 0
    return 0


def total_goals(h: Optional[int], a: Optional[int]) -> Optional[int]:
    if h is None or a is None:
        return None
    return int(h) + int(a)


def load_joined_rows(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    q = """
    SELECT
        bm.id,
        COALESCE(bm.league_name, bm.league) AS league,
        bm.match_date,
        bm.home_team,
        bm.away_team,
        bm.home_score,
        bm.away_score,
        h.home_position,
        h.away_position,
        h.form_last_5_home,
        h.form_last_5_away,
        h.form_points_last_5_home,
        h.form_points_last_5_away,
        h.home_goals_scored_avg,
        h.away_goals_scored_avg,
        h.home_goals_allowed_avg,
        h.away_goals_allowed_avg
    FROM backtest_matches bm
    JOIN historical_match_features h
      ON h.match_id = bm.id
    WHERE bm.home_score IS NOT NULL
      AND bm.away_score IS NOT NULL
    ORDER BY bm.match_date, bm.id
    """
    return conn.execute(q).fetchall()


def inspect_total_columns(conn: sqlite3.Connection) -> List[str]:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(backtest_matches)").fetchall()]
    patterns = [
        r"over", r"under", r"ou", r"total", r"tot", r"o25", r"u25", r"o_2_5", r"u_2_5"
    ]
    out = []
    for c in cols:
        lc = c.lower()
        if any(re.search(p, lc) for p in patterns):
            out.append(c)
    return out


def hit_rate_report(rows: List[sqlite3.Row], outdir: Path) -> None:
    groups: Dict[str, Dict[str, Any]] = {}

    def add(key: str, over25: bool, under25: bool, over35: bool, under35: bool) -> None:
        g = groups.setdefault(key, {
            "group": key, "sample": 0,
            "over25_hits": 0, "under25_hits": 0,
            "over35_hits": 0, "under35_hits": 0
        })
        g["sample"] += 1
        g["over25_hits"] += 1 if over25 else 0
        g["under25_hits"] += 1 if under25 else 0
        g["over35_hits"] += 1 if over35 else 0
        g["under35_hits"] += 1 if under35 else 0

    for r in rows:
        tg = total_goals(r["home_score"], r["away_score"])
        if tg is None:
            continue

        hs = r["home_goals_scored_avg"]
        as_ = r["away_goals_scored_avg"]
        ha = r["home_goals_allowed_avg"]
        aa = r["away_goals_allowed_avg"]
        if None in (hs, as_, ha, aa):
            continue

        exp_total = float(hs) + float(as_)
        exp_allow = float(ha) + float(aa)
        shape = exp_total + exp_allow

        league = r["league"] or "UNKNOWN"
        over25 = tg >= 3
        under25 = tg <= 2
        over35 = tg >= 4
        under35 = tg <= 3

        add(f"LEAGUE::{league}", over25, under25, over35, under35)

        if shape >= 5.6:
            add("HYP::HIGH_TOTAL_SHAPE", over25, under25, over35, under35)
        if shape <= 4.3:
            add("HYP::LOW_TOTAL_SHAPE", over25, under25, over35, under35)

        pos_gap = None
        if r["home_position"] is not None and r["away_position"] is not None:
            pos_gap = abs(int(r["home_position"]) - int(r["away_position"]))
            if pos_gap <= 4 and shape <= 4.5:
                add("HYP::BALANCED_LOW_SHAPE", over25, under25, over35, under35)
            if pos_gap >= 8 and shape >= 5.4:
                add("HYP::WIDE_GAP_HIGH_SHAPE", over25, under25, over35, under35)

        hfp = r["form_points_last_5_home"] if r["form_points_last_5_home"] is not None else parse_form_points(r["form_last_5_home"])
        afp = r["form_points_last_5_away"] if r["form_points_last_5_away"] is not None else parse_form_points(r["form_last_5_away"])
        if abs(hfp - afp) <= 2 and shape <= 4.6:
            add("HYP::FORM_BALANCED_LOW_SHAPE", over25, under25, over35, under35)
        if (hfp >= 9 and afp >= 9) and shape >= 5.2:
            add("HYP::BOTH_HOT_HIGH_SHAPE", over25, under25, over35, under35)

    rows_out = []
    for g in groups.values():
        s = g["sample"]
        rows_out.append({
            "group": g["group"],
            "sample": s,
            "over25_hit_pct": round(g["over25_hits"] / s * 100.0, 2),
            "under25_hit_pct": round(g["under25_hits"] / s * 100.0, 2),
            "over35_hit_pct": round(g["over35_hits"] / s * 100.0, 2),
            "under35_hit_pct": round(g["under35_hits"] / s * 100.0, 2),
        })

    rows_out.sort(key=lambda x: (x["sample"], x["over25_hit_pct"]), reverse=True)

    txt = outdir / "totals_hit_rates.txt"
    csvp = outdir / "totals_hit_rates.csv"
    jsonp = outdir / "totals_hit_rates.json"

    jsonp.write_text(json.dumps(rows_out, ensure_ascii=False, indent=2), encoding="utf-8")
    with csvp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()))
        w.writeheader()
        w.writerows(rows_out)

    lines = ["TOTALS HIT RATE RESEARCH", "=" * 100]
    for r in rows_out:
        if r["sample"] < 25:
            continue
        lines.append(
            f"{r['group']}: sample={r['sample']} "
            f"O2.5={r['over25_hit_pct']}% U2.5={r['under25_hit_pct']}% "
            f"O3.5={r['over35_hit_pct']}% U3.5={r['under35_hit_pct']}%"
        )
    txt.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--outdir", default="reports")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    total_cols = inspect_total_columns(conn)
    rows = load_joined_rows(conn)
    conn.close()

    schema_path = outdir / "totals_schema_check.txt"
    schema_lines = ["TOTALS SCHEMA CHECK", "=" * 80]
    if total_cols:
        schema_lines.append("Possible totals-related columns found in backtest_matches:")
        for c in total_cols:
            schema_lines.append(f"- {c}")
    else:
        schema_lines.append("No obvious totals odds columns found in backtest_matches.")
        schema_lines.append("So this script reports hit-rates only, not bookmaker-ROI on totals.")
    schema_path.write_text("\n".join(schema_lines), encoding="utf-8")

    hit_rate_report(rows, outdir)

    print(f"Saved:\n  {schema_path}\n  {outdir / 'totals_hit_rates.txt'}\n  {outdir / 'totals_hit_rates.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
