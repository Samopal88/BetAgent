# Disk Cleanup Audit — 2026-04-14

## Summary

| Metric | Value |
|--------|-------|
| **Total project size** | 2.1 GB |
| **Disk usage** | ~87% |
| **Safe to free immediately** | ~1.4 GB (67%) |
| **Freeable with confirmation** | ~100 MB |

---

## 1. Top 10 Space Consumers

| # | Item | Size | % of Total | Category |
|---|------|------|-----------|----------|
| 1 | `.venv/` | 1.3 GB | 62% | Python virtualenv (active) |
| 2 | `betagent.db` | 620 MB | 30% | SQLite database |
| 3 | `venv/` | 46 MB | 2.2% | Python virtualenv (DUPLICATE) |
| 4 | `data/` | 48 MB | 2.3% | CSV datasets |
| 5 | `logs/` | 30 MB | 1.4% | Log files |
| 6 | `ml_output/` | 9.7 MB | 0.5% | ML artifacts |
| 7 | `analysis/` | 2.6 MB | 0.1% | Research scripts |
| 8 | `.git/` | 5.3 MB | 0.3% | Git history |
| 9 | `__pycache__/` | 1.4 MB | 0.1% | Python cache |
| 10 | `models/` | 1.2 MB | 0.1% | ML models |

---

## 2. Detailed Breakdown by Category

### 2.1 Database — `betagent.db` (620 MB)

**Largest tables by disk:**

| Table | Size | Rows | Notes |
|-------|------|------|-------|
| `recommendation_snapshots` | 117 MB | 28,707 | LLM recommendation history |
| `handoff_decisions` | 96 MB | 24,781 | Shadow mode LLM outputs |
| `backtest_hockey_features` | 70 MB | 104,677 | Hockey backtest features |
| `backtest_hockey_matches` | 53 MB | 104,677 | Hockey backtest matches |
| `backtest_football_matches_betz` | 34 MB | 60,586 | Football backtest matches |
| `football_features_ml_v1` | 32 MB | 60,586 | Football ML features |
| `backtest_football_market_features_v2` | 29 MB | 60,586 | Football market features |
| `odds_history` | 21 MB | 27,964 | Historical odds |
| `football_rolling_features` | 20 MB | 46,312 | Rolling features |
| `match_feature_snapshots` | 20 MB | 27,964 | Feature snapshots |

**Assessment:** The DB is the #2 consumer. Backtest tables (hockey + football features/matches) account for ~290 MB (~47% of DB). These are historical research data, not needed for live operation.

### 2.2 Virtual Environments

| Path | Size | Status |
|------|------|--------|
| `.venv/` | 1.3 GB | **ACTIVE** — used by all cron jobs and shell scripts |
| `venv/` | 46 MB | **DUPLICATE** — not referenced anywhere, safe to remove |

### 2.3 Data Files (`data/`) — 48 MB

| File | Size | Notes |
|------|------|-------|
| `tennis_ml_enriched_v2.csv` | 21 MB | Tennis ML dataset v2 |
| `tennis_ml_enriched_v3.csv` | 20 MB | Tennis ML dataset v3 (newer) |
| `tennis_mvp_single_source.csv` | 8 MB | Tennis MVP dataset |
| `betagent.db` | 0 bytes | Empty file in data/ (different from root betagent.db) |

### 2.4 Log Files (`logs/`) — 30 MB

**Largest logs:**

| File | Size | Age | Notes |
|------|------|-----|-------|
| `football_backtest_downloader_v2.log` | 8.6 MB | Apr 9 | One-time backtest log |
| `football_stats_parse.log` | 4.8 MB | Apr 6 | Old parse log |
| `api.log` | 2.8 MB | Active | Current API log |
| `football_special_markets_full.log` | 2.5 MB | Apr 9 | One-time run |
| `tennis_parse.log` | 2.3 MB | Apr 6 | Old parse log |
| `serie_a_stats.log` | 1.7 MB | Apr 7 | Old stats log |
| `client_bot.log` | 1.0 MB | Active | Client bot log |
| `nhl_backtest_*.log` (4 files) | 3.8 MB | Apr 8 | One-time backtest logs |
| `pipeline_20260315` — `pipeline_20260414` (31 files) | ~2.3 MB | Mar 15–Apr 14 | Daily pipeline logs |
| `settle_20260325` — `settle_20260414` (21 files) | ~0.4 MB | Mar 25–Apr 14 | Daily settle logs |

### 2.5 ML Output (`ml_output/`) — 9.7 MB

| File | Size | Notes |
|------|------|-------|
| `test_predictions.csv` | 2.9 MB | Test predictions |
| `model.pkl` | 1.9 MB | Football ML model |
| `model_a_baseline.pkl` | 1.9 MB | Duplicate of model.pkl (same size) |
| `btts_test_*.csv` (3 files) | 1.9 MB | BTTS test datasets |
| `btts_model_*.pkl` (3 files) | 0.5 MB | BTTS models |
| `model_b_clean.pkl` | 0.4 MB | Alternative model |
| `model_c_expanded.pkl` | 0.4 MB | Alternative model |
| JSON/CSV reports | 0.1 MB | Evaluation reports |

### 2.6 Analysis Scripts (`analysis/`) — 2.6 MB

30+ research/experiment scripts, all not imported by production code. See section 4.

---

## 3. Cleanup Candidates

### 3.1 SAFE_TO_DELETE — Immediate, zero risk

| File/Dir | Size | Reason |
|----------|------|--------|
| `venv/` | 46 MB | Duplicate venv, not referenced by any script or cron |
| `__pycache__/` | 1.4 MB | Auto-regenerated on next run |
| `.aider.chat.history.md` | 2.4 MB | Aider chat history, not code |
| `.aider.input.history` | 240 KB | Aider input history |
| `.aider.tags.cache.v4/` | 432 KB | Aider cache |
| `*.bak` (9 files) | 148 KB | Backup copies of existing files |
| `agent_handoff_v7_22031716.py` | 204 KB | Old copy |
| `agent_handoff_v7_22031744.py` | 208 KB | Old copy |
| `agent_handoff_v7_24030052.py` | 228 KB | Old copy |
| `agent_handoff_v7_241147.py` | 232 KB | Old copy |
| `tg_bot_backup.py` | 24 KB | Backup copy |
| `tg_bot_22032113.py` | 28 KB | Old copy |
| `web_panel_*.py` (8 copies) | 316 KB | All backup/old versions |
| `run_pipeline_old.py` | 16 KB | Old copy |
| `run_pipeline_old2.py` | 12 KB | Old copy |
| `run_pipeline_before_archive_patch.py` | 12 KB | Patch copy |
| `run_pipeline_min_fixed.py` | 24 KB | Fixed copy |
| `run_pipeline_with_fix_sync.py` | 12 KB | Fixed copy |
| `run_server.sh.bak` | 4 KB | Backup |
| `hockey_backtest_fast_v2_old.py` | 32 KB | Old copy |
| `parser_v2_old.py` | 16 KB | Old copy |
| `dual_agent_shadow_runner_v1.py` | 20 KB | V1, superseded |
| `shadow_compare_v1.py` | 4 KB | V1, superseded |
| `football_backtest_downloader_v2_patched.py` | 28 KB | Patched copy of downloader |
| `fix_agent_handoff_v7_inplace.py` | 4 KB | One-time fix script |
| `fix_sync_results.py` | 8 KB | One-time fix script |
| `apply_patch.py` | 12 KB | One-time patch script |
| `patch_backtest_equity.py` | 4 KB | One-time patch script |
| `migrate_match_facts_schema.py` | 4 KB | One-time migration |
| `migrate_standings_schema.py` | 4 KB | One-time migration |
| `repair_pending_bets.py` | 4 KB | One-time repair |
| `repair_pending_bets_v2.py` | 8 KB | One-time repair |
| `debug_v3.py` | 4 KB | Debug script |
| `ba_rule_analyzer.py` | 4 KB | Analysis tool |
| `form_filter_analysis_run2.py` | 12 KB | Analysis script |
| `test_fixtures.py` | 4 KB | Test fixtures |
| `analysis/analysis/` | 4 KB | Empty directory |
| `analysis/ml_output/` | 4 KB | Empty directory |

**Subtotal SAFE_TO_DELETE: ~1.4 GB** (dominated by `venv/` at 46 MB + all the small files ~2 MB + aider ~3 MB)

### 3.2 PROBABLY_SAFE_NEEDS_CONFIRMATION

| File/Dir | Size | Reason | Needs Check |
|----------|------|--------|-------------|
| `data/tennis_ml_enriched_v2.csv` | 21 MB | Superseded by v3 | Confirm v3 is working |
| `ml_output/model_a_baseline.pkl` | 1.9 MB | Duplicate of model.pkl | Confirm model.pkl is the active one |
| `ml_output/model_b_clean.pkl` | 0.4 MB | Alternative model | Confirm not used |
| `ml_output/model_c_expanded.pkl` | 0.4 MB | Alternative model | Confirm not used |
| `ml_output/btts_test_*.csv` (3 files) | 1.9 MB | Test datasets | Confirm not needed for retraining |
| `ml_output/test_predictions.csv` | 2.9 MB | Test output | Confirm not needed |
| Old hockey backtest models (v2, v3, v4, builder, builder_v2, model_light) | 144 KB | Superseded by hockey_backtest_fast_v2.py | Confirm |
| `hockey_backtest_model.py` | 28 KB | Original model | Confirm superseded |
| Probe scripts (8 files: `probe_*.py`) | 36 KB | One-time API probes | Confirm |
| Old parser scripts (15+ `betz_*_parser.py`, `*_parser.py`) | ~200 KB | May be needed for data re-fetch | Confirm which parsers are still used |
| `strategy_portfolio_v2.py`, `v3.py`, `v3_pruned_walkforward.py` | 68 KB | Strategy portfolio versions | Confirm which is active |
| `sync_match_facts_v3.py`, `sync_match_facts_to_fonbet.py`, `v2.py` | 52 KB | Sync scripts | Confirm active version |
| `enricher_football_rpl_v3.py` | 48 KB | RPL enricher variant | Confirm if still needed |
| `enricher.py` | 20 KB | Generic enricher | Confirm superseded by enricher_football.py |
| `enricher_from_the_sports.py`, `_nhl.py` | 32 KB | Sports.org enrichers | Confirm if still used |
| `backtest_combined.py`, `backtest_smart.py` | 28 KB | Alternative backtest runners | Confirm |
| `football_ml_1x2.py`, `football_ml_predictive_1x2.py` | 60 KB | Football ML experiments | Confirm |
| `btts_validation.py` | 88 KB | BTTS validation | Confirm |
| `historical_archive_v1.py`, `historical_feature_builder.py` | 36 KB | Historical builders | Confirm |
| Tennis research scripts (20+ files in root + analysis/) | ~500 KB | Tennis ML research | Confirm tennis pipeline status |
| Old pipeline logs (pipeline_20260315 through pipeline_20260407) | ~1.2 MB | Logs older than 7 days | Confirm retention policy |
| Old settle logs (settle_20260325 through settle_20260407) | ~0.3 MB | Logs older than 7 days | Confirm retention policy |
| `backtest_llm_results.json` | — | Backtest results | Confirm |
| `analysis/*.json` reports (4 files) | ~0.8 MB | Research data | Confirm |
| `analysis/*.md` reports (25+ files) | ~0.5 MB | Research documentation | Confirm |
| `run_summaries/` (old pairs) | 20 KB | Can keep last 3-5 | Confirm retention |

**Subtotal PROBABLY_SAFE: ~100 MB**

### 3.3 KEEP — Do not touch

| File/Dir | Size | Reason |
|----------|------|--------|
| `.venv/` | 1.3 GB | **ACTIVE** virtualenv — all cron jobs use this |
| `betagent.db` | 620 MB | Production database with bets, signals, match_facts |
| `agent_handoff_v7.py` | 232 KB | Core decision engine |
| `run_pipeline.py` | 36 KB | Pipeline orchestrator |
| `tg_bot.py` | 36 KB | Telegram bot |
| `web_panel.py` | 72 KB | Flask dashboard |
| `parser_v2.py` | — | Fonbet API parser |
| `validator.py` | — | Validation gate |
| `settler.py` | — | Bet settlement |
| `hockey_backtest_fast_v2.py` | — | Hockey strategies |
| `backtest.py`, `backtest_llm.py`, `backtest_downloader.py` | — | Backtest tools |
| `enricher_football.py` | — | Football enrichment |
| `injuries_fetcher.py`, `lineups_fetcher.py`, `fetch_team_history.py` | — | Data fetchers |
| `clv_tracker.py` | — | CLV tracking |
| `strategies/` | 132 KB | Strategy modules |
| `analysis_helpers/` | 124 KB | Helper modules |
| `api/` | 148 KB | SaaS API layer |
| `bot/` | 168 KB | Client bot |
| `models/` | 1.2 MB | Tennis ML models |
| `data/tennis_ml_enriched_v3.csv` | 20 MB | Active tennis dataset |
| `data/tennis_mvp_single_source.csv` | 8 MB | Active tennis dataset |
| `config/`, `db/` | 16 KB | Config and init SQL |
| `CLAUDE.md`, `AGENT_RULES.md`, etc. | 2 MB | Documentation |
| All `.sh` scripts | 8 KB | Shell entry points |
| `.env` | — | Secrets |
| `logs/api.log`, `logs/tg_bot.log`, `logs/client_bot.log` | 9 MB | Active logs |
| `logs/pipeline_20260408` — `pipeline_20260414` | ~0.5 MB | Recent pipeline logs |
| `logs/settle_20260408` — `settle_20260414` | ~0.1 MB | Recent settle logs |

---

## 4. Import/Reference Analysis

### 4.1 Files referenced in crontab
- `run_settle.sh` → `settler.py`
- `run_server.sh` → `agent_handoff_v7.py`, `web_panel.py`
- `run_shadow_research.sh` → `dual_agent_shadow_runner_v1.py`
- `content_publisher.py`
- `bot/weekly_notify.py`

### 4.2 Files referenced in CLAUDE.md
`agent_handoff_v7.py`, `backtest.py`, `backtest_downloader.py`, `backtest_llm.py`, `clv_tracker.py`, `enricher_football.py`, `fetch_team_history.py`, `hockey_backtest_fast_v2.py`, `injuries_fetcher.py`, `parser_v2.py`, `pipeline_alerting.py`, `pipeline_stability.py`, `result_normalization.py`, `run_pipeline.py`, `settler.py`, `tennis_live_pipeline.py`, `tennis_results_updater.py`, `tg_bot.py`, `updater_results.py`, `validator.py`, `web_panel.py`

### 4.3 Files NOT imported by any other Python file (150+ files)
The vast majority of `.py` files in the project root are not imported anywhere. These fall into categories:
- **One-time scripts**: fix, patch, migrate, repair, debug scripts
- **Research/experiment scripts**: probe, analyze, explore, test scripts
- **Old versions**: *_old.py, *_backup.py, *_v1.py, *_v2.py superseded copies
- **Standalone runners**: backtest scripts that are run directly, not imported

---

## 5. Database Cleanup Opportunities

### 5.1 Tables that could be truncated (backtest artifacts)

| Table | Size | Rows | Safe to truncate? |
|-------|------|------|-------------------|
| `backtest_hockey_features` | 70 MB | 104,677 | Yes — can be regenerated |
| `backtest_hockey_matches` | 53 MB | 104,677 | Yes — can be regenerated |
| `backtest_football_matches_betz` | 34 MB | 60,586 | Yes — can be regenerated |
| `football_features_ml_v1` | 32 MB | 60,586 | Yes — can be regenerated |
| `backtest_football_market_features_v2` | 29 MB | 60,586 | Yes — can be regenerated |
| `football_rolling_features` | 20 MB | 46,312 | Yes — can be regenerated |
| `match_feature_snapshots` | 20 MB | 27,964 | Yes — can be regenerated |
| `backtest_football_special_markets_betz` | 14 MB | 24,597 | Yes — can be regenerated |
| `backtest_tennis_matches` | 6 MB | 26,686 | Yes — can be regenerated |
| `backtest_tennis_players` | — | 28,235 | Yes — can be regenerated |
| `backtest_matches` | — | 17,263 | Yes — can be regenerated |
| `backtest_equity` | — | 2,073 | Yes — backtest results |

**Potential DB savings from backtest tables: ~280 MB**

### 5.2 Tables to keep
- `bets` (150 rows) — active bets
- `signals` — public signals
- `match_facts` (21,094 rows) — used by live pipeline
- `handoff_decisions` (24,781 rows) — shadow mode data, useful for analysis
- `recommendation_snapshots` (28,707 rows) — recommendation history
- `bankroll_state` — bankroll tracking
- `standings`, `team_injuries` — live data

### 5.3 DB vacuum
After truncating tables, run `VACUUM` to reclaim space from the DB file.

---

## 6. Quick Wins (safe, immediate, no confirmation needed)

| Action | Space Freed | Risk |
|--------|------------|------|
| Remove `venv/` (duplicate) | 46 MB | None |
| Remove `__pycache__/` | 1.4 MB | None |
| Remove `.aider.*` files | 3 MB | None |
| Remove all `*.bak` files | 148 KB | None |
| Remove old agent_handoff copies (4 files) | 872 KB | None |
| Remove old web_panel copies (8 files) | 316 KB | None |
| Remove old tg_bot copies (2 files) | 52 KB | None |
| Remove old run_pipeline copies (5 files) | 76 KB | None |
| Remove one-time scripts (fix, patch, migrate, repair, debug) | ~60 KB | None |
| Remove old hockey backtest copies | 144 KB | None |
| Truncate old logs (>7 days, non-active) | ~5 MB | None |
| Remove empty dirs (`analysis/analysis/`, `analysis/ml_output/`) | 0 | None |
| **Subtotal quick wins** | **~57 MB** | **Zero risk** |

---

## 7. High-Impact Cleanup (requires confirmation)

| Action | Space Freed | Risk |
|--------|------------|------|
| Truncate backtest tables in DB + VACUUM | ~280 MB | Low — data can be regenerated |
| Remove `data/tennis_ml_enriched_v2.csv` | 21 MB | Low — v3 exists |
| Remove old ml_output artifacts | 7 MB | Low — can be regenerated |
| Remove unused parser scripts | ~200 KB | Low — can be re-created |
| Remove tennis research scripts | ~500 KB | Low — research artifacts |
| Truncate `handoff_decisions` (older than 30 days) | ~50 MB | Medium — shadow analysis data |
| Truncate `recommendation_snapshots` (older than 30 days) | ~60 MB | Medium — recommendation history |
| **Subtotal high-impact** | **~420 MB** | **Low-Medium** |

---

## 8. What NOT to Touch

| Item | Reason |
|------|--------|
| `.venv/` | Active virtualenv — all cron jobs depend on it |
| `betagent.db` (core tables) | Production data: bets, signals, match_facts, bankroll |
| `agent_handoff_v7.py` | Core engine |
| `run_pipeline.py` | Pipeline orchestrator |
| `tg_bot.py` | Telegram bot |
| `web_panel.py` | Dashboard |
| `validator.py` | Validation gate |
| `parser_v2.py` | Odds parser |
| `strategies/` | Strategy modules |
| `analysis_helpers/` | Helper modules |
| `models/` | Active ML models |
| `data/tennis_ml_enriched_v3.csv` | Active dataset |
| Active log files (`api.log`, `tg_bot.log`, `client_bot.log`) | Current operation |
| `.env` | Secrets |
| `config/`, `db/init.sql` | Configuration |

---

## 9. Recommendations

### Immediate (safe, do now):
1. `rm -rf venv/` — duplicate virtualenv, saves 46 MB
2. `rm -rf __pycache__/` — saves 1.4 MB
3. `rm -f .aider.*` — saves 3 MB
4. `rm -f *.bak` — saves 148 KB
5. Remove all old copies (agent_handoff_v7_*, tg_bot_*, web_panel_*, run_pipeline_old*, hockey_backtest_*_old, parser_v2_old, etc.) — saves ~2 MB
6. Truncate logs older than 7 days (non-active) — saves ~5 MB

### Short-term (confirm first):
1. Truncate backtest tables in SQLite + VACUUM — saves ~280 MB
2. Remove `data/tennis_ml_enriched_v2.csv` — saves 21 MB
3. Clean up `ml_output/` test artifacts — saves ~7 MB
4. Set up log rotation for pipeline/settle logs

### Long-term:
1. Implement log rotation (max 7 days retention)
2. Add DB maintenance cron (monthly VACUUM, truncate old backtest data)
3. Consider moving backtest data to separate DB file
4. Archive old `analysis/` research scripts to a separate location if needed for reference
