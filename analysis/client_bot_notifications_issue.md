# Client Bot Notifications — Root Cause Analysis

**Date:** 2026-04-15
**Scope:** `bot/client_bot.py` + `bot/notifier.py` + pipeline notification flow

---

## 1. Is client_bot.py running?

**YES** — PID 3777289, running since Apr 1 (14 days).

```
root  3777289  0.0  1.3  445416  13460  Ssl  Apr01  8:37  .venv/bin/python3 bot/client_bot.py
```

## 2. Are there multiple instances of client_bot.py?

**NO** — only one instance running. No duplicate instance problem for client_bot.

## 3. Does client_bot use the same BOT TOKEN as tg_bot?

**NO** — different tokens:
- `tg_bot.py` uses `TELEGRAM_BOT_TOKEN` (46 chars) — admin bot
- `client_bot.py` uses `CLIENT_BOT_TOKEN` (46 chars) — subscriber bot

The Conflict errors seen in logs are from `tg_bot.py` (admin bot), NOT from `client_bot.py`.

## 4. Are there Telegram API Conflict errors from client_bot?

**NO** — client_bot.log.1 contains:
- **0** Conflict errors
- **23** `BadRequest: Can't parse entities` errors (in `do_history`, line 530)
- **2** `NetworkError: httpx.ReadError` (transient network timeouts)

The Conflict error (`terminated by other getUpdates request`) is exclusively in `tg_bot.py` (admin bot, PID 3487179).

## 5. Does client_bot receive new signals from DB but fail to send?

**NO — the signals never reach the client bot at all.** This is the ROOT CAUSE.

### How notifications are supposed to work:

```
Pipeline (run_pipeline.py)
  └── task_notify_client("bets")
        └── subprocess: python3 bot/notifier.py --mode bets
              └── notify_new_bets() / notify_tennis_signals()
                    └── tg_send() → Telegram Bot API → user chat
```

### What actually happens:

The cron schedule runs `run_server.sh` which calls `run_pipeline.py --now`, which calls `run_full()`.

**`run_full()` has 10 tasks:**
```
settle → parse → enrich_football → parse_football_stats → enrich_hockey
→ bet_football → bet_hockey → bet_tennis → archive_snapshot → notify_unified
```

**`run_full()` does NOT call:**
- `task_notify_client("bets")` — sends new bet notifications to subscribers
- `task_notify_tennis("bets")` — sends tennis signal notifications to subscribers

Compare with other runners that DO have client notifications:

| Runner | notify_client | notify_tennis | Tasks |
|--------|--------------|---------------|-------|
| `run_morning()` | YES | YES | 12+ |
| `run_afternoon()` | YES | YES | 12+ |
| `run_evening()` | YES (bets+results) | YES (bets+results) | 19 |
| `run_night()` | YES | YES | 12+ |
| **`run_full()`** | **NO** | **NO** | **10** |

Since all cron runs of `run_server.sh` use `--now` → `run_full()`, **client notifications have never been sent from the main pipeline runner**.

### Evidence:

- Last `client_notifications` entry: **2026-04-12 05:25** (bet 881, user 3)
- This coincides with the last time a runner OTHER than `run_full()` was executed
- Since then: 9 new pending bets created (916-924), zero notifications sent
- 10 users (ids 17, 19, 24-29) have **never** received a single notification

## 6. Are there parse_entities errors in client bot formatting?

**YES** — in `client_bot.py:530` (`do_history` function).

The error: `Can't parse entities: can't find end of the entity starting at byte offset 287`

This happens when `do_history` formats bet history with Markdown. If a team name contains a Markdown special character (`_`, `*`, `[`, `]`, etc.) that opens a formatting entity but doesn't close it properly, Telegram rejects the message.

Example: team name `"Андреева М"` — the underscore in `Андреева` is not a Markdown char, but names like `"O'Connell"` or names with underscores would break. The `fmt_new_signal()` and `fmt_new_tennis_signal()` functions in `notifier.py` also don't escape Markdown special characters in team/league names.

**Impact:** This affects the `/history` command in client_bot, NOT the notification push flow (which uses `notifier.py`'s `tg_send()`). However, `notifier.py` has the same vulnerability — unescaped team names in Markdown messages.

---

## Summary of Issues

| # | Issue | Severity | Impact |
|---|-------|----------|--------|
| **1** | `run_full()` missing `notify_client` + `notify_tennis` tasks | **CRITICAL** | Zero client notifications from main pipeline (all cron runs use `run_full`) |
| **2** | `do_history` parse_entities error | MEDIUM | `/history` command fails for some users |
| **3** | `notifier.py` doesn't escape Markdown in team names | MEDIUM | Push notifications may fail for matches with special chars in names |
| **4** | 10 users never received any notification | HIGH (consequence of #1) | New users (ids 24-29) signed up but never got push notifications |

---

## Fix for Issue #1 (Critical)

Add client notification tasks to `run_full()` in `run_pipeline.py`:

```python
# After line 760 (notify_unified), add:
run_task("notify_client", lambda: task_notify_client("bets"), summary=summary)
run_task("notify_tennis_bets", lambda: task_notify_tennis("bets"), summary=summary)
```

This aligns `run_full()` with `run_night()` and other runners.

## Fix for Issue #2 (Medium)

In `client_bot.py:530` (`do_history`), escape Markdown special characters in team names before formatting:

```python
def escape_md(text):
    """Escape Telegram MarkdownV2 special chars, or use parse_mode=HTML."""
    # For Markdown: escape _ * [ ] ( ) ~ ` > # + - = | { } . !
    return text  # or use parse_mode="HTML" instead
```

Alternatively, switch from `parse_mode="Markdown"` to `parse_mode="HTML"` which is more forgiving with team names.

## Fix for Issue #3 (Medium)

Same as #2 — add Markdown escaping to `notifier.py`'s `fmt_new_signal()` and `fmt_new_tennis_signal()` functions.
