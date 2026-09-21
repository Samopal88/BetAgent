#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batch backtest runner for agent_handoff_v7.py.

Usage:
  cd /root/betagent
  source .venv/bin/activate
  set -a && source .env && set +a
  python3 batch_backtest_report.py

Outputs:
  /root/betagent/reports/batch_backtest_report.json
  /root/betagent/reports/batch_backtest_report.csv
  /root/betagent/reports/batch_backtest_report.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Dict


ROOT = Path("/root/betagent")
AGENT = ROOT / "agent_handoff_v7.py"
OUTDIR = ROOT / "reports"


@dataclass
class Scenario:
    name: str
    args: List[str]


@dataclass
class Result:
    name: str
    exit_code: int
    total: Optional[int] = None
    settled: Optional[int] = None
    wins: Optional[int] = None
    losses: Optional[int] = None
    no_result: Optional[int] = None
    staked: Optional[float] = None
    profit: Optional[float] = None
    roi: Optional[float] = None
    matches: Optional[int] = None
    preflight_skip: Optional[int] = None
    llm_calls: Optional[int] = None
    bets: Optional[int] = None
    hist_count: Optional[int] = None
    p1_count: int = 0
    p2_count: int = 0
    x_count: int = 0
    ba_count: int = 0
    ba_draw_sa: int = 0
    ba_away_sa: int = 0
    ba_p1_pd: int = 0
    ba_draw_bl1_fl1: int = 0
    ba_away_bl1: int = 0
    output_file: str = ""
    stderr_file: str = ""


SUMMARY_RE = re.compile(
    r"BACKTEST SUMMARY:\s*total=(\d+)\s*\|\s*settled=(\d+)\s*\|\s*wins=(\d+)\s*\|\s*losses=(\d+)\s*\|\s*no_result=(\d+)"
)
PROFIT_RE = re.compile(
    r"Staked=([-0-9.]+)\s*\|\s*Profit=([-0-9.]+)\s*\|\s*ROI=([-0-9.]+)%"
)
FINAL_RE = re.compile(
    r"Итог:\s*матчей=(\d+)\s*\|\s*pre-flight SKIP=(\d+)\s*\|\s*LLM вызовов=(\d+)\s*\|\s*BET=(\d+)"
)
HIST_RE = re.compile(r"Loaded historical features for (\d+) matches")


def count_occurrences(text: str, needle: str) -> int:
    return text.count(needle)


def run_one(scenario: Scenario) -> Result:
    cmd = [sys.executable, str(AGENT)] + scenario.args
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout = proc.stdout
    stderr = proc.stderr

    OUTDIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTDIR / f"{scenario.name}.stdout.txt"
    err_file = OUTDIR / f"{scenario.name}.stderr.txt"
    out_file.write_text(stdout, encoding="utf-8")
    err_file.write_text(stderr, encoding="utf-8")

    res = Result(
        name=scenario.name,
        exit_code=proc.returncode,
        output_file=str(out_file),
        stderr_file=str(err_file),
    )

    m = SUMMARY_RE.search(stdout)
    if m:
        res.total = int(m.group(1))
        res.settled = int(m.group(2))
        res.wins = int(m.group(3))
        res.losses = int(m.group(4))
        res.no_result = int(m.group(5))

    m = PROFIT_RE.search(stdout)
    if m:
        res.staked = float(m.group(1))
        res.profit = float(m.group(2))
        res.roi = float(m.group(3))

    m = FINAL_RE.search(stdout)
    if m:
        res.matches = int(m.group(1))
        res.preflight_skip = int(m.group(2))
        res.llm_calls = int(m.group(3))
        res.bets = int(m.group(4))

    m = HIST_RE.search(stdout)
    if m:
        res.hist_count = int(m.group(1))

    res.p1_count = count_occurrences(stdout, "Исход: П1")
    res.p2_count = count_occurrences(stdout, "Исход: П2")
    res.x_count = count_occurrences(stdout, "Исход: X")
    res.ba_count = count_occurrences(stdout, "[BA:")
    res.ba_draw_sa = count_occurrences(stdout, "[BA:DRAW_SA")
    res.ba_away_sa = count_occurrences(stdout, "[BA:AWAY_SA")
    res.ba_p1_pd = count_occurrences(stdout, "[BA:P1_PD")
    res.ba_draw_bl1_fl1 = count_occurrences(stdout, "[BA:DRAW_BL1_FL1")
    res.ba_away_bl1 = count_occurrences(stdout, "[BA:AWAY_BL1")

    return res


def build_scenarios(limit: int, bankroll: float) -> List[Scenario]:
    return [
        Scenario(
            "football_hist_no_llm_all",
            ["--backtest", "--sport", "football", "--limit", str(limit), "--no-llm", "--bankroll", str(bankroll)],
        ),
        Scenario(
            "football_hist_no_llm_300",
            ["--backtest", "--sport", "football", "--limit", "300", "--no-llm", "--bankroll", str(bankroll)],
        ),
        Scenario(
            "football_hist_no_llm_1000",
            ["--backtest", "--sport", "football", "--limit", "1000", "--no-llm", "--bankroll", str(bankroll)],
        ),
    ]


def write_outputs(results: List[Result]) -> Dict[str, str]:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTDIR / "batch_backtest_report.json"
    csv_path = OUTDIR / "batch_backtest_report.csv"
    txt_path = OUTDIR / "batch_backtest_report.txt"

    json_path.write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))

    lines = ["BATCH BACKTEST REPORT", "=" * 80]
    for r in results:
        lines.extend([
            f"Scenario: {r.name}",
            f"  exit_code      : {r.exit_code}",
            f"  hist_count     : {r.hist_count}",
            f"  matches        : {r.matches}",
            f"  preflight_skip : {r.preflight_skip}",
            f"  llm_calls      : {r.llm_calls}",
            f"  bets           : {r.bets}",
            f"  total          : {r.total}",
            f"  settled        : {r.settled}",
            f"  wins           : {r.wins}",
            f"  losses         : {r.losses}",
            f"  no_result      : {r.no_result}",
            f"  staked         : {r.staked}",
            f"  profit         : {r.profit}",
            f"  roi            : {r.roi}",
            f"  P1 / P2 / X    : {r.p1_count} / {r.p2_count} / {r.x_count}",
            f"  BA total       : {r.ba_count}",
            f"  BA rules       : DRAW_SA={r.ba_draw_sa}, AWAY_SA={r.ba_away_sa}, P1_PD={r.ba_p1_pd}, DRAW_BL1_FL1={r.ba_draw_bl1_fl1}, AWAY_BL1={r.ba_away_bl1}",
            f"  stdout         : {r.output_file}",
            f"  stderr         : {r.stderr_file}",
            "-" * 80,
        ])
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    return {"json": str(json_path), "csv": str(csv_path), "txt": str(txt_path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--bankroll", type=float, default=100000.0)
    args = ap.parse_args()

    if not AGENT.exists():
        print(f"agent file not found: {AGENT}")
        return 1

    scenarios = build_scenarios(args.limit, args.bankroll)
    results: List[Result] = []
    for sc in scenarios:
        print(f"Running: {sc.name}")
        results.append(run_one(sc))

    paths = write_outputs(results)
    print("\nSaved reports:")
    for k, v in paths.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
