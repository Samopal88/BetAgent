# Log Retention Plan — 2026-04-14

## Overview

Three-layer approach to prevent silent log growth:
1. **RotatingFileHandler** for `pipeline.log` (Python-level rotation)
2. **logrotate** for all shell-redirected active logs
3. **cleanup_logs.py** for dated log files in `logs/`

---

## Log Inventory

### Active Logs (Python FileHandler — now rotated)

| Log | Size | Writer | Rotation |
|-----|------|--------|----------|
| `pipeline.log` | 3.7 MB | `run_pipeline.py` (RotatingFileHandler) | 2 MB max, 3 backups |

### Active Logs (Shell Redirect — logrotate)

| Log | Size | Writer | Rotation |
|-----|------|--------|----------|
| `cron.log` | 4 KB | cron → `run_server.sh` | 7 days, 100 KB min |
| `shadow.log` | 88 KB | cron → `run_shadow_research.sh` | 7 days, 100 KB min |
| `api.log` | 4 KB | web_panel.py | 7 days, 100 KB min |
| `web_panel.log` | 12 KB | web_panel.py | 7 days, 100 KB min |
| `tg_bot.log` | 5.2 MB | `start_tg_bot.sh` (nohup) | 7 days, 100 KB min |
| `logs/tg_bot.log` | 5.2 MB | `start_tg_bot.sh` (nohup) | 7 days, 100 KB min |
| `logs/client_bot.log` | 1.0 MB | client bot | 7 days, 100 KB min |
| `logs/api.log` | 2.8 MB | API layer | 7 days, 100 KB min |

### Dated Logs (shell `date +%Y%m%d` — cleanup script)

| Pattern | Count | Writer | Retention |
|---------|-------|--------|-----------|
| `logs/pipeline_YYYYMMDD.log` | 8 files | `run_server.sh` | 7 days |
| `logs/settle_YYYYMMDD.log` | 7 files | `run_settle.sh` | 7 days |

### One-time / Historical Logs (cleanup script)

| Log | Size | Status |
|-----|------|--------|
| `logs/football_backtest_downloader_v2.log` | 8.6 MB | Old backtest, cleaned by logrotate |
| `logs/football_stats_parse.log` | 4.8 MB | Old parse, cleaned by logrotate |
| `logs/football_special_markets_full.log` | 2.5 MB | One-time run, cleaned by logrotate |
| `logs/tennis_parse.log` | 2.3 MB | Old parse, cleaned by logrotate |
| `logs/serie_a_stats.log` | 1.7 MB | Old stats, cleaned by logrotate |
| `logs/nhl_backtest_*.log` (4 files) | 3.8 MB | Old backtest, cleaned by logrotate |
| `logs/mls_parse.log` | 355 KB | Old parse, cleaned by logrotate |
| `logs/scandinavia_*.log` (2 files) | 783 KB | Old parse, cleaned by logrotate |

---

## Retention Policy

| Log Type | Mechanism | Retention | Max Size |
|----------|-----------|-----------|----------|
| `pipeline.log` | RotatingFileHandler | 3 × 2 MB backups | ~8 MB total |
| Dated logs (`pipeline_*.log`, `settle_*.log`) | `cleanup_logs.py` (cron daily 06:00) | 7 days | — |
| Active service logs | logrotate (daily) | 7 rotated copies | 100 KB min trigger |
| One-time/historical logs | logrotate (daily) | 7 rotated copies, compressed | 100 KB min trigger |

---

## Changes Made

### 1. `run_pipeline.py` — RotatingFileHandler
- Replaced `logging.FileHandler` with `RotatingFileHandler`
- Max file size: 2 MB
- Backup count: 3 (pipeline.log.1, .2, .3)
- Total max: ~8 MB for pipeline.log

### 2. `/etc/logrotate.d/betagent` — logrotate config
- Covers 23 log files (root-level + logs/ directory)
- Daily check, rotate if > 100 KB
- Keep 7 rotated copies
- Compress after rotation (delaycompress)
- Uses `copytruncate` (safe for active files)

### 3. `cleanup_logs.py` — dated log cleanup
- Removes `pipeline_YYYYMMDD.log` and `settle_YYYYMMDD.log` older than 7 days
- Default: dry-run mode
- `--apply` flag for actual deletion
- `--days N` to customize retention
- Scheduled via cron: daily at 06:00

### 4. Initial cleanup executed
- Removed 37 old dated log files (2.2 MB freed)
- Kept 16 recent files (last 7 days)

---

## What Is NOT Touched

- Current active logs (today's pipeline/settle logs)
- `tg_bot.log` and `client_bot.log` (active service logs — rotated by logrotate, not deleted)
- Any log files not matching known patterns
- Logs in `/mnt/data/` (DB location, no logs there)

---

## Future Maintenance

- If new dated log patterns are added, update `DATED_PATTERNS` in `cleanup_logs.py`
- If new active log files are created, add to `/etc/logrotate.d/betagent`
- To change retention: edit `RETENTION_DAYS` in `cleanup_logs.py` or `rotate 7` in logrotate config
