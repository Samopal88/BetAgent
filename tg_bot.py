#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sqlite3, logging, json
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Загружаем .env
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
DB_PATH   = Path(os.getenv("BETAGENT_DB", "betagent.db"))
BANK      = float(os.getenv("BETAGENT_BANK", "100000"))
logging.basicConfig(level=logging.WARNING)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_tg_schema():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tg_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_key TEXT UNIQUE,
            kind TEXT NOT NULL,
            bet_id INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tg_notifications_kind ON tg_notifications(kind)")
    conn.commit()
    conn.close()

def was_sent(kind: str, sent_key: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM tg_notifications WHERE kind=? AND sent_key=? LIMIT 1", (kind, sent_key)).fetchone()
    conn.close()
    return row is not None

def mark_sent(kind: str, sent_key: str, bet_id=None):
    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO tg_notifications (sent_key, kind, bet_id, created_at)
        VALUES (?, ?, ?, ?)
    """, (sent_key, kind, bet_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def fmt_sport(sport):
    return {"hockey": "🏒", "football": "⚽", "tennis": "🎾"}.get(sport, "🎯")

def fmt_market(label, home_team=None, away_team=None):
    def _tennis_side(prefix, name):
        team = (name or "").strip()
        return f"{prefix} ({team})" if team else prefix

    mapping = {
        "П1": "🏠П1", "П2": "✈️П2", "X": "🤝X",
        "home": "🏠П1", "away": "✈️П2", "draw": "🤝X",
        "btts_yes": "⚽⚽ОЗ да", "btts_no": "⛔ОЗ нет",
        "ОЗ да": "⚽⚽ОЗ да", "ОЗ нет": "⛔ОЗ нет",
        "over_2_5": "📈ТБ 2.5", "under_2_5": "📉ТМ 2.5",
        "over_1_5": "📈ТБ 1.5", "under_1_5": "📉ТМ 1.5",
        "player1_win": f"🎾{_tennis_side('П1', home_team)}",
        "player2_win": f"🎾{_tennis_side('П2', away_team)}",
    }
    return mapping.get(label, label or "?")

def fmt_strategy(rule, signal_type):
    """Форматирует стратегию в читаемый вид"""
    if rule:
        labels = {
            "BTTS_YES_CORE": "⚽⚽ Оба забьют",
            "DRAW_SA": "🤝 Ничья SerieA",
            "DRAW_BL1_FL1": "🤝 Ничья Бундеслига/Лига1",
            "DRAW_BALANCED_LINE_SA": "🤝 Ничья равная SerieA",
            "AWAY_SA_STRICT_PLUS": "✈️ Гость SerieA",
            "RPL_OVER25_BTTS": "⚽ ТБ 2.5 РПЛ (двойной сигнал)",
            "PD_BTTS_DOUBLE": "⚽⚽ Оба забьют Ла Лига (двойной сигнал)",
        }
        return labels.get(rule, rule)
    conf = {"High": "🔥 Высокая", "Medium": "⚡ Средняя", "Low": "💤 Низкая"}.get(signal_type, signal_type or "")
    return conf

def extract_bet_info(b):
    """Извлекает rule и reasons из ставки"""
    b = dict(b) if not isinstance(b, dict) else b
    rule = b["rule"] if b.get("rule") else None
    confidence = b["signal_type"] or "Medium"
    try:
        if b.get("reasons"):
            rd = json.loads(b["reasons"] or "{}")
            if rd.get("rule") and not rule:
                rule = rd["rule"]
    except Exception:
        pass
    return rule, confidence

def fmt_result(result):
    return {"won": "✅", "lost": "❌", "pending": "⏳"}.get(result, "?")

def roi_icon(roi):
    return "✅" if roi >= 4 else ("⚠️" if roi >= 0 else "❌")

def get_stats(days=30, sport=None):
    conn = get_conn()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sport_filter = "AND m.sport = ?" if sport else ""
    params = [since] + ([sport] if sport else [])
    s = conn.execute(f"""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN b.result='won' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN b.result='lost' THEN 1 ELSE 0 END) as losses,
               SUM(CASE WHEN b.result='pending' THEN 1 ELSE 0 END) as pending,
               COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.stake ELSE 0 END),0) as staked,
               COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.profit ELSE 0 END),0) as profit,
               COALESCE(AVG(CASE WHEN b.result IN ('won','lost') THEN b.odds ELSE NULL END),0) as avg_odds
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE COALESCE(b.excluded_from_stats,0)=0 AND b.created_at >= ? {sport_filter}
    """, params).fetchone()
    conn.close()
    return s

def get_golden_stats(days=9999):
    conn = get_conn()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    s = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN b.result='won' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN b.result='lost' THEN 1 ELSE 0 END) as losses,
               SUM(CASE WHEN b.result='pending' THEN 1 ELSE 0 END) as pending,
               COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.stake ELSE 0 END),0) as staked,
               COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.profit ELSE 0 END),0) as profit
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.is_golden = 1 AND COALESCE(b.excluded_from_stats,0)=0 AND b.created_at >= ?
    """, (since,)).fetchone()
    conn.close()
    return s

def get_pending_bets(sport=None, date_str=None):
    conn = get_conn()
    filters = ["b.result = 'pending'"]
    params = []
    if sport:
        filters.append("m.sport = ?")
        params.append(sport)
    if date_str:
        filters.append("DATE(m.match_date) = ?")
        params.append(date_str)
    where = " AND ".join(filters)
    bets = conn.execute(f"""
        SELECT b.id, b.market, b.odds, b.stake, b.ev, b.our_probability,
               b.signal_type, b.confidence, b.created_at, b.agent_reasoning,
               m.sport, m.league, m.home_team, m.away_team, m.match_date,
               b.reasons, b.rule, b.edge, b.model_prob, b.market_prob,
               COALESCE(b.recommended_bookmaker, 'fonbet') as bookmaker
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.id IN (
            SELECT MIN(b2.id)
            FROM bets b2 JOIN matches m2 ON b2.match_id = m2.id
            WHERE b2.result = 'pending'
            GROUP BY b2.match_id, b2.market
        )
        AND {where}
        ORDER BY m.match_date ASC
    """, params).fetchall()
    conn.close()
    return bets

def get_closed_bets(days=1, sport=None):
    conn = get_conn()
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    sport_filter = "AND m.sport = ?" if sport else ""
    params = [since] + ([sport] if sport else [])
    bets = conn.execute(f"""
        SELECT b.id as bet_id, b.created_at, b.result, b.market, b.odds, b.stake, b.profit,
               m.sport, m.home_team, m.away_team, m.match_date, m.home_score, m.away_score
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost') AND COALESCE(b.excluded_from_stats,0)=0 AND DATE(b.settled_at) >= ? {sport_filter}
        ORDER BY b.settled_at DESC
        LIMIT 50
    """, params).fetchall()
    conn.close()
    return bets

def get_upcoming_dates():
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT DATE(m.match_date) as d
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result = 'pending'
        ORDER BY d ASC LIMIT 7
    """).fetchall()
    conn.close()
    return [r["d"] for r in rows]

def text_main_menu():
    conn = get_conn()
    pending = conn.execute("SELECT COUNT(*) as c FROM bets WHERE result='pending'").fetchone()["c"]
    conn.close()
    total_profit = get_stats(30)["profit"]
    current_bank = BANK + total_profit
    return (f"🤖 <b>BETAGENT</b>\n\n💰 Банк: <b>{current_bank:,.0f} руб</b>\n"
            f"⏳ Активных ставок: <b>{pending}</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\nВыбери раздел:")

def text_stats(days, sport=None):
    s = get_stats(days, sport)
    closed = (s["wins"] or 0) + (s["losses"] or 0)
    winrate = s["wins"] / closed * 100 if closed > 0 else 0
    roi = s["profit"] / s["staked"] * 100 if s["staked"] > 0 else 0
    current_bank = BANK + s["profit"]
    period = {1: "сегодня", 7: "7 дней", 30: "30 дней", 9999: "всё время"}.get(days, f"{days} дней")
    sport_label = {"football": "⚽ Футбол", "hockey": "🏒 Хоккей", "tennis": "🎾 Теннис"}.get(sport, "🌍 Все виды спорта")
    lines = [
        f"📊 <b>Статистика — {period}</b>",
        f"<i>{sport_label}</i>\n",
        f"💰 Банк: <b>{current_bank:,.0f} руб</b>",
        f"{roi_icon(roi)} ROI: <b>{roi:+.2f}%</b>",
        f"📈 Прибыль: <b>{s['profit']:+,.0f} руб</b>\n",
        f"📋 Всего ставок: {s['total']}",
        f"✅ Выиграно: {s['wins'] or 0}  ❌ Проиграно: {s['losses'] or 0}  ⏳ Активных: {s['pending'] or 0}",
    ]
    if closed > 0:
        lines += [
            f"🎯 Винрейт: <b>{winrate:.1f}%</b>",
            f"💵 Поставлено: {s['staked']:,.0f} руб",
            f"📊 Средний коэф: {s['avg_odds']:.2f}",
        ]
    # По спортам если показываем все
    if not sport:
        sf = get_stats(days, "football")
        sh = get_stats(days, "hockey")
        st = get_stats(days, "tennis")
        f_roi = sf["profit"] / sf["staked"] * 100 if sf["staked"] > 0 else 0
        h_roi = sh["profit"] / sh["staked"] * 100 if sh["staked"] > 0 else 0
        t_roi = st["profit"] / st["staked"] * 100 if st["staked"] > 0 else 0
        f_closed = (sf["wins"] or 0) + (sf["losses"] or 0)
        h_closed = (sh["wins"] or 0) + (sh["losses"] or 0)
        t_closed = (st["wins"] or 0) + (st["losses"] or 0)
        if f_closed > 0 or h_closed > 0 or t_closed > 0:
            lines.append("\n<b>По видам спорта:</b>")
        if f_closed > 0:
            lines.append(f"⚽ Футбол: {roi_icon(f_roi)} ROI {f_roi:+.1f}% | W:{sf['wins']} L:{sf['losses']} | {sf['profit']:+,.0f} руб")
        if h_closed > 0:
            lines.append(f"🏒 Хоккей: {roi_icon(h_roi)} ROI {h_roi:+.1f}% | W:{sh['wins']} L:{sh['losses']} | {sh['profit']:+,.0f} руб")
        if t_closed > 0:
            lines.append(f"🎾 Теннис: {roi_icon(t_roi)} ROI {t_roi:+.1f}% | W:{st['wins']} L:{st['losses']} | {st['profit']:+,.0f} руб")
    return "\n".join(lines)

def text_golden():
    """Текст для ЖБ ставок — активная + статистика."""
    conn = get_conn()
    # Активная ЖБ
    golden = conn.execute("""
        SELECT b.id, b.market, b.odds, b.stake, b.ev, b.golden_reasoning, b.golden_confidence,
               m.sport, m.home_team, m.away_team, m.match_date, m.league
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.is_golden = 1 AND b.result = 'pending'
        ORDER BY m.match_date ASC LIMIT 1
    """).fetchone()
    # История ЖБ
    history = conn.execute("""
        SELECT b.result, b.profit, b.odds, b.market,
               m.home_team, m.away_team, m.match_date
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.is_golden = 1 AND b.result IN ('won','lost')
        ORDER BY b.created_at DESC LIMIT 10
    """).fetchall()
    conn.close()

    s = get_golden_stats()
    closed = (s["wins"] or 0) + (s["losses"] or 0)
    winrate = s["wins"] / closed * 100 if closed > 0 else 0
    roi = s["profit"] / s["staked"] * 100 if s["staked"] > 0 else 0

    lines = ["💎 <b>ЖБ СТАВКИ</b>\n"]

    # Активная ЖБ
    if golden:
        ev_pct = (golden["ev"] or 0) * 100
        date_str = str(golden["match_date"])[5:16]
        confidence = golden["golden_confidence"] or 0
        reasoning = golden["golden_reasoning"] or ""
        lines.append(
            f"🔥 <b>Активная ЖБ:</b>\n"
            f"{fmt_sport(golden['sport'])} <b>{golden['home_team']} — {golden['away_team']}</b>\n"
            f"   📅 {date_str} | {fmt_market(golden['market'], golden['home_team'], golden['away_team'])} @ <b>{golden['odds']}</b>\n"
            f"   🏆 Уверенность: {confidence}/10 | EV: {ev_pct:.1f}%\n"
            f"   💰 {golden['stake']:,.0f} руб"
        )
        if reasoning:
            lines.append(f"   📝 <i>{reasoning[:200]}</i>")
        lines.append("")
    else:
        lines.append("⏳ Нет активной ЖБ ставки\n")

    # Статистика
    lines.append(f"<b>Статистика ЖБ (всё время):</b>")
    lines.append(f"📋 Всего: {closed} | W:{s['wins'] or 0} L:{s['losses'] or 0} | ⏳{s['pending'] or 0}")
    if closed > 0:
        lines.append(f"🎯 Винрейт: <b>{winrate:.1f}%</b>")
        lines.append(f"{roi_icon(roi)} ROI: <b>{roi:+.1f}%</b> | Прибыль: <b>{s['profit']:+,.0f} руб</b>")

    # История последних
    if history:
        lines.append("\n<b>Последние ЖБ:</b>")
        for b in history[:5]:
            profit = b["profit"] or 0
            date_str = str(b["match_date"])[5:10]
            lines.append(
                f"{fmt_result(b['result'])} {b['home_team']} — {b['away_team']} "
                f"({date_str}) | {fmt_market(b['market'])} @ {b['odds']} | {profit:+,.0f} руб"
            )

    return "\n".join(lines)

def text_bets_by_date(date_str, sport=None):
    bets = get_pending_bets(sport=sport, date_str=date_str)
    if not bets:
        return f"⏳ Нет активных ставок на {date_str}"
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        date_label = d.strftime("%d.%m.%Y")
    except:
        date_label = date_str
    lines = [f"🎯 <b>Прогнозы на {date_label}</b> ({len(bets)} ставок)\n"]
    for b in bets:
        ev_pct = (b["ev"] or 0) * 100
        stake = b["stake"] or 0
        rule, confidence = extract_bet_info(b)
        strategy_label = fmt_strategy(rule, confidence)
        ev_icon = "🔥" if ev_pct >= 20 else ("✅" if ev_pct >= 10 else "⚡")
        lines.append(
                f"{fmt_sport(b['sport'])} <b>{b['home_team']} — {b['away_team']}</b>\n"
            f"   🕐 {str(b['match_date'])[11:16]} | {fmt_market(b['market'], b['home_team'], b['away_team'])} @ <b>{b['odds']}</b> | БК: <b>{str(b['bookmaker']).upper()}</b>\n"
            f"   📋 {strategy_label}\n"
            f"   💰 {stake:,.0f} руб | {ev_icon} EV: {ev_pct:.1f}%"
        )
    return "\n".join(lines)

def text_bets_all(sport=None):
    bets = get_pending_bets(sport=sport)
    if not bets:
        sport_label = {"football": "футболу", "hockey": "хоккею", "tennis": "теннису"}.get(sport, "")
        return f"⏳ Нет активных ставок{' по ' + sport_label if sport_label else ''}"
    sport_label = {"football": "⚽ Футбол", "hockey": "🏒 Хоккей", "tennis": "🎾 Теннис"}.get(sport, "Все виды спорта")
    lines = [f"🎯 <b>Активные прогнозы — {sport_label}</b> ({len(bets)})\n"]
    cur_date = None
    for b in bets:
        date = str(b["match_date"])[:10]
        if date != cur_date:
            cur_date = date
            try:
                d = datetime.strptime(date, "%Y-%m-%d")
                lines.append(f"\n📅 <b>{d.strftime('%d.%m')}</b>")
            except:
                lines.append(f"\n📅 <b>{date}</b>")
        ev_pct = (b["ev"] or 0) * 100
        stake = b["stake"] or 0
        rule, confidence = extract_bet_info(b)
        strategy_label = fmt_strategy(rule, confidence)
        lines.append(
            f"{fmt_sport(b['sport'])} {b['home_team']} — {b['away_team']}\n"
            f"   {fmt_market(b['market'], b['home_team'], b['away_team'])} @ <b>{b['odds']}</b> | БК: <b>{str(b['bookmaker']).upper()}</b> | 💰{stake:,.0f} руб | EV:{ev_pct:.0f}%\n"
            f"   📋 {strategy_label}"
        )
    return "\n".join(lines)

def text_results(days=1):
    bets = get_closed_bets(days=days)
    if not bets:
        return "📋 Нет закрытых ставок за этот период"
    total_profit = sum(b["profit"] or 0 for b in bets)
    wins = sum(1 for b in bets if b["result"] == "won")
    losses = sum(1 for b in bets if b["result"] == "lost")
    period = {1: "сегодня", 7: "7 дней", 30: "30 дней"}.get(days, f"{days} дней")
    lines = [f"📋 <b>Результаты — {period}</b>", f"W:{wins} L:{losses} | Итог: <b>{total_profit:+,.0f} руб</b>\n"]
    for b in bets:
        score = f" {b['home_score']}:{b['away_score']}" if b["home_score"] is not None else ""
        profit = b["profit"] or 0
        lines.append(f"{fmt_result(b['result'])} {fmt_sport(b['sport'])} {b['home_team']} — {b['away_team']}{score}\n"
                     f"   {fmt_market(b['market'])} @ {b['odds']} | {profit:+,.0f} руб")
    return "\n".join(lines)

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Прогнозы", callback_data="bets_menu"),
         InlineKeyboardButton("📊 Статистика", callback_data="stats_menu")],
        [InlineKeyboardButton("📋 Результаты", callback_data="results_menu"),
         InlineKeyboardButton("💎 ЖБ Ставка", callback_data="golden_menu")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="main")],
    ])

def kb_bets():
    dates = get_upcoming_dates()
    rows, date_row = [], []
    for d in dates[:4]:
        try:
            label = datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m")
        except:
            label = d
        date_row.append(InlineKeyboardButton(label, callback_data=f"bets_date_{d}"))
    if date_row:
        rows.append(date_row)
    rows.append([InlineKeyboardButton("⚽ Футбол", callback_data="bets_sport_football"),
                 InlineKeyboardButton("🏒 Хоккей", callback_data="bets_sport_hockey"),
                 InlineKeyboardButton("🎾 Теннис", callback_data="bets_sport_tennis"),
                 InlineKeyboardButton("🌍 Все", callback_data="bets_all")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="main")])
    return InlineKeyboardMarkup(rows)

def kb_stats():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Сегодня", callback_data="stats_1"), InlineKeyboardButton("📅 7 дней", callback_data="stats_7")],
        [InlineKeyboardButton("📅 30 дней", callback_data="stats_30"), InlineKeyboardButton("📅 Всё время", callback_data="stats_9999")],
        [InlineKeyboardButton("⚽ Футбол", callback_data="stats_30_football"), InlineKeyboardButton("🏒 Хоккей", callback_data="stats_30_hockey"), InlineKeyboardButton("🎾 Теннис", callback_data="stats_30_tennis")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main")],
    ])

def kb_results():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Сегодня", callback_data="results_1"), InlineKeyboardButton("📅 7 дней", callback_data="results_7")],
        [InlineKeyboardButton("📅 30 дней", callback_data="results_30")],
        [InlineKeyboardButton("⚽ Футбол", callback_data="results_sport_football"), InlineKeyboardButton("🏒 Хоккей", callback_data="results_sport_hockey"), InlineKeyboardButton("🎾 Теннис", callback_data="results_sport_tennis")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main")],
    ])

def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main")]])

# Persistent bottom keyboard — always visible after /start
KB_PERSISTENT = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🎯 Прогнозы"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("📋 Результаты"), KeyboardButton("💎 ЖБ Ставка")],
        [KeyboardButton("🔄 Обновить")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(text_main_menu(), parse_mode="HTML", reply_markup=kb_main(), reply_to_message_id=update.message.message_id)
    await update.message.reply_text("📌 Быстрый доступ:", reply_markup=KB_PERSISTENT)

async def cmd_bets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(text_bets_all(), parse_mode="HTML", reply_markup=kb_bets())

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выбери период:", parse_mode="HTML", reply_markup=kb_stats())

async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    try:
        if data == "main":
            await q.edit_message_text(text_main_menu(), parse_mode="HTML", reply_markup=kb_main())
        elif data == "bets_menu":
            await q.edit_message_text("🎯 <b>Прогнозы</b>\n\nВыбери дату или вид спорта:", parse_mode="HTML", reply_markup=kb_bets())
        elif data == "bets_all":
            await q.edit_message_text(text_bets_all(), parse_mode="HTML", reply_markup=kb_bets())
        elif data.startswith("bets_date_"):
            date_str = data.replace("bets_date_", "")
            await q.edit_message_text(text_bets_by_date(date_str), parse_mode="HTML", reply_markup=kb_bets())
        elif data.startswith("bets_sport_"):
            sport = data.replace("bets_sport_", "")
            await q.edit_message_text(text_bets_all(sport=sport), parse_mode="HTML", reply_markup=kb_bets())
        elif data == "stats_menu":
            await q.edit_message_text("📊 <b>Статистика</b>\n\nВыбери период:", parse_mode="HTML", reply_markup=kb_stats())
        elif data.startswith("stats_"):
            parts = data.replace("stats_", "").split("_")
            days = int(parts[0]); sport = parts[1] if len(parts) > 1 else None
            await q.edit_message_text(text_stats(days, sport), parse_mode="HTML", reply_markup=kb_stats())
        elif data == "golden_menu":
            await q.edit_message_text(text_golden(), parse_mode="HTML", reply_markup=kb_back())
        elif data == "results_menu":
            await q.edit_message_text("📋 <b>Результаты</b>\n\nВыбери период:", parse_mode="HTML", reply_markup=kb_results())
        elif data.startswith("results_sport_"):
            sport = data.replace("results_sport_", "")
            await q.edit_message_text(text_results(days=1), parse_mode="HTML", reply_markup=kb_results())
        elif data.startswith("results_"):
            days = int(data.replace("results_", ""))
            await q.edit_message_text(text_results(days), parse_mode="HTML", reply_markup=kb_results())
    except Exception as e:
        if "Message is not modified" in str(e):
            return
        await q.edit_message_text(f"❌ Ошибка: {e}", reply_markup=kb_back())

def notify(mode: str, days: int = 1):
    import requests as req
    def send(text):
        req.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                 json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                 timeout=10)
    ensure_tg_schema()
    if mode == "bets":
        conn = get_conn()
        bets = conn.execute("""
            SELECT b.id as bet_id, b.market, b.odds, b.stake, b.ev, b.signal_type,
                   COALESCE(b.recommended_bookmaker, 'fonbet') as bookmaker,
                   m.sport, m.home_team, m.away_team, m.match_date
            FROM bets b JOIN matches m ON b.match_id = m.id
            WHERE b.result = 'pending'
              AND b.created_at >= datetime('now', '-30 days')
            ORDER BY m.match_date ASC
        """, ()).fetchall()
        conn.close()

        # Split tennis and non-tennis bets
        tennis_bets = [b for b in bets if b["sport"] == "tennis"]
        other_bets = [b for b in bets if b["sport"] != "tennis"]

        # --- Tennis bets ---
        tennis_unsent = []
        for b in tennis_bets:
            sent_key = f"bets_tennis:{b['bet_id']}"
            if not was_sent("bets", sent_key):
                tennis_unsent.append((b, sent_key))
        if tennis_unsent:
            lines = [f"🎾 <b>Теннисные прогнозы — {len(tennis_unsent)} шт.</b>\n"]
            for b, sent_key in tennis_unsent:
                ev_pct = (b["ev"] or 0) * 100
                stake = b["stake"] or 0
                date_str = str(b["match_date"])[:10]
                market_display = fmt_market(b["market"], b["home_team"], b["away_team"])
                ev_icon = "🔥" if ev_pct >= 20 else ("✅" if ev_pct >= 10 else "⚡")
                lines.append(
                    f"🎾 <b>{b['home_team']} — {b['away_team']}</b>\n"
                    f"   📅 {date_str} | {market_display} @ <b>{b['odds']}</b>\n"
                    f"   💰 {stake:,.0f} руб | {ev_icon} EV: {ev_pct:.1f}%"
                )
            send("\n".join(lines))
            for b, sent_key in tennis_unsent:
                mark_sent("bets", sent_key, b["bet_id"])

        # --- Other sports bets ---
        other_unsent = []
        for b in other_bets:
            sent_key = f"bets:{b['bet_id']}"
            if not was_sent("bets", sent_key):
                other_unsent.append((b, sent_key))
        if not other_unsent and not tennis_unsent:
            return
        if other_unsent:
            lines = [f"🎯 <b>Новые прогнозы — {len(other_unsent)} шт.</b>\n"]
            for b, sent_key in other_unsent:
                ev_pct = (b["ev"] or 0) * 100
                stake = b["stake"] or 0
                date_str = str(b["match_date"])[5:16]
                rule, confidence = extract_bet_info(b)
                strategy_label = fmt_strategy(rule, confidence)
                ev_icon = "🔥" if ev_pct >= 20 else ("✅" if ev_pct >= 10 else "⚡")
                lines.append(
                    f"{fmt_sport(b['sport'])} <b>{b['home_team']} — {b['away_team']}</b>\n"
                    f"   📅 {date_str} | {fmt_market(b['market'], b['home_team'], b['away_team'])} @ <b>{b['odds']}</b> | БК: <b>{str(b['bookmaker']).upper()}</b>\n"
                    f"   📋 {strategy_label}\n"
                    f"   💰 {stake:,.0f} руб | {ev_icon} EV: {ev_pct:.1f}%"
                )
            send("\n".join(lines))
            for b, sent_key in other_unsent:
                mark_sent("bets", sent_key, b["bet_id"])
    elif mode == "golden":
        conn = get_conn()
        golden = conn.execute("""
            SELECT b.id as bet_id, b.market, b.odds, b.stake, b.ev, b.signal_type,
                   COALESCE(b.recommended_bookmaker, 'fonbet') as bookmaker,
                   b.golden_reasoning, b.golden_confidence, b.is_golden,
                   m.sport, m.home_team, m.away_team, m.match_date, m.league
            FROM bets b JOIN matches m ON b.match_id = m.id
            WHERE b.is_golden = 1 AND b.result = 'pending'
            AND DATE(m.match_date) = DATE('now', '+1 day')
            ORDER BY m.match_date ASC
            LIMIT 1
        """).fetchone()
        conn.close()
        if not golden:
            return
        sent_key = f"golden:{golden['bet_id']}"
        if was_sent("golden", sent_key):
            return
        ev_pct = (golden["ev"] or 0) * 100
        date_str = str(golden["match_date"])[5:16]
        reasoning = golden["golden_reasoning"] or ""
        confidence = golden["golden_confidence"] or 0
        lines = [
            f"💎 <b>ЖБ СТАВКА ДНЯ</b>\n",
            f"{fmt_sport(golden['sport'])} <b>{golden['home_team']} — {golden['away_team']}</b>",
            f"   📅 {date_str} | {fmt_market(golden['market'])} @ <b>{golden['odds']}</b> | БК: <b>{str(golden['bookmaker']).upper()}</b>",
            f"   🏆 Уверенность: {confidence}/10",
            f"   💰 {golden['stake']:,.0f} руб | 🔥 EV: {ev_pct:.1f}%",
        ]
        if reasoning:
            lines.append(f"\n📝 <i>{reasoning}</i>")
        text = "\n".join(lines)
        send(text)
        mark_sent("golden", sent_key, golden["bet_id"])
    elif mode == "results":
        bets = get_closed_bets(days=2)
        if not bets:
            return
        unsent = []
        for b in bets:
            sent_key = f"results:{b['bet_id']}:{b['result']}"
            if not was_sent("results", sent_key):
                unsent.append((b, sent_key))
        if not unsent:
            return
        wins = sum(1 for b, _ in unsent if b["result"] == "won")
        losses = sum(1 for b, _ in unsent if b["result"] == "lost")
        total_profit = sum((b["profit"] or 0) for b, _ in unsent)
        lines = [f"📋 <b>Результаты за сегодня</b> | W:{wins} L:{losses} | {total_profit:+,.0f} руб\n"]
        for b, sent_key in unsent:
            score = f" {b['home_score']}:{b['away_score']}" if b["home_score"] is not None else ""
            profit = b["profit"] or 0
            lines.append(f"{fmt_result(b['result'])} {fmt_sport(b['sport'])} {b['home_team']} — {b['away_team']}{score} | {fmt_market(b['market'])} @ {b['odds']} | {profit:+,.0f} руб")
        send("\n".join(lines))
        for b, sent_key in unsent:
            mark_sent("results", sent_key, b["bet_id"])
    elif mode == "report":
        s = get_stats(30)
        closed = (s["wins"] or 0) + (s["losses"] or 0)
        roi = s["profit"] / s["staked"] * 100 if s["staked"] > 0 else 0
        current_bank = BANK + s["profit"]
        send(f"📈 <b>Вечерний отчёт</b>\n\n💰 Банк: <b>{current_bank:,.0f} руб</b>\n{roi_icon(roi)} ROI: <b>{roi:+.2f}%</b>\n📊 За 30 дней: {closed} ставок | W:{s['wins']} L:{s['losses']}\n⏳ Активных: {s['pending'] or 0}")
    elif mode == "test":
        send("🤖 <b>BETAGENT подключён!</b>\n\nДоступные команды:\n/start — главное меню\n/bets — активные прогнозы\n/stats — статистика\n\n" + f"💰 Банк: {BANK:,.0f} руб")

async def handle_persistent_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle clicks on the persistent bottom keyboard."""
    text = update.message.text
    if text == "🎯 Прогнозы":
        await update.message.reply_text(text_bets_all(), parse_mode="HTML", reply_markup=kb_bets())
    elif text == "📊 Статистика":
        await update.message.reply_text("Выбери период:", parse_mode="HTML", reply_markup=kb_stats())
    elif text == "📋 Результаты":
        await update.message.reply_text(text_results(days=1), parse_mode="HTML", reply_markup=kb_results())
    elif text == "💎 ЖБ Ставка":
        await update.message.reply_text(text_golden(), parse_mode="HTML", reply_markup=kb_back())
    elif text == "🔄 Обновить":
        await update.message.reply_text(text_main_menu(), parse_mode="HTML", reply_markup=kb_main())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--notify", choices=["bets","results","report","test","golden"], help="Отправить уведомление без запуска бота")
    ap.add_argument("--days", type=int, default=1)
    args = ap.parse_args()
    ensure_tg_schema()
    if args.notify:
        notify(args.notify, days=args.days)
        print(f"✅ Уведомление '{args.notify}' отправлено")
    else:
        from telegram.ext import MessageHandler, filters
        print("🤖 BETAGENT Telegram Bot запущен...")
        print("   Ctrl+C для остановки")
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("bets", cmd_bets))
        app.add_handler(CommandHandler("stats", cmd_stats))
        app.add_handler(CallbackQueryHandler(callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_persistent_button))
        app.run_polling(drop_pending_updates=True)
