# CLAUDE.md Update Log

**Date:** 2026-04-13
**Reason:** Architecture changed with pipeline stability layer + result normalization layer

---

## Sections Updated

### 1. Project Structure Table
**Added:**
- `result_normalization.py` — Result normalization layer
- `pipeline_stability.py` — Pipeline hardening (task wrapper, fail-fast, run summaries)
- `updater_results.py` — Marked as transitional

**Updated:**
- `settler.py` — Description changed to "dual-path: normalized primary, raw fallback"
- `run_pipeline.py` — Time corrected (21:00, not 14:00 for evening), noted stability layer

### 2. Database Schema — Local SQLite
**Added:**
- `normalized_results` — Full schema documentation (20 columns, unique constraint, 5 indexes)
- `results_raw` — Marked as transitional, noted 7+ parsers
- `tennis_live_results` — Marked as transitional

### 3. New Sections Added
- **Pipeline Stability Layer** — Components, fail-fast behavior table, run summaries
- **Result Normalization Layer** — Flow diagram, per-sport rules, name normalization, lookup API
- **Settlement Architecture (Dual-Path)** — Two-path strategy, hockey OT/SO semantics, tennis settlement
- **Pipeline Orchestration** — Daily runners table, pipeline steps table with `task_normalize_results()`
- **Transitional / Deprecated Logic** — Table of components to phase out

---

## New Architectural Elements Documented

| Element | File/Table | Description |
|---------|-----------|-------------|
| Pipeline stability layer | `pipeline_stability.py` | TaskResult, RunSummary, run_task(), sanity checks |
| Fail-fast behavior | `run_pipeline.py` | Parse failure skips dependent steps |
| Run summaries | `run_summaries/` | JSON + text artifacts per pipeline run |
| Result normalization | `result_normalization.py` | Canonical winner/score from raw sources |
| Normalized results table | `normalized_results` | 20-column canonical entity |
| Dual-path settlement | `settler.py` | Normalized primary, raw fallback |
| Hockey OT semantics fix | `normalized_results.is_overtime` | Regulation-time draw captured explicitly |

---

## Transitional Components

| Component | Why Transitional | Planned Fix |
|-----------|-----------------|-------------|
| `updater_results.py` fuzzy matching | Writes to `matches`, not `normalized_results` | Upsert to `normalized_results` after fuzzy match |
| `settler.py` raw fallback | Still uses 4-char substring matching | Reduce as normalized coverage grows |
| Tennis surname matching | `LIKE '%surname%'` in `tennis_live_pipeline.py` | Dual-path with `normalized_results` |
| `results_raw` as settlement source | 7+ parsers, inconsistent formats | `normalized_results` should become primary |
| `bot/notifier.py` | Dead code — referenced but doesn't exist | Detected + warned, not fixed |

---

## What Was NOT Changed

- Strategies section (football rules, hockey strategies) — unchanged
- Form calculation logic — unchanged
- LLM calls section — unchanged
- Validation pipeline — unchanged
- Common patterns for adding filters — unchanged
- Key constants — unchanged
- Backtest vs Live mode section — unchanged
