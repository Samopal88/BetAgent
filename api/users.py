from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime, timedelta
from api.database import fetchone, execute
from api.auth import create_token, get_current_user, get_subscription

router = APIRouter(tags=["users"])

class TelegramAuthRequest(BaseModel):
    telegram_id: int
    username: str = ""
    first_name: str = ""
    ref: str = ""  # реферальный код: "ref_123456789"

def ensure_trial(user_id: int):
    existing = fetchone("SELECT id FROM subscriptions WHERE user_id=%s", (user_id,))
    if not existing:
        execute("""
            INSERT INTO subscriptions (user_id, plan, status, end_date, trial)
            VALUES (%s, 'basic', 'active', %s, TRUE)
        """, (user_id, datetime.utcnow() + timedelta(days=7)))

def process_referral(new_user_id: int, ref: str):
    """Записать реферала если пришёл по ссылке."""
    if not ref or not ref.startswith("ref_"):
        return
    try:
        referrer_tg_id = int(ref.replace("ref_", ""))
    except ValueError:
        return

    referrer = fetchone("SELECT id FROM users WHERE telegram_id=%s", (referrer_tg_id,))
    if not referrer:
        return
    if referrer["id"] == new_user_id:
        return  # нельзя приглашать самого себя

    # Записываем связь
    try:
        execute("""
            INSERT INTO referrals (referrer_id, referee_id, status)
            VALUES (%s, %s, 'pending')
            ON CONFLICT (referee_id) DO NOTHING
        """, (referrer["id"], new_user_id))
        execute("""
            UPDATE users SET referred_by=%s WHERE id=%s
        """, (referrer["id"], new_user_id))
    except Exception:
        pass

@router.post("/auth/telegram")
def auth_telegram(req: TelegramAuthRequest):
    user = fetchone("SELECT * FROM users WHERE telegram_id=%s", (req.telegram_id,))
    is_new = user is None

    if not user:
        execute("""
            INSERT INTO users (telegram_id, username, first_name)
            VALUES (%s, %s, %s)
        """, (req.telegram_id, req.username, req.first_name))
        user = fetchone("SELECT * FROM users WHERE telegram_id=%s", (req.telegram_id,))

    user = dict(user)

    if user.get("status") == "blocked":
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")

    # Обрабатываем реферал только для новых пользователей
    if is_new and req.ref:
        process_referral(user["id"], req.ref)

    ensure_trial(user["id"])

    token = create_token(user["id"], user["telegram_id"])
    sub = get_subscription(user["id"])

    return {
        "token": token,
        "user": {
            "id": user["id"],
            "telegram_id": user["telegram_id"],
            "username": user.get("username"),
            "first_name": user.get("first_name"),
        },
        "subscription": dict(sub) if sub else None,
        "is_new": is_new,
    }

@router.get("/account")
def account(user=Depends(get_current_user)):
    sub = get_subscription(user["id"])

    # Считаем рефералов
    refs = fetchone("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status='rewarded' THEN 1 ELSE 0 END) as rewarded
        FROM referrals WHERE referrer_id=%s
    """, (user["id"],))

    return {
        "user": {
            "id": user["id"],
            "telegram_id": user["telegram_id"],
            "username": user.get("username"),
            "first_name": user.get("first_name"),
            "status": user["status"],
        },
        "subscription": {
            "plan": sub["plan"] if sub else None,
            "status": sub["status"] if sub else "none",
            "expires_at": sub["end_date"].isoformat() if sub and sub.get("end_date") else None,
            "trial": sub.get("trial", False) if sub else False,
        } if sub else None,
        "has_access": sub is not None,
        "referrals": {
            "total": refs["total"] if refs else 0,
            "rewarded": refs["rewarded"] if refs else 0,
        }
    }

@router.get("/referral-link")
def referral_link(user=Depends(get_current_user)):
    link = f"https://t.me/betagent_analytics_bot?start=ref_{user['telegram_id']}"
    return {"link": link, "telegram_id": user["telegram_id"]}
