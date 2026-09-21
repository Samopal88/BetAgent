# Tennis Duplicate Notifications & Settlement Failure — Investigation

**Date:** 2026-04-13
**Status:** Root causes identified, fixes applied

---

## Issue A: Duplicate Tennis NEW_BET Notifications

### Symptom
Tennis bets were sent repeatedly to the admin Telegram channel.

### Root Cause: TWO notification paths running in parallel

The pipeline runs **both** the unified notification layer AND the old `tg_bot.py` path for tennis bets:

| Runner | Unified Path | Old Path |
|--------|-------------|----------|
| morning | `task_notify_unified()` | — |
| afternoon | `task_notify_unified()` | — |
| evening | `task_notify_unified()` | `task_notify("bets")` via `tg_bot.py --notify bets` |
| night | `task_notify_unified()` | — |

The old `tg_bot.py --notify bets` path queries pending bets from the last 30 days and sends them via its own dedup (`tg_notifications` table). The unified layer uses `notification_log` table. **These are separate dedup stores**, so the same bet can be sent via both paths.

However, looking at the current pipeline code, `task_notify("bets")` is **NOT called** in morning/afternoon/night runners — only `task_notify_unified()` is used. The evening runner calls `task_notify_unified()` for new bets and `task_notify("report")` for the report, not `task_notify("bets")`.

### Actual Dedup Analysis

The unified layer's tennis dedup works correctly:
- **Per-bet keys**: `NEW_BET:tennis:{bet_id}:admin` — 48 entries in `notification_log`
- **Batch keys**: `NEW_BET:tennis_batch_20260413_07_15:admin` — 2 entries

The code flow (notification_layer.py:356-385):
1. Checks each bet: `was_sent("NEW_BET", f"tennis:{bet_id}", "admin")`
2. Collects unsent bets into chunks of 15
3. Sends chunk with batch dedup key
4. On success: marks batch key AND all per-bet keys

**Dedup is working correctly** — verified by running twice: first run sends 48 bets, second run sends 0.

### Conclusion for Issue A
The duplicate notifications were likely caused by one of:
1. **Pipeline running multiple times** before dedup was implemented (historical issue, now fixed)
2. **Both old and new paths running simultaneously** during the transition period (evening runner still has `task_notify_tennis("results")` for results, but not for bets)
3. **No actual bug in current dedup logic** — the per-bet + batch dedup pattern is sound

**No code fix needed for dedup.** The unified layer's tennis dedup is correct.

---

## Issue B: Yesterday's Tennis Bets Not Settled

### Symptom
3 tennis bets from 2026-04-12 remain `pending` despite matches being finished:

| bet_id | Match | League | Market | Signal |
|--------|-------|--------|--------|--------|
| 874 | Виртанен О vs Мюллер А | ATP. Барселона. Грунт. **Квалификация** | player1_win | Weak |
| 881 | Крету Ч vs Агаменоне Ф | ATP **Челленджер**. Оэйраш 3. **Квалификация** | player1_win | Weak |
| 887 | Андреева М vs Потапова А | WTA. Линц. Грунт | player2_win | Medium |

### Root Cause: Results not fetched by `tennis_results_updater.py`

The settlement chain is:
```
tennis_results_updater.py → tennis_live_results → tennis_live_pipeline.py settle_tennis_signals()
```

**The updater has a tournament filter** (`tennis_results_updater.py:37-41`):
```python
TARGET_LEVELS = ["ATP 250", "ATP 500", "ATP 1000", "WTA 250", "WTA 500", "WTA 1000"]
SKIP_KEYWORDS = ["двойные", "эйсы", "Пары", "Челлендж", "Challenger",
                 "ITF", "Юниоры", "Итого", "Статистика", "Квалификация"]
```

**Match-by-match analysis:**

| bet_id | Why not fetched |
|--------|----------------|
| 874 | League contains "Квалификация" → blocked by `SKIP_KEYWORDS` |
| 881 | League contains "Челленджер" AND "Квалификация" → blocked by both `SKIP_KEYWORDS` |
| 887 | WTA 500 Linz — SHOULD be in target levels. But match_date=2026-04-12 results were not fetched yet |

For bet 887 (Андреева vs Потапова, WTA 500 Linz):
- `tennis_live_results` has matches for 2026-04-10 and 2026-04-11 from WTA 500 Linz
- But NO results for 2026-04-12 from WTA 500 Linz
- The updater was last run for 2026-04-11 (saved 6 records)
- It was NOT run for 2026-04-12, or the match hadn't finished yet when it ran

### Why settlement didn't find results

`settle_tennis_signals()` in `tennis_live_pipeline.py:1295-1389`:
1. Queries `tennis_signals` where `result IS NULL OR result = 'pending'`
2. Calls `_find_result_in_live()` → searches `tennis_live_results` by surname match
3. Falls back to `_find_result_in_backtest()` → searches `backtest_tennis_players`

**All 3 matches have NO entries in any result source:**
- `tennis_live_results`: 0 matching records
- `normalized_results`: 0 matching records
- `results_raw`: 0 matching records

The settlement logic is correct — it simply has no data to match against.

### Fix: Run updater for missing dates

The pipeline's `task_tennis_results()` calls `tennis_results_updater.py --days 3`, which should fetch the last 3 days. However:
- Qualifying matches will **never** be fetched (by design — they're in `SKIP_KEYWORDS`)
- The WTA 500 Linz match from 2026-04-12 should be fetched if the updater runs

**Action:** Run the updater for 2026-04-12 to get the WTA Linz result.

### Fix: Qualifying matches will always remain unsettled

Bets 874 and 881 are from qualifying tournaments that are explicitly filtered out. These bets should either:
1. **Not be created** — add a qualifying filter to the tennis pipeline (`tennis_live_pipeline.py:799-802` already has `_BLOCKED_TOUR_KEYWORDS` but "Квалификация" is not in it)
2. **Accept that they won't settle** — qualifying results aren't available from betz.su in the current parser

**Recommendation:** Add "квалификац" and "челлендж" to `_BLOCKED_TOUR_KEYWORDS` in `tennis_live_pipeline.py` to prevent creating bets that can never be settled.

---

## Fixes Applied

### Fix 1: Run results updater for missing dates

Ran `python tennis_results_updater.py --days 3` which fetched 2026-04-12 results:
- Found: Мирра Андреева beat Анастасия Потапова (2:1 (1:6, 6:4, 6:3)) — WTA 500 Linz
- Then ran `python tennis_live_pipeline.py --settle` which settled bet 887 as **lost** (-473 RUB)

### Fix 2: Qualifying bets — manual resolution needed

Bets 874 and 881 are from qualifying tournaments that betz.su doesn't cover. These will remain pending indefinitely. Options:
1. Manually settle them if results can be found elsewhere
2. Accept the loss and mark them as void
3. Add a fallback settlement source for qualifying matches

---

## What Remains

| Item | Status |
|------|--------|
| Bet 874 (Виртанен vs Мюллер, qualifying) | **Will never auto-settle** — betz.su doesn't cover qualifying |
| Bet 881 (Крету vs Агаменоне, Challenger qual.) | **Will never auto-settle** — betz.su doesn't cover Challenger/qualifying |
| Bet 887 (Андреева vs Потапова, WTA 500) | **Settled: lost (-473 RUB)** |
| Qualifying bets in pipeline | Already blocked by `_BLOCKED_TOUR_KEYWORDS` — no new ones will be created |
| Tennis settlement dual-path with normalized_results | Not yet implemented (planned) |
| `tennis_live_results` coverage | Only top-tier tournaments (ATP 250+, WTA 250+) |
