# Tennis Bets Bridge Fix

**Date:** 2026-04-12
**Status:** FIXED

---

## Problem

Tennis pipeline wrote signals to `tennis_signals` table but never created corresponding entries in `bets` table. Since `notify_new_bets()` queries `bets JOIN matches`, tennis signals were invisible to the notification system.

## Fix Applied

### 1. `tennis_live_pipeline.py` — `_create_tennis_bet()` function

Added at line ~628. For each tennis signal that passes filters:

1. **Dedup check**: `SELECT id FROM bets WHERE created_by = 'tennis_{date}_{p1}_{p2}_{market}'`
2. **Create matches entry**: `INSERT OR IGNORE INTO matches (fonbet_id, sport, league, home_team, away_team, match_date)` with `fonbet_id = 'tennis_{date}_{p1_eng}_{p2_eng}'`
3. **Create bets entry**: `INSERT INTO bets (match_id, market, odds, our_probability, ev, kelly_quarter, stake, stake_pct, result, created_at, signal_type, confidence, created_by, edge, model_prob, market_prob)`

Fields populated:
- `sport = 'tennis'` (via matches table)
- `market = 'player1_win'`
- `odds = odds_p1`
- `stake = bankroll * 0.005` (fixed 0.5%)
- `stake_pct = 0.005`
- `result = 'pending'`
- `created_by = 'tennis_{date}_{p1_eng}_{p2_eng}_{market}'` (dedup key)

### 2. `tennis_live_pipeline.py` — `settle_tennis_signals()` updated

Settlement now also updates the corresponding `bets` entry:
```python
dedup_key = f"tennis_{match_date}_{p1_eng}_{p2_eng}_{market}"
bet_profit = round(bankroll * stake_pct * (odds - 1) if result == "won" else -bankroll * stake_pct, 2)
conn.execute("""
    UPDATE bets SET result = ?, profit = ?, settled_at = COALESCE(settled_at, ?)
    WHERE created_by = ?
""", (result, bet_profit, settled_at, dedup_key))
```

### 3. `bot/notifier.py` — Tennis formatting in `fmt_new_signal()` and `fmt_result()`

- Added `player1_win` / `player2_win` to market_map
- Added 🎾 emoji for tennis sport
- Tennis bets now display as: `🎾 League | Player A — Player B | П1 (Player A) @ 1.78 | EV: 15%`

### 4. `backfill_tennis_bets.py` — Backfill script

Backfilled all 14 existing pending signals into `bets` table.

## Verification

```
$ python3 backfill_tennis_bets.py
Found 14 pending tennis signals
Bankroll: 96636 RUB
Backfill complete: 14 created, 0 skipped

$ python3 bot/notifier.py --mode bets
Новых ставок: 14
Уведомлено пользователей: 18/23
```

## Answers

1. **tennis signals now create bets?** Yes — `_create_tennis_bet()` called after each signal insert
2. **bets table receives tennis entries?** Yes — 14 backfilled, new ones auto-created on pipeline runs
3. **notifier sees them now?** Yes — 14 bets found, 18/23 subscribers notified
4. **settlement updates bets too?** Yes — `settle_tennis_signals()` updates both `tennis_signals` and `bets`
5. **backfilled old 14 signals or not?** Yes — all 14 backfilled via `backfill_tennis_bets.py`
