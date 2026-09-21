# Tennis Pipeline Audit

Date: 2026-04-19
Scope: tennis only
Code reviewed: `tennis_live_pipeline.py`, `backfill_tennis_bets.py`, `analysis_helpers/probability_pipeline.py`, `run_pipeline.py`, `bot/notifier.py`
DB reviewed: `/mnt/data/betagent/betagent.db`

## 1. Architecture overview

### Code path

1. `run_pipeline.py`
   Runs tennis generation via `task_bet_tennis()` -> `tennis_live_pipeline.py`, then `task_tennis_results()`, then `task_tennis_settle()`, then client/admin notifications.

2. `tennis_live_pipeline.py`
   - loads live tennis matches
   - canonicalizes players for dedup / `fonbet_id` / `bets.created_by`
   - inserts into `tennis_signals`
   - bridges each signal into `matches` + `bets`
   - settles via `settle_tennis_signals()`

3. `backfill_tennis_bets.py`
   Recreates `matches` + `bets` rows from `tennis_signals` for rows still considered pending.

4. Notifications
   - general client flow: `bot/notifier.py --mode bets|results` reads from `bets`
   - separate tennis flow still exists: `bot/notifier.py --mode ... --tennis` reads from `tennis_signals`

### Tables in practice

- `tennis_signals` is the tennis-specific signal ledger.
- `matches` stores the tennis match row used by `bets.match_id`.
- `bets` is the actual stake/profit ledger.
- `tennis_live_results` is the primary settlement source.
- `client_notifications` is not in SQLite; `bot/notifier.py` uses PostgreSQL for it.

### Files requested but not actually driving tennis

- `analysis_helpers/probability_pipeline.py`: no tennis-specific execution path here; it is helper code for other sports and is not imported by `tennis_live_pipeline.py`.
- `strategies/tennis.py`: file is absent in this workspace. Tennis strategy is embedded directly in `tennis_live_pipeline.py`.

## 2. Issues found

### High

#### 2.1 Match identity is not Russian-only and is not stable

`tennis_live_pipeline.py:153-204` and `backfill_tennis_bets.py:20-37` claim to canonicalize names, but:

- `load_name_mapping()` stores keys with original case.
- `canonicalize_name()` lowercases input before lookup.
- therefore Russian names from `tennis_player_mapping` usually miss the mapping and fall back to raw lowercase.
- English variants from `tennis_name_lookup` do map.

Result: the same match can produce different IDs:

- `tennis_2026-04-15_Blockx A._ben shelton_player2_win`
- `tennis_2026-04-15_Блокс А_Шелтон Б_player2_win`
- `tennis_2026-04-15_блокс а_шелтон б_player2_win`

Observed in live DB:

- duplicate match rows:
  - `2026-04-15 Блокс А vs Шелтон Б` -> match ids `33700, 34015, 34202`
  - `2026-04-16 Мухова К vs Мертенс Э` -> match ids `33806, 34018, 34203`
- duplicate bet groups:
  - `2026-04-15 Блокс А vs Шелтон Б player2_win` -> bet ids `916, 919, 923`
  - `2026-04-16 Мухова К vs Мертенс Э player1_win` -> bet ids `918, 922, 924`

This violates the requirement that tennis use Russian names only and have one stable identifier across ingestion, bet creation, settlement, and notifications.

Relevant code:

- `tennis_live_pipeline.py:153-204`
- `tennis_live_pipeline.py:723-741`
- `backfill_tennis_bets.py:20-37`
- `backfill_tennis_bets.py:79-97`

#### 2.2 Duplicate protection is incomplete

Application-level dedup only checks existing pending signals loaded before the current run:

- `tennis_live_pipeline.py:804-820`
- `tennis_live_pipeline.py:941-947`

But the current run never adds newly accepted keys back into the in-memory set, so duplicate source rows inside one pipeline run can both pass.

Database-level protection exists only for `bets.created_by` and only when:

- the `created_by` string matches exactly
- `result = 'pending'`

Schema:

```sql
CREATE UNIQUE INDEX idx_bets_tennis_dedup
ON bets(created_by)
WHERE created_by LIKE 'tennis_%' AND result = 'pending';
```

Problems:

- it does not protect `tennis_signals` at all
- it does not protect different `created_by` spellings for the same Russian match
- it stops protecting a row once it is settled

Observed in DB:

- `tennis_signals`: 60 rows total, but only 53 unique `(match_date, player1, player2, market)` groups
- `bets`: 58 tennis rows total, but only 53 unique `(match_date, home_team, away_team, market)` groups

#### 2.3 Signal and bet settlement are inconsistent

Live DB anomalies:

- `signal_pending_but_bet_settled = 3`
- `signal_settled_but_bet_mismatch = 6`

Concrete rows:

Signals still pending while linked bets are already settled:

- signal `13` -> bet `880:void`
- signal `37` -> bet `904:lost`
- signal `43` -> bet `910:void`

Signals settled while linked bets disagree:

- signal `38 won` vs bet `905 void`
- signal `39 lost` vs bet `906 void`
- signal `48 lost` vs bet `915 void`
- signals `49/52/56 won` vs linked bet set includes `916 lost`

This means the pipeline is not consistent end-to-end today.

Relevant code:

- settlement reads pending by `result`, not `status`: `tennis_live_pipeline.py:1538-1544`
- bet lookup is by exact match row identity only: `tennis_live_pipeline.py:1635-1652`
- there is no direct `tennis_signals.bet_id`

The direct consequence is that settlement can only guess which bet row belongs to a signal when duplicates already exist.

#### 2.4 Separate tennis client notifications still exist

`run_pipeline.py` still defines and uses `task_notify_tennis()`:

- function: `run_pipeline.py:433-445`
- still executed in evening runner: `run_pipeline.py:685-687`

`bot/notifier.py` also still has a dedicated tennis path:

- `notify_tennis_signals()` at `bot/notifier.py:259-365`
- it dedups through PostgreSQL `client_notifications` using `kind='tennis'`

So the separate tennis notification path has not been fully removed.

### Medium

#### 2.5 `status` in `tennis_signals` is stale and causes table confusion

Every row in `tennis_signals` currently has `status='pending'`, including settled ones.

Observed in DB:

```text
pending|60
```

Settlement updates only `result`, `profit`, `settled_at`, `winner_name`:

- `tennis_live_pipeline.py:1609-1613`
- `tennis_live_pipeline.py:1729-1733`

Backfill and some notification code still rely on `status='pending'`:

- `backfill_tennis_bets.py:47-55`
- `bot/notifier.py:264-274`

This is the main source of confusion between `tennis_signals` and `bets`.

#### 2.6 `backfill_tennis_bets.py` can recreate the same duplicate problem

The backfill script repeats the same unstable canonicalization bug as the live pipeline:

- `backfill_tennis_bets.py:20-37`
- `backfill_tennis_bets.py:79-112`

It also selects rows by `status='pending'`, which currently means all tennis signals forever, including many already settled rows.

#### 2.7 Settlement profit itself no longer falls back to zero, but lookup is still unsafe

Current code is improved here:

- profit for `bets` is calculated from stored `b.stake`
- no explicit fallback to zero stake exists

Relevant lines:

- `tennis_live_pipeline.py:1607-1623`

I found no current tennis `bets` rows with:

- `stake IS NULL`
- `stake = 0`
- settled `profit = 0` for `won/lost`

So the specific `bet_profit = 0 due to missing bet_row` issue does not appear in current live tennis rows.

However the lookup is still unsafe because it relies on exact names and picks one row from duplicates:

```sql
ORDER BY CASE WHEN b.result = 'pending' THEN 0 ELSE 1 END, b.id DESC
```

If duplicates exist, this is only a heuristic. The safe fix is to persist `bet_id` on the signal at creation time and settle by primary key.

#### 2.8 Zero-signal days in the last 3 days look like true filter outcomes, not a hidden pipeline crash

Observed recent counts:

- `2026-04-17`: `0` tennis signals
- `2026-04-18`: `0` tennis signals
- `2026-04-19`: `0` tennis signals

Pipeline logs for those runs show tennis analysis executing normally and mostly rejecting:

- ITF doubles
- UTR Pro
- Liga Pro
- season-summary pseudo-events

Examples are visible in:

- `logs/pipeline_20260417.log`
- `logs/pipeline_20260418.log`
- `logs/pipeline_20260419.log`

Given the current tennis filters in `tennis_live_pipeline.py:914-1061`:

- blocked tour keywords
- strict odds window `1.40-2.00`
- `raw_prob >= 0.60`
- `EV >= 0.03`
- at least 5 matches of form

the recent zero output looks much more like a strict-slate outcome than a processing failure.

## 3. Risk level

High.

Reasons:

- duplicate tennis bets already exist in production data
- signal and bet settlement are already inconsistent in production data
- identity still depends on English-based canonicalization paths
- separate tennis client notifications still exist in the evening runner

## 4. Fix recommendations

### Required

1. Replace English-based tennis identity with one Russian canonical key.
   Use Russian only for `signal_key`, `fonbet_id`, and bet dedup.

2. Add same-run dedup in `tennis_live_pipeline.py`.
   After accepting a signal, immediately add its key to the in-memory dedup set.

3. Persist `bet_id` on `tennis_signals`.
   Set it at creation time. Use it first during settlement and cancellation.

4. Keep `tennis_signals.status` synchronized or stop using it.
   Minimal safe option: update `status` to `settled` / `cancelled`, and stop using it for backfill eligibility.

5. Remove separate tennis auto-notification from pipeline schedules.
   Tennis should only flow through general `notify_client`.

### Recommended cleanup

1. Add a unique index for tennis signals based on a stored stable Russian `signal_key`.
2. Migrate existing duplicate tennis rows before enabling that index.
3. Add an audit query or health check that compares `tennis_signals` vs `bets` daily.

## 5. Minimal patch proposals

These are review-only diffs. They are not applied.

### Patch A: stable Russian key + same-run dedup + `bet_id`

```diff
diff --git a/tennis_live_pipeline.py b/tennis_live_pipeline.py
@@
-def load_name_mapping(conn) -> Dict[str, str]:
-    """Load confident (needs_review=0) Russian -> English name mapping."""
-    mapping = {}
-    for rus, eng in conn.execute(
-        "SELECT rus_name, eng_name FROM tennis_player_mapping WHERE needs_review = 0"
-    ).fetchall():
-        mapping[rus.strip()] = eng.strip()
-    log.info(f"Loaded {len(mapping)} confident name mappings")
-    return mapping
+def load_name_mapping(conn) -> Dict[str, str]:
+    """Load confident Russian -> English mapping with lowercase lookup keys."""
+    mapping = {}
+    for rus, eng in conn.execute(
+        "SELECT rus_name, eng_name FROM tennis_player_mapping WHERE needs_review = 0"
+    ).fetchall():
+        mapping[rus.strip().lower()] = eng.strip()
+    log.info(f"Loaded {len(mapping)} confident name mappings")
+    return mapping
@@
-def canonicalize_name(raw_name: str, name_map: Dict[str, str], name_lookup: Dict[str, str]) -> str:
-    """Resolve any name variant (English or Russian) to a stable canonical form.
+def canonicalize_name(raw_name: str, name_map: Dict[str, str], name_lookup: Dict[str, str]) -> str:
+    """Resolve any name variant to a stable canonical form."""
@@
-    # 3) Fallback: use the raw name normalized
+    # 3) Fallback: use the raw name normalized
     return key
+
+def _signal_key(match_date: str, p1_name: str, p2_name: str, market: str) -> str:
+    p1 = normalize_player_name(p1_name).replace(".", "").lower()
+    p2 = normalize_player_name(p2_name).replace(".", "").lower()
+    return f"tennis|{match_date}|{p1}|{p2}|{market}"
@@
-    dedup_key = f"tennis_{match_date}_{p1_c}_{p2_c}_{market}"
+    dedup_key = sig["signal_key"]
@@
-    fonbet_id = f"tennis_{match_date}_{p1_c}_{p2_c}"
+    fonbet_id = f"tennis_{match_date}_{normalize_player_name(p1).replace('.', '').lower()}_{normalize_player_name(p2).replace('.', '').lower()}"
@@
-    existing_signals = set()
+    existing_signals = set()
     for row in conn.execute("""
-        SELECT match_date, player1, player2
+        SELECT match_date, player1, player2, market
         FROM tennis_signals
-        WHERE status = 'pending'
+        WHERE result IS NULL OR result = 'pending'
     """).fetchall():
-        p1_c = canonicalize_name(row[1], name_map, name_lookup)
-        p2_c = canonicalize_name(row[2], name_map, name_lookup)
-        key = (row[0], p1_c, p2_c)
-        existing_signals.add(key)
+        existing_signals.add(_signal_key(row[0], row[1], row[2], row[3]))
@@
-        sig_key = (match_date, p1_canonical, p2_canonical)
+        sig_key = _signal_key(match_date, p1_name, p2_name, market)
         if sig_key in existing_signals:
             skipped_duplicate += 1
             log.info(f"  SKIP (duplicate): {p1_name} vs {p2_name}")
             continue
@@
         signal = {
@@
-            "p1_canonical": p1_canonical,
-            "p2_canonical": p2_canonical,
+            "signal_key": _signal_key(match_date, p1_name, p2_name, market),
@@
         }
         signals.append(signal)
+        existing_signals.add(signal["signal_key"])
@@
+    cols = [row[1] for row in conn.execute("PRAGMA table_info(tennis_signals)").fetchall()]
+    if "bet_id" not in cols:
+        conn.execute("ALTER TABLE tennis_signals ADD COLUMN bet_id INTEGER")
+    if "signal_key" not in cols:
+        conn.execute("ALTER TABLE tennis_signals ADD COLUMN signal_key TEXT")
+    conn.execute(\"\"\"
+        CREATE UNIQUE INDEX IF NOT EXISTS idx_tennis_signals_signal_key_pending
+        ON tennis_signals(signal_key)
+        WHERE result IS NULL OR result = 'pending'
+    \"\"\")
@@
-                bet_id = _create_tennis_bet(conn, sig, bankroll)
+                bet_id = _create_tennis_bet(conn, sig, bankroll)
+                conn.execute(
+                    "UPDATE tennis_signals SET bet_id = ?, signal_key = ? WHERE id = last_insert_rowid()",
+                    (bet_id, sig["signal_key"]),
+                )
```

### Patch B: settle by stored `bet_id`, keep `status` in sync

```diff
diff --git a/tennis_live_pipeline.py b/tennis_live_pipeline.py
@@
-        SELECT id, match_date, player1, player2, player1_eng, player2_eng,
-               market, odds_p1, odds_p2, stake_pct, our_probability, league, surface
+        SELECT id, match_date, player1, player2, player1_eng, player2_eng,
+               market, odds_p1, odds_p2, stake_pct, our_probability, league, surface, bet_id
         FROM tennis_signals
         WHERE result IS NULL OR result = 'pending'
@@
-        (sig_id, match_date, p1_rus, p2_rus, p1_eng, p2_eng,
-         market, odds_p1, odds_p2, stake_pct, our_prob, league, surface) = row
+        (sig_id, match_date, p1_rus, p2_rus, p1_eng, p2_eng,
+         market, odds_p1, odds_p2, stake_pct, our_prob, league, surface, bet_id_hint) = row
@@
-            bet_row = _find_tennis_bet_row(
-                conn,
-                match_date,
-                p1_rus or p1_eng,
-                p2_rus or p2_eng,
-                market,
-            )
+            bet_row = None
+            if bet_id_hint:
+                bet_row = conn.execute(
+                    "SELECT id, stake FROM bets WHERE id = ? LIMIT 1",
+                    (bet_id_hint,),
+                ).fetchone()
+            if not bet_row:
+                bet_row = _find_tennis_bet_row(
+                    conn,
+                    match_date,
+                    p1_rus or p1_eng,
+                    p2_rus or p2_eng,
+                    market,
+                )
@@
             conn.execute("""
                 UPDATE tennis_signals
-                SET result = ?, profit = ?, settled_at = COALESCE(settled_at, ?), winner_name = ?
+                SET result = ?, status = 'settled', profit = ?, settled_at = COALESCE(settled_at, ?), winner_name = ?
                 WHERE id = ?
-            """, (result, profit, settled_at, winner, sig_id))
+            """, (result, profit, settled_at, winner, sig_id))
@@
         conn.execute("""
             UPDATE tennis_signals
-            SET result = 'cancelled', profit = 0, settled_at = COALESCE(settled_at, ?), winner_name = ?
+            SET result = 'cancelled', status = 'cancelled', profit = 0, settled_at = COALESCE(settled_at, ?), winner_name = ?
             WHERE id = ?
         """, (settled_at, f"cancelled: {reason}", sig_id))
```

### Patch C: backfill should use real pending state, not stale `status`

```diff
diff --git a/backfill_tennis_bets.py b/backfill_tennis_bets.py
@@
-        FROM tennis_signals
-        WHERE status = 'pending'
+        FROM tennis_signals
+        WHERE result IS NULL OR result = 'pending'
```

### Patch D: remove separate tennis results notification from schedule

```diff
diff --git a/run_pipeline.py b/run_pipeline.py
@@
-    run_task("notify_client_bets", lambda: task_notify_client("bets"), summary=summary)
-    run_task("notify_client_results", lambda: task_notify_client("results"), summary=summary)
-    run_task("notify_tennis_results", lambda: task_notify_tennis("results"), summary=summary)
+    run_task("notify_client_bets", lambda: task_notify_client("bets"), summary=summary)
+    run_task("notify_client_results", lambda: task_notify_client("results"), summary=summary)
```

## 6. Confirmation whether pipeline is stable

No.

Current tennis pipeline is not stable yet.

What is already good:

- settlement profit for `bets` currently uses stored stake, not recomputed bankroll
- no current live tennis rows show `stake=0` or `bet_profit=0` on `won/lost`
- recent zero-signal days appear to be strict-filter outcomes, not a hard crash

What is still broken:

- duplicate tennis bets already exist
- match identity is not Russian-only and not stable
- signal and bet settlement are already inconsistent in live data
- `tennis_signals.status` is misleading and causes reprocessing ambiguity
- separate tennis client notifications still remain in the evening runner

Until the Russian-only key, direct `bet_id` linkage, and notification cleanup are in place, I would not call the tennis pipeline stable.
