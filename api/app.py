import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
DEFAULT_SQLITE_DB = str(BASE_DIR / "betagent.db")

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")

from api.users import router as users_router
from api.signals import router as signals_router

app = FastAPI(
    title="BetAgent API",
    description="Аналитика спортивных событий",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(users_router)
app.include_router(signals_router)

@app.get("/")
def root():
    return {"status": "ok", "service": "BetAgent API", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "ok"}

from api.billing import router as billing_router
app.include_router(billing_router)

@app.get("/stats/equity")
def get_equity_data():
    """Данные для графика банка: бэктест + реальные ставки (по каждой ставке)."""
    import sqlite3, os
    db = os.getenv("BETAGENT_DB", DEFAULT_SQLITE_DB)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    # Бэктест — каждая ставка отдельно, последний run_id
    run_id = conn.execute(
        "SELECT run_id FROM backtest_equity ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    run_id = run_id[0] if run_id else None
    bt_rows = conn.execute("""
        SELECT match_date, profit
        FROM backtest_equity
        WHERE run_id = ?
        ORDER BY match_date ASC, id ASC
    """, (run_id,)).fetchall() if run_id else []

    # Реальные ставки — группируем по дням
    live_rows = conn.execute("""
        SELECT DATE(m.match_date) as match_date, SUM(b.profit) as profit
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost')
        AND b.profit IS NOT NULL
        AND COALESCE(b.excluded_from_stats,0)=0
        GROUP BY DATE(m.match_date)
        ORDER BY m.match_date ASC
    """).fetchall()
    conn.close()

    # Строим кривую бэктеста (прореживаем до 300 точек)
    bank = 100000
    all_bt = []
    for row in bt_rows:
        bank += (row["profit"] or 0)
        all_bt.append({"date": str(row["match_date"])[:10], "bank": round(bank)})
    step = max(1, len(all_bt) // 300)
    backtest_points = all_bt[::step]
    if all_bt and all_bt[-1] != backtest_points[-1]:
        backtest_points.append(all_bt[-1])

    # Реальные ставки — все точки
    live_points = []
    if backtest_points:
        bank = backtest_points[-1]["bank"]
    for row in live_rows:
        bank += (row["profit"] or 0)
        live_points.append({"date": str(row["match_date"])[:10], "bank": round(bank)})

    return {
        "backtest": backtest_points,
        "live": live_points,
        "start_bank": 100000,
        "current_bank": round(bank),
    }

@app.get("/stats/recent_bets")
def get_recent_bets():
    import sqlite3, os
    db = os.getenv("BETAGENT_DB", DEFAULT_SQLITE_DB)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT m.home_team, m.away_team, b.market, b.odds, b.result, b.profit
        FROM bets b JOIN matches m ON b.match_id = m.id
        WHERE b.result IN ('won','lost')
        AND b.profit IS NOT NULL
        AND COALESCE(b.excluded_from_stats,0)=0
        ORDER BY m.match_date DESC, b.created_at DESC
        LIMIT 10
    """).fetchall()
    conn.close()
    market_labels = {
        'draw': 'Ничья', 'home': 'П1', 'away': 'П2',
        'btts_yes': 'Обе забьют', 'over_2_5': 'ТБ 2.5',
        'under_2_5': 'ТМ 2.5'
    }
    return {"bets": [{
        "match": f"{r['home_team']} — {r['away_team']}",
        "market": market_labels.get(r['market'], r['market']),
        "odds": round(float(r['odds']), 2),
        "result": r['result'],
        "profit": round(float(r['profit']), 0)
    } for r in rows]}

# ── CABINET API ────────────────────────────────────────────
import secrets, hashlib
from datetime import datetime, timedelta

def _pg():
    import psycopg2, psycopg2.extras, os
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    conn.autocommit = True
    return conn

def _sqlite():
    import sqlite3, os
    db = os.getenv("BETAGENT_DB", DEFAULT_SQLITE_DB)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/cabinet/me")
def cabinet_me(token: str = ""):
    """Получить данные пользователя по токену сессии."""
    if not token:
        return JSONResponse({"error": "no_token"}, status_code=401)
    pg = _pg()
    cur = pg.cursor(cursor_factory=__import__('psycopg2').extras.RealDictCursor)
    cur.execute("""
        SELECT cs.user_id, cs.expires_at, u.telegram_id, u.first_name, u.username,
               s.plan, s.status, s.end_date, s.trial,
               u.referred_by
        FROM cabinet_sessions cs
        JOIN users u ON u.id = cs.user_id
        LEFT JOIN subscriptions s ON s.user_id = cs.user_id
        WHERE cs.token = %s AND cs.expires_at > NOW()
        ORDER BY s.end_date DESC LIMIT 1
    """, (token,))
    row = cur.fetchone()
    pg.close()
    if not row:
        return JSONResponse({"error": "invalid_token"}, status_code=401)
    # Достаём сигналы пользователя через user_signal_views -> signals -> bets в SQLite
    pg4 = _pg()
    cur4 = pg4.cursor(cursor_factory=__import__('psycopg2').extras.RealDictCursor)
    cur4.execute("""
        SELECT s.home_team, s.away_team, s.match_date, s.sport,
               s.market, s.odds, s.result, s.profit, s.created_at,
               usv.watermark_stake as stake
        FROM user_signal_views usv
        JOIN signals s ON s.id = usv.signal_id
        WHERE usv.user_id = %s
        ORDER BY usv.shown_at DESC LIMIT 50
    """, (row["user_id"],))
    pg_signals = cur4.fetchall()
    pg4.close()

    # Если сигналов нет в PG — показываем последние ставки из SQLite (старые данные)
    if pg_signals:
        bets_raw = [dict(s) for s in pg_signals]
    else:
        db = _sqlite()
        bets_raw = [dict(b) for b in db.execute("""
            SELECT m.home_team, m.away_team, m.match_date, m.sport,
                   b.market, b.odds, b.stake, b.result, b.profit, b.ev,
                   b.created_at
            FROM bets b JOIN matches m ON b.match_id = m.id
            WHERE COALESCE(b.excluded_from_stats,0)=0
            ORDER BY b.created_at DESC LIMIT 50
        """).fetchall()]
        db.close()
    bets = bets_raw
    # Статистика
    closed = [b for b in bets if b.get("result") in ("won","lost")]
    total_staked = sum(float(b.get("stake") or b.get("watermark_stake") or 1000) for b in closed)
    total_profit = sum(float(b.get("profit") or 0) for b in closed)
    roi = round(total_profit / total_staked * 100, 2) if total_staked else 0
    wins = sum(1 for b in closed if b.get("result") == "won")
    # Реферальная статистика
    pg2 = _pg()
    cur2 = pg2.cursor(cursor_factory=__import__('psycopg2').extras.RealDictCursor)
    cur2.execute("""
        SELECT COUNT(*) as count FROM referrals
        WHERE referrer_id = %s AND rewarded_at IS NOT NULL
    """, (row["user_id"],))
    ref_row = cur2.fetchone()
    pg2.close()
    plan_labels = {"basic":"Basic 🔵","pro":"Pro 🟣","premium":"Premium 💎","trial":"Пробный"}
    end_date = row["end_date"]
    days_left = max(0, (end_date.date() - datetime.now().date()).days) if end_date else 0
    # Проверяем привязанный email
    pg3 = _pg()
    cur3 = pg3.cursor(cursor_factory=__import__('psycopg2').extras.RealDictCursor)
    cur3.execute("SELECT email FROM user_emails WHERE user_id=%s AND verified=TRUE LIMIT 1", (row["user_id"],))
    email_row = cur3.fetchone()
    pg3.close()

    return {
        "user": {
            "first_name": row["first_name"],
            "username": row["username"],
            "telegram_id": row["telegram_id"],
        },
        "email_linked": email_row["email"] if email_row else None,
        "subscription": {
            "plan": row["plan"],
            "plan_label": plan_labels.get(row["plan"] or "trial", row["plan"]),
            "status": row["status"],
            "end_date": str(end_date)[:10] if end_date else None,
            "days_left": days_left,
            "trial": row["trial"],
        },
        "stats": {
            "total_bets": len(closed),
            "wins": wins,
            "losses": len(closed) - wins,
            "roi": roi,
            "profit": round(total_profit, 0),
            "winrate": round(wins / len(closed) * 100, 1) if closed else 0,
        },
        "referrals": {"paid_count": ref_row["count"] if ref_row else 0},
        "bets": [dict(b) for b in bets[:20]],
    }

@app.post("/cabinet/tg_login")
def cabinet_tg_login(data: dict):
    """Создать сессию по telegram_id (вызывается из бота)."""
    tg_id = data.get("telegram_id")
    secret = data.get("secret")
    # Проверяем секрет
    import os, hmac
    expected = hmac.new(os.getenv("JWT_SECRET","").encode(), str(tg_id).encode(), hashlib.sha256).hexdigest()[:16]
    if secret != expected:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    pg = _pg()
    cur = pg.cursor(cursor_factory=__import__('psycopg2').extras.RealDictCursor)
    cur.execute("SELECT id FROM users WHERE telegram_id = %s", (tg_id,))
    user = cur.fetchone()
    if not user:
        pg.close()
        return JSONResponse({"error": "user_not_found"}, status_code=404)
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(days=30)
    cur.execute("""
        INSERT INTO cabinet_sessions (user_id, token, expires_at)
        VALUES (%s, %s, %s)
    """, (user["id"], token, expires))
    pg.close()
    return {"token": token, "expires_at": str(expires)[:10]}

# ── EMAIL AUTH ─────────────────────────────────────────────
@app.post("/cabinet/send_code")
def cabinet_send_code(data: dict):
    """Отправить код подтверждения на email."""
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return JSONResponse({"error": "invalid_email"}, status_code=400)
    try:
        from api.email_auth import send_auth_code
        send_auth_code(email)
        return {"ok": True, "message": "Код отправлен"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/cabinet/verify_code")
def cabinet_verify_code(data: dict):
    """Проверить код и создать сессию."""
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not email or not code:
        return JSONResponse({"error": "missing_fields"}, status_code=400)
    from api.email_auth import verify_code, get_or_create_user_by_email
    import secrets as _secrets
    from datetime import datetime, timedelta
    if not verify_code(email, code):
        return JSONResponse({"error": "invalid_code"}, status_code=401)
    user = get_or_create_user_by_email(email)
    if not user:
        return JSONResponse({"error": "email_not_linked", "email": email}, status_code=404)
    # Создаём сессию
    pg = _pg()
    cur = pg.cursor()
    token = _secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(days=30)
    cur.execute(
        "INSERT INTO cabinet_sessions (user_id, token, expires_at) VALUES (%s, %s, %s)",
        (user["id"], token, expires)
    )
    pg.close()
    return {"token": token, "expires_at": str(expires)[:10]}

@app.post("/cabinet/link_email")
def cabinet_link_email(data: dict):
    """Привязать email к аккаунту (нужен токен сессии)."""
    token = data.get("token", "")
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not token or not email or not code:
        return JSONResponse({"error": "missing_fields"}, status_code=400)
    from api.email_auth import verify_code
    if not verify_code(email, code):
        return JSONResponse({"error": "invalid_code"}, status_code=401)
    pg = _pg()
    cur = pg.cursor(cursor_factory=__import__('psycopg2').extras.RealDictCursor)
    cur.execute("SELECT user_id FROM cabinet_sessions WHERE token=%s AND expires_at>NOW()", (token,))
    sess = cur.fetchone()
    if not sess:
        pg.close()
        return JSONResponse({"error": "invalid_token"}, status_code=401)
    # Привязываем email
    cur.execute("""
        INSERT INTO user_emails (user_id, email, verified)
        VALUES (%s, %s, TRUE)
        ON CONFLICT (email) DO UPDATE SET verified=TRUE, user_id=%s
    """, (sess["user_id"], email, sess["user_id"]))
    pg.close()
    return {"ok": True}

@app.get("/ref/{tg_id}")
def referral_redirect(tg_id: str):
    """Реферальная ссылка без Telegram — редирект в бот."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"https://t.me/betagent_analytics_bot?start=ref_{tg_id}")

@app.post("/billing/pay")
def billing_pay_cabinet(data: dict, authorization: str = ""):
    """Создать платёж из личного кабинета."""
    import os
    from fastapi.responses import JSONResponse as JR
    # Получаем токен из заголовка
    token = authorization.replace("Bearer ", "").strip() if authorization else data.get("token","")
    if not token:
        return JR({"error": "no_token"}, status_code=401)
    plan = data.get("plan", "basic")
    pg = _pg()
    cur = pg.cursor(cursor_factory=__import__('psycopg2').extras.RealDictCursor)
    cur.execute("SELECT user_id FROM cabinet_sessions WHERE token=%s AND expires_at>NOW()", (token,))
    sess = cur.fetchone()
    if not sess:
        pg.close()
        return JR({"error": "invalid_token"}, status_code=401)
    cur.execute("SELECT telegram_id FROM users WHERE id=%s", (sess["user_id"],))
    user = cur.fetchone()
    pg.close()
    if not user:
        return JR({"error": "user_not_found"}, status_code=404)
    # Используем существующий billing endpoint
    from api.billing import PLAN_PRICES, PLAN_LABELS, PLAN_DAYS
    from yookassa import Configuration, Payment as YPayment
    import uuid
    Configuration.account_id = os.getenv("YOOKASSA_SHOP_ID")
    Configuration.secret_key = os.getenv("YOOKASSA_SECRET_KEY")
    if plan not in PLAN_PRICES:
        return JR({"error": "invalid_plan"}, status_code=400)
    amount = PLAN_PRICES[plan]
    payment = YPayment.create({
        "amount": {"value": str(amount), "currency": "RUB"},
        "confirmation": {"type": "redirect", "return_url": "https://bet-agent.ru/cabinet?tab=pricing"},
        "description": f"BetAgent {PLAN_LABELS[plan]}",
        "metadata": {"plan": plan, "user_id": str(sess["user_id"]), "telegram_id": str(user["telegram_id"])},
        "receipt": {"customer": {"email": "noreply.betagent@yandex.ru"}, "items": [{"description": f"BetAgent {PLAN_LABELS[plan]}", "quantity": "1", "amount": {"value": str(amount), "currency": "RUB"}, "vat_code": "1"}]},
    }, str(uuid.uuid4()))
    return {"payment_id": payment.id, "payment_url": payment.confirmation.confirmation_url}

@app.get("/billing/status/{payment_id}")
def billing_status(payment_id: str):
    """Проверить статус платежа."""
    from yookassa import Configuration, Payment as YPayment
    import os
    Configuration.account_id = os.getenv("YOOKASSA_SHOP_ID")
    Configuration.secret_key = os.getenv("YOOKASSA_SECRET_KEY")
    try:
        p = YPayment.find_one(payment_id)
        return {"status": p.status}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
