# Pipeline Health Check

**Date:** 2026-04-15 21:30 UTC
**Scope:** End-to-end pipeline audit — scheduler, signal generation, bet creation, Telegram delivery, client bot

---

## 1. Scheduler Status

**WORKING** — cron is active, pipeline runs 6x/day.

| Cron Time | Task | Last Run |
|-----------|------|----------|
| 05:00 | `run_server.sh` (morning full pipeline) | 2026-04-15 05:05 |
| 08:00 | `run_settle.sh` | 2026-04-15 08:00 |
| 11:00 | `run_server.sh` (afternoon) | 2026-04-15 11:05 |
| 14:00 | `run_settle.sh` | 2026-04-15 14:00 |
| 18:00 | `run_server.sh` (evening) | 2026-04-15 18:05 |
| 20:30 | `run_server.sh` (night full) | 2026-04-15 20:35 |

Latest run summary (20:35): `10/10 tasks ok, 0 failed, 320.9s total`

**Running processes:**
- `web_panel.py` — PID 2122578 (since Mar 29)
- `tg_bot.py` — PID 3487179 (since Apr 14)
- `uvicorn api.app:8001` — PID 2655145 (since Apr 6)

---

## 2. Last Signal/Bet by Sport

| Sport | Last Signal | Last Bet | Status |
|-------|-------------|----------|--------|
| **Tennis** | 2026-04-15 20:35 (signal 59) | 2026-04-15 11:05 (bet 924) | ACTIVE |
| **Football** | 2026-04-11 18:05 (bet 867) | 2026-04-11 18:05 (bet 867) | **STOPPED** |
| **Hockey** | 2026-04-08 05:04 (bet 864) | 2026-04-08 05:04 (bet 864) | **STOPPED** |

---

## 3. Signals Created Last 7 Days

| Sport | Count | Notes |
|-------|-------|-------|
| Tennis | 59 signals (tennis_signals table) | Active, generating daily |
| Football | 0 new bets | 27 BET decisions in handoff_decisions, but all on Apr 10-11 (duplicate runs of same matches). 337 PASS decisions since then |
| Hockey | 0 new bets | 0 BET decisions in last 7 days. 261 PASS decisions |

---

## 4. ROOT CAUSE: Football Stopped

**Error:** `Pre-flight: нет данных (standings, форма, голы) — PASS без LLM`

Every football match today is rejected at the pre-flight check because enrichment data is missing.

**Evidence from pipeline log (20:35 run):**
```
enrich_football (108.4s) | enrich_ok=True
bet_football (0.9s) | signals_created=0, bets_created=0
РЕШЕНИЯ: всего=5 | BET=0 | PASS=5 | valid=0 | invalid=5
```

Enrichment runs successfully (`enrich_ok=True`) but produces no usable data for today's matches. The 5 matches parsed today are:
- Аль-Джазира Амман vs Аль-Бакаа (Jordan)
- Дегерфорс vs Эльфсборг (Sweden)
- Юргорден vs Мальме (Sweden)
- Шелбурн vs Дерри Сити (Ireland)
- Дандолк vs Голуэй (Ireland)

All are minor leagues (Jordan, Sweden, Ireland) — NOT the leagues with enabled strategies (Serie A, Bundesliga, La Liga, Ligue 1, RPL, EPL, MLS).

**The real issue:** The major leagues (Serie A, Bundesliga, La Liga) have matches on Apr 17-18, not today (Apr 15-16). The enrichment data exists for those future matches in `match_facts` (Ростов vs Сочи, Интер vs Кальяри, etc.) but Fonbet doesn't have odds for them yet today.

**Secondary issue:** The last football BET decisions (Apr 10-11) show **duplicate runs** — the same matches were processed 4+ times within minutes:
- Вольфсбург vs Айнтрахт: 22:22, 22:23, 22:24, 22:55, 00:51, 01:04 (6 times!)
- Боруссия Д vs Байер: same pattern
- Аталанта vs Ювентус: same pattern

This suggests the pipeline was running multiple times per hour instead of the scheduled 4x/day, creating duplicate bets.

---

## 5. ROOT CAUSE: Hockey Stopped

**Error:** `League NHL has no enabled strategies`

**ALL 10 hockey matches today are NHL.** The NHL strategy (`nhl_draw_tight`) was **explicitly disabled** in `strategies/hockey.py:43-47`:

```python
# "NHL": {  # Отключено — стратегия убыточна на реальных данных (ROI -7%)
#     "mode": "single",
#     "strategies": ["nhl_draw_tight"],
#     "stake_mode": "flat_pct_1_00",
# },
```

**Currently enabled hockey leagues:**
| League | Strategy | Status |
|--------|----------|--------|
| KHL | underdog_live + defensive_wall (intersection) | Enabled, but no KHL matches today |
| CZECH | czech_home_favorite, czech_home_sd | Enabled, but no Czech matches today |
| NLA | nla_bern_away_draw | Enabled, but no Swiss matches today |
| DEL | del_home_form5 | Enabled, but no German matches today |
| SHL | shl_skelleftea_home | Enabled, but no Swedish matches today |
| **NHL** | **DISABLED** | **ALL today's matches are NHL** |

**Last hockey bet:** Apr 8 (Баффало vs Коламбус, draw @ 4.3, lost). Before that, all hockey bets were NHL draw bets. Since NHL is the only league with matches during the regular season, disabling it means zero hockey signals.

---

## 6. Telegram Notification Status

**PARTIALLY BROKEN**

### Admin notifications (notification_layer.py)
- Last admin notification: 2026-04-15 11:05 (tennis bets 923, 924)
- Evening run (18:05) and night run (20:35) sent **zero** notifications
- Reason: `notify_new_bet_unified()` queries bets created in last 2 hours for channel, last 30 days for admin. But dedup (`was_sent()`) marks bets as already sent, so subsequent runs skip them.

### Channel notifications
- Last channel notification: 2026-04-15 11:05 (bets 923, 924)
- `channel_sent_log` shows last entries on Apr 12 (bets 868-881)
- **Gap between Apr 12 and Apr 15** — no channel notifications for 3 days

### tg_bot.py (admin bot)
- **Running** (PID 3487179, since Apr 14)
- **ERROR:** `telegram.error.Conflict: Conflict: terminated by other getUpdates request; make sure that only one bot instance is running`
- This means there are **two instances** of tg_bot.py running simultaneously, causing Telegram API conflicts
- The bot may not be receiving commands or sending messages reliably

### Client bot (bot/client_bot.py)
- **Running** (client_bot.log is empty today — log rotated)
- **ERRORS in previous log:**
  1. `telegram.error.Conflict: terminated by other getUpdates request` — same duplicate instance issue
  2. `telegram.error.BadRequest: Can't parse entities: can't find end of the entity starting at byte offset 287` — HTML/Markdown parsing error in message formatting
  3. `telegram.error.NetworkError: httpx.ReadError` — network timeouts

---

## 7. Client Bot Signal Delivery

**BROKEN** — client bot fetches from API (`/signals/active` on port 8001).

The API endpoint `get_sqlite_signals()` queries:
```sql
SELECT ... FROM bets b JOIN matches m ON b.match_id = m.id
WHERE b.result = 'pending'
  AND datetime(b.created_at) <= datetime('now', '-15 minutes')  -- free plan delay
ORDER BY b.created_at DESC
LIMIT 20
```

This returns pending tennis bets (916-924). But the client bot has **Telegram delivery errors** (Conflict + parse entities), so even though the API returns data, the bot may fail to display it to users.

---

## 8. Pipeline Blockage Map

```
data → model → signal → bet → telegram → client bot
 │       │        │       │       │          │
 │       │        │       │       │          └── BROKEN: Conflict errors, parse errors
 │       │        │       │       └── DEGRADED: dedup prevents re-send, channel gap 3 days
 │       │        │       └── OK (tennis only)
 │       │        └── BLOCKED (football/hockey)
 │       └── N/A (tennis uses ML model, football/hockey use rules+LLM)
 └── OK (data arrives, but wrong leagues)
```

---

## 9. Summary Answers

| Question | Answer |
|----------|--------|
| **Last signal: tennis** | 2026-04-15 20:35 (signal 59, Мухова vs Мертенс) |
| **Last signal: football** | 2026-04-11 18:05 (bet 867, Аталанта vs Ювентус draw) |
| **Last signal: hockey** | 2026-04-08 05:04 (bet 864, Баффало vs Коламбус draw) |
| **Last bet created** | 2026-04-15 11:05 (bet 924, tennis) |
| **Signals last 7 days** | Tennis: 59, Football: 0 new, Hockey: 0 |
| **Telegram send errors** | YES — Conflict (duplicate bot instances), parse entities error, network errors |
| **Scheduler working** | YES — 6x/day cron, all 10 tasks passing |
| **Worker running** | YES — web_panel, tg_bot, uvicorn all running |
| **Task backlog** | NO — no backlog, pipeline completes in ~5 min |
| **Where pipeline stopped** | **Football:** pre-flight data missing for today's minor leagues. **Hockey:** NHL strategy disabled, only NHL matches available. **Telegram:** Conflict errors from duplicate bot instances. **Client bot:** parse entities + Conflict errors |

---

## 10. Recommended Fixes (Priority Order)

### P0 — tg_bot Conflict (blocks client notifications)
Two instances of tg_bot.py are running. Kill the old one:
```bash
# Find all instances
ps aux | grep tg_bot | grep -v grep
# Kill duplicates, keep only one
```

### P0 — Client bot parse entities error
The error `can't find end of the entity starting at byte offset 287` in `client_bot.py:530` (do_history) means a message has malformed Markdown/HTML. Need to sanitize message formatting.

### P1 — Hockey: NHL strategy disabled
NHL is the ONLY league with matches during the season. With it disabled, hockey produces zero signals. Options:
1. Re-enable `nhl_draw_tight` with tighter filters (higher min EV, lower probability cap)
2. Add a new NHL strategy with better ROI
3. Accept zero hockey during NHL-only periods

### P1 — Football: minor leagues only on off-days
Today's football matches are Jordan/Sweden/Ireland — none have enabled strategies. The major leagues (Serie A, Bundesliga, La Liga) have matches Apr 17-18. This is **normal** — no fix needed, just fewer matches on certain days.

### P2 — Football duplicate runs
The same matches were processed 4-6 times within hours (Apr 10-11), creating duplicate bets. The pipeline should deduplicate at the handoff_decisions level, not just at the bets level.
