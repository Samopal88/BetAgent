# Telegram Routing Diagnosis

**Date:** 2026-04-12
**Status:** FIXED

---

## Architecture: 3 notification paths

| Path | File | Purpose | Token | Target |
|------|------|---------|-------|--------|
| Admin bot | `tg_bot.py` | Interactive bot for admin | `TELEGRAM_BOT_TOKEN` | `TELEGRAM_CHAT_ID` (560034010) |
| Client bot | `bot/notifier.py` | Push notifications to subscribers | `CLIENT_BOT_TOKEN` | PostgreSQL `users.telegram_id` |
| Channel | `content_publisher.py` | Publish to public channel | `CHANNEL_BOT_TOKEN` | `CHANNEL_ID` (@betagent_chanel) |

---

## Problem Found

**`run_pipeline.py` only called `tg_bot.py` (admin bot).**

The `task_notify()` function at line 206 only invoked:
```python
subprocess.Popen([sys.executable, "tg_bot.py", "--notify", mode], ...)
```

Neither `bot/notifier.py` (client bot) nor `content_publisher.py` (channel) were ever called from the pipeline.

### Why admin bot worked
- `tg_bot.py` was called directly by `task_notify()` in every runner
- Uses `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — both configured in `.env`

### Why client bot didn't work
- `bot/notifier.py` exists and is functional (tested: 7/9 users notified on 2026-04-03)
- Uses `CLIENT_BOT_TOKEN` — configured in `.env`
- **But was never called from `run_pipeline.py`**

### Why channel didn't work
- `content_publisher.py` exists and is functional (tested: published 1/1 on 2026-04-04)
- Uses `CHANNEL_BOT_TOKEN` + `CHANNEL_ID` — both configured in `.env`
- **But was never called from `run_pipeline.py`**

---

## Fix Applied

Added two new functions to `run_pipeline.py`:

```python
def task_notify_client(mode: str = "bets"):
    """Send notifications to subscribers via client bot."""
    run("bot/notifier.py", ["--mode", mode], timeout=120)

def task_publish_channel(mode: str = "bets"):
    """Publish to public channel."""
    run("content_publisher.py", ["--mode", mode], timeout=60)
```

Updated all 5 runners:

| Runner | Before | After |
|--------|--------|-------|
| morning | `task_notify("bets")` | `+ task_notify_client("bets")` + `task_publish_channel("bets")` |
| afternoon | (no notify) | `+ task_notify_client("bets")` + `task_publish_channel("bets")` |
| evening | `task_notify("bets")` + `task_notify("report")` | `+ task_notify_client("bets")` + `task_notify_client("results")` + `task_publish_channel("bets")` + `task_publish_channel("results")` |
| night | (no notify) | `+ task_notify_client("bets")` + `task_publish_channel("bets")` |
| full | `task_notify("bets")` | `+ task_notify_client("bets")` + `task_publish_channel("bets")` |

---

## Verification

```
2026-04-12 04:48:12 [INFO] 📱 Telegram уведомление 'bets' (client bot)...
2026-04-12 04:48:12 [INFO] → bot/notifier.py --mode bets
2026-04-12 04:48:12 [INFO]    Новых ставок нет
2026-04-12 04:48:12 [INFO] 📢 Публикация в канал 'bets'...
2026-04-12 04:48:12 [INFO] → content_publisher.py --mode bets
2026-04-12 04:48:13 [INFO]    [bets] Опубликовано: 0 из 0
```

Both paths now execute. "0 new bets" is expected — no bets placed in last 24h.

---

## Answers

1. **my bot path works?** yes
2. **client bot path exists?** yes
3. **client bot path broken because of what exactly?** `bot/notifier.py` was never called from `run_pipeline.py` — the pipeline only invoked `tg_bot.py` (admin bot). The client bot and channel publisher scripts existed but were orphaned from the pipeline.
4. **channel publish path exists?** yes
5. **exact fix applied?** Added `task_notify_client()` and `task_publish_channel()` to `run_pipeline.py`, wired into all 5 runners
