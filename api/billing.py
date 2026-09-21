import os
from pathlib import Path
import uuid
import hmac
import hashlib
import json
import requests as req
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from dotenv import load_dotenv
from api.database import fetchone, execute
from api.auth import get_current_user

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

YOOKASSA_SHOP_ID   = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET    = os.getenv("YOOKASSA_SECRET_KEY", "")
API_BASE_URL       = os.getenv("API_BASE_URL", "http://localhost:8001")
CLIENT_BOT_TOKEN   = os.getenv("CLIENT_BOT_TOKEN", "")

YOOKASSA_API = "https://api.yookassa.ru/v3"

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_PRICES = {
    "basic":   int(os.getenv("PRICE_BASIC",   "990")),
    "pro":     int(os.getenv("PRICE_PRO",     "2490")),
    "premium": int(os.getenv("PRICE_PREMIUM", "4900")),
}

PLAN_DAYS = {
    "basic":   25,
    "pro":     28,
    "premium": 35,
}

PLAN_LABELS = {
    "basic":   "Basic 🔵 — 990 ₽ / 25 дней",
    "pro":     "Pro 🟣 — 2 490 ₽ / 28 дней",
    "premium": "Premium 💎 — 4 900 ₽ / 35 дней",
}

# ── Создание платежа ───────────────────────────────────────────────────────
class CreatePaymentRequest(BaseModel):
    plan: str  # basic | pro | premium

@router.post("/create-payment")
def create_payment(body: CreatePaymentRequest, user=Depends(get_current_user)):
    plan = body.plan
    if plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail="Неверный тариф")

    if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET:
        raise HTTPException(status_code=503, detail="Платёжная система не настроена")

    amount = PLAN_PRICES[plan]
    idempotence_key = str(uuid.uuid4())

    payload = {
        "amount": {"value": f"{amount}.00", "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": f"https://t.me/betagent_analytics_bot"
        },
        "capture": True,
        "description": f"BetAgent Analytics — тариф {PLAN_LABELS[plan]}",
        "receipt": {
            "customer": {"email": "client@betagent.ru"},
            "items": [{
                "description": f"Подписка BetAgent {PLAN_LABELS[plan]}",
                "quantity": "1.00",
                "amount": {"value": f"{amount}.00", "currency": "RUB"},
                "vat_code": 1,
                "payment_mode": "full_payment",
                "payment_subject": "service",
            }]
        },
        "metadata": {
            "user_id": str(user["id"]),
            "telegram_id": str(user["telegram_id"]),
            "plan": plan,
        }
    }

    try:
        response = req.post(
            f"{YOOKASSA_API}/payments",
            json=payload,
            auth=(YOOKASSA_SHOP_ID, YOOKASSA_SECRET),
            headers={
                "Idempotence-Key": idempotence_key,
                "Content-Type": "application/json",
            },
            timeout=15
        )
        data = response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ошибка платёжной системы: {e}")

    if response.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=data.get("description", "Ошибка ЮKassa"))

    payment_id = data["id"]
    payment_url = data["confirmation"]["confirmation_url"]

    # Сохраняем платёж в БД
    execute("""
        INSERT INTO payments (user_id, amount, currency, provider, provider_payment_id, status, plan)
        VALUES (%s, %s, 'RUB', 'yookassa', %s, 'pending', %s)
    """, (user["id"], amount, payment_id, plan))

    return {
        "payment_id": payment_id,
        "payment_url": payment_url,
        "amount": amount,
        "plan": plan,
        "description": PLAN_LABELS[plan],
    }

# ── Webhook от ЮKassa ──────────────────────────────────────────────────────
@router.post("/webhook")
async def yookassa_webhook(request: Request):
    body = await request.body()

    # Верификация подписи (опционально но рекомендуется)
    # ЮKassa шлёт POST с JSON, проверка по IP или подписи
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = data.get("event")
    payment_obj = data.get("object", {})
    payment_id = payment_obj.get("id")
    status = payment_obj.get("status")
    metadata = payment_obj.get("metadata", {})

    if event != "payment.succeeded" or status != "succeeded":
        return {"ok": True}  # Игнорируем другие события

    user_id = int(metadata.get("user_id", 0))
    telegram_id = int(metadata.get("telegram_id", 0))
    plan = metadata.get("plan", "basic")

    if not user_id or not plan:
        return {"ok": True}

    # Обновляем статус платежа
    execute("""
        UPDATE payments SET status='succeeded'
        WHERE provider_payment_id=%s
    """, (payment_id,))

    # Активируем или продлеваем подписку
    activate_subscription(user_id, plan)

    # Уведомляем пользователя в Telegram
    if telegram_id and CLIENT_BOT_TOKEN:
        notify_user(telegram_id, plan)

    return {"ok": True}

def activate_subscription(user_id: int, plan: str):
    """Активировать или продлить подписку."""
    days = PLAN_DAYS.get(plan, 30)
    now = datetime.utcnow()

    # Проверяем есть ли активная подписка
    existing = fetchone("""
        SELECT * FROM subscriptions
        WHERE user_id=%s AND status='active' AND end_date > now()
        ORDER BY end_date DESC LIMIT 1
    """, (user_id,))

    if existing:
        new_end = existing["end_date"] + timedelta(days=days)
        execute("""
            UPDATE subscriptions
            SET plan=%s, end_date=%s, trial=FALSE, payment_provider='yookassa'
            WHERE id=%s
        """, (plan, new_end, existing["id"]))
    else:
        execute("""
            INSERT INTO subscriptions (user_id, plan, status, end_date, trial, payment_provider)
            VALUES (%s, %s, 'active', %s, FALSE, 'yookassa')
        """, (user_id, plan, now + timedelta(days=days)))

    # Начислить бонус рефереру если первая оплата
    reward_referrer(user_id)

def reward_referrer(user_id: int):
    """Начислить +7 дней Pro рефереру при первой оплате реферала."""
    # Проверяем — есть ли реферал и ещё не был награждён
    ref = fetchone("""
        SELECT * FROM referrals
        WHERE referee_id=%s AND status='pending'
    """, (user_id,))

    if not ref:
        return

    referrer_id = ref["referrer_id"]

    # Начисляем +7 дней Pro рефереру
    existing = fetchone("""
        SELECT * FROM subscriptions
        WHERE user_id=%s AND status='active' AND end_date > now()
        ORDER BY end_date DESC LIMIT 1
    """, (referrer_id,))

    bonus_days = 7
    now = datetime.utcnow()

    if existing:
        new_end = existing["end_date"] + timedelta(days=bonus_days)
        execute("""
            UPDATE subscriptions
            SET end_date=%s, plan='pro'
            WHERE id=%s
        """, (new_end, existing["id"]))
    else:
        execute("""
            INSERT INTO subscriptions (user_id, plan, status, end_date, trial)
            VALUES (%s, 'pro', 'active', %s, FALSE)
        """, (referrer_id, now + timedelta(days=bonus_days)))

    # Отмечаем реферала как награждённого
    execute("""
        UPDATE referrals SET status='rewarded', rewarded_at=now()
        WHERE id=%s
    """, (ref["id"],))

    # Уведомляем реферера
    referrer = fetchone("SELECT telegram_id FROM users WHERE id=%s", (referrer_id,))
    if referrer and CLIENT_BOT_TOKEN:
        notify_user_text(
            referrer["telegram_id"],
            "🎁 *Бонус за приглашение!*\n\n"
            "Ваш друг оплатил подписку.\n"
            "*+7 дней Pro* вам в подарок 🟣\n\n"
            "Приглашайте ещё — за каждого друга +7 дней!"
        )


def notify_user_text(telegram_id: int, text: str):
    try:
        req.post(
            f"https://api.telegram.org/bot{CLIENT_BOT_TOKEN}/sendMessage",
            json={"chat_id": telegram_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        print(f"notify_user_text error: {e}")

def notify_user(telegram_id: int, plan: str):
    """Отправить уведомление пользователю в Telegram."""
    label = PLAN_LABELS.get(plan, plan)
    days = PLAN_DAYS.get(plan, 30)
    text = (
        f"✅ *Оплата прошла успешно!*\n\n"
        f"Тариф: *{label}*\n"
        f"Подписка активирована на {days} дней.\n\n"
        f"Используй /signals чтобы увидеть сигналы."
    )
    try:
        req.post(
            f"https://api.telegram.org/bot{CLIENT_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": telegram_id,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10
        )
    except Exception as e:
        print(f"notify_user error: {e}")

# ── Ручная активация (для admin) ───────────────────────────────────────────
class ManualActivateRequest(BaseModel):
    telegram_id: int
    plan: str
    days: int = 30

@router.post("/admin/activate")
def admin_activate(body: ManualActivateRequest, request: Request):
    """Ручная активация подписки администратором."""
    admin_key = request.headers.get("X-Admin-Key", "")
    if admin_key != os.getenv("API_KEY", ""):
        raise HTTPException(status_code=403, detail="Forbidden")

    user = fetchone("SELECT * FROM users WHERE telegram_id=%s", (body.telegram_id,))
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    now = datetime.utcnow()
    existing = fetchone("""
        SELECT * FROM subscriptions
        WHERE user_id=%s AND status='active' AND end_date > now()
        ORDER BY end_date DESC LIMIT 1
    """, (user["id"],))

    if existing:
        new_end = existing["end_date"] + timedelta(days=body.days)
        execute("""
            UPDATE subscriptions SET plan=%s, end_date=%s, trial=FALSE
            WHERE id=%s
        """, (body.plan, new_end, existing["id"]))
    else:
        execute("""
            INSERT INTO subscriptions (user_id, plan, status, end_date, trial)
            VALUES (%s, %s, 'active', %s, FALSE)
        """, (user["id"], body.plan, now + timedelta(days=body.days)))

    if CLIENT_BOT_TOKEN:
        notify_user(user["telegram_id"], body.plan)

    return {"ok": True, "user_id": user["id"], "plan": body.plan, "days": body.days}

# ── Статус платежа ─────────────────────────────────────────────────────────
@router.get("/status/{payment_id}")
def payment_status(payment_id: str, user=Depends(get_current_user)):
    payment = fetchone("""
        SELECT * FROM payments
        WHERE provider_payment_id=%s AND user_id=%s
    """, (payment_id, user["id"]))

    if not payment:
        raise HTTPException(status_code=404, detail="Платёж не найден")

    return {
        "payment_id": payment_id,
        "status": payment["status"],
        "amount": payment["amount"],
        "plan": payment["plan"],
        "created_at": payment["created_at"].isoformat() if payment.get("created_at") else None,
    }
