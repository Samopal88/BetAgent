#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ba_rule_analyzer.py

Analyze BA bets JSON and summarize per-rule performance.

Usage:
  cd /root/betagent
  python3 ba_rule_analyzer.py --input /mnt/data/all_all_pure_ba.bets.json
  python3 ba_rule_analyzer.py --input /root/betagent/reports/all_all_pure_ba.bets.json
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from collections import defaultdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Path to BA bets JSON")
    ap.add_argument("--outdir", default="reports", help="Output directory")
    args = ap.parse_args()

    in_path = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rows = json.loads(in_path.read_text(encoding="utf-8"))

    grouped = defaultdict(list)
    for r in rows:
        grouped[r.get("ba_rule", "NO_RULE")].append(r)

    summary_rows = []
    for rule, items in sorted(grouped.items()):
        staked = 0.0
        profit = 0.0
        wins = 0
        losses = 0
        odds_sum = 0.0
        for r in items:
            stake = float(r.get("stake_abs", 0.0) or 0.0)
            odds = float(r.get("odds", 0.0) or 0.0)
            odds_sum += odds
            staked += stake
            if r.get("won") is True:
                wins += 1
                profit += stake * (odds - 1.0)
            elif r.get("won") is False:
                losses += 1
                profit -= stake
        count = len(items)
        avg_odds = odds_sum / count if count else 0.0
        roi = (profit / staked * 100.0) if staked else 0.0
        winrate = (wins / (wins + losses) * 100.0) if (wins + losses) else 0.0
        summary_rows.append({
            "ba_rule": rule,
            "count": count,
            "wins": wins,
            "losses": losses,
            "winrate_pct": round(winrate, 2),
            "avg_odds": round(avg_odds, 3),
            "staked": round(staked, 2),
            "profit": round(profit, 2),
            "roi_pct": round(roi, 2),
        })

    json_path = outdir / "ba_rule_summary.json"
    csv_path = outdir / "ba_rule_summary.csv"
    txt_path = outdir / "ba_rule_summary.txt"

    json_path.write_text(json.dumps(summary_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    lines = ["BA RULE SUMMARY", "=" * 80]
    for r in sorted(summary_rows, key=lambda x: (x["roi_pct"], x["profit"]), reverse=True):
        lines.append(
            f'{r["ba_rule"]}: count={r["count"]} wins={r["wins"]} losses={r["losses"]} '
            f'winrate={r["winrate_pct"]}% avg_odds={r["avg_odds"]} '
            f'profit={r["profit"]} roi={r["roi_pct"]}%'
        )
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Saved:\n  {json_path}\n  {csv_path}\n  {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
