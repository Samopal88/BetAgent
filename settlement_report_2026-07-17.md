# Settlement Report — 2026-07-17

## Summary

- **Pending before**: 12 bets (all tennis)
- **Settled now**: 11
- **Remaining pending**: 1 (today's match, awaiting result)

## Settlement Results

| Bet | Match | Date | Market | Odds | Stake | Result | Profit | Source |
|-----|-------|------|--------|------|-------|--------|--------|--------|
| 1001 | Бергс З vs Геа А | 2026-05-19 | player1_win | 1.55 | 297.69 | cancelled | 0.00 | tennis_live (отмена) |
| 1015 | Киргиос Н vs Мутэ К | 2026-06-09 | player1_win | 1.68 | 292.22 | won | +198.71 | tennis_live |
| 1016 | Шимабукуро Ш vs Киргиос Н | 2026-06-11 | player2_win | 1.55 | 292.22 | lost | -292.22 | tennis_live |
| 1017 | Бузкова М vs Векич Д | 2026-06-10 | player2_win | 1.93 | 292.22 | won | +271.76 | tennis_live |
| 1023 | Векич Д vs Эала А | 2026-06-15 | player1_win | 1.78 | 293.12 | lost | -293.12 | tennis_live |
| 1028 | Грикспор Т vs Шимабукуро Ш | 2026-06-16 | player1_win | 1.67 | 293.12 | lost | -293.12 | tennis_live |
| 1034 | Ли Э vs Александрова Е | 2026-06-21 | player2_win | 1.68 | 292.51 | won | +198.91 | tennis_live |
| 1037 | Бергс З vs Мунар Х | 2026-06-22 | player1_win | 1.65 | 292.04 | won | +189.83 | tennis_live |
| 1040 | Уолтон А vs Киргиос Н | 2026-06-22 | player2_win | 1.70 | 292.04 | lost | -292.04 | tennis_live |
| 1045 | Мухова К vs Осака Н | 2026-06-27 | player1_win | 1.90 | 291.95 | cancelled | 0.00 | manual (оба вылетели ранее) |
| 1049 | Сврчина Д vs Димитров Г | 2026-07-14 | player2_win | 1.50 | 293.85 | won | +146.93 | tennis_live |

**Net P&L from settled**: -164.36 RUB

## Remaining Pending

| Bet | Match | Date | Market | Reason |
|-----|-------|------|--------|--------|
| 1053 | Риндеркнеш А vs Циципас С | 2026-07-17 | player2_win | match_not_finished — today's match, Циципас проиграл в QF 07-16, возможно walkover или замена |

**Action**: перезапустить `python3 tennis_results_updater.py --days 1` + `python3 settler.py` завтра.

## Root Causes Fixed

Settler mapping failures (все 12 были `mapping_failed`) вызваны:

1. **Date window слишком узкий** (±1 день → расширен до ±3)
2. **Транслитерация Кирьос/Киргиос** — `ь` удалялась, `г` оставалась → skeleton mismatch. Fix: skeleton edit distance ≤ 1.
3. **Surname extraction threshold** — фамилии ≤3 букв (Жеа, Ли) принимались за инициалы. Fix: порог снижен до ≤1.
4. **Token-level fuzzy matching** — добавлен для "Мунар"/"Муньяр" (edit distance 1 в рамках одного токена ≥4 символов).
5. **Partial match для cancellations** — достаточно совпадения одного игрока, если запись cancelled.

## Code Changes (settler.py)

1. `_surname()`: threshold `len(parts[-1]) <= 3` → `len(parts[-1]) <= 1`
2. `_same_player()`: добавлена проверка `_edit_distance(left_skeleton, right_skeleton) <= 1` для скелетов длиной ≥3
3. `_same_player()`: добавлен token-level fuzzy matching с edit distance ≤ 1 для токенов ≥ 4 символов
4. Date window: расширен с `[-1, 0, +1]` до `[0, +1, -1, +2, +3, -2]`
5. Cancellation partial match: если один игрок совпал + запись с "отмен" → void

## Final DB State

```
cancelled : 10
lost      : 160
pending   :  2
void      :  5
won       : 110
```
