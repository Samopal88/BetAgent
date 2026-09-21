# Tennis Client Bot Integration

**Date:** 2026-04-12
**Status:** INTEGRATED

---

## What was done

### 1. `bot/notifier.py` — Tennis notification pipeline

Added 3 new functions:

| Function | Purpose |
|----------|---------|
| `fmt_new_tennis_signal()` | Format tennis bet: league, players, pick (П1/П2 with player name), odds, EV, edge, stake % |
| `fmt_tennis_result()` | Format tennis result: players, pick, profit |
| `notify_tennis_signals(mode)` | Query `tennis_signals` table, send to subscribers via `tg_send()` |

**Schema mapping:**
- `tennis_signals` table has different columns than `bets` (player1/2 instead of home_team/away_team, odds_p1/p2 instead of single odds, stake_pct instead of stake)
- Tennis uses `player1_win` / `player2_win` markets (not home/away/draw)
- Tennis formatter maps `player1_win` → `П1 (Player Name)`, `player2_win` → `П2 (Player Name)`

**CLI:** Added `--tennis` flag to `main()`:
```bash
python3 bot/notifier.py --mode bets --tennis
python3 bot/notifier.py --mode results --tennis
```

**Dedup:** Uses `client_notifications` table with kind=`tennis` and key=`tennis_{mode}_{id}_u{user_id}` — separate from football/hockey notifications.

### 2. `run_pipeline.py` — Wire tennis notifications

Added `task_notify_tennis(mode)` function. Updated all 5 runners:

| Runner | Tennis bets | Tennis results |
|--------|-------------|----------------|
| morning | `task_notify_tennis("bets")` | — |
| afternoon | `task_notify_tennis("bets")` | — |
| evening | `task_notify_tennis("bets")` | `task_notify_tennis("results")` |
| night | `task_notify_tennis("bets")` | — |
| full | — | — |

### 3. `bot/client_bot.py` — Tennis display support

- Added `player1_win` / `player2_win` to `market_map` in `fmt_signal()`
- Added 🎾 emoji for tennis sport in `fmt_signal()`
- Added tennis count to `do_stats()` sport breakdown
- Added tennis market handling to `do_history()`

### 4. `bot/weekly_notify.py` — Weekly stats with tennis

Rewrote from simple promo message to actual weekly stats report:
- Queries `signals` table for last 7 days: total, won, lost, winrate
- Breaks down by sport (football, hockey, tennis)
- Shows per-sport counts and wins
- Still includes cabinet reminder

---

## Verification

```
$ python3 bot/notifier.py --mode bets --tennis
Теннисных ставок: 14
Теннис уведомлено: 18/23
```

14 pending tennis signals found in `tennis_signals` table.
18 out of 23 subscribers received notifications (5 failed — likely blocked/inactive).

```
$ python3 bot/notifier.py --mode results --tennis
Теннисных результатов нет
```

Expected — no tennis signals have been settled yet (all 14 are pending).

---

## Signal format example

```
🎾 *ATP. Барселона. Грунт*
⚔️ Махач Т — Баэс С
📅 2026-04-13
📌 *П1 (Махач Т)* @ 1.78
📊 EV: +15.7% | Edge: 11.5%
💵 Ставка: 5.0% банка
```
