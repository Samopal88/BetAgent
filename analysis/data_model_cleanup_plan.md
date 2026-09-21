# Data Model Cleanup Plan

**Date:** 2026-04-13
**Scope:** Pragmatic data model audit — categorize tables, identify sources of truth, plan safe normalization
**Constraint:** No destructive migration. Plan first, act later.

---

## 1. Table Inventory — Categorized

### 1A. LIVE PRODUCTION (core operational tables)

| Table | Rows | Role | Source of Truth | Action |
|-------|------|------|----------------|--------|
| `matches` | 678 | Current live matches from Fonbet parser | **YES** — canonical live match list | **KEEP** — add indexes |
| `bets` | 147 | Placed bets with status, profit, settlement | **YES** — canonical live bet record | **KEEP** — add indexes |
| `results_raw` | 3,116 | Match results from external scrapers | **YES** — canonical result source for settlement | **KEEP** — add indexes |
| `match_facts` | 20,949 | Enriched match context (form, table, H2H, injuries) | Secondary — derived from external APIs | **KEEP** — used by live pipeline |
| `standings` | 80 | Current league standings | Secondary — derived | **KEEP** |
| `team_injuries` | 0 | Team injury data | Secondary — derived | **KEEP** (empty but schema is right) |
| `bankroll_state` | 1 | Current bankroll tracking | **YES** — single row of truth | **KEEP** |
| `rules` | 6 | Active betting rules | Secondary — reference | **KEEP** |

### 1B. SIGNALS / RECOMMENDATIONS

| Table | Rows | Role | Source of Truth | Action |
|-------|------|------|----------------|--------|
| `handoff_decisions` | 24,781 | All LLM/rule recommendations (PASS + bets) | **YES** — canonical recommendation log | **KEEP** — needs archival |
| `shadow_recommendations` | 1,785 | Shadow mode recommendations | Secondary — research/comparison | **KEEP** — needs archival |
| `tennis_signals` | 46 | Tennis ML pipeline signals | **YES** — canonical tennis signal record | **KEEP** — add indexes |
| `recommendation_snapshots` | 25,459 | Historical snapshots of recommendations | Secondary — audit trail | **ARCHIVE** — growing unbounded |

### 1C. SETTLEMENT / RESULTS

| Table | Rows | Role | Source of Truth | Action |
|-------|------|------|----------------|--------|
| `bets.result` | (column) | Settlement status per bet | **YES** — final settlement truth | **KEEP** |
| `accuracy_log` | 102 | Per-settlement accuracy records | Secondary — derived from bets | **KEEP** — add index |
| `tennis_live_results` | 6 | Fresh tennis match results | Secondary — cache from updater | **KEEP** |
| `tennis_signals.result` | (column) | Tennis signal settlement | Secondary — mirrors bet settlement for tennis | **KEEP** |

### 1D. NOTIFICATIONS

| Table | Rows | Role | Source of Truth | Action |
|-------|------|------|----------------|--------|
| `tg_notifications` | 236 | Admin notification dedup tracking | **YES** — canonical notification log | **KEEP** |
| `channel_sent_log` | 17 | Channel publication log | **YES** — canonical channel log | **KEEP** |

### 1E. ENRICHMENT / MATCH FEATURES

| Table | Rows | Role | Source of Truth | Action |
|-------|------|------|----------------|--------|
| `match_features` | 1,656 | Live match feature vectors | Secondary — derived for analysis | **KEEP** — used by live pipeline |
| `match_feature_snapshots` | 27,615 | Historical feature snapshots | Secondary — audit/odds tracking | **ARCHIVE** — growing unbounded |
| `hockey_match_features` | 1,891 | Hockey-specific features | Secondary — derived | **KEEP** |
| `football_rolling_features` | 46,312 | Rolling football features | Secondary — research/ML prep | **SPLIT** — research data |
| `football_features_ml_v1` | 60,586 | Football ML feature dataset | Secondary — research | **SPLIT** — research data |

### 1F. ODDS / COMPARISON

| Table | Rows | Role | Source of Truth | Action |
|-------|------|------|----------------|--------|
| `odds_history` | 27,615 | Historical Fonbet odds snapshots | Secondary — CLV tracking | **ARCHIVE** — growing unbounded |
| `odds_avg` | 26 | Averaged odds across bookmakers | Secondary — derived | **KEEP** (small) |
| `odds_merged` | 27 | Best odds across bookmakers | Secondary — derived | **KEEP** (small) |
| `odds_pari` | 130 | Pari bookmaker odds | Secondary — comparison | **KEEP** (small) |
| `odds_leon` | 6 | Leon bookmaker odds | Secondary — comparison | **KEEP** (small) |
| `odds_betboom` | 0 | BetBoom odds | Secondary — comparison | **DROP** (empty) |

### 1G. BACKTEST / RESEARCH

| Table | Rows | Role | Source of Truth | Action |
|-------|------|------|----------------|--------|
| `backtest_matches` | 17,263 | Historical football matches | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_hockey_matches` | 104,677 | Historical hockey matches | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_hockey_features` | 104,677 | Hockey backtest features | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_hockey_features_v2` | 0 | Empty v2 features | — | **DROP** (empty) |
| `backtest_football_matches_betz` | 60,586 | Betz football historical | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_football_market_features_v2` | 60,586 | Market features | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_football_special_markets_betz` | 24,597 | Special markets | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_football_stats` | 16,201 | Football stats (corners, YC, shots) | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_tennis_matches` | 26,686 | Historical tennis matches | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_tennis_players` | 28,235 | Tennis player match data | Secondary — backtest data | **SPLIT** — move to research DB |
| `backtest_equity` | 2,073 | Backtest equity curves | Secondary — backtest results | **SPLIT** — move to research DB |
| `tennis_data_odds` | 15,245 | Historical tennis odds | Secondary — research | **SPLIT** — move to research DB |
| `tennis_player_mapping` | 950 | Tennis name mapping (EN↔RU) | Secondary — operational mapping | **KEEP** — used by live pipeline |
| `tennis_name_lookup` | 2,390 | Tennis name lookup | Secondary — operational mapping | **KEEP** — used by live pipeline |
| `tennis_player_mapping_review` | 536 | Pending name mappings | Secondary — review queue | **KEEP** — used by live pipeline |

### 1H. TEMP / UNDOCUMENTED

| Table | Rows | Role | Referenced By | Action |
|-------|------|------|---------------|--------|
| `_j` | 1,764 | Tennis join temp table | `tennis_fast_strategy.py` (research only) | **DROP** — research artifact |
| `_j2` | 2,648 | Tennis join temp table | **NOWHERE** | **DROP** — orphaned |
| `_jtm` | 70 | Tennis tournament mapping | `tennis_join_improved.py` (research only) | **DROP** — research artifact |
| `_btm` | 303 | Tennis bookmaker mapping | `tennis_join_improved.py` (research only) | **DROP** — research artifact |
| `_m12_ids` | 1,764 | Tennis match IDs | `tennis_join_improved.py` (research only) | **DROP** — research artifact |
| `_m3_ids` | 0 | Tennis match IDs | `tennis_join_improved.py` (research only) | **DROP** — empty + research |

### 1I. ANALYTICS / REPORTING

| Table | Rows | Role | Source of Truth | Action |
|-------|------|------|----------------|--------|
| `clv_history` | 110 | Closing Line Value tracking | Secondary — derived from bets | **KEEP** — add indexes |
| `league_edge_report` | 1,319 | League-level edge analysis | Secondary — analytics | **KEEP** |

---

## 2. Source of Truth — Explicit Answers

### What is the canonical source of truth for live bets?

**`bets` table** in `betagent.db`.

- Columns: `id`, `match_id`, `market`, `odds`, `stake`, `result`, `profit`, `settled_at`
- `handoff_decisions` is the recommendation log (pre-bet), not the bet itself
- `tennis_signals` is the tennis-specific signal log (pre-bet for tennis)
- `bets` is the only table that tracks actual placed bets with settlement status

**Gap:** `bets` has no indexes. Queries by `match_id`, `result`, `created_at` are full table scans.

### What is the canonical source of truth for live results?

**`results_raw`** for football/hockey results (external scraper output).
**`tennis_live_results`** for tennis results (from updater).

**Gap:** Two separate result sources with different schemas. No unified result table. Settlement reads from `results_raw` directly, which means if the scraper changes format, settlement breaks.

### What is the canonical source of truth for notifications?

**`tg_notifications`** for admin notifications (dedup tracking).
**`channel_sent_log`** for channel publications.

**Gap:** These tables track "what was sent" but not "what should have been sent." There's no notification queue — just a dedup log.

### What is the canonical source of truth for settlement status?

**`bets.result`** column (`pending` / `won` / `lost`) + `bets.settled_at` timestamp.

**Gap:** `settler.py` uses fuzzy string matching (`LIKE '%substr%'`) to link results to bets. No canonical team name mapping means settlement can be wrong.

---

## 3. Dangerous Areas

### 3.1 Duplicated Concepts

| Concept | Tables | Problem |
|---------|--------|---------|
| Match data | `matches`, `match_facts`, `match_features`, `match_feature_snapshots`, `backtest_matches`, `backtest_hockey_matches`, `backtest_tennis_matches` | 7 tables with overlapping match info |
| Odds data | `matches.odds_*`, `odds_history`, `odds_avg`, `odds_merged`, `odds_pari`, `odds_leon`, `odds_betboom` | 7 tables/sets of columns for odds |
| Recommendations | `handoff_decisions`, `shadow_recommendations`, `recommendation_snapshots` | 3 tables for the same concept |
| Tennis results | `tennis_live_results`, `tennis_signals.result`, `backtest_tennis_matches` | 3 tables with overlapping result data |
| Features | `match_features`, `match_feature_snapshots`, `hockey_match_features`, `football_rolling_features`, `football_features_ml_v1` | 5 tables for features |

### 3.2 Weak or Missing Unique Keys

| Table | Issue | Risk |
|-------|-------|------|
| `bets` | No indexes at all | Slow queries, no duplicate prevention |
| `matches` | `fonbet_id` is UNIQUE (good) but no index on `sport`, `match_date` | Slow lookups |
| `handoff_decisions` | No unique constraint on `(match_id, market)` | Duplicate recommendations possible |
| `accuracy_log` | No indexes | Slow aggregation queries |
| `standings` | No unique constraint on `(league, team_name)` | Duplicate standings possible |
| `match_facts` | `match_id` is UNIQUE (good) but `match_id` is not a FK to `matches` | Orphaned records possible |

### 3.3 Missing Foreign-Key-Like Relationships

- `bets.match_id` → `matches.id` — no FK, no index. `repair_pending_bets_v2.py` exists specifically to fix broken links.
- `match_facts.match_id` → `matches.id` — no FK
- `match_features.match_id` — no FK, no clear target table
- `handoff_decisions.match_id` — no FK
- `clv_history.bet_id` — no FK to `bets`
- `clv_history.match_id` — no FK to `matches`

### 3.4 Temp/Undocumented Tables

All 6 underscore-prefixed tables (`_j`, `_j2`, `_jtm`, `_btm`, `_m12_ids`, `_m3_ids`) are **research artifacts** from tennis data joins. Only `_j` is referenced by `tennis_fast_strategy.py` (a research script, not the live pipeline). The other 5 are completely orphaned.

### 3.5 Live and Research Data Mixed

The production DB (`betagent.db`) contains:
- **~500 rows** of live operational data (matches, bets, signals, notifications)
- **~400,000+ rows** of backtest/research data (backtest_*, features_ml, rolling_features)

This means:
- Backup/restore is slow (mostly research data)
- Queries on live tables scan a bloated DB file
- No clear boundary between "this is production" and "this is research"

---

## 4. Target Data Model Proposal

### 4.1 Canonical Entities

```
┌─────────────────────────────────────────────────────────────┐
│  canonical_match                                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ id (PK) | fonbet_id (UNIQUE) | sport | league       │    │
│  │ home_team | away_team | match_date | status          │    │
│  │ odds_home | odds_draw | odds_away | ...              │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  live_signal                                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ id (PK) | match_id (FK) | sport | market | odds     │    │
│  │ our_probability | ev | confidence | signal_type     │    │
│  │ decision | created_at | rule                        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  live_bet                                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ id (PK) | match_id (FK) | market | odds | stake     │    │
│  │ result | profit | settled_at | created_at            │    │
│  │ our_probability | ev | kelly_quarter | signal_type   │    │
│  │ rule | confidence | market_error                    │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  normalized_result                                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ id (PK) | sport | league | home_team | away_team    │    │
│  │ match_date | home_score | away_score | is_finished  │    │
│  │ is_overtime | source | updated_at                    │    │
│  │ UNIQUE(sport, league, match_date, home_team, away)  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  settlement_event                                           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ id (PK) | bet_id (FK) | result | profit | settled_at│    │
│  │ source | verified_at                                │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

Research data → separate betagent_research.db
Audit/snapshot data → archived monthly to CSV or separate tables
```

### 4.2 Key Design Decisions

1. **`normalized_result`** replaces the current dual-source pattern (`results_raw` + sport-specific result tables). Single table with `source` column for provenance.

2. **`settlement_event`** separates the settlement action from the bet record. This enables re-settlement, void handling, and audit trails without mutating the bet record.

3. **`live_signal`** unifies `handoff_decisions` (filtered to non-PASS) and `tennis_signals` into a single concept. Sport-specific columns can be JSON.

4. **Research data** moves to `betagent_research.db` — separate file, separate backup strategy, no impact on live operations.

---

## 5. Safe Implementation Roadmap

### A. Minimal Safe Changes Now (1–3 days)

| # | Action | Risk | Impact |
|---|--------|------|--------|
| A1 | **Add indexes to `bets`** — `CREATE INDEX idx_bets_match_id ON bets(match_id)`, `CREATE INDEX idx_bets_result ON bets(result)`, `CREATE INDEX idx_bets_created_at ON bets(created_at)` | None (additive) | Faster settlement queries, bet counting, web panel |
| A2 | **Add indexes to `matches`** — `CREATE INDEX idx_matches_sport_date ON matches(sport, match_date)`, `CREATE INDEX idx_matches_status ON matches(status)` | None (additive) | Faster parse lookups, stale match detection |
| A3 | **Add index to `accuracy_log`** — `CREATE INDEX idx_accuracy_created ON accuracy_log(created_at)` | None (additive) | Faster accuracy aggregation |
| A4 | **Drop empty tables** — `DROP TABLE _m3_ids`, `DROP TABLE backtest_hockey_features_v2`, `DROP TABLE odds_betboom`, `DROP TABLE team_injuries` | Low (all empty) | Cleaner schema, less confusion |
| A5 | **Drop orphaned temp tables** — `DROP TABLE _j2` (referenced nowhere) | Low (not used by live code) | Cleaner schema |
| A6 | **Add UNIQUE constraint to `standings`** — `CREATE UNIQUE INDEX idx_standings_league_team ON standings(league, team_name)` | Low (additive) | Prevents duplicate standings |
| A7 | **Document remaining temp tables** — Add comment/note that `_j`, `_jtm`, `_btm`, `_m12_ids` are tennis research artifacts, safe to drop after research scripts are updated | None (documentation) | Clear ownership |

### B. Medium Refactor Later (1–3 weeks)

| # | Action | Risk | Impact |
|---|--------|------|--------|
| B1 | **Split research DB** — Move all `backtest_*`, `football_features_ml_v1`, `football_rolling_features`, `tennis_data_odds` to `betagent_research.db`. Update code references. | Medium (code changes) | Live DB shrinks from ~400MB to ~5MB |
| B2 | **Archive growing tables** — Move `handoff_decisions` > 90 days old, `recommendation_snapshots` > 30 days old, `odds_history` > 30 days old to archive tables or CSV | Medium (data movement) | Prevents unbounded growth |
| B3 | **Add canonical team name mapping** — Single `team_aliases` table with `(canonical_name, alias, sport)` | Low (additive) | Enables exact-match settlement |
| B4 | **Create `normalized_result` table** — Unified result table with sport, source, unique constraint. Migrate `results_raw` data. | Medium (migration) | Single source of truth for results |
| B5 | **Drop remaining temp tables** — After updating `tennis_fast_strategy.py` and `tennis_join_improved.py` to not use `_j`, `_jtm`, `_btm`, `_m12_ids` | Low (after code fix) | Clean schema |
| B6 | **Add FK-like constraints** — `PRAGMA foreign_keys = ON` + add indexes on FK columns | Low (additive) | Data integrity |

### C. What Should NOT Be Touched Yet

| Item | Why Not Yet |
|------|------------|
| `bets` table schema | Working, 147 rows, no bugs reported. Add indexes, don't change columns |
| `matches` table schema | Working, parser writes to it correctly |
| `settler.py` logic | Working settlement. Fix data quality (team names) first, then logic |
| `handoff_decisions` structure | Well-indexed, used by web panel and analysis |
| PostgreSQL SaaS schema | Separate concern, working independently |
| Tennis ML tables | `tennis_signals`, `tennis_player_mapping` are working fine |
| `tg_notifications` | Working dedup mechanism, no issues |

---

## 6. Summary Answers

1. **source of truth for live bets** = `bets` table in `betagent.db`. `handoff_decisions` is the recommendation log (pre-bet). `tennis_signals` is the tennis signal log (pre-bet).

2. **source of truth for results** = `results_raw` for football/hockey, `tennis_live_results` for tennis. Two separate sources, no unified result table — this is a gap.

3. **biggest current data-model problem** = **400K+ rows of research data sharing the same DB as ~500 rows of live production data.** This bloats backups, slows queries, and blurs the line between "this is production" and "this is research." Second biggest: no indexes on `bets` table.

4. **what can be fixed safely right now** = Add indexes to `bets`, `matches`, `accuracy_log`. Drop 5 empty/orphaned tables. Document remaining temp tables. All additive, zero risk.

5. **what should be migrated later** = Split research DB, archive growing tables, create unified result table, add canonical team name mapping. These require code changes and testing.
