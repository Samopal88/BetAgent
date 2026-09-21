# Tennis Pipeline Stabilization Step 1

## Scope

Minimal tennis-only stabilization applied in:

- [tennis_live_pipeline.py](/root/betagent/tennis_live_pipeline.py)
- [run_pipeline.py](/root/betagent/run_pipeline.py)

No football or hockey logic was changed.

## Changes

1. Stable tennis live identity:
- Primary key is now `source_match_id + market`.
- Fallback is now normalized Russian `player1 + player2 + match_date + market`.
- Active tennis live dedup now uses this identity instead of English canonicalization.

2. Stable signal -> bet linkage:
- `tennis_signals` now carries `source_match_id`, `live_identity`, and `bet_id`.
- When a tennis bet is created or found, the linked `bet_id` is stored on the signal row.

3. Tennis-only status sync repair:
- Added linked-bet sync so a settled linked bet forces the signal out of `pending`.
- Settlement updates `tennis_signals.status` and `tennis_signals.result` together.
- Existing linked mismatches are repaired before settlement proceeds.

4. Evening tennis notification duplication reduced:
- Removed the separate evening `task_notify_tennis("results")` call.
- Unified result notification path remains active.

## Verification

Verification used a temporary SQLite fixture, not the production DB, because the live DB path available in this workspace is not populated.

### Duplicate prevention on rerun

Fixture result:

- First `_create_tennis_bet(...)` returned bet id `1`
- Second `_create_tennis_bet(...)` with the same live identity returned the same bet id
- Bet row count after rerun: `1`

Conclusion:

- No new duplicate tennis bet was created on rerun in the verified path.

### Signal -> bet linkage

Fixture result:

- Inserted tennis signal stored `bet_id = 1`

Conclusion:

- Explicit signal -> bet linkage exists.

### Zero-stake settlement path

Fixture result:

- Linked tennis signal had `stake_pct = 0.0`
- Linked bet had `stake = 500.0`
- After settlement, bet profit became `400.0` at odds `1.8`

Interpretation:

- Bet settlement still uses the original bet stake from `bets.stake`
- It no longer depends on a zero signal stake for bet PnL

Relevant code:

- Signal-side display profit still derives from `stake_pct`
- Bet-side settlement uses `original_stake`

### Pending/settled mismatch repair

Fixture result:

- Linked bet was preset to `result='won'`, `profit=400.0`, `settled_at='2026-04-19 10:00:00'`
- Linked signal started as `status='pending'`, `result='pending'`
- `_sync_linked_tennis_signals(...)` repaired `1` row
- Signal became:
  - `status='won'`
  - `result='won'`
  - `profit=400.0`
  - `settled_at='2026-04-19 10:00:00'`

Conclusion:

- One pending/settled mismatch case is resolved correctly.

## Notes

- English name canonicalization helpers still exist for non-active settlement support, but they are no longer in the active live tennis dedup path.
- `run_pipeline.py` already had unrelated local modifications in this worktree; this step only removed the separate evening tennis results notification call.
