# Tennis Notification Format Fix

**Date:** 2026-04-12
**Status:** FIXED

---

## Problems Found

### 1. Admin bot tennis delivery — MISSING

**Root cause:** `tg_bot.py` `notify("bets")` queried ALL pending bets from `bets` table (including tennis), but:
- `fmt_sport()` had no tennis mapping → fell through to generic "🎯"
- `fmt_market()` had no `player1_win`/`player2_win` mapping → showed raw market name
- `extract_bet_info()` expected `rule`/`reasons` fields that tennis bets don't have → empty strategy label
- No separate dedup key for tennis → could conflict with football/hockey bets

**Fix:** Split tennis vs non-tennis bets in `notify("bets")`:
- Tennis bets use `sent_key = "bets_tennis:{bet_id}"` (separate dedup)
- Tennis template: 🎾 emoji, player names, date, market with player, odds, EV, stake
- Non-tennis bets continue with existing format (strategy label, bookmaker, etc.)

### 2. Channel tennis template — GENERIC

**Root cause:** `content_publisher.py` `publish_bets()` used same generic template for all sports:
- Only selected `b.id, b.odds, m.sport, m.league, m.match_date` — no player names, no market
- Template showed "Коэффициент: 1.6+" instead of actual pick
- `sport_emoji()` had no tennis support → showed ⚽️ for tennis

**Fix:**
- Added `b.market, b.ev, b.our_probability, m.home_team, m.away_team` to SELECT
- Tennis bets get dedicated template: 🎾, league, players, datetime, pick (П1/П2 with name), odds, EV%
- Non-tennis bets keep existing generic template
- `sport_emoji()` already fixed in previous session to include 🎾

---

## Files Modified

| File | Change |
|------|--------|
| `tg_bot.py` | `fmt_sport()` → added tennis 🎾; `fmt_market()` → added `player1_win`/`player2_win` with player names; `notify("bets")` → split tennis vs other bets with separate template and dedup; stats → added tennis breakdown; menu → added tennis button |
| `content_publisher.py` | `publish_bets()` → added tennis-specific template with player names, pick, EV; already fixed `sport_emoji()` |

---

## Test Results

### Admin bot (tg_bot.py --notify bets)
- **Before:** 0 tennis notifications sent
- **After:** 14/14 tennis bets notified, separate 🎾 template with player names

### Channel (content_publisher.py --mode bets)
- **Before:** 14/14 published with generic ⚽️ template, no player names
- **After:** 14/14 published with 🎾 template, player names, pick, odds, EV

### Client bot (bot/notifier.py --mode bets --tennis)
- **Status:** Still works — 18/23 users notified (unchanged)

---

## Answers

1. **my bot tennis delivery fixed?** Yes — 14/14 tennis bets notified via admin bot with 🎾 template
2. **client bot still works?** Yes — unchanged, 18/23 users
3. **channel tennis template fixed?** Yes — 🎾, player names, pick, odds, EV shown
4. **tested successfully?** Yes — both admin bot and channel publish verified with real API calls
