import smtplib, ssl, os, random, string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import psycopg2, psycopg2.extras

def get_pg():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    conn.autocommit = True
    return conn

def send_email(to: str, subject: str, html: str, text: str):
    host = os.getenv("SMTP_HOST", "smtp.yandex.ru")
    port = int(os.getenv("SMTP_PORT", 465))
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASS")
    frm  = os.getenv("SMTP_FROM", user)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())

def generate_code() -> str:
    return ''.join(random.choices(string.digits, k=6))

def send_auth_code(email: str) -> bool:
    code = generate_code()
    pg = get_pg()
    cur = pg.cursor()
    # Инвалидируем старые коды
    cur.execute("UPDATE auth_codes SET used=TRUE WHERE email=%s AND used=FALSE", (email,))
    # Сохраняем новый код
    expires = datetime.now() + timedelta(minutes=15)
    cur.execute(
        "INSERT INTO auth_codes (email, code, expires_at) VALUES (%s, %s, %s)",
        (email, code, expires)
    )
    pg.close()
    html = f"""
    <div style="font-family:monospace;background:#080b0f;color:#e8edf5;padding:40px;max-width:480px;margin:0 auto;border-radius:12px">
      <div style="font-size:20px;font-weight:800;color:#00e5a0;margin-bottom:8px">BetAgent</div>
      <div style="font-size:14px;color:#7a8a9a;margin-bottom:32px">Аналитика ставок</div>
      <div style="font-size:14px;margin-bottom:16px">Ваш код для входа в личный кабинет:</div>
      <div style="font-size:48px;font-weight:800;color:#00e5a0;letter-spacing:8px;margin:24px 0">{code}</div>
      <div style="font-size:12px;color:#4a5a6a">Код действителен 15 минут.<br>Если вы не запрашивали код — проигнорируйте это письмо.</div>
    </div>
    """
    text = f"BetAgent — код для входа: {code}\nДействителен 15 минут."
    send_email(email, "BetAgent — код для входа", html, text)
    return True

def verify_code(email: str, code: str) -> bool:
    pg = get_pg()
    cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id FROM auth_codes
        WHERE email=%s AND code=%s AND used=FALSE AND expires_at > NOW()
        LIMIT 1
    """, (email, code))
    row = cur.fetchone()
    if row:
        cur.execute("UPDATE auth_codes SET used=TRUE WHERE id=%s", (row["id"],))
    pg.close()
    return row is not None

def get_or_create_user_by_email(email: str) -> dict | None:
    pg = get_pg()
    cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # Ищем привязанный аккаунт
    cur.execute("""
        SELECT u.* FROM users u
        JOIN user_emails ue ON ue.user_id = u.id
        WHERE ue.email = %s AND ue.verified = TRUE
    """, (email,))
    user = cur.fetchone()
    pg.close()
    return dict(user) if user else None
