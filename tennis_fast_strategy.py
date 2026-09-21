#!/usr/bin/env python3
"""Fast dominant winner strategy — SQL join + Python strategy sim."""
import sqlite3, sys, time, os
from collections import defaultdict
from pathlib import Path

# Unbuffered output
sys.stdout.reconfigure(line_buffering=True)

db = str(Path(__file__).parent / "betagent.db")
conn = sqlite3.connect(db, timeout=30)
t0 = time.time()

cov, strat = [], []
def w(m):
    cov.append(m); print(m)
def ws(m):
    strat.append(m); print(m)

# ================================================================
w("=" * 70)
w("TENNIS DOMINANT WINNER STRATEGY — FAST IMPLEMENTATION")
w("=" * 70)

w(f"\nSTEP 1: Bidirectional JOIN")
w("-" * 50)

# Drop old temp table
conn.execute("DROP TABLE IF EXISTS _j")

conn.execute("""
CREATE TABLE _j AS
SELECT p.*, m.odds_p1, m.odds_p2, m.odds_total_under, m.total_line,
       m.id as match_id, m.player1, m.player2, m.match_date
FROM backtest_tennis_players p
JOIN tennis_name_lookup lw ON LOWER(p.winner_name) = lw.eng_name
JOIN tennis_name_lookup ll ON LOWER(p.loser_name) = ll.eng_name
JOIN backtest_tennis_matches m ON m.tour = p.tour
  AND ((m.player1 = lw.betz_name AND m.player2 = ll.betz_name)
    OR (m.player1 = ll.betz_name AND m.player2 = lw.betz_name))
  AND ABS(JULIANDAY(p.tourney_date) - JULIANDAY(m.match_date)) <= 1
""")

jc = conn.execute("SELECT COUNT(*) FROM _j").fetchone()[0]
ptot = conn.execute("SELECT COUNT(*) FROM backtest_tennis_players").fetchone()[0]
tm = conn.execute("SELECT COUNT(*) FROM backtest_tennis_matches").fetchone()[0]
mb = conn.execute("""
    SELECT COUNT(*) FROM backtest_tennis_matches m
    JOIN tennis_name_lookup t1 ON t1.betz_name=m.player1
    JOIN tennis_name_lookup t2 ON t2.betz_name=m.player2
""").fetchone()[0]

w(f"Joined rows:              {jc}")
w(f"Total player records:     {ptot}")
w(f"Total betz matches:       {tm}")
w(f"Both in lookup:           {mb} ({mb/tm*100:.1f}%)")
w(f"Time:                     {time.time()-t0:.1f}s")

# ================================================================
w(f"\nSTEP 2: Player history for dominant_pct")
w("-" * 50)

# Build player history from ALL backtest_tennis_players (WTA only)
ph = defaultdict(list)
cnt = 0
for d, wn, ln, sl in conn.execute(
    "SELECT tourney_date, winner_name, loser_name, sets_loser"
    " FROM backtest_tennis_players WHERE tour='WTA' ORDER BY tourney_date"
).fetchall():
    ph[wn.lower()].append((d, True, sl))
    ph[ln.lower()].append((d, False, sl))
    cnt += 1

w(f"Loaded {cnt} WTA player perspectives from {len(ph)} players")

def dom_pct(player, dt, n=10):
    prev = sorted([(d,w,sl) for d,w,sl in ph.get(player,[]) if d < dt], reverse=True)[:n]
    wins = [(d,w,sl) for d,w,sl in prev if w]
    if not wins:
        return None
    return sum(1 for _,_,sl in wins if sl == 0) / len(wins) * 100

# pre-load lookup: eng_lower -> betz_name
lmap = {}
for bn, en in conn.execute("SELECT betz_name, eng_name FROM tennis_name_lookup").fetchall():
    lmap[en] = bn

# ================================================================
def run(rank_max, rd_min, dp_min, label):
    w(f"  {label}...")
    res = defaultdict(lambda: [0,0,0,0.0])
    for row in conn.execute(
        "SELECT id, year, tour, LOWER(winner_name), LOWER(loser_name),"
        " winner_rank, loser_rank, tourney_date, sets_loser, straight_sets,"
        " odds_p1, odds_p2, player1, player2"
        " FROM _j WHERE tour='WTA'"
    ).fetchall():
        pid, yr, tour, wn, ln, wr, lr, td, sl, ss, op1, op2, p1, p2 = row
        wri = int(wr) if wr else 999
        lri = int(lr) if lr else 0
        if wri > rank_max or (lri - wri) < rd_min:
            continue
        dp = dom_pct(wn, td)
        if dp is None or dp < dp_min:
            continue
        wb = lmap.get(wn)
        if not wb:
            continue
        wo = op1 if wb == p1 else (op2 if wb == p2 else None)
        if wo is None:
            continue
        so = max(1.10, wo * 0.75 + 0.40)
        k = (int(yr) if yr else 0, tour)
        res[k][0] += 1
        res[k][3] += so
        if sl == 0:
            res[k][1] += 1
        else:
            res[k][2] += 1
    # Print
    ws(f"\n{label}")
    ws(f"{'Year':>4} {'Tour':>3} {'N':>5} {'Straight':>9} {'Win%':>7} {'Lost':>6} {'AvgOdds':>8} {'ROI':>8}")
    ws("-" * 65)
    tn=ts=tl=to=0
    for k in sorted(res.keys()):
        n,s,l,so = res[k]
        pct=s/n*100 if n else 0; ao=so/n if n else 0
        roi=(s*ao-n)/n*100 if n else 0
        ws(f"{k[0]:>4} {k[1]:>3} {n:>5} {s:>9} {pct:>6.1f}% {l:>6} {ao:>8.2f} {roi:>+8.1f}%")
        tn+=n; ts+=s; tl+=l; to+=so
    if tn:
        op=ts/tn*100; oa=to/tn; roi=(ts*oa-tn)/tn*100
        ws("-" * 65)
        ws(f"{'ALL':>4} {'':>3} {tn:>5} {ts:>9} {op:>6.1f}% {tl:>6} {oa:>8.2f} {roi:>+8.1f}%")
    else:
        ws("No bets qualified.")
    return tn

# Strict
n1 = run(15, 50, 65, "WTA: rank<=15, rd>=50, dom>=65%")
# Relaxed
n2 = run(20, 40, 55, "WTA: rank<=20, rd>=40, dom>=55%")
# Even more relaxed
n3 = run(20, 30, 50, "WTA: rank<=20, rd>=30, dom>=50%")

# ================================================================
w(f"\nSTEP 3: Summary")
w("-" * 50)
w(f"Joined player records:     {jc} ({jc/ptot*100:.1f}% of {ptot})")
w(f"Both players in lookup:    {mb} ({mb/tm*100:.1f}% of {tm} betz matches)")
w(f"Bets qualified (strict):   {n1}")
w(f"Bets qualified (relaxed):  {n2}")
w(f"Bets qualified (wide):     {n3}")
w(f"Total time:                {time.time()-t0:.1f}s")

# Save
with open("/tmp/tennis_join_coverage.txt","w") as f: f.write("\n".join(cov))
with open("/tmp/tennis_dominant_v2.txt","w") as f: f.write("\n".join(strat))
print("\nSaved /tmp/tennis_join_coverage.txt and /tmp/tennis_dominant_v2.txt")
conn.close()
print("DONE")
