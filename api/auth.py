import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import jwt
from jwt import PyJWTError
from fastapi import Header, HTTPException, status
from dotenv import load_dotenv
from api.database import fetchone

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
ALGORITHM = "HS256"

def create_token(user_id: int, telegram_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "tg": telegram_id, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Недействительный токен")

def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Нужен Bearer токен")
    token = authorization[7:]
    payload = decode_token(token)
    user_id = int(payload.get("sub", 0))
    user = fetchone("SELECT * FROM users WHERE id=%s AND status='active'", (user_id,))
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return dict(user)

def get_subscription(user_id: int) -> Optional[dict]:
    row = fetchone("""
        SELECT * FROM subscriptions
        WHERE user_id=%s AND status='active' AND end_date > now()
        ORDER BY end_date DESC LIMIT 1
    """, (user_id,))
    return dict(row) if row else None

def require_subscription(authorization: str = Header(...)):
    user = get_current_user(authorization)
    sub = get_subscription(user["id"])
    if not sub:
        raise HTTPException(
            status_code=403,
            detail="Требуется активная подписка. /buy для оплаты."
        )
    user["subscription"] = sub
    return user
