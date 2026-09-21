#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
import requests
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN     = os.getenv("CLIENT_BOT_TOKEN", "")
API_URL       = os.getenv("API_BASE_URL", "http://localhost:8001")
PRICE_BASIC   = os.getenv("PRICE_BASIC", "990")
PRICE_PRO     = os.getenv("PRICE_PRO", "2490")
PRICE_PREMIUM = os.getenv("PRICE_PREMIUM", "4900")

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)

# Хранилище токенов (in-memory)
USER_TOKENS: dict[int, str] = {}

MAIN_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("📡 Сигналы"),    KeyboardButton("🏆 Топ сигнал")],
    [KeyboardButton("📊 Статистика"), KeyboardButton("📋 История")],
    [KeyboardButton("👤 Аккаунт"),    KeyboardButton("💳 Подписка")],
    [KeyboardButton("🌐 Личный кабинет")],
    [KeyboardButton("🎁 Пригласить друга")],
    [KeyboardButton("📋 Правила"),    KeyboardButton("❓ Помощь")],
], resize_keyboard=True)

OFERTA_TEXT = (
    "📋 *ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ*\n\n"
    "*BetAgent Analytics* — информационно-аналитический сервис.\n\n"
    "*Что мы предоставляем:*\n"
    "• Математический анализ линий букмекеров\n"
    "• Вероятностные модели на основе исторических данных\n"
    "• Сигналы с положительным математическим ожиданием (EV)\n\n"
    "*Что мы НЕ предоставляем:*\n"
    "• Гарантии прибыли или дохода\n"
    "• Букмекерские услуги\n"
    "• Инвестиционные советы\n\n"
    "*Важно понимать:*\n"
    "• Ставки на спорт сопряжены с риском потери средств\n"
    "• Прошлые результаты не гарантируют будущих\n"
    "• Вы принимаете решения самостоятельно\n"
    "• Сервис предназначен для лиц старше 18 лет\n\n"
    "*Статистика сервиса публична и честна* — включая просадки и проигрышные серии.\n\n"
    "*Конфиденциальность:* Мы храним только ваш Telegram ID. "
    "Данные не передаются третьим лицам.\n\n"
    "*Подписка:* не продлевается автоматически без вашего согласия. "
    "Возврат средств — в течение 24 часов если сигналов не было.\n\n"
    "Нажимая *«Принимаю условия»*, вы подтверждаете:\n"
    "✓ Ознакомились с условиями\n"
    "✓ Вам есть 18 лет\n"
    "✓ Принимаете решения о ставках самостоятельно"
)

SEP = "─" * 28


# ── API helpers ─────────────────────────────────────────────────────────────

def api_auth(telegram_id, username, first_name):
    try:
        r = requests.post(f"{API_URL}/auth/telegram", json={
            "telegram_id": telegram_id,
            "username": username or "",
            "first_name": first_name or "",
        }, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.error(f"api_auth: {e}")
    return None


def api_get(endpoint, token):
    try:
        r = requests.get(
            f"{API_URL}{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code == 401:
            return {"error": "token_expired"}
        if r.status_code == 403:
            return {"error": "subscription_required"}
    except Exception as e:
        log.error(f"api_get {endpoint}: {e}")
    return None


def get_token(user):
    """Получить JWT токен — из кэша или через /auth/telegram."""
    tg_id = user.id
    if tg_id in USER_TOKENS:
        return USER_TOKENS[tg_id]
    data = api_auth(
        tg_id,
        getattr(user, "username", "") or "",
        getattr(user, "first_name", "") or "",
    )
    if data and "token" in data:
        USER_TOKENS[tg_id] = data["token"]
        return data["token"]
    return None


def refresh_token(user):
    """Принудительно обновить токен."""
    tg_id = user.id
    USER_TOKENS.pop(tg_id, None)
    return get_token(user)

def get_token_with_ref(user, ref: str = ""):
    """Получить токен с передачей реферального кода при первой регистрации."""
    tg_id = user.id
    if tg_id in USER_TOKENS and not ref:
        return USER_TOKENS[tg_id]
    try:
        r = requests.post(f"{API_URL}/auth/telegram", json={
            "telegram_id": tg_id,
            "username": getattr(user, "username", "") or "",
            "first_name": getattr(user, "first_name", "") or "",
            "ref": ref,
        }, timeout=10)
        if r.status_code == 200:
            data = r.json()
            USER_TOKENS[tg_id] = data["token"]
            return data["token"]
    except Exception as e:
        log.error(f"get_token_with_ref: {e}")
    return None


def fmt_signal(s):
    """Форматировать один сигнал в текст."""
    golden = "💎 *GOLDEN BET*\n" if s.get("is_golden") else ""
    conf_map = {"high": "🟢 Высокая", "medium": "🟡 Средняя", "low": "🔴 Низкая"}
    conf = conf_map.get(s.get("confidence", "medium"), "🟡 Средняя")
    market_map = {
        "draw": "Ничья (X)",
        "home": "П1",
        "away": "П2",
        "btts_yes": "Обе забьют",
        "over_2_5": "Тотал больше 2.5",
        "player1_win": f"П1 ({s.get('player1', '')})",
        "player2_win": f"П2 ({s.get('player2', '')})",
    }
    market = market_map.get(s.get("market", ""), s.get("market", ""))
    date_str = str(s.get("match_date", ""))[:10]
    stake = s.get("recommended_stake", 1000)
    sport = s.get("sport", "")
    league = s.get("league", "").split(".")[0].strip()
    if sport == "tennis":
        icon = "🎾"
    elif sport == "football":
        icon = "⚽"
    else:
        icon = "🏒"

    lines = [
        golden + SEP,
        f"{icon} *{league}*",
        f"⚔️ {s.get('match', '')}",
        f"📅 {date_str}",
        SEP,
        f"📌 Рынок: *{market}*",
        f"💰 Коэффициент: *{s.get('odds', '?')}*",
        # Букмекер скрыт намеренно
        f"📊 EV: {s.get('ev_range', '?')}",
        f"🎯 Уверенность: {conf}",
        f"💵 Рек. ставка: *{stake} ₽*",
        "",
    ]
    return "\n".join(lines)


# ── Handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Обрабатываем реферальный параметр
    ref = ""
    ref = ctx.args[0] if ctx.args and ctx.args[0].startswith("ref_") else ""
    token = get_token_with_ref(user, ref)
    if not token:
        await update.message.reply_text("❌ Ошибка подключения. Попробуй позже.")
        return

    data = api_auth(
        user.id,
        getattr(user, "username", "") or "",
        getattr(user, "first_name", "") or "",
    )
    # Показываем оферту только новым пользователям с trial, ещё не принявшим
    is_new = (
        data
        and data.get("subscription")
        and data["subscription"].get("trial")
        and data["subscription"].get("status") == "active"
    )
    accepted = ctx.bot_data.get(f"oferta_{user.id}", False)

    if is_new and not accepted:
        kb = [[InlineKeyboardButton("✅ Принимаю условия", callback_data="accept_oferta")]]
        await update.message.reply_text(
            OFERTA_TEXT,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb),
        )
    else:
        await update.message.reply_text(
            f"👋 С возвращением, *{user.first_name}*!\n\nВыбери раздел в меню ниже 👇",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )


async def cb_accept_oferta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    ctx.bot_data[f"oferta_{user.id}"] = True
    await query.edit_message_text(
        f"✅ *Условия приняты!*\n\n"
        f"👋 Добро пожаловать в *BetAgent Analytics*, {user.first_name}!\n\n"
        "Мы используем математические модели для поиска value-ставок.\n\n"
        "📊 *Бэктест 5 лет:* ROI +24%, банк 100к → 514к руб\n\n"
        "🎁 Вам активирован *пробный период на 7 дней (Basic)*\n\n"
        "Используй кнопку *📡 Сигналы* чтобы увидеть первые сигналы.",
        parse_mode="Markdown",
    )
    await query.message.reply_text(
        "📋 *Правила и условия использования*\n\n"
        "Пожалуйста, ознакомьтесь перед началом работы\. Команда /rules для повторного просмотра\.",
        parse_mode="MarkdownV2",
    )
    rules_text = (
        "⚠️ *ВАЖНО — прочитайте перед началом работы*\n\n"
        "BETAGENT — система алгоритмической аналитики линий букмекеров\. "
        "Мы не даём гарантий прибыли\. Мы даём математическое преимущество на дистанции\.\n\n"
        "─────────────────────────\n"
        "📐 *КАК ПРАВИЛЬНО ИСПОЛЬЗОВАТЬ*\n"
        "─────────────────────────\n\n"
        "*1\. Размер рекомендации — 1% от банка \(флэт\)*\n"
        "Не увеличивайте размер после проигрышей и не уменьшайте после выигрышей\. "
        "Флэт — основа математического преимущества\.\n\n"
        "*2\. Минимальный банк — от 70 000 ₽*\n"
        "При меньшем банке преимущество не успевает реализоваться до критической просадки\. "
        "Работайте только с деньгами, потеря которых не влияет на вашу жизнь\.\n\n"
        "*3\. Дистанция решает всё*\n"
        "Не делайте выводов по 10–20 рекомендациям\. "
        "Минимальная дистанция для оценки — 200\+ рекомендаций\.\n\n"
        "─────────────────────────\n"
        "📉 *О ПРОСАДКАХ*\n"
        "─────────────────────────\n\n"
        "Проигрышные серии — нормальная часть любой математической системы\.\n\n"
        "На истории за 5 лет:\n"
        "• Максимальная серия без результата: 11 подряд\n"
        "• Теоретически возможная серия: до 15 подряд\n\n"
        "❌ *НИКОГДА* не используйте догон \(увеличение размера после проигрыша\)\. "
        "Догон уничтожает банк быстрее, чем любая проигрышная серия\.\n\n"
        "─────────────────────────\n"
        "📌 *ТЕХНИЧЕСКИЕ УСЛОВИЯ*\n"
        "─────────────────────────\n\n"
        "• Рекомендации публикуются 4 раза в день\n"
        "• Сигналы действительны до начала матча\n"
        "• Проверяйте актуальность коэффициента перед размещением\n"
        "• Basic: задержка 15 мин, до 3–5 сигналов в неделю\n"
        "• Pro/Premium: все сигналы без задержки\n\n"
        "─────────────────────────\n"
        "🏦 *О БУКМЕКЕРАХ*\n"
        "─────────────────────────\n\n"
        "BETAGENT не рекомендует конкретных букмекеров и не сотрудничает ни с одной "
        "букмекерской компанией\. Выбор площадки — исключительно ваше решение\.\n\n"
        "─────────────────────────\n"
        "🔒 *ИНТЕЛЛЕКТУАЛЬНАЯ СОБСТВЕННОСТЬ*\n"
        "─────────────────────────\n\n"
        "Все материалы, сигналы и алгоритмы BETAGENT являются результатом работы нашей "
        "команды аналитиков и разработчиков и охраняются как интеллектуальная собственность\.\n\n"
        "Строго запрещено:\n"
        "• копирование и распространение сигналов\n"
        "• перепродажа аналитики третьим лицам\n"
        "• публикация сигналов в открытых источниках\n\n"
        "При выявлении нарушений будут применяться все предусмотренные законом меры, "
        "включая блокировку аккаунта и юридическое преследование\.\n\n"
        "─────────────────────────\n"
        "⚖️ *ОТКАЗ ОТ ОТВЕТСТВЕННОСТИ*\n"
        "─────────────────────────\n\n"
        "• BETAGENT предоставляет аналитику, а не финансовые советы\n"
        "• Все решения и финансовые риски вы принимаете на себя\n"
        "• Прошлые результаты не гарантируют будущую прибыль\n"
        "• Сервис предназначен для лиц старше 18 лет\n\n"
        "Используя BETAGENT, вы подтверждаете принятие всех условий\.\n\n"
        "По всем вопросам: @betagent\_admin"
    )
    await query.message.reply_text(rules_text, parse_mode="MarkdownV2")
    await query.message.reply_text("Меню доступно ниже 👇", reply_markup=MAIN_KEYBOARD)



RULES_TEXT = (
    "⚠️ *ВАЖНО — прочитайте перед началом работы*\n\n"
    "BETAGENT — система алгоритмической аналитики линий букмекеров\. "
    "Мы не даём гарантий прибыли\. Мы даём математическое преимущество на дистанции\.\n\n"
    "─────────────────────────\n"
    "📐 *КАК ПРАВИЛЬНО ИСПОЛЬЗОВАТЬ*\n"
    "─────────────────────────\n\n"
    "*1\. Размер рекомендации — 1% от банка \(флэт\)*\n"
    "Не увеличивайте размер после проигрышей и не уменьшайте после выигрышей\. "
    "Флэт — основа математического преимущества\.\n\n"
    "*2\. Минимальный банк — от 70 000 ₽*\n"
    "При меньшем банке преимущество не успевает реализоваться до критической просадки\. "
    "Работайте только с деньгами, потеря которых не влияет на вашу жизнь\.\n\n"
    "*3\. Дистанция решает всё*\n"
    "Не делайте выводов по 10–20 рекомендациям\. "
    "Минимальная дистанция для оценки — 200\+ рекомендаций\.\n\n"
    "─────────────────────────\n"
    "📉 *О ПРОСАДКАХ*\n"
    "─────────────────────────\n\n"
    "Проигрышные серии — нормальная часть любой математической системы\.\n\n"
    "На истории за 5 лет:\n"
    "• Максимальная серия без результата: 11 подряд\n"
    "• Теоретически возможная серия: до 15 подряд\n\n"
    "❌ *НИКОГДА* не используйте догон \(увеличение размера после проигрыша\)\. "
    "Догон уничтожает банк быстрее, чем любая проигрышная серия\.\n\n"
    "─────────────────────────\n"
    "📌 *ТЕХНИЧЕСКИЕ УСЛОВИЯ*\n"
    "─────────────────────────\n\n"
    "• Рекомендации публикуются 4 раза в день\n"
    "• Сигналы действительны до начала матча\n"
    "• Проверяйте актуальность коэффициента перед размещением\n"
    "• Basic: задержка 15 мин, до 3–5 сигналов в неделю\n"
    "• Pro/Premium: все сигналы без задержки\n\n"
    "─────────────────────────\n"
    "🏦 *О БУКМЕКЕРАХ*\n"
    "─────────────────────────\n\n"
    "BETAGENT не рекомендует конкретных букмекеров и не сотрудничает ни с одной "
    "букмекерской компанией\. Выбор площадки — исключительно ваше решение\.\n\n"
    "─────────────────────────\n"
    "🔒 *ИНТЕЛЛЕКТУАЛЬНАЯ СОБСТВЕННОСТЬ*\n"
    "─────────────────────────\n\n"
    "Все материалы, сигналы и алгоритмы BETAGENT являются результатом работы нашей "
    "команды аналитиков и разработчиков и охраняются как интеллектуальная собственность\.\n\n"
    "Строго запрещено:\n"
    "• копирование и распространение сигналов\n"
    "• перепродажа аналитики третьим лицам\n"
    "• публикация сигналов в открытых источниках\n\n"
    "При выявлении нарушений будут применяться все предусмотренные законом меры, "
    "включая блокировку аккаунта и юридическое преследование\.\n\n"
    "─────────────────────────\n"
    "⚖️ *ОТКАЗ ОТ ОТВЕТСТВЕННОСТИ*\n"
    "─────────────────────────\n\n"
    "• BETAGENT предоставляет аналитику, а не финансовые советы\n"
    "• Все решения и финансовые риски вы принимаете на себя\n"
    "• Прошлые результаты не гарантируют будущую прибыль\n"
    "• Сервис предназначен для лиц старше 18 лет\n\n"
    "Используя BETAGENT, вы подтверждаете принятие всех условий\.\n\n"
    "По всем вопросам: @betagent\_admin"
)

async def cmd_rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RULES_TEXT, parse_mode="MarkdownV2")

async def do_signals(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    token = get_token(user)
    if not token:
        await update.message.reply_text("❌ Ошибка. Попробуй /start")
        return

    msg = await update.message.reply_text("⏳ Загружаю сигналы...")
    data = api_get("/signals/active", token)

    # Если токен истёк — обновляем и повторяем
    if data and data.get("error") == "token_expired":
        token = refresh_token(user)
        data = api_get("/signals/active", token) if token else None

    if not data:
        await msg.edit_text("❌ Ошибка сервера. Попробуй позже.")
        return
    if data.get("error") == "subscription_required":
        await msg.edit_text(
            "🔒 *Требуется подписка*\n\nНажми *💳 Подписка* для оформления.",
            parse_mode="Markdown",
        )
        return

    signals = data.get("signals", [])
    plan = data.get("plan", "basic")

    if not signals:
        await msg.edit_text(
            "📭 *Активных сигналов пока нет*\n\n"
            "Алгоритм ищет только реальные value-ставки.\n"
            "Загляни позже — пайплайн обновляется несколько раз в день.",
            parse_mode="Markdown",
        )
        return

    plan_label = {"basic": "Basic 🔵", "pro": "Pro 🟣", "premium": "Premium 💎"}.get(plan, plan)
    text = f"📡 *Активные сигналы* | {plan_label}\n\n"
    for s in signals:
        text += fmt_signal(s)

    if plan == "basic":
        wr = data.get("weekly_remaining", 5)
        wu = data.get("weekly_used", 0)
        text += f"🔵 *Basic* — использовано {wu}/5 сигналов на этой неделе\nОсталось: {wr} · Задержка 15 мин\nВсе сигналы без ограничений → *💳 Подписка*"

    await msg.edit_text(text, parse_mode="Markdown")


async def do_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    token = get_token(user)
    if not token:
        await update.message.reply_text("❌ Ошибка. Попробуй /start")
        return

    msg = await update.message.reply_text("⏳ Ищу лучший сигнал дня...")
    data = api_get("/signals/top", token)

    if data and data.get("error") == "token_expired":
        token = refresh_token(user)
        data = api_get("/signals/top", token) if token else None

    if not data or not data.get("signal"):
        await msg.edit_text("📭 Топ-сигнала сегодня пока нет. Загляни позже.")
        return

    await msg.edit_text(
        "🏆 *Лучший сигнал дня*\n\n" + fmt_signal(data["signal"]),
        parse_mode="Markdown",
    )


async def do_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    token = get_token(user)
    if not token:
        await update.message.reply_text("❌ Ошибка. Попробуй /start")
        return

    msg = await update.message.reply_text("⏳ Загружаю статистику...")
    data = api_get("/signals/history", token)

    if data and data.get("error") == "token_expired":
        token = refresh_token(user)
        data = api_get("/signals/history", token) if token else None

    if not data or data.get("error"):
        await msg.edit_text("🔒 Требуется подписка → *💳 Подписка*", parse_mode="Markdown")
        return

    st = data.get("stats", {})
    total = st.get("total", 0)
    won = st.get("won", 0)
    lost = total - won
    winrate = st.get("winrate", 0)
    profit = st.get("profit", 0)
    history = data.get("history", [])
    football = sum(1 for h in history if h.get("sport") == "football")
    hockey = sum(1 for h in history if h.get("sport") == "hockey")
    tennis = sum(1 for h in history if h.get("sport") == "tennis")
    profit_emoji = "📈" if profit >= 0 else "📉"

    text = "\n".join([
        "📊 *Статистика BetAgent*",
        SEP,
        "*Боевые результаты:*",
        f"✅ Выиграно: *{won}*",
        f"❌ Проиграно: *{lost}*",
        f"📋 Всего ставок: *{total}*",
        f"🎯 Winrate: *{winrate}%*",
        f"{profit_emoji} Прибыль: *{profit:+.0f} ₽*",
        SEP,
        "*По видам спорта:*",
        f"⚽ Футбол: {football} ставок",
        f"🏒 Хоккей: {hockey} ставок",
        f"🎾 Теннис: {tennis} ставок",
        SEP,
        "*Бэктест (5 лет, 2020–2026):*",
        "📈 ROI: *+24%*",
        "💰 Банк: 100к → 514к руб",
        "📦 Ставок: 1,854",
        "⚠️ Макс. серия проигрышей: 11",
        SEP,
        "_Статистика в реальном времени._",
        "_Показываем всё включая просадки — честно._",
    ])
    await msg.edit_text(text, parse_mode="Markdown")


async def do_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    token = get_token(user)
    if not token:
        await update.message.reply_text("❌ Ошибка. Попробуй /start")
        return

    msg = await update.message.reply_text("⏳ Загружаю историю...")
    data = api_get("/signals/history", token)

    if data and data.get("error") == "token_expired":
        token = refresh_token(user)
        data = api_get("/signals/history", token) if token else None

    if not data or data.get("error"):
        await msg.edit_text("🔒 Требуется подписка → *💳 Подписка*", parse_mode="Markdown")
        return

    history = data.get("history", [])[:10]
    if not history:
        await msg.edit_text("📭 История ставок пока пуста.")
        return

    market_map = {
        "draw": "X", "home": "П1", "away": "П2",
        "btts_yes": "ОЗ", "over_2_5": "Тб2.5",
        "player1_win": "П1", "player2_win": "П2",
    }
    lines = ["📋 *Последние ставки*", ""]
    for h in history:
        res = "✅" if h["result"] == "won" else "❌"
        profit = h.get("profit") or 0
        profit_str = f"+{profit:.0f} ₽" if profit > 0 else f"{profit:.0f} ₽"
        market = market_map.get(h.get("market", ""), h.get("market", ""))
        date = str(h.get("match_date", ""))[:10]
        sport = h.get("sport", "")
        if sport == "tennis":
            p1 = h.get("home_team", "") or h.get("player1", "")
            p2 = h.get("away_team", "") or h.get("player2", "")
            lines.append(f"{res} 🎾 *{p1} — {p2}*")
        else:
            lines.append(f"{res} *{h.get('home_team', '')} — {h.get('away_team', '')}*")
        lines.append(f"   {market} @ {h.get('odds', '?')} | {profit_str} | {date}")
        lines.append("")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def do_account(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    token = get_token(user)
    if not token:
        await update.message.reply_text("❌ Ошибка. Попробуй /start")
        return

    data = api_get("/account", token)

    if data and data.get("error") == "token_expired":
        token = refresh_token(user)
        data = api_get("/account", token) if token else None

    if not data:
        await update.message.reply_text("❌ Ошибка сервера.")
        return

    sub = data.get("subscription")
    plan_label = {"basic": "Basic 🔵", "pro": "Pro 🟣", "premium": "Premium 💎"}
    if sub:
        plan = plan_label.get(sub.get("plan", ""), "Basic")
        expires = str(sub.get("expires_at", ""))[:10] if sub.get("expires_at") else "—"
        trial_str = " *(пробный период)*" if sub.get("trial") else ""
        status = f"✅ Активна{trial_str}"
    else:
        plan = "Нет подписки"
        expires = "—"
        status = "❌ Неактивна"

    u = data.get("user", {})
    sep24 = "─" * 24
    cabinet_url = f"https://bet-agent.ru/cabinet"
    text = "\n".join([
        "👤 *Ваш аккаунт*",
        sep24,
        f"Имя: {u.get('first_name', '')}",
        f"ID: `{u.get('telegram_id', '')}`",
        sep24,
        f"📦 Тариф: *{plan}*",
        f"📅 Активна до: {expires}",
        f"🔰 Статус: {status}",
        sep24,
        "🌐 [Личный кабинет на сайте](" + cabinet_url + ")",
        "_Для входа: /cabinet_",
    ])
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🌐 Личный кабинет", url="https://bet-agent.ru/cabinet"),
        InlineKeyboardButton("📧 Привязать email", callback_data="link_email_start"),
    ]])
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb)


async def do_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = [
        "💳 *Тарифы BetAgent Analytics*",
        SEP,
        "",
        "🔵 *Basic — 990 ₽ / 25 дней*",
        "• 3–5 сигналов в неделю",
        "• Задержка выдачи 15 минут",
        "• История за 30 дней",
        "",
        "🟣 *Pro — 2490 ₽ / 28 дней*",
        "• Все сигналы без задержки",
        "• Оба вида спорта",
        "• Полная история",
        "",
        "💎 *Premium — 4900 ₽ / 35 дней*",
        "• Всё из Pro",
        "• Golden Bet — лучший сигнал дня",
        "• Ранний доступ к сигналам",
        "",
        SEP,
        "🎁 Новым пользователям — *7 дней Basic бесплатно*",
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Купить Basic — 990 ₽ / 25 дней", callback_data="pay_basic")],
        [InlineKeyboardButton("🟣 Купить Pro — 2490 ₽ / 28 дней", callback_data="pay_pro")],
        [InlineKeyboardButton("💎 Купить Premium — 4900 ₽ / 35 дней", callback_data="pay_premium")],
    ])
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def do_pay_plan(update: Update, ctx: ContextTypes.DEFAULT_TYPE, plan: str):
    query = update.callback_query
    user = query.from_user
    token = get_token(user)
    if not token:
        await query.answer("❌ Ошибка. Напиши /start", show_alert=True)
        return

    await query.answer()

    labels = {
        "basic":   "Basic 🔵 — 990 ₽ / 25 дней",
        "pro":     "Pro 🟣 — 2490 ₽ / 28 дней",
        "premium": "Premium 💎 — 4900 ₽ / 35 дней",
    }
    prices = {"basic": "990", "pro": "2490", "premium": "4900"}

    msg = await query.message.reply_text("⏳ Создаю ссылку на оплату...")
    try:
        r = requests.post(
            f"{API_URL}/billing/create-payment",
            json={"plan": plan},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Оплатить", url=data["payment_url"])],
                [InlineKeyboardButton("✅ Я оплатил", callback_data=f"check_pay_{data['payment_id']}")],
            ])
            await msg.edit_text(
                f"💳 *Оплата — {labels[plan]}*\n\n"
                f"Сумма: *{prices[plan]} ₽*\n\n"
                "Нажми кнопку ниже для оплаты.\n"
                "После оплаты нажми *«Я оплатил»* для активации.",
                parse_mode="Markdown",
                reply_markup=kb,
            )
        elif r.status_code == 503:
            await msg.edit_text(
                "⏳ *Приём оплаты временно недоступен*\n\n"
                "Платёжная система на подключении.\n"
                "Для оплаты напиши: @betagent\\_admin",
                parse_mode="Markdown",
            )
        else:
            await msg.edit_text("❌ Ошибка. Попробуй позже или напиши @betagent\\_admin")
    except Exception as e:
        log.error(f"do_pay_plan: {e}")
        await msg.edit_text("❌ Ошибка сервера. Напиши @betagent\\_admin")


async def check_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE, payment_id: str):
    query = update.callback_query
    user = query.from_user
    token = get_token(user)
    if not token:
        await query.answer("❌ Ошибка", show_alert=True)
        return
    try:
        r = requests.get(
            f"{API_URL}/billing/status/{payment_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if data["status"] == "succeeded":
                await query.answer("✅ Оплата подтверждена!", show_alert=True)
                await query.message.reply_text(
                    "✅ *Подписка активирована!*\n\nИспользуй кнопку 📡 Сигналы.",
                    parse_mode="Markdown",
                )
            else:
                await query.answer(
                    "⏳ Оплата ещё не поступила. Попробуй через минуту.",
                    show_alert=True,
                )
        else:
            await query.answer("❌ Платёж не найден", show_alert=True)
    except Exception:
        await query.answer("❌ Ошибка сервера", show_alert=True)


async def do_refer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    token = get_token(user)
    if not token:
        await update.message.reply_text("❌ Ошибка. Попробуй /start")
        return

    data = api_get("/referral-link", token)
    if not data:
        await update.message.reply_text("❌ Ошибка сервера.")
        return

    link = data.get("link", "")
    account_data = api_get("/account", token)
    refs = account_data.get("referrals", {}) if account_data else {}
    total = refs.get("total", 0)
    rewarded = refs.get("rewarded", 0)

    text = (
        "🎁 *Пригласи друга — получи бонус*\n\n"
        "За каждого друга который оплатит подписку:\n"
        "*+7 дней Pro* тебе в подарок 🟣\n\n"
        f"🔗 *Твоя ссылка:*\n`{link}`\n\n"
        f"📊 *Твоя статистика:*\n"
        f"• Приглашено: {total}\n"
        f"• Оплатили (бонусов получено): {rewarded}\n\n"
        "_Отправь ссылку другу. Когда он зарегистрируется и оплатит — "
        "тебе автоматически придут +7 дней Pro._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def do_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = "\n".join([
        "🤖 *BetAgent Analytics*\n🌐 bet-agent.ru | 📢 t.me/betagent\_chanel",
        "",
        "Аналитический сервис для поиска value-ставок.",
        "",
        "*Кнопки меню:*",
        "📡 Сигналы — активные рекомендации",
        "🏆 Топ сигнал — лучший сигнал дня",
        "📊 Статистика — ROI и winrate",
        "📋 История — закрытые ставки",
        "👤 Аккаунт — тариф и подписка",
        "💳 Подписка — тарифы и оплата",
        "",
        "*Команды:*",
        "/start — перезапустить бота",
        "/rules — правила и условия",
        "/help — эта справка",
        "",
        "По вопросам: @betagent\\_admin",
    ])
    await update.message.reply_text(text, parse_mode="Markdown")


async def menu_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    # Проверяем ожидание email привязки
    if user.id in _email_wait:
        await link_email_got_email(update, ctx)
        return
    if text == "📡 Сигналы":
        await do_signals(update, ctx)
    elif text == "🏆 Топ сигнал":
        await do_top(update, ctx)
    elif text == "📊 Статистика":
        await do_stats(update, ctx)
    elif text == "📋 История":
        await do_history(update, ctx)
    elif text == "👤 Аккаунт":
        await do_account(update, ctx)
    elif text == "🌐 Личный кабинет":
        await cmd_cabinet(update, ctx)
    elif user.id in _email_wait and isinstance(_email_wait.get(user.id), dict) and _email_wait[user.id].get("state") == "waiting_code":
        # Проверяем код привязки email
        code = text.strip()
        state = _email_wait[user.id]
        email = state["email"]
        import requests as req, os, hmac, hashlib
        api_url = os.getenv("API_BASE_URL", "http://localhost:8001")
        # Получаем токен пользователя
        tg_id = user.id
        secret = hmac.new(os.getenv("JWT_SECRET","").encode(), str(tg_id).encode(), hashlib.sha256).hexdigest()[:16]
        try:
            tr = req.post(f"{api_url}/cabinet/tg_login", json={"telegram_id": tg_id, "secret": secret}, timeout=5)
            cab_token = tr.json().get("token", "")
            r = req.post(f"{api_url}/cabinet/link_email", json={"token": cab_token, "email": email, "code": code}, timeout=10)
            if r.status_code == 200:
                del _email_wait[user.id]
                await update.message.reply_text(
                    f"✅ *Email успешно привязан!*\n\n"
                    f"📧 {email}\n\n"
                    f"Теперь вы можете войти в кабинет через email на сайте bet-agent.ru",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Неверный или истёкший код. Попробуйте ещё раз через /account")
                del _email_wait[user.id]
        except Exception as e:
            await update.message.reply_text("❌ Ошибка сервера. Попробуйте позже.")
            del _email_wait[user.id]
    elif text == "🌐 Личный кабинет":
        await cmd_cabinet(update, ctx)
    elif user.id in _email_wait and isinstance(_email_wait.get(user.id), dict) and _email_wait[user.id].get("state") == "waiting_code":
        # Проверяем код привязки email
        code = text.strip()
        state = _email_wait[user.id]
        email = state["email"]
        import requests as req, os, hmac, hashlib
        api_url = os.getenv("API_BASE_URL", "http://localhost:8001")
        # Получаем токен пользователя
        tg_id = user.id
        secret = hmac.new(os.getenv("JWT_SECRET","").encode(), str(tg_id).encode(), hashlib.sha256).hexdigest()[:16]
        try:
            tr = req.post(f"{api_url}/cabinet/tg_login", json={"telegram_id": tg_id, "secret": secret}, timeout=5)
            cab_token = tr.json().get("token", "")
            r = req.post(f"{api_url}/cabinet/link_email", json={"token": cab_token, "email": email, "code": code}, timeout=10)
            if r.status_code == 200:
                del _email_wait[user.id]
                await update.message.reply_text(
                    f"✅ *Email успешно привязан!*\n\n"
                    f"📧 {email}\n\n"
                    f"Теперь вы можете войти в кабинет через email на сайте bet-agent.ru",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Неверный или истёкший код. Попробуйте ещё раз через /account")
                del _email_wait[user.id]
        except Exception as e:
            await update.message.reply_text("❌ Ошибка сервера. Попробуйте позже.")
            del _email_wait[user.id]
    elif text == "💳 Подписка":
        await do_buy(update, ctx)
    elif text == "🎁 Пригласить друга":
        await do_refer(update, ctx)
    elif text == "📋 Правила":
        await cmd_rules(update, ctx)
    elif text == "❓ Помощь":
        await do_help(update, ctx)


async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    # Не отвечаем тут — каждый handler отвечает сам
    if data == "accept_oferta":
        await cb_accept_oferta(update, ctx)
    elif data == "pay_basic":
        await do_pay_plan(update, ctx, "basic")
    elif data == "pay_pro":
        await do_pay_plan(update, ctx, "pro")
    elif data == "pay_premium":
        await do_pay_plan(update, ctx, "premium")
    elif data.startswith("check_pay_"):
        payment_id = data.replace("check_pay_", "")
        await check_payment(update, ctx, payment_id)
    else:
        await query.answer()



_email_wait = {}

async def link_email_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    # Проверяем не привязан ли уже email
    import requests as req
    import hmac, hashlib
    api_url = os.getenv("API_BASE_URL", "http://localhost:8001")
    secret = hmac.new(os.getenv("JWT_SECRET","").encode(), str(user.id).encode(), hashlib.sha256).hexdigest()[:16]
    try:
        tr = req.post(f"{api_url}/cabinet/tg_login", json={"telegram_id": user.id, "secret": secret}, timeout=5)
        cab_token = tr.json().get("token","")
        me = req.get(f"{api_url}/cabinet/me?token={cab_token}", timeout=5).json()
        if me.get("email_linked"):
            await query.message.reply_text(
                f"📧 Email уже привязан: *{me['email_linked']}*\n\n"
                "Для смены email обратитесь в поддержку @betagent\_admin",
                parse_mode="Markdown"
            )
            return
    except Exception:
        pass
    _email_wait[user.id] = "waiting_email"
    await query.message.reply_text(
        "📧 *Привязка email*\n\nВведите ваш email адрес:",
        parse_mode="Markdown"
    )

async def link_email_got_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in _email_wait:
        return
    state = _email_wait[user.id]
    text = update.message.text.strip().lower()
    if isinstance(state, str) and state == "waiting_email":
        if "@" not in text or "." not in text:
            await update.message.reply_text("❌ Некорректный email. Введите ещё раз:")
            return
        import requests as req
        api_url = os.getenv("API_BASE_URL", "http://localhost:8001")
        try:
            r = req.post(f"{api_url}/cabinet/send_code", json={"email": text}, timeout=10)
            log.warning(f"send_code status={r.status_code} body={r.text[:100]}")
            if r.status_code == 200:
                _email_wait[user.id] = {"state": "waiting_code", "email": text}
                await update.message.reply_text(
                    f"✅ Код отправлен на *{text}*\n\nВведите 6-значный код:",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Ошибка отправки.")
                del _email_wait[user.id]
        except Exception:
            await update.message.reply_text("❌ Ошибка подключения.")
            del _email_wait[user.id]
    elif isinstance(state, dict) and state.get("state") == "waiting_code":
        import requests as req, hmac, hashlib
        code = text.strip()
        email = state["email"]
        api_url = os.getenv("API_BASE_URL", "http://localhost:8001")
        secret = hmac.new(os.getenv("JWT_SECRET","").encode(), str(user.id).encode(), hashlib.sha256).hexdigest()[:16]
        try:
            tr = req.post(f"{api_url}/cabinet/tg_login", json={"telegram_id": user.id, "secret": secret}, timeout=5)
            cab_token = tr.json().get("token","")
            r = req.post(f"{api_url}/cabinet/link_email", json={"token": cab_token, "email": email, "code": code}, timeout=10)
            if r.status_code == 200:
                del _email_wait[user.id]
                await update.message.reply_text(
                    f"✅ *Email {email} привязан!*\n\nТеперь входите на bet-agent.ru через email.",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("❌ Неверный код. Попробуйте ещё раз через 👤 Аккаунт.")
                del _email_wait[user.id]
        except Exception:
            await update.message.reply_text("❌ Ошибка сервера.")
            del _email_wait[user.id]


async def cmd_cabinet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Открыть личный кабинет на сайте."""
    user = update.effective_user
    import requests, os, hmac, hashlib
    tg_id = user.id
    secret = hmac.new(os.getenv("JWT_SECRET","").encode(), str(tg_id).encode(), hashlib.sha256).hexdigest()[:16]
    api_url = os.getenv("API_BASE_URL", "http://localhost:8001")
    try:
        r = requests.post(f"{api_url}/cabinet/tg_login",
            json={"telegram_id": tg_id, "secret": secret}, timeout=5)
        if r.status_code == 200:
            token = r.json().get("token")
            expires = r.json().get("expires_at")
            url = f"https://bet-agent.ru/cabinet?token={token}"
            await update.message.reply_text(
                f"🌐 *Личный кабинет*\n\n"
                f"Ссылка действует 30 дней:\n{url}\n\n"
                f"_Не передавайте ссылку другим людям_",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("⚠️ Не удалось создать сессию. Попробуйте позже.")
    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка подключения к серверу.")


def main():
    if not BOT_TOKEN:
        raise ValueError("CLIENT_BOT_TOKEN не задан в .env")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("signals", do_signals))
    app.add_handler(CommandHandler("top",     do_top))
    app.add_handler(CommandHandler("stats",   do_stats))
    app.add_handler(CommandHandler("history", do_history))
    app.add_handler(CommandHandler("account", do_account))
    app.add_handler(CommandHandler("buy",     do_buy))
    app.add_handler(CommandHandler("help",    do_help))
    app.add_handler(CommandHandler("refer",   do_refer))
    app.add_handler(CommandHandler("cabinet", cmd_cabinet))
    app.add_handler(CallbackQueryHandler(link_email_start, pattern="^link_email_start$"))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_router))
    log.warning("Client bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    # При старте проверяем пропущенные уведомления
    import subprocess, sys
    try:
        subprocess.Popen(
            [sys.executable, str(BASE_DIR / "bot" / "notifier.py"), "--mode", "bets"],
            cwd=str(BASE_DIR),
        )
        print("✅ Запущена проверка пропущенных уведомлений")
    except Exception as e:
        print(f"⚠️ Не удалось запустить notifier: {e}")
    main()
