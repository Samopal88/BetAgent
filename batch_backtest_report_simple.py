#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# batch_backtest_report.py

import argparse, csv, json, re, subprocess, sys
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path("/root/betagent")
AGENT = ROOT / "agent_handoff_v7.py"
OUTDIR = ROOT / "reports"

@dataclass
class Scenario:
    name: str
    args: list

@dataclass
class Result:
    name: str
    exit_code: int
    total: int=None
    settled: int=None
    wins: int=None
    losses: int=None
    no_result: int=None
    staked: float=None
    profit: float=None
    roi: float=None
    matches: int=None
    preflight_skip: int=None
    llm_calls: int=None
    bets: int=None
    hist_count: int=None
    p1_count: int=0
    p2_count: int=0
    x_count: int=0
    ba_count: int=0
    output_file: str=""
    stderr_file: str=""

def run_one(sc):
    cmd = [sys.executable, str(AGENT)] + sc.args
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out, err = p.stdout, p.stderr

    OUTDIR.mkdir(exist_ok=True)
    out_file = OUTDIR / f"{sc.name}.txt"
    err_file = OUTDIR / f"{sc.name}.err.txt"
    out_file.write_text(out, encoding="utf-8")
    err_file.write_text(err, encoding="utf-8")

    r = Result(name=sc.name, exit_code=p.returncode, output_file=str(out_file), stderr_file=str(err_file))

    m = re.search(r"total=(\d+).*wins=(\d+).*losses=(\d+)", out)
    if m:
        r.total = int(m.group(1))
        r.wins = int(m.group(2))
        r.losses = int(m.group(3))

    m = re.search(r"Profit=([-0-9.]+).*ROI=([-0-9.]+)%", out)
    if m:
        r.profit = float(m.group(1))
        r.roi = float(m.group(2))

    r.p1_count = out.count("Исход: П1")
    r.p2_count = out.count("Исход: П2")
    r.x_count = out.count("Исход: X")
    r.ba_count = out.count("[BA:")

    return r

def main():
    scenarios = [
        Scenario("all_2000", ["--backtest","--sport","football","--limit","2000","--no-llm"]),
        Scenario("all_1000", ["--backtest","--sport","football","--limit","1000","--no-llm"]),
        Scenario("all_300", ["--backtest","--sport","football","--limit","300","--no-llm"]),
    ]

    results = []
    for sc in scenarios:
        print("Running", sc.name)
        results.append(run_one(sc))

    OUTDIR.mkdir(exist_ok=True)
    txt = OUTDIR / "report.txt"

    lines = []
    for r in results:
        lines.append(f"{r.name}: ROI={r.roi} profit={r.profit}")
        lines.append(f"P1={r.p1_count} P2={r.p2_count} X={r.x_count} BA={r.ba_count}")
        lines.append("-"*40)

    txt.write_text("\n".join(lines), encoding="utf-8")

    print("Saved:", txt)

if __name__ == "__main__":
    main()
