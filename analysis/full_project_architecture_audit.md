# BetAgent — Full Architectural Audit

> Historical note: this audit describes the pre-publication production server as it existed on 2026-04-13. The public repository was sanitized on 2026-09-21: `.env`, databases, logs and live credentials are not included. References below to plaintext production secrets document the former deployment risk, not the current public tree.

**Date:** 2026-04-13
**Scope:** Complete engineering / product / data / ML / operations audit
**Verdict:** Working prototype with real value, but structurally fragile for production scaling

---

## 1. Executive Summary

BetAgent is a **multi-sport betting decision engine** that has evolved iteratively from a single script into a complex system spanning ~112 Python files. It successfully parses live odds, applies rule-driven and ML-based strategies, validates recommendations, places bets, settles results, and notifies users via Telegram.

**The good:** The core betting logic works. Rule strategies are profitable. The tennis ML pipeline produces signals. The validation gate is well-designed. The system is operational with cron + tmux + systemd.

**The bad:** The project is held together by cron scripts, a 5200-line god file, ~1.3 MB of dead code copies, zero tests, plaintext secrets, and a database with 50+ tables of mixed roles. The `bot/notifier.py` path is dead code. Two validators exist but only one is used. The settlement layer uses fuzzy string matching for team names.

**The ugly:** All secrets (LLM keys, Telegram tokens, YooKassa, JWT, SMTP passwords) are in plaintext `.env`. The pipeline can silently fail on individual steps without alerting anyone. There is no idempotency guarantee across the parse → enrich → bet → notify → settle chain.

---

## 2. Current Architecture Overview

### Layer Map

```
┌─────────────────────────────────────────────────────────────┐
│  SCHEDULING: crontab (9 entries) + tmux + systemd (4 svcs)  │
├─────────────────────────────────────────────────────────────┤
│  ORCHESTRATION: run_pipeline.py (484 lines, 4 daily runs)   │
├──────────────┬──────────────┬───────────────────────────────┤
│  INGESTION   │  ENRICHMENT  │  ANALYSIS                     │
│  parser_v2   │  enricher_   │  agent_handoff_v7.py (5200ln) │
│  sportsru_*  │  football_*  │  tennis_live_pipeline.py      │
│  the_sports_*│  sync_match_ │  hockey_backtest_fast_v2.py   │
│  betz_*      │  fetch_team_ │                               │
│  injuries_*  │  standings_* │                               │
├──────────────┴──────────────┴───────────────────────────────┤
│  VALIDATION: validator.py (partially used)                  │
│  STORAGE:    SQLite (betagent.db, 50+ tables)               │
│              PostgreSQL (SaaS layer, 6 tables)              │
├─────────────────────────────────────────────────────────────┤
│  SETTLEMENT: settler.py + settler_watchdog.py               │
│  NOTIFICATION: tg_bot.py + content_publisher.py             │
│  WEB: web_panel.py (Flask, basic auth)                      │
│  API: api/app.py (FastAPI SaaS layer)                       │
└─────────────────────────────────────────────────────────────┘
```

### File Size Distribution (Top 15)

| File | Size | Assessment |
|------|------|------------|
| `agent_handoff_v7.py` | 234 KB / 5191 lines | **GOD FILE** — LLM, rules, calibration, DB, shadow mode |
| `btts_validation.py` | 88 KB / 1797 lines | Large validation module, unclear if used in pipeline |
| `web_panel.py` | 70 KB | Flask dashboard, mixed concerns |
| `tennis_live_pipeline.py` | 57 KB | Tennis ML pipeline, reasonably structured |
| `hockey_backtest_fast_v2.py` | 53 KB / 1478 lines | Hockey strategies, well-organized |
| `enricher_football_rpl_v3.py` | 47 KB | RPL-specific enricher, versioned |
| `sync_match_facts_v3.py` | 34 KB | Data sync, versioned |
| `tg_bot.py` | 31 KB | Telegram bot, reasonable |
| `parser_v2.py` | 31 KB | Fonbet parser, reasonable |
| `enricher_football.py` | 28 KB | Football enricher, reasonable |
| `sportsru_hockey_results_parser.py` | 29 KB | Hockey results parser |
| `tennis_player_mapping_tdo.py` | 28 KB | Player name mapping |
| `tennis_join_improved.py` | 25 KB | Tennis data join |
| `the_sports_nhl_parser.py` | 23 KB | NHL parser |
| `agent_handoff_v7_241147.py` | 234 KB | **DEAD COPY** |

### Dead Code Inventory

**Old file copies (not imported, not used):**
- 4 copies of `agent_handoff_v7_*.py` — ~885 KB
- 7 copies of `run_pipeline_*.py` / `run_pipeline.py.*` — ~80 KB
- 9 copies of `web_panel_*.py` — ~266 KB
- 3 copies of `tg_bot*.py` — ~77 KB
- 3 copies of `hockey_backtest_fast*.py` — ~150 KB
- 2 copies of `parser_v2*.py` — ~60 KB
- 12+ `.bak` files across the project
- 15 `README_*.txt` debug notes

**Total dead code: ~1.5 MB across ~50 files**

**Dead code paths:**
- `bot/notifier.py` — imported in `run_pipeline.py:249,258` but `bot/` directory does not exist
- `bot/weekly_notify.py` — referenced in crontab but does not exist
- All commented-out shadow tasks in `run_pipeline.py`
- `content_publisher.py` — referenced but may not exist (verify)

---

## 3. Strengths

1. **Validation gate (`validator.py`)** — Well-designed: EV recompute, Kelly recompute, signal classification, odds zones, exposure caps, loss streak halving. Clean, testable, single-responsibility.

2. **Sport profiles (`sport_profiles.json`)** — Good separation of per-sport calibration parameters (caps, penalties, floors, preflight rules). Config-driven, not hardcoded.

3. **Rule-driven strategies are profitable** — The football and hockey rule strategies have been backtested and show positive ROI. The `get_pruned_live_rule()` pattern is clear and auditable.

4. **Tennis ML pipeline** — LightGBM model with proper feature engineering, surface-specific features, H2H, form. The FAVORITE strategy with raw probabilities and kill switch is well-implemented.

5. **Operational awareness** — The system has cron scheduling, tmux sessions, systemd services, lock files, and multiple notification channels. Someone is actively running this in production.

---

## 4. Weaknesses

### 4.1 God File: `agent_handoff_v7.py` (5191 lines)

This single file contains:
- LLM API calls and system prompt (200+ lines of prompt text)
- All football rule strategies (`get_pruned_live_rule()`, ~300 lines)
- Probability calibration (`calibrate_probability()`, ~100 lines)
- EV/Kelly computation (duplicates `validator.py`)
- Stake calculation
- Database I/O (SQLite reads/writes)
- Dual-agent shadow mode
- Backtest mode
- Its own `validate_recommendation()` that shadows `validator.py`
- Response normalization
- Pre-flight checks
- Match fact loading
- Team quality checks

**Impact:** Any change risks breaking unrelated functionality. Onboarding is impossible. Code review is impractical.

### 4.2 Two Competing Validators

- `validator.py:validate_recommendation()` — the canonical, well-tested gate
- `agent_handoff_v7.py` has its own inline validation logic
- Only `compute_kelly` and `confidence_cap_pct` are imported from `validator.py`
- The full validation pipeline in `validator.py` is **never called** by the main engine

**Impact:** Inconsistent validation between what's defined and what's enforced.

### 4.3 Zero Test Coverage

No `tests/` directory, no pytest config, no `conftest.py`. The only test-related file is `test_fixtures.py` (a helper, not a test).

**Impact:** Every change is a leap of faith. Regression detection is manual.

### 4.4 Plaintext Secrets

`.env` contains:
- `LLM_API_KEY=<REDACTED>` (live API key)
- `TELEGRAM_BOT_TOKEN=<REDACTED>`
- `CLIENT_BOT_TOKEN=<REDACTED>`
- `YOOKASSA_SECRET_KEY=<REDACTED>`
- `JWT_SECRET=<REDACTED>`
- `SMTP_PASS=<REDACTED>`
- `PANEL_PASS=<REDACTED>`
- `DATABASE_URL=<REDACTED>`

All committed to git (no `.env` in `.gitignore` — wait, `.gitignore` exists but `.env` may be tracked).

**Impact:** If the repo is ever pushed to a public remote, all credentials are compromised.

### 4.5 Fuzzy Team Name Matching in Settlement

`settler.py` uses substring matching for team names:
```sql
rr.home_team = matches.home_team
OR matches.home_team LIKE '%' || substr(rr.home_team,1,4) || '%'
OR rr.home_team LIKE '%' || substr(matches.home_team,1,4) || '%'
```

**Impact:** False positive match risk. "Man United" could match "Man City" via first 4 chars. Settlement is the financial truth — this needs exact or canonical matching.

### 4.6 Database Schema Chaos

50+ tables with no clear ownership:
- `backtest_*` tables (historical/research) mixed with live tables
- `_j`, `_j2`, `_jtm`, `_btm`, `_m12_ids`, `_m3_ids` — undocumented temp tables
- `match_facts` vs `match_features` vs `match_feature_snapshots` — three tables for similar concepts
- `odds_avg`, `odds_betboom`, `odds_history`, `odds_leon`, `odds_merged`, `odds_pari` — six odds tables
- No foreign keys in SQLite (not enforced)
- No unique constraints on `matches.fonbet_id`
- `handoff_decisions` (24K rows) and `recommendation_snapshots` (25K rows) — growing without archival

---

## 5. Critical Risks

### R1: Pipeline Silent Failures

`run_pipeline.py` calls `run()` which returns `True/False` but the runners don't check all return values. If `task_enrich_football()` fails, `task_bet_football()` still runs with stale data.

```python
def run_morning(dry_run=False):
    task_settle()
    task_parse(dry_run)       # ← if this fails, nobody stops the next steps
    task_enrich_football(dry_run)
    task_bet_football(dry_run)  # ← runs on stale data
```

**Impact:** Bets placed on outdated odds or missing enrichment data.

### R2: No Idempotency

Running `run_pipeline.py --now` twice in quick succession could:
- Parse the same matches twice
- Create duplicate signals
- Send duplicate Telegram notifications
- Double-settle bets (mitigated by `COALESCE(settled_at, ...)` but not fully)

**Impact:** Duplicate bets, duplicate notifications, inflated statistics.

### R3: Single Point of Failure — `agent_handoff_v7.py`

If this file has a syntax error, import failure, or API issue, **all sports analysis stops**. Football, hockey — everything goes through this one file.

**Impact:** Complete analysis outage from a single file bug.

### R4: Settlement Depends on External Scrapers

`settler.py` depends on `results_raw` being populated by `sportsru_football_results_parser.py` and `updater_results.py`. If sports.ru changes their HTML or goes down, settlement stalls.

**Impact:** Pending bets never settle, bankroll calculations are wrong, notifications stop.

### R5: No Health Monitoring

There is no health check endpoint, no heartbeat, no alerting if the pipeline stops running. The only visibility is reading log files manually.

**Impact:** The system could be silently broken for days before anyone notices.

---

## 6. Data / DB Audit

### 6.1 Table Inventory (50 tables)

| Category | Tables | Assessment |
|----------|--------|------------|
| **Live betting** | `matches`, `bets`, `signals`, `odds_history` | Core, needed |
| **Enrichment** | `match_facts`, `match_features`, `standings`, `team_injuries` | Core, needed |
| **Backtest/Research** | `backtest_matches`, `backtest_hockey_matches`, `backtest_football_matches_betz`, `backtest_tennis_matches`, `backtest_hockey_features`, `backtest_hockey_features_v2`, `backtest_football_market_features_v2`, `backtest_football_special_markets_betz`, `backtest_football_stats`, `backtest_tennis_players`, `backtest_equity`, `football_features_ml_v1`, `football_rolling_features` | Research data, should be in separate DB |
| **Snapshots/Audit** | `handoff_decisions` (24K), `recommendation_snapshots` (25K), `match_feature_snapshots` (27K), `odds_history` (27K), `shadow_recommendations` (1.8K), `accuracy_log` (102), `clv_history` (110) | Growing unbounded, needs archival |
| **Odds comparison** | `odds_avg`, `odds_betboom`, `odds_leon`, `odds_merged`, `odds_pari` | Multi-bookmaker, useful but fragmented |
| **Notifications** | `tg_notifications`, `channel_sent_log` | Operational, needed |
| **Tennis ML** | `tennis_signals`, `tennis_live_results`, `tennis_data_odds`, `tennis_name_lookup`, `tennis_player_mapping`, `tennis_player_mapping_review` | Tennis-specific, reasonable |
| **SaaS (PostgreSQL)** | `users`, `subscriptions`, `payments`, `signals`, `user_signal_views`, `audit_log` | Separate DB, good |
| **Temp/Unknown** | `_j` (1.8K), `_j2` (2.6K), `_jtm`, `_btm`, `_m12_ids`, `_m3_ids` | **Undocumented, should be cleaned** |
| **Misc** | `bankroll_state`, `league_edge_report`, `hockey_match_features`, `rules`, `sqlite_sequence` | Mixed utility |

### 6.2 Issues

1. **No separation of live vs historical data** — `backtest_*` tables (hundreds of thousands of rows) share the same DB as live betting data. This bloats the DB, slows queries, and risks backup/restore confusion.

2. **No foreign key enforcement** — SQLite supports FKs but they're not enabled (`PRAGMA foreign_keys = ON` is not set). `bets.match_id` can point to non-existent matches.

3. **No unique constraints** — `matches.fonbet_id` should be UNIQUE to prevent duplicate match entries.

4. **Underscore-prefixed tables** — `_j`, `_j2`, `_jtm`, `_btm`, `_m12_ids`, `_m3_ids` are undocumented. Likely temp tables from tennis data joins that were never cleaned up.

5. **Growing tables without archival** — `handoff_decisions` (24K), `recommendation_snapshots` (25K), `odds_history` (27K) grow every run. `historical_archive_v1.py` is called but unclear if it actually prunes.

6. **Naming inconsistency** — `match_facts` vs `match_features` vs `match_feature_snapshots`. `odds_history` vs `odds_avg` vs `odds_merged`. `backtest_matches` vs `matches`.

### 6.3 Recommendations

- **Split DB:** Move all `backtest_*` tables to a separate `betagent_research.db`
- **Clean temp tables:** Drop `_j`, `_j2`, `_jtm`, `_btm`, `_m12_ids`, `_m3_ids` if not needed
- **Add FK enforcement:** `PRAGMA foreign_keys = ON` at connection time
- **Add unique constraints:** `matches.fonbet_id UNIQUE`
- **Implement archival:** Monthly rotation of `handoff_decisions`, `recommendation_snapshots`, `odds_history` to archive tables or CSV

---

## 7. Pipeline / Orchestration Audit

### 7.1 Current Schedule

| Time | Runner | Key Tasks |
|------|--------|-----------|
| 08:00 | morning | settle → parse → enrich → bet (all sports) → archive → notify |
| 14:00 | afternoon | parse → enrich → bet (football, tennis) → archive → notify |
| 21:00 | evening | settle → parse → enrich → bet (all sports) → archive → notify (all channels) |
| 23:30 | night | parse → enrich (hockey) → bet (hockey, tennis) → archive → notify |

Plus crontab entries at 02:00, 05:00, 06:00, 08:00, 11:00, 14:00, 18:00, 20:30, 23:00 — some overlap with the scheduler loop.

### 7.2 Issues

1. **Dual scheduling** — Both `run_pipeline.py`'s internal `scheduler_loop()` AND crontab entries trigger runs. This creates potential for overlapping executions. The lock file in `run_server.sh` protects the shell wrapper but not `run_pipeline.py --now` called directly.

2. **No step-level failure handling** — If `task_parse()` fails, subsequent tasks still run. There's no `if not task_parse(): return` pattern.

3. **`task_notify()` uses `Popen`** — Fire-and-forget subprocess. If the notification fails, it's lost. No retry, no logging of the subprocess output.

4. **`task_notify_client()` calls dead code** — `bot/notifier.py` does not exist. This will crash silently (caught by `run()` returning False).

5. **`task_bet_football()` timeout = 1200s** — 20 minutes for a single run. If the LLM API is slow or rate-limited, this blocks the entire pipeline.

6. **No state between runs** — Each run is independent. There's no concept of "already processed this match" beyond the `handoff_decisions` table.

7. **`get_current_bankroll()` uses bare `except:`** — Any DB error falls back to initial bankroll, silently.

### 7.3 Recommendations

- **Fail-fast or circuit-breaker:** If parse fails, skip analysis. If enrich fails, skip analysis.
- **Remove dead code paths:** Delete `task_notify_client()` and `task_notify_tennis()` or fix the `bot/` directory.
- **Single scheduling source:** Either use crontab OR the scheduler_loop, not both.
- **Add run manifest:** Write a JSON file per run with start/end time, status of each step, errors.

---

## 8. Parsing / Source Reliability Audit

### 8.1 Sources

| Source | Sport | Parser | Fragility |
|--------|-------|--------|-----------|
| Fonbet API | Football, Hockey, Tennis | `parser_v2.py` | API-based, relatively stable |
| sports.ru | Football results | `sportsru_football_results_parser.py` | HTML scraping, fragile |
| sports.ru | Hockey results | `sportsru_hockey_results_parser.py` | HTML scraping, fragile |
| thesportsdb.com | KHL/NHL enrichment | `the_sports_khl_parser.py`, `the_sports_nhl_parser.py` | API-based |
| betz.su | Football/hockey historical | `betz_football_stats_parser.py` | HTML scraping |
| football-data.org | Football enrichment | `enricher_football.py` | API-based, rate-limited |

### 8.2 Issues

1. **HTML scrapers are fragile** — `sportsru_*` parsers depend on HTML structure. Any site redesign breaks them silently.

2. **No source health monitoring** — If Fonbet API changes its response format, the parser may return empty data without raising an error.

3. **No data freshness checks** — The pipeline doesn't verify that parsed data is from today. Stale cached data could be used.

4. **No fallback sources** — If sports.ru is down, there's no alternative result source for settlement.

5. **`parser_v2.py` league whitelist** — Uses exact matching for most leagues, substring for summer leagues and now Ecuador. Inconsistent approach.

### 8.3 Recommendations

- **Add sanity checks:** After parsing, verify N > 0 matches, odds are in reasonable range, dates are today.
- **Add source adapters:** Abstract each source behind a common interface (`parse_odds()`, `fetch_results()`).
- **Add fallback result sources:** For settlement, have 2+ result sources.

---

## 9. Rule-Driven Audit

### 9.1 Current State

Football rules are in `agent_handoff_v7.py:get_pruned_live_rule()` (~300 lines). Each rule checks league, odds range, table position, form, and goal averages.

Hockey strategies are in `hockey_backtest_fast_v2.py` — well-organized with separate functions per strategy.

### 9.2 Strengths

- Rules are readable and auditable
- Each rule returns a name + market, making tracking easy
- Hockey strategies are properly separated into functions
- `sport_profiles.json` provides configuration layer

### 9.3 Weaknesses

1. **Rules embedded in god file** — Football rules are inside `agent_handoff_v7.py`, not in a separate module. The `strategies/football.py` module only has league detection, not the actual betting rules.

2. **No rule registry** — Rules are a long if-elif chain. Adding a new rule requires editing the god file.

3. **Hardcoded team names** — `SA_AWAY_TEAMS`, `_MLS_HOME_TEAMS`, `SUMMER_TEAMS` are scattered across files.

4. **No rule testing** — No way to test a rule against historical data without running the full backtest.

5. **Disabled rules remain in code** — `DRAW_BL1`, `AWAY_SA`, `DRAW_BALANCED_LINE_BL1` are commented out but still present, creating confusion.

### 9.4 Recommendations

- **Move rules to `strategies/football_rules.py`** — Separate rule definitions from the engine
- **Create a rule registry** — Dict of `{rule_name: rule_function}` for dynamic dispatch
- **Add rule config** — Odds ranges, table diffs, thresholds in a JSON/YAML file
- **Remove disabled rules** — Delete commented-out code or move to a `disabled_rules.py` archive

---

## 10. ML Audit

### 10.1 Tennis ML Pipeline

**Architecture:** LightGBM binary classifier trained on historical match data. Features include rank diff, form, serve/return stats, surface-specific stats, H2H, fatigue.

**Strengths:**
- Proper feature engineering (surface-specific, form windows)
- FAVORITE strategy with raw probabilities and clear filters
- Kill switch for monthly loss limits
- Model + meta pickle files for versioning

**Weaknesses:**
1. **No model versioning beyond filenames** — `tennis_hybrid_v1.pkl` — no MLflow, no experiment tracking
2. **No retraining automation** — Model is trained manually, not on a schedule
3. **Feature drift risk** — If the feature set changes between training and inference, predictions are silently wrong
4. **No calibration validation** — `calibrate_probability()` returns raw probabilities for FAVORITE strategy, but the profile still defines caps/penalties that may or may not be applied
5. **Hardcoded TENNIS_PROFILE** in `tennis_live_pipeline.py` — duplicates `sport_profiles.json`

### 10.2 Football ML (Research Phase)

`football_features_ml_v1` table (60K rows) and `train_btts_model.py` suggest football ML is in research phase. Not yet in production pipeline.

### 10.3 Data Leakage Risks

1. **Backtest tables include future data** — `backtest_hockey_features` has columns like `home_ppg_all_before` — the "before" naming suggests care was taken, but this needs verification per table.
2. **`football_rolling_features`** — 46K rows with form stats. Unclear if these are computed with look-ahead bias protection.
3. **Tennis `_j` table** — 1764 rows with odds and match data. Unclear if this is train/test split properly.

### 10.4 Recommendations

- **Add MLflow or similar** — Track experiments, models, metrics
- **Automate retraining** — Monthly or quarterly retraining on new data
- **Feature validation** — At inference time, verify feature names match training
- **Consolidate tennis profile** — Use `sport_profiles.json` instead of hardcoded dict
- **Document data leakage protections** — Or add them if missing

---

## 11. Settlement Audit

### 11.1 Current Flow

1. `settler.py` finds pending bets
2. Syncs scores from `results_raw` into `matches` using fuzzy team name matching
3. For hockey, fetches regulation-time scores
4. Computes win/loss via `result_for_market()`
5. Writes to `bets` and `accuracy_log`

### 11.2 Strengths

- Idempotent settlement (`COALESCE(settled_at, ...)`)
- Handles multiple markets (1X2, BTTS, O/U 1.5/2.5)
- Hockey OT/SO handling for draw market
- `settler_watchdog.py` for stuck bets

### 11.3 Weaknesses

1. **Fuzzy team name matching** — `LIKE '%' || substr(name,1,4) || '%'` can produce false positives
2. **No handling for postponed/cancelled/void matches** — `result_for_market()` returns `None` for unknown markets, silently skipping
3. **No result source for tennis** — Tennis settlement depends on `tennis_results_updater.py` which may not cover all tournaments
4. **No settlement for BTTS/O/U in hockey** — Only 1X2 markets are settled
5. **`results_raw` is the single source of truth** — If it's empty or wrong, settlement is wrong
6. **No reconciliation** — No process to compare settled bets against bookmaker results

### 11.4 Recommendations

- **Canonical team name mapping** — Single source of truth for team name normalization across all sources
- **Add void/cancelled handling** — Return stake for postponed matches
- **Add result reconciliation** — Periodic check against bookmaker settlement
- **Add tennis result source** — Ensure all tennis tournaments are covered

---

## 12. Notifications / Reporting Audit

### 12.1 Current Architecture

| Component | Role | Transport |
|-----------|------|-----------|
| `tg_bot.py` | Admin notifications | Telegram (admin chat) |
| `content_publisher.py` | Channel publishing | Telegram (channel) |
| `bot/notifier.py` | Client notifications | **DOES NOT EXIST** |
| `web_panel.py` | Web dashboard | Flask + basic auth |
| `api/app.py` | SaaS API | FastAPI |

### 12.2 Issues

1. **`bot/notifier.py` is dead code** — Referenced in `run_pipeline.py` and crontab but doesn't exist. Client notifications are broken.

2. **Duplicate notification paths** — `task_notify()` (admin) and `task_notify_client()` (clients) and `task_publish_channel()` (channel) — three separate paths with no unified formatting.

3. **No notification deduplication** — `tg_notifications` table has `sent_key UNIQUE` but the key generation logic is unclear.

4. **`task_notify()` uses `Popen`** — Fire-and-forget. If the bot crashes mid-notification, it's lost.

5. **No notification templates** — Message formatting is scattered across `tg_bot.py`, `content_publisher.py`, and potentially `bot/notifier.py`.

### 12.3 Recommendations

- **Fix or remove `bot/notifier.py`** — Either create it or remove the references
- **Unified notification formatter** — Single module that formats messages for all channels
- **Add notification queue** — Instead of fire-and-forget, use a queue with retry logic

---

## 13. Observability / Ops Audit

### 13.1 Current State

| Aspect | Status |
|--------|--------|
| Logging | 6 separate log files, no centralized config |
| Monitoring | None |
| Alerting | None (manual log checking) |
| Health checks | None |
| Dashboards | `web_panel.py` (basic), Flask |
| Run manifests | None |
| Error classification | None |
| Metrics | None (no Prometheus, no statsd) |

### 13.2 Issues

1. **No way to know if the pipeline is broken** — If `agent_handoff_v7.py` crashes, the cron entry logs an error but nobody is alerted.

2. **No daily run summary** — No single place to see: "Today: 4 runs, 3 succeeded, 1 failed at step X, N bets placed, N signals generated."

3. **Log files grow unbounded** — `tg_bot.log` is 5.4 MB, `shadow.log` is 83 KB, `pipeline.log` exists. No rotation.

4. **No structured logging** — All logs are plain text. Can't query "show me all errors from today."

5. **No uptime monitoring** — The tmux sessions and systemd services run, but there's no check that they're actually functional.

### 13.3 Recommendations

- **Add a daily run summary** — JSON file with per-step status, duration, errors
- **Add structured logging** — JSON logs with level, module, message, timestamp
- **Add log rotation** — `logrotate` config or Python `RotatingFileHandler`
- **Add a health check endpoint** — Simple HTTP endpoint that returns pipeline status
- **Add error alerting** — Send Telegram message on pipeline failure

---

## 14. Security / Config Audit

### 14.1 Critical: Secrets in Plaintext

`.env` contains 12+ secrets in plaintext. If the server is compromised, all are exposed.

### 14.2 Issues

1. **`.env` may be in git** — `.gitignore` exists but needs verification that `.env` is excluded
2. **No secret rotation** — All secrets appear to be static
3. **PostgreSQL password in connection string** — `DATABASE_URL=<REDACTED>`
4. **JWT secret is static** — `JWT_SECRET=<REDACTED>` — if leaked, all tokens are forgeable
5. **YooKassa live key** — `<REDACTED>` — financial access
6. **No input validation on API** — `api/app.py` may not validate all inputs
7. **Flask basic auth** — `web_panel.py` uses basic auth, credentials in `.env`

### 14.3 Recommendations

- **Verify `.env` is in `.gitignore`**
- **Add secret rotation plan** — Especially for financial keys
- **Consider a secrets manager** — Even a simple encrypted file would be better
- **Add rate limiting to API** — Prevent abuse
- **Add HTTPS** — If not already (ACME cron entry suggests it is)

---

## 15. Scalability Audit

### 15.1 What Breaks First

| Scale Dimension | Breaking Point | Why |
|----------------|---------------|-----|
| More sports | `agent_handoff_v7.py` | Already 5200 lines for 3 sports. Adding MMA/esports makes it unmaintainable |
| More strategies | `get_pruned_live_rule()` | Long if-elif chain. Each new rule adds complexity |
| More users | `tg_bot.py` + `bot/notifier.py` | Single bot, no queue, fire-and-forget |
| More data sources | Parser proliferation | Each source is a separate script with no abstraction |
| More historical data | SQLite | Single file DB, no concurrent writes, growing to GBs |
| More models | No ML lifecycle | Manual training, no versioning, no A/B testing |

### 15.2 Code Scalability

- **Monolithic:** Everything in one repo, one DB, one process
- **No abstraction layers:** Each new sport requires editing the god file
- **No plugin system:** Strategies are hardcoded, not dynamically loaded
- **No configuration management:** Mix of `.env`, `sport_profiles.json`, hardcoded constants

### 15.3 Data Scalability

- **SQLite limits:** Single file, no concurrent writes, no replication
- **No data partitioning:** All data in one DB, growing unbounded
- **No archival strategy:** `historical_archive_v1.py` exists but unclear if effective

### 15.4 Operational Scalability

- **Manual operations:** No runbooks, no automated recovery
- **No CI/CD:** No automated testing, no deployment pipeline
- **Single server:** Everything on one VPS

### 15.5 Recommendations

- **Don't over-engineer yet** — The current architecture works for the current scale
- **Focus on reliability first** — Tests, monitoring, error handling
- **Plan for modularity** — Split `agent_handoff_v7.py` before adding more sports
- **Consider PostgreSQL for everything** — Migrate from SQLite when data grows

---

## 16. Recommended Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  ORCHESTRATION: Prefect / Dagster / simple cron + manifest  │
├──────────────┬──────────────┬───────────────────────────────┤
│  INGESTION   │  ENRICHMENT  │  ANALYSIS                     │
│  (adapters)  │  (adapters)  │  (per-sport modules)          │
│  Fonbet      │  Form        │  football_engine.py           │
│  Sports.ru   │  Standings   │  hockey_engine.py             │
│  TheSportsDB │  Injuries    │  tennis_engine.py             │
│  Betz.su     │  H2H         │  mma_engine.py (future)       │
├──────────────┴──────────────┴───────────────────────────────┤
│  VALIDATION: validator.py (single source of truth)          │
│  STRATEGIES: strategies/ (config-driven rule registry)      │
│  ML: models/ (MLflow, automated retraining)                 │
├─────────────────────────────────────────────────────────────┤
│  STORAGE: PostgreSQL (single DB, partitioned by role)       │
│    - live schema (matches, bets, signals)                   │
│    - research schema (backtest_*, features)                 │
│    - audit schema (handoff_decisions, snapshots)            │
├─────────────────────────────────────────────────────────────┤
│  SETTLEMENT: settler.py + canonical team name mapping       │
│  NOTIFICATIONS: unified formatter + queue + retry           │
│  OBSERVABILITY: structured logs + health checks + alerts    │
└─────────────────────────────────────────────────────────────┘
```

**Key principles:**
- One file, one responsibility
- Config over code for strategy parameters
- Adapters for external sources
- Single validation gate
- Structured logging
- Test coverage for critical paths

---

## 17. Prioritized Roadmap

### A. Срочно (1–3 дня)

| # | What | Why | Impact | Risk if Not Done |
|---|------|-----|--------|-----------------|
| A1 | **Delete dead code files** — all `_*.py` copies, `.bak` files, old versions | Reduces confusion, git noise, disk usage | Low effort, high clarity gain | Continued confusion about which file is canonical |
| A2 | **Fix `bot/notifier.py` dead code path** — either create it or remove references from `run_pipeline.py` and crontab | Pipeline silently fails on client notifications | Client notifications are broken | Users don't receive signals |
| A3 | **Add pipeline step failure checks** — if parse fails, skip analysis; if enrich fails, skip analysis | Prevents bets on stale data | Prevents bad bets | Bets placed on wrong odds |
| A4 | **Verify `.env` is in `.gitignore`** | Prevents secret leakage | Security | All credentials exposed if repo goes public |
| A5 | **Add daily run summary** — JSON file with per-step status, duration, errors | Operational visibility | Can diagnose issues without reading 6 log files | Blind to failures |

### B. Краткосрочно (1–3 недели)

| # | What | Why | Impact | Risk if Not Done |
|---|------|-----|--------|-----------------|
| B1 | **Split `agent_handoff_v7.py`** — extract football rules, LLM calls, calibration, shadow mode into separate modules | Maintainability, testability | Each module can be tested and reviewed independently | God file grows, bugs increase |
| B2 | **Unify validation** — make `agent_handoff_v7.py` use `validator.py:validate_recommendation()` | Single source of truth | Consistent validation across all paths | Inconsistent bet quality |
| B3 | **Add canonical team name mapping** — single module that normalizes team names across all sources | Settlement accuracy | Eliminates fuzzy matching false positives | Wrong settlement results |
| B4 | **Add structured logging + log rotation** — JSON logs, rotating file handler | Debuggability, disk management | Can query errors, logs don't grow unbounded | Disk full, can't debug |
| B5 | **Add basic tests** — test validator, test rule functions, test settlement for known results | Regression protection | Catch bugs before they hit production | Silent regressions |
| B6 | **Split DB** — move `backtest_*` tables to `betagent_research.db` | Performance, clarity | Live DB stays small and fast | DB grows, queries slow |
| B7 | **Add sanity checks after parsing** — verify N > 0, odds in range, dates today | Data quality | Catch parser breaks early | Silent bad data |
| B8 | **Clean up temp tables** — drop `_j`, `_j2`, `_jtm`, `_btm`, `_m12_ids`, `_m3_ids` if unused | DB hygiene | Cleaner schema, less confusion | Undocumented tables grow |

### C. Среднесрочно (1–2 месяца)

| # | What | Why | Impact | Risk if Not Done |
|---|------|-----|--------|-----------------|
| C1 | **Create strategy registry** — config-driven rule system with JSON/YAML config | Easy to add/test strategies | New strategies without code changes | Each new strategy requires god file edit |
| C2 | **Add ML lifecycle** — MLflow or similar, automated retraining, feature validation | Model quality, reproducibility | Track model performance over time | Model drift, no reproducibility |
| C3 | **Add health check + alerting** — HTTP endpoint, Telegram alert on failure | Operational reliability | Know immediately when something breaks | Silent failures for days |
| C4 | **Add notification queue** — reliable delivery with retry | No lost notifications | Users always get signals | Lost signals during bot restart |
| C5 | **Add result reconciliation** — periodic check against bookmaker results | Settlement accuracy | Catch settlement errors | Wrong PnL calculations |
| C6 | **Migrate to PostgreSQL** — move from SQLite to PostgreSQL for all data | Scalability, concurrent access | Supports multiple users, better queries | SQLite limits at scale |
| C7 | **Add CI/CD** — GitHub Actions or similar, run tests on push | Quality gate | Catch bugs before deploy | Broken deploys |
| C8 | **Document architecture** — ADRs, runbooks, onboarding guide | Team scalability | New developers can contribute | Bus factor = 1 |

---

## 18. Honest Assessment

### Top 5 Weakest Points

1. **`agent_handoff_v7.py` — 5200-line god file** — Single point of failure, unmaintainable, untestable
2. **Zero test coverage** — Every change is a leap of faith
3. **Plaintext secrets in `.env`** — 12+ live credentials exposed
4. **Dead code paths** — `bot/notifier.py` doesn't exist, client notifications broken
5. **Fuzzy settlement matching** — Financial truth determined by `LIKE '%substr%'`

### Top 5 Strongest Points

1. **Validation gate design** — EV/Kelly recompute, signal classification, odds zones — well thought out
2. **Sport profiles** — Config-driven calibration, not hardcoded
3. **Profitable rule strategies** — Backtested, positive ROI, auditable logic
4. **Tennis ML pipeline** — Proper feature engineering, FAVORITE strategy with kill switch
5. **Operational setup** — Cron + tmux + systemd + lock files — someone is running this for real

### Biggest Architectural Risk

**Silent data corruption.** The pipeline has no validation that data is correct at each step. A parser returning empty data, an enricher failing silently, or a fuzzy match settling the wrong bet — all can happen without anyone knowing.

### Biggest Scaling Bottleneck

**`agent_handoff_v7.py`.** Adding a 4th sport to this file makes it unmaintainable. The current structure doesn't support parallel development — two people can't work on different sports without merge conflicts.

### What Should Be Fixed First

**A1–A5 (the urgent items).** Delete dead code, fix broken notification paths, add failure checks, secure secrets, add run summaries. These are low-effort, high-impact fixes that immediately improve reliability.

### Where the Project Can Realistically Go Next

**Phase 1 (stability):** Tests, monitoring, error handling, dead code cleanup. Make the current system reliable.

**Phase 2 (modularity):** Split the god file, unify validation, add strategy registry. Make the system maintainable.

**Phase 3 (scale):** ML lifecycle, notification queue, PostgreSQL migration, CI/CD. Make the system scalable.

The project has real value — profitable strategies, working ML, operational infrastructure. The priority should be **stability before features, modularity before scale.**
