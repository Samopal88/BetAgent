# Tennis Settlement Analysis: April 15-16, 2026

**Date of analysis:** 2026-04-16 19:24  
**Analyzed by:** settler.py (tennis_live_results path)

---

## Summary

| Metric | Count |
|--------|-------|
| **Total pending before** | 6 |
| **Settled now** | 6 |
| **Voided** | 0 |
| **Still not found** | 0 |

**Net P/L from settled bets:** +785.75 RUB

---

## Root Cause

**Tennis results updater did not run for ATP/WTA 500 Munich/Stuttgart results on April 15-16.**

The `tennis_live_results` table had only Challenger-level results for those dates. ATP 500 Munich and WTA 500 Stuttgart matches were missing.

After manual fetch (`tennis_results_updater.py --date 2026-04-15` and `--date 2026-04-16`), 70 new results were loaded (34 for 15 Apr, 36 for 16 Apr).

**Additionally:** Match records in `matches` table had `status='upcoming'` instead of `'finished'`. This blocked the settler from processing them, even though results existed in `tennis_live_results`.

---

## Bet Details

| Bet ID | Match | Market | Odds | Stake | Result | Profit | Settlement Path |
|--------|-------|--------|------|-------|--------|--------|-----------------|
| 919 | Bloks A vs Shelton B (15 Apr) | player2_win | 1.70 | 331.39 | **WON** | +231.97 | tennis_live(sets=2:0) |
| 920 | Marojan F vs Tsitsipas S (15 Apr) | player2_win | 1.72 | 331.39 | **LOST** | -331.39 | tennis_live(sets=2:1) |
| 921 | Altmaier D vs Molchan A (16 Apr) | player2_win | 2.00 | 331.39 | **WON** | +331.39 | tennis_live(sets=2:0) |
| 922 | Muhova K vs Mertens E (16 Apr) | player1_win | 1.45 | 331.39 | **WON** | +149.13 | tennis_live(sets=2:1) |
| 923 | Bloks A vs Shelton B (15 Apr) | player2_win | 1.68 | 328.99 | **WON** | +223.71 | tennis_live(sets=2:0) |
| 924 | Muhova K vs Mertens E (16 Apr) | player1_win | 1.55 | 328.99 | **WON** | +180.94 | tennis_live(sets=2:1) |

---

## Match Results from Sources

All matches were found in `betz.su` (via tennis_results_updater):

| Date | Winner | Loser | Score | Tournament |
|------|--------|-------|-------|------------|
| 2026-04-15 | Ben Shelton | Alexander Bloks | 2:0 (6:4, 7:6) | ATP 500 Munich |
| 2026-04-15 | Fabian Marojan | Stefanos Tsitsipas | 2:1 (3:6, 7:6, 6:4) | ATP 500 Munich |
| 2026-04-16 | Alex Molchan | Daniel Altmaier | 2:0 (6:4, 7:6) | ATP 500 Munich |
| 2026-04-16 | Karolina Muhova | Elise Mertens | 2:1 (1:6, 6:3, 6:0) | WTA 500 Stuttgart |

---

## Pipeline Issues Identified

1. **Results updater gap:** The scheduled `tennis_results_updater.py` task did not fetch ATP/WTA 500 results for April 15-16.
   
2. **Match status not updated:** Even after results existed, matches remained `status='upcoming'` in the `matches` table. The settler checks `status='finished'` before proceeding.

3. **Fix applied:**
   - Manually ran `tennis_results_updater.py --date 2026-04-15` and `--date 2026-04-16`
   - Updated match statuses to `'finished'` with correct set scores
   - Ran `settler.py` to settle all 6 bets

---

## Remaining Pending

| Bet ID | Match | Date | Status |
|--------|-------|------|--------|
| 925 | Zverev A vs Serundolo F | 2026-04-17 | pending (match not yet played) |

This bet is for April 17 and correctly remains pending.

---

## Recommendations

1. **Add ATP/WTA 500 to scheduled fetches** — Ensure `tennis_results_updater.py` runs daily with `--days 3` to catch delayed results.

2. **Sync match status from results** — Modify settler or add a pre-settle step that automatically updates `matches.status='finished'` when a result exists in `tennis_live_results`.

3. **Monitor results coverage** — Add a sanity check in `pipeline_stability.py` that flags when pending tennis bets have matching results but unsettled status.
