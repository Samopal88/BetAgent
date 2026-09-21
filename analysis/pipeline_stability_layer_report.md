# Pipeline Stability Layer — Report

**Date:** 2026-04-13
**Scope:** Minimal hardening of `run_pipeline.py` — fail-fast, task wrapper, run summary, sanity checks

---

## Changes

### New File: `pipeline_stability.py`

Core stability primitives:

| Component | Purpose |
|-----------|---------|
| `TaskResult` | Dataclass: name, started_at, ended_at, duration, success, error, metadata |
| `RunSummary` | Collects per-task results, aggregates counters, saves JSON + text |
| `run_task(name, fn, summary)` | Wraps any callable with timing, exception handling, auto-adds to summary |
| `check_parse_sanity(sport, db)` | Verifies parsed matches exist, odds are in range, no stale pending matches |
| `check_enrich_sanity(sport, db)` | Verifies enrichment produced data today |

### Modified File: `run_pipeline.py`

Changes are **additive** — existing `run()` function and task signatures are preserved.

1. **Import stability layer** — `RunSummary`, `run_task`, sanity checks
2. **Tasks return metadata** — `task_parse()`, `task_enrich_*()`, `task_bet_*()`, `task_settle()`, `task_tennis_*()`, `task_notify_*()` now return `dict` with counters
3. **Runners use `run_task()` wrapper** — All 5 runners (`morning`, `afternoon`, `evening`, `night`, `full`) wrap each step in `run_task()`
4. **Fail-fast logic** — If `parse` fails, dependent enrich/bet steps are skipped. If `enrich_football` fails, `bet_football` is skipped. Same for hockey.
5. **Dead code detection** — `task_notify_client()` and `task_notify_tennis()` now check if `bot/notifier.py` exists before attempting to call it, logging a warning instead of silently failing
6. **Run summary** — Each runner creates a `RunSummary`, saves JSON + text to `run_summaries/`, and logs the text summary

---

## Fail-Fast Behavior

### Dependency Graph

```
parse ──┬── enrich_football ── bet_football
        │
        └── enrich_hockey ── bet_hockey

bet_tennis (independent — runs even if parse fails)
settle (independent — runs even if parse fails)
notify/archive (non-critical — always runs)
```

### Rules

| Failure | Action |
|---------|--------|
| `parse` fails | Skip `enrich_football`, `enrich_hockey`, `bet_football`, `bet_hockey`. Tennis still runs. |
| `enrich_football` fails | Skip `bet_football`. Hockey and tennis still run. |
| `enrich_hockey` fails | Skip `bet_hockey`. Football and tennis still run. |
| `settle` fails | Log warning, continue (results may be stale but not critical) |
| `notify` fails | Log warning, continue (non-critical) |
| `bot/notifier.py` missing | Log warning, skip (no crash) |

---

## Run Summary Format

### JSON (`run_summaries/morning_20260413_080000.json`)

```json
{
  "runner": "morning",
  "dry_run": true,
  "started_at": "2026-04-13 08:00:01",
  "ended_at": "2026-04-13 08:05:32",
  "fail_fast_triggered": false,
  "fail_fast_reason": "",
  "notes": [],
  "summary": {
    "total_tasks": 12,
    "succeeded": 11,
    "failed": 1,
    "skipped": 0,
    "total_duration_sec": 331.0,
    "counters": {
      "matches_parsed": 24,
      "signals_created": 3,
      "bets_created": 1,
      "bets_settled": 5,
      "notifications_sent": 2
    }
  },
  "tasks": [
    {
      "name": "settle",
      "status": "ok",
      "duration_sec": 15.2,
      "error": "",
      "metadata": {"settle_ok": true, "bets_settled": 5}
    },
    {
      "name": "parse",
      "status": "ok",
      "duration_sec": 42.1,
      "error": "",
      "metadata": {"matches_parsed": 24, "football_ok": true, "hockey_ok": true, "warnings": []}
    },
    ...
  ]
}
```

### Text (logged to pipeline.log)

```
============================================================
RUN SUMMARY — morning (DRY-RUN)
Started: 2026-04-13 08:00:01
Ended:   2026-04-13 08:05:32
Tasks:   11/12 ok, 1 failed, 0 skipped
Duration: 331.0s total
------------------------------------------------------------
  [OK] settle (15.2s) | bets_settled=5
  [OK] parse (42.1s) | matches_parsed=24
  [OK] enrich_football (28.3s)
  [OK] enrich_hockey (35.7s)
  [OK] bet_football (120.5s) | signals_created=2, bets_created=1
  [OK] bet_hockey (45.2s) | signals_created=1, bets_created=0
  [OK] bet_tennis (18.4s) | signals_created=0
  [OK] archive_snapshot (5.1s)
  [OK] tennis_results (3.2s)
  [OK] tennis_settle (2.8s)
  [FAIL] notify_bets (0.0s) — ConnectionError: timeout
  [OK] notify_client (1.5s)
  [OK] publish_channel (1.0s)
============================================================
```

---

## Sanity Checks

### `check_parse_sanity(sport, db)`

After parsing, checks:
- **Matches today** — Are there matches with today's date? (Warns if 0, doesn't fail — could be off-day)
- **Odds presence** — Do matches have odds? (Warns if matches exist but none have odds — parser may be broken)
- **Odds range** — Are odds in 1.01–50.0 range? (Warns if suspicious)
- **Stale pending matches** — Are there old pending matches? (Warns if > 0)

### `check_enrich_sanity(sport, db)`

After enrichment, checks:
- **Match facts updated today** — Were any `match_facts` rows updated today?

---

## What Was NOT Changed

- Strategy logic (no changes to `agent_handoff_v7.py`, `hockey_backtest_fast_v2.py`, etc.)
- ML logic (no changes to `tennis_live_pipeline.py`)
- Database schema
- Notification formatting
- Parser logic
- Settlement logic
- Existing `run()` function (preserved for backward compatibility)
- CLI interface (`--now`, `--settle`, `--dry-run`, `--run`)

---

## What Still Remains Weak

1. **`agent_handoff_v7.py` is still a 5200-line god file** — This hardening layer doesn't touch it. If it crashes internally, the wrapper catches it, but the root cause remains.

2. **No health monitoring / alerting** — Run summaries are saved to files, but nobody is automatically alerted if a run fails. Still requires manual log checking.

3. **No idempotency guarantee** — Running the pipeline twice can still create duplicate signals. The wrapper tracks what happened but doesn't prevent duplicates.

4. **Settlement still uses fuzzy matching** — `settler.py` unchanged.

5. **No test coverage** — The stability layer itself has no automated tests.

6. **`bot/notifier.py` still doesn't exist** — We detect and warn, but the underlying issue (missing client notification system) is unresolved.

7. **Sanity checks are basic** — They warn but don't block. A parser returning garbage data with plausible-looking odds would pass.

---

## Answers

1. **task wrapper added?** — Yes. `run_task()` in `pipeline_stability.py`
2. **fail-fast added?** — Yes. Parse failure skips dependent steps. Enrich failure skips sport-specific betting.
3. **run summary added?** — Yes. JSON + text saved to `run_summaries/` directory, text logged to `pipeline.log`
4. **pipeline safer now?** — Yes. Silent failures are now logged, tracked, and visible. Dependent steps are skipped on upstream failure.
5. **what still remains weak?** — God file (`agent_handoff_v7.py`), no alerting on failure, no idempotency, fuzzy settlement, no tests, dead `bot/notifier.py`
