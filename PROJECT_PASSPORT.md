# PROJECT_PASSPORT.md

# BETAGENT --- Project Passport

Version: v2 draft\
Status: working master file\
Purpose: single source of truth describing the BETAGENT platform
architecture, current production state, and research roadmap.

------------------------------------------------------------------------

## 1. Purpose

BETAGENT is a betting platform running on a VPS designed to:

-   automatically parse bookmaker lines
-   enrich events with statistics and contextual data
-   analyze matches using rule‑based and model‑based strategies
-   generate betting recommendations
-   archive every decision and dataset snapshot
-   support research workflows (backtesting, CLV analysis, calibration)
-   eventually support automated execution after full validation

------------------------------------------------------------------------

## 2. Current Operational Reality

The production system is launched via:

-   run_server.sh
-   run_pipeline.py

Execution flow:

1.  load environment from `.env`
2.  change directory to `/root/betagent`
3.  run `python3 run_pipeline.py --now`
4.  run `python3 tg_bot.py --notify bets`
5.  log completion

The **true runtime behavior of the system is defined by
`run_pipeline.py`.**

This file determines:

-   which sports are processed
-   which modules run
-   when settle happens
-   when archive snapshots are created
-   when notifications are sent

If documentation differs from runtime behavior, `run_pipeline.py` is
considered the authoritative source.

------------------------------------------------------------------------

## 3. Strategic Goal

The long‑term objective:

Build a fully autonomous betting platform capable of:

-   parsing multiple sportsbooks
-   generating data‑driven betting decisions
-   validating strategies via research infrastructure
-   scaling across sports

Target performance goal:

**\> +4% bankroll growth per month (long‑term average)**

Important clarification:

This is a **target KPI**, not a guarantee.\
Edge must be validated using:

-   CLV
-   out‑of‑sample backtests
-   calibration tests
-   shadow comparisons

------------------------------------------------------------------------

## 4. Current System Modes

### Legacy Production

Real betting system.

Properties:

-   sports: football + hockey
-   real bankroll exposure
-   decision engine: `agent_handoff_v7.py`
-   participates in settle, bankroll tracking, notifications

Rule:

Legacy production must remain stable and must not be broken by research
refactoring.

------------------------------------------------------------------------

### Next Shadow System

Experimental research layer.

Properties:

-   implemented via `dual_agent_shadow_runner_v1.py`
-   compares legacy vs experimental strategies
-   does NOT execute real bets

Current product focus:

**football shadow testing only**

------------------------------------------------------------------------

### LLM Status

LLM decision layer is currently experimental and showing negative ROI.

Therefore:

-   it must be treated as a research hypothesis
-   it must pass CLV and backtests before production use
-   the platform architecture must not depend solely on LLM reasoning

------------------------------------------------------------------------

## 5. Data Flow

High‑level pipeline:

parsers\
→ matches table\
→ repair integrity\
→ enrichers / feature builders\
→ match_facts / feature snapshots\
→ decision engine\
→ validator\
→ bets / shadow_recommendations\
→ settlement\
→ archive snapshots\
→ notifications

------------------------------------------------------------------------

## 6. Core Database Entities

Primary tables:

-   matches
-   bets
-   shadow_recommendations

Archive tables:

-   odds_history
-   match_feature_snapshots
-   recommendation_snapshots

Future tables (v2):

-   pipeline_runs
-   pipeline_task_log
-   result_updates_log
-   clv_history
-   raw_ingestion_events

------------------------------------------------------------------------

## 7. Core Architecture Layers

### Orchestration Layer

Files:

-   run_server.sh
-   run_pipeline.py

Responsibilities:

-   scheduling
-   pipeline order
-   feature flags

Future improvement:

Move scheduling and tasks to a config file.

------------------------------------------------------------------------

### Data Ingestion Layer

Files:

-   parser_v2.py
-   the_sports_khl_parser.py
-   the_sports_nhl_parser.py

Responsibilities:

-   fetch bookmaker data
-   normalize match events
-   maintain ingestion timestamps

Future improvement:

Unified parser interface: `parse_sport(sport)`

------------------------------------------------------------------------

### Integrity Layer

File:

-   repair_pending_bets_v2.py

Responsibilities:

-   maintain links between bets and matches
-   protect pending bets after re‑parsing

Future improvement:

Introduce `match_linker` with audit history.

------------------------------------------------------------------------

### Feature Store Layer

Football enrichers:

-   enricher_football.py
-   enricher_football_rpl_v3.py
-   fetch_team_history.py
-   injuries_fetcher.py

Hockey enrichers:

-   enricher_from_the_sports.py
-   enricher_from_the_sports_nhl.py
-   sync_match_facts_v3.py

Responsibilities:

Build feature context for decision engines.

Future improvement:

Create unified feature snapshot builder.

------------------------------------------------------------------------

### Decision Layer

Legacy production decision engine:

-   agent_handoff_v7.py

Shadow research engine:

-   dual_agent_shadow_runner_v1.py

Target architecture:

Decision layer split into:

1.  shortlist generator
2.  reasoning layer
3.  validator
4.  bankroll policy

------------------------------------------------------------------------

### Settlement Layer

Files:

-   updater_results.py
-   tg_bot.py

Responsibilities:

-   settle matches
-   record results
-   send notifications

Future improvement:

Separate settlement engine with logging.

------------------------------------------------------------------------

### Archive & Research Layer

File:

-   historical_archive_v1.py

Responsibilities:

-   archive odds snapshots
-   archive feature snapshots
-   archive recommendations

Future modules:

-   clv_tracker.py
-   backtest_from_snapshots.py
-   strategy_lab.py
-   module_performance_report.py

------------------------------------------------------------------------

### Notification Layer

File:

-   tg_bot.py

Responsibilities:

-   notify bets
-   notify results
-   notify reports

Future commands:

/status\
/pending\
/results\
/shadow\
/bankroll\
/clv

------------------------------------------------------------------------

## 8. Architecture Rules

1.  Production and research must remain separate.
2.  Legacy engine must remain stable.
3.  Shadow system must never place real bets.
4.  Football is current research priority.
5.  Hockey research comes later.
6.  Every decision must be reproducible from archived snapshots.
7.  Every bet must be traceable to its feature state and line snapshot.

------------------------------------------------------------------------

## 9. Research Priorities

1.  stabilize system architecture
2.  implement CLV tracking
3.  build reproducible backtesting
4.  discover working strategies and parameters
5.  expand sports coverage

------------------------------------------------------------------------

## 10. Sports Expansion Plan

Planned sports:

-   Tennis
-   MMA
-   Basketball

Each sport must follow lifecycle:

1.  data ingestion
2.  feature layer
3.  baseline strategy
4.  validator integration
5.  archive support
6.  shadow testing
7.  CLV validation
8.  production candidate

------------------------------------------------------------------------

## 11. Project Thesis

BETAGENT v2 is not simply a betting bot.

It is a **research‑driven betting platform** where:

-   data is reproducible
-   strategies are testable
-   signals are measurable
-   decisions are auditable

The final goal is a system capable of autonomous analysis and execution
once edge is scientifically validated.
