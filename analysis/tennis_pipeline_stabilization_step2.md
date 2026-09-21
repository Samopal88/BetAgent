# Tennis Pipeline Stabilization Step 2

## Scope

Tennis only.

Applied:

- live DB cleanup on `/mnt/data/betagent/betagent.db`
- code patches in:
  - [tennis_live_pipeline.py](/root/betagent/tennis_live_pipeline.py)
  - [backfill_tennis_bets.py](/root/betagent/backfill_tennis_bets.py)

Reference SQL used for the live DB cleanup:

- [tennis_pipeline_step2_cleanup.sql](/root/betagent/analysis/tennis_pipeline_step2_cleanup.sql)

Safety step:

- SQLite backup created before cleanup: `/tmp/betagent_pre_tennis_step2_20260419.db`

## Pre-cleanup Audit

Live DB state before cleanup:

- `tennis_signals`: 60 rows
- duplicate tennis signal groups by Russian match identity + market: 3
- duplicate tennis bet groups by Russian match identity + market: 3
- `tennis_signals` still had stale `status='pending'` on settled rows: 57 rows
- `tennis_signals` had no `source_match_id`, `live_identity`, `bet_id`, or `signal_key` columns

Duplicate signal groups found:

1. `2026-04-15 | player2_win | Блокс А vs Шелтон Б`
   Rows: `49, 52, 56`
2. `2026-04-15 | player2_win | Марожан Ф vs Циципас С`
   Rows: `50, 53`
3. `2026-04-16 | player1_win | Мухова К vs Мертенс Э`
   Rows: `51, 55, 57, 58, 59`

Duplicate bet groups found:

1. `2026-04-15 | player2_win | Блокс А vs Шелтон Б`
   Bets: `916, 919, 923`
2. `2026-04-15 | player2_win | Марожан Ф vs Циципас С`
   Bets: `917, 920`
3. `2026-04-16 | player1_win | Мухова К vs Мертенс Э`
   Bets: `918, 922, 924`

## Canonical Decisions

### Tennis signals

Rule used:

- rank signals by `created_at, id` inside the stable Russian match identity group
- rank tennis bets the same way inside the matching group
- pair signal rank N with bet rank N
- if a signal has no matching bet after rank pairing, archive it as `archived_duplicate`

Decisions:

1. `Блокс А vs Шелтон Б | player2_win`
   Keep signal `49` linked to bet `916`
   Keep signal `52` linked to bet `919`
   Keep signal `56` linked to bet `923`

2. `Марожан Ф vs Циципас С | player2_win`
   Keep signal `50` linked to bet `917`
   Keep signal `53` linked to bet `920`

3. `Мухова К vs Мертенс Э | player1_win`
   Keep signal `51` linked to bet `918`
   Keep signal `55` linked to bet `922`
   Keep signal `57` linked to bet `924`
   Archive signal `58` as `archived_duplicate`
   Archive signal `59` as `archived_duplicate`

### Tennis bets

Rule used:

- no settled tennis bet rows were deleted or voided
- settled duplicate bet rows were left untouched because they are financial ledger entries and changing them would rewrite historical PnL

Left untouched:

- bet groups `916/919/923`, `917/920`, `918/922/924`

## Live DB Changes Applied

Schema migration:

- added `tennis_signals.source_match_id`
- added `tennis_signals.live_identity`
- added `tennis_signals.bet_id`
- added `tennis_signals.signal_key`
- added partial unique index `idx_tennis_signals_signal_key_pending`

Data cleanup:

- backfilled `live_identity` and `signal_key` for existing rows
- backfilled `bet_id` by deterministic rank pairing within each tennis identity group
- synchronized linked `tennis_signals` from linked `bets`
- normalized stale `status='pending'` rows to settled status values
- archived unlinked surplus duplicate signal rows

## Post-cleanup Verification

### Active duplicates

Real pending definition used:

- pending means `result IS NULL OR result='pending'`

Results:

- duplicate active tennis signal groups: `0`
- duplicate active tennis bet groups: `0`

### Linked signal/bet state

Results:

- pending signal linked to settled bet: `0`
- linked tennis signals after backfill: `58`

Example repaired rows:

- signal `49` was corrected from stale `won`-style signal settlement to linked bet `916`:
  - `status='lost'`
  - `result='lost'`
  - `profit=-476.32`
  - `settled_at='2026-04-16 20:30:04'`
- signals `58` and `59` were marked `archived_duplicate`

### Backfill safety

`backfill_tennis_bets.py` now:

- uses real pending definition from `result`
- ignores already linked rows via `bet_id`
- uses stable tennis live identity instead of stale English dedup
- writes `bet_id`, `live_identity`, and `signal_key` back to `tennis_signals`

Verification query result:

- stale settled rows that still qualify as backfill candidates: `0`

## Residual Risk

Historical duplicate settled bet rows remain in the live DB:

- duplicate historical bet groups still present: `3`
- extra historical bet rows beyond one canonical row per identity group: `5`

These were intentionally left untouched because rewriting settled bet rows would alter financial history.

Historical duplicate signal groups also still exist as history:

- duplicate historical signal groups still present: `3`
- extra historical signal rows beyond one canonical row per identity group: `7`

Interpretation:

- `5` of those extra signal rows remain linked to distinct historical duplicate bets
- `2` of those extra signal rows are now explicitly marked `archived_duplicate`

## Conclusion

Step 2 achieved the safe part of the cleanup:

- no duplicate active tennis bets remain
- no duplicate active tennis signals remain
- no pending signal linked to a settled bet remains
- stale backfill recreation path is closed

What remains is legacy settled duplicate bet history, intentionally preserved for safety.
