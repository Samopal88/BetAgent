#!/usr/bin/env python3
"""
Adjusted tennis replay: replay all tennis bets with unified 0.5% bankroll staking.
Also audit cancelled/void matches.
"""
import sqlite3
import csv
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "betagent.db")
INITIAL_BANKROLL = 100_000.0
STAKE_PCT = 0.005

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT b.id, b.market, b.odds, b.stake, b.profit, b.result, b.stake_pct,
           b.created_at, b.settled_at,
           m.home_team, m.away_team, m.league
    FROM bets b JOIN matches m ON b.match_id = m.id
    WHERE m.sport = 'tennis'
    ORDER BY b.id ASC
""").fetchall()

# Also get tennis_signals for cancelled status cross-check
signals = {}
for s in conn.execute("SELECT id, result, profit FROM tennis_signals").fetchall():
    signals[s["id"]] = dict(s)

conn.close()

# ── Replay ──
bankroll = INITIAL_BANKROLL
replay_rows = []
cancelled_bets = []

for r in rows:
    bet_id = r["id"]
    odds = float(r["odds"])
    actual_stake = float(r["stake"])
    actual_profit = float(r["profit"]) if r["profit"] is not None else 0.0
    actual_result = r["result"] or "pending"
    actual_stake_pct = float(r["stake_pct"])
    created_at = r["created_at"]
    settled_at = r["settled_at"]
    home = r["home_team"]
    away = r["away_team"]
    league = r["league"]
    market = r["market"]

    # Adjusted stake = 0.5% of current replay bankroll
    adj_stake = round(bankroll * STAKE_PCT, 2)

    if actual_result == "won":
        adj_profit = round(adj_stake * (odds - 1), 2)
    elif actual_result == "lost":
        adj_profit = round(-adj_stake, 2)
    elif actual_result in ("cancelled", "void", "push", "postponed"):
        adj_profit = 0.0
    else:
        # pending — no profit, no bankroll change
        adj_profit = None

    # Update bankroll
    if adj_profit is not None:
        bankroll += adj_profit

    row_data = {
        "bet_id": bet_id,
        "match": f"{home} vs {away}",
        "league": league,
        "market": market,
        "odds": odds,
        "actual_stake": actual_stake,
        "actual_profit": actual_profit,
        "actual_result": actual_result,
        "actual_stake_pct": actual_stake_pct,
        "adj_stake": adj_stake,
        "adj_profit": adj_profit,
        "adj_bankroll_after": round(bankroll, 2),
        "created_at": created_at,
        "settled_at": settled_at,
    }
    replay_rows.append(row_data)

    if actual_result in ("cancelled", "void", "push", "postponed"):
        cancelled_bets.append(row_data)

# ── Stats ──
settled = [r for r in replay_rows if r["actual_result"] in ("won", "lost")]
won = [r for r in settled if r["actual_result"] == "won"]
lost = [r for r in settled if r["actual_result"] == "lost"]
pending = [r for r in replay_rows if r["actual_result"] == "pending"]

actual_total_pnl = sum(r["actual_profit"] for r in settled)
adj_total_pnl = sum(r["adj_profit"] for r in settled)
actual_staked = sum(r["actual_stake"] for r in settled)
adj_staked = sum(r["adj_stake"] for r in settled)

# Max drawdown (adjusted)
peak = INITIAL_BANKROLL
max_dd = 0.0
max_dd_bankroll = INITIAL_BANKROLL
for r in replay_rows:
    br = r["adj_bankroll_after"]
    if br > peak:
        peak = br
    dd = peak - br
    if dd > max_dd:
        max_dd = dd
        max_dd_bankroll = br

# Losing streak (adjusted)
max_lose_streak = 0
cur_lose = 0
for r in replay_rows:
    if r["actual_result"] == "lost":
        cur_lose += 1
        max_lose_streak = max(max_lose_streak, cur_lose)
    else:
        cur_lose = 0

# ── Output ──
print("=" * 80)
print("TENNIS ADJUSTED REPLAY — 0.5% Bankroll Staking")
print("=" * 80)
print(f"Initial bankroll:      {INITIAL_BANKROLL:,.2f}")
print(f"Total bets:            {len(replay_rows)}")
print(f"  Settled (won/lost):  {len(settled)}")
print(f"  Won:                 {len(won)}")
print(f"  Lost:                {len(lost)}")
print(f"  Cancelled/void:      {len(cancelled_bets)}")
print(f"  Pending:             {len(pending)}")
print()
print(f"Hit rate:              {len(won)}/{len(settled)} = {len(won)/len(settled)*100:.1f}%")
print()
print(f"ACTUAL total PnL:      {actual_total_pnl:+,.2f} RUB")
print(f"ADJUSTED total PnL:    {adj_total_pnl:+,.2f} RUB")
print()
print(f"ACTUAL total staked:   {actual_staked:,.2f} RUB")
print(f"ADJUSTED total staked: {adj_staked:,.2f} RUB")
print()
print(f"ACTUAL ROI:            {actual_total_pnl/actual_staked*100:+.2f}%" if actual_staked else "N/A")
print(f"ADJUSTED ROI:          {adj_total_pnl/adj_staked*100:+.2f}%" if adj_staked else "N/A")
print()
print(f"ACTUAL final bankroll: {INITIAL_BANKROLL + actual_total_pnl:,.2f}")
print(f"ADJUSTED final bankroll: {bankroll:,.2f}")
print()
print(f"Max drawdown (adj):    {max_dd:,.2f} RUB (bankroll fell to {max_dd_bankroll:,.2f})")
print(f"Max losing streak:     {max_lose_streak}")
print(f"Avg actual stake:      {actual_staked/len(settled):,.2f}" if settled else "N/A")
print(f"Avg adjusted stake:    {adj_staked/len(settled):,.2f}" if settled else "N/A")
print()

# ── Cancelled audit ──
print("=" * 80)
print("CANCELLED / VOID / POSTPONED TENNIS BETS AUDIT")
print("=" * 80)
if cancelled_bets:
    for cb in cancelled_bets:
        print(f"  bet_id={cb['bet_id']} | {cb['match']} | {cb['league']}")
        print(f"    market={cb['market']} odds={cb['odds']} | result={cb['actual_result']}")
        print(f"    actual_profit={cb['actual_profit']:.2f} | adj_profit={cb['adj_profit']:.2f}")
        print(f"    created={cb['created_at']} settled={cb['settled_at']}")
        # Check if actual profit is 0 (correct for cancelled)
        if abs(cb['actual_profit']) > 0.01:
            print(f"    *** INCORRECT: cancelled bet has non-zero profit {cb['actual_profit']:.2f} ***")
        else:
            print(f"    OK: profit is zero")
        print()
else:
    print("  No cancelled/void bets found.")

# ── Per-bet detail (first 20) ──
print("=" * 80)
print("PER-BET DETAIL (first 20)")
print("=" * 80)
print(f"{'ID':>4} {'Result':>10} {'Odds':>5} {'ActStake':>9} {'ActPnL':>9} {'AdjStake':>9} {'AdjPnL':>9} {'AdjBR':>10} | Match")
for r in replay_rows[:20]:
    pnl_str = f"{r['adj_profit']:+,.0f}" if r['adj_profit'] is not None else "—"
    br_str = f"{r['adj_bankroll_after']:,.0f}"
    print(f"{r['bet_id']:>4} {r['actual_result']:>10} {r['odds']:>5.2f} {r['actual_stake']:>9,.0f} {r['actual_profit']:>9,.0f} {r['adj_stake']:>9,.0f} {pnl_str:>9} {br_str:>10} | {r['match']}")

# ── Write CSV ──
csv_path = os.path.join(os.path.dirname(__file__), "tennis_adjusted_05pct_replay.csv")
with open(csv_path, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=[
        "bet_id", "match", "league", "market", "odds",
        "actual_stake", "actual_profit", "actual_result", "actual_stake_pct",
        "adj_stake", "adj_profit", "adj_bankroll_after",
        "created_at", "settled_at"
    ])
    w.writeheader()
    w.writerows(replay_rows)
print(f"\nCSV written: {csv_path}")

# ── Write cancelled audit CSV ──
cancel_csv = os.path.join(os.path.dirname(__file__), "tennis_cancelled_matches_audit.csv")
with open(cancel_csv, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=[
        "bet_id", "match", "league", "market", "odds",
        "actual_stake", "actual_profit", "actual_result",
        "adj_stake", "adj_profit",
        "created_at", "settled_at", "correct"
    ], extrasaction="ignore")
    w.writeheader()
    for cb in cancelled_bets:
        cb["correct"] = "YES" if abs(cb["actual_profit"]) < 0.01 else "NO"
        w.writerow(cb)
print(f"Cancelled audit CSV: {cancel_csv}")
