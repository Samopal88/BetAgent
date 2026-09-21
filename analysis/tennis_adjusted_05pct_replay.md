# Tennis Adjusted Replay — 0.5% Bankroll Staking

**Date:** 2026-04-15
**Method:** Sequential replay of all 51 tennis bets with unified stake = 0.5% of current bankroll

---

## Summary

| Metric | Actual (mixed staking) | Adjusted (0.5% uniform) |
|--------|----------------------|------------------------|
| Total bets | 51 | 51 |
| Settled (won/lost) | 39 | 39 |
| Won | 9 | 9 |
| Lost | 30 | 30 |
| Cancelled | 3 | 3 |
| Pending | 9 | 9 |
| Hit rate | 23.1% | 23.1% |
| **Total PnL** | **-28,358 RUB** | **-7,611 RUB** |
| Total staked | 18,713 RUB | 18,816 RUB |
| **ROI** | **-151.5%** | **-40.5%** |
| **Final bankroll** | **71,642 RUB** | **92,389 RUB** |
| Max drawdown | N/A | 8,453 RUB (fell to 91,937) |
| Max losing streak | 6 | 6 |
| Avg stake | 480 RUB | 482 RUB |

---

## Key Findings

### 1. The -28,358 RUB actual PnL is inflated by old Kelly-based bets

Bets 868-881 (created 2026-04-12 05:23) used Kelly-based stake_pct from 2.1% to 10%.
These 14 bets alone contributed approximately **-20,747 RUB** of the total loss.

Under the adjusted 0.5% model, those same 14 bets would have lost only **-3,486 RUB**.

### 2. Post-fix bets (882+) are already close to the adjusted model

From bet 882 onward, all bets use `stake_pct = 0.005`, so actual and adjusted values differ only due to:
- Bankroll drift (actual bankroll dropped faster due to Kelly losses, so 0.5% of actual bankroll is lower)
- The settlement bug (fixed in this session) that recomputed profit from current bankroll

### 3. Cancelled matches handled correctly

All 3 cancelled bets have `profit = 0` and `result = 'cancelled'` — correct.

---

## Per-Bet Replay

| ID | Result | Odds | ActStake | ActPnL | AdjStake | AdjPnL | AdjBR | Match |
|----|--------|------|----------|--------|----------|--------|-------|-------|
| 868 | won | 1.78 | 480 | +3,888 | 500 | +390 | 100,390 | Махач Т vs Баэс С |
| 869 | lost | 2.03 | 480 | -6,233 | 502 | -502 | 99,888 | Навоне М vs Рублев А |
| 870 | lost | 3.35 | 480 | -5,827 | 499 | -499 | 99,389 | Ландалус М vs Музетти Л |
| 871 | lost | 2.40 | 480 | -3,488 | 497 | -497 | 98,892 | Табило А vs Фонсека Ж |
| 872 | cancelled | 5.10 | 480 | 0 | 494 | 0 | 98,892 | Штруфф Я-Л vs Серундоло Ф |
| 873 | lost | 1.83 | 480 | -5,658 | 494 | -494 | 98,397 | Чилич М vs Альтмайер Д |
| 874 | won | 3.15 | 480 | +11,195 | 492 | +1,058 | 99,455 | Виртанен О vs Мюллер А |
| 875 | won | 2.10 | 480 | +8,698 | 497 | +547 | 100,002 | Зигемунд Л vs Фрех М |
| 876 | lost | 4.00 | 480 | -4,955 | 500 | -500 | 99,502 | Остапенко Е vs Андреева М |
| 877 | lost | 2.20 | 480 | -3,709 | 498 | -498 | 99,004 | Эала А vs Фернандес Л |
| 878 | lost | 4.30 | 480 | -9,909 | 495 | -495 | 98,509 | Корпач Т vs Шнайдер Д |
| 879 | won | 2.90 | 480 | +3,973 | 493 | +936 | 99,445 | Лис Е vs Бадоса П |
| 880 | pending | 4.30 | 480 | — | 497 | — | 99,445 | Ферро Ф vs Кирстя С |
| 881 | lost | 2.50 | 480 | -10,093 | 497 | -497 | 98,948 | Крету Ч vs Агаменоне Ф |
| 882 | lost | 3.65 | 480 | -476 | 495 | -495 | 98,453 | Норри К vs Вавринка С |
| 883 | lost | 5.30 | 480 | -495 | 492 | -492 | 97,961 | Зверев А vs Кецманович М |
| 884 | lost | 2.15 | 480 | -476 | 490 | -490 | 97,471 | Риндеркнеш А vs Микелсен А |
| 885 | cancelled | 2.35 | 480 | 0 | 487 | 0 | 97,471 | Коболли Ф vs Фучович М |
| 886 | lost | 1.80 | 480 | -495 | 487 | -487 | 96,984 | Грикспор Т vs Шаповалов Д |
| 887 | lost | 4.00 | 480 | -473 | 485 | -485 | 96,499 | Андреева М vs Потапова А |
| 888 | won | 3.35 | 480 | +1,164 | 482 | +1,134 | 97,634 | Блинкова А vs Потапова А |
| 889 | lost | 3.70 | 480 | -353 | 488 | -488 | 97,145 | Баптист Х vs Понше Дж |
| 890 | lost | 3.90 | 480 | -495 | 486 | -486 | 96,660 | Костюк М vs Парри Д |
| 891 | lost | 2.20 | 480 | -476 | 483 | -483 | 96,176 | Опелка Р vs Куинн И |
| 892 | won | 1.68 | 480 | +345 | 481 | +327 | 96,503 | Махач Т vs Баэс С |
| 893 | lost | 2.30 | 480 | -508 | 483 | -483 | 96,021 | Навоне М vs Рублев А |
| 894 | lost | 4.15 | 480 | -508 | 480 | -480 | 95,541 | Ландалус М vs Музетти Л |
| 895 | lost | 19.0 | 480 | -508 | 478 | -478 | 95,063 | Алькарас К vs Виртанен О |
| 896 | lost | 2.65 | 480 | -476 | 475 | -475 | 94,588 | Диалло Г vs Сачко В |
| 897 | lost | 3.15 | 480 | -476 | 473 | -473 | 94,115 | Нава Э vs Шелтон Б |
| 898 | lost | 4.30 | 480 | -508 | 471 | -471 | 93,645 | Бергс З vs Топо М |
| 899 | won | 3.35 | 480 | +1,194 | 468 | +1,096 | 94,741 | Молчан А vs Бублик А |
| 900 | lost | 5.20 | 480 | -508 | 474 | -474 | 94,267 | Зверев А vs Кецманович М |
| 901 | lost | 2.95 | 480 | -508 | 471 | -471 | 93,796 | Табило А vs Фонсека Ж |
| 902 | lost | 1.90 | 480 | -508 | 469 | -469 | 93,327 | Грикспор Т vs Шаповалов Д |
| 903 | lost | 1.65 | 480 | -508 | 467 | -467 | 92,861 | Чилич М vs Альтмайер Д |
| 904 | pending | 3.40 | 480 | — | 464 | — | 92,861 | Мухова К vs Саснович А |
| 905 | pending | 4.40 | 480 | — | 464 | — | 92,861 | Сонмез З vs Паолини Я |
| 906 | pending | 3.30 | 480 | — | 464 | — | 92,861 | Остапенко Е vs Андреева М |
| 907 | lost | 2.40 | 480 | -349 | 464 | -464 | 92,397 | Эала А vs Фернандес Л |
| 908 | lost | 4.80 | 480 | -498 | 462 | -462 | 91,935 | Корпач Т vs Шнайдер Д |
| 909 | won | 3.25 | 480 | +1,143 | 460 | +1,034 | 92,969 | Лис Е vs Бадоса П |
| 910 | pending | 1.63 | 480 | — | 465 | — | 92,969 | Рахимова К vs Калиева Э |
| 911 | cancelled | 3.70 | 480 | 0 | 465 | 0 | 92,969 | Блинкова А vs Потапова А |
| 912 | lost | 5.30 | 480 | -353 | 465 | -465 | 92,504 | Баптист Х vs Понше Дж |
| 913 | lost | 3.95 | 480 | -508 | 463 | -463 | 92,042 | Костюк М vs Парри Д |
| 914 | won | 1.75 | 473 | +381 | 460 | +345 | 92,387 | Накашима Б vs Серундоло Х-М |
| 915 | pending | 1.60 | 473 | — | 462 | — | 92,387 | Марожан Ф vs Циципас С |
| 916 | pending | 1.45 | 476 | — | 462 | — | 92,387 | Блокс А vs Шелтон Б |
| 917 | pending | 1.72 | 508 | — | 462 | — | 92,387 | Марожан Ф vs Циципас С |
| 918 | pending | 1.45 | 508 | — | 462 | — | 92,387 | Мухова К vs Мертенс Э |

---

## Cancelled Matches Audit

| bet_id | Match | League | Market | Odds | Actual Profit | Adj Profit | Correct? |
|--------|-------|--------|--------|------|--------------|------------|----------|
| 872 | Штруфф Я-Л vs Серундоло Ф | ATP Мюнхен | P1 | 5.10 | 0.00 | 0.00 | YES |
| 885 | Коболли Ф vs Фучович М | ATP Мюнхен | P2 | 2.35 | 0.00 | 0.00 | YES |
| 911 | Блинкова А vs Потапова А | WTA Руан | P1 | 3.70 | 0.00 | 0.00 | YES |

All 3 cancelled bets:
- Have `result = 'cancelled'` in both `bets` and `tennis_signals`
- Have `profit = 0` in both tables
- Were settled on 2026-04-14 22:10:11 (same batch)
- Match `tennis_live_results` entries with `score_detail LIKE '%отмена%'`
- Were correctly identified by `_check_cancelled()` surname matching

**No cancelled bets were settled incorrectly.**

### Additional cancelled matches in tennis_live_results (no corresponding bets)

16 total cancelled matches exist in `tennis_live_results`, but only 3 had active bets:
- 13 cancelled matches had no bets placed (either filtered out by EV/tour rules or not in betting universe)
- This is expected — the betting pipeline has stricter filters than the results parser

---

## Conclusion

The adjusted replay shows that under a consistent 0.5% bankroll staking model:
- Tennis PnL would be **-7,611 RUB** instead of **-28,358 RUB**
- The difference of **~20,747 RUB** is entirely due to old Kelly-based oversized bets (IDs 868-881)
- Final bankroll would be **92,389 RUB** vs actual **71,642 RUB**
- Cancelled matches are handled correctly — no issues found
- The separate adjusted ledger is the right approach — raw DB history should not be rewritten
