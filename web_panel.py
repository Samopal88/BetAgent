#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template_string, request, Response
from functools import wraps
import secrets

# Загружаем .env явно
_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("BETAGENT_DB", str(BASE_DIR / "betagent.db"))
START_BANK = float(os.getenv("BETAGENT_BANK", "100000"))

# ── Basic Auth ──
PANEL_USER = os.getenv("PANEL_USER", "betagent")
PANEL_PASS = os.getenv("PANEL_PASS", "")

def check_auth(username, password):
    return secrets.compare_digest(username, PANEL_USER) and secrets.compare_digest(password, PANEL_PASS)

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Доступ запрещён", 401,
                {"WWW-Authenticate": 'Basic realm="BETAGENT"'}
            )
        return f(*args, **kwargs)
    return decorated



@app.before_request
def auth_check():
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return Response(
            "Доступ запрещён", 401,
            {"WWW-Authenticate": 'Basic realm="BETAGENT"'}
        )

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def table_exists(conn, name):
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None

def pick_col(conn, table, candidates):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols = [r["name"] for r in rows]
    for c in candidates:
        if c in cols:
            return c
    return None

def safe_read(path, limit=25000):
    try:
        if path and Path(path).exists():
            return Path(path).read_text(encoding="utf-8", errors="replace")[-limit:]
    except Exception as e:
        return f"Ошибка чтения {path}: {e}"
    return ""

def latest_matching_file(directory, pattern):
    files = sorted(Path(directory).glob(pattern))
    return files[-1] if files else None

def service_status(name):
    try:
        active = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=10)
        enabled = subprocess.run(["systemctl", "is-enabled", name], capture_output=True, text=True, timeout=10)
        return {"active": active.stdout.strip(), "enabled": enabled.stdout.strip()}
    except Exception as e:
        return {"active": f"error: {e}", "enabled": "unknown"}

def process_running(pattern):
    try:
        r = subprocess.run(["bash", "-lc", f"pgrep -f '{pattern}' >/dev/null && echo yes || echo no"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "yes"
    except Exception:
        return False

def current_bankroll(conn):
    if not table_exists(conn, "bets"):
        return START_BANK
    row = conn.execute("SELECT COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END), 0) AS p FROM bets WHERE COALESCE(excluded_from_stats,0)=0").fetchone()
    return round(START_BANK + (row["p"] or 0), 2)

def stats_30d(conn):
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    if not table_exists(conn, "bets"):
        return {"wins":0,"losses":0,"pending":0,"staked":0,"profit":0,"roi":0,"winrate":0,"pending_sum":0}
    row = conn.execute("""
        SELECT
            SUM(CASE WHEN result='won' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN result='lost' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN result='pending' THEN 1 ELSE 0 END) AS pending,
            COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) AS staked,
            COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) AS profit,
            COALESCE(SUM(CASE WHEN result='pending' THEN stake ELSE 0 END),0) AS pending_sum
        FROM bets WHERE COALESCE(excluded_from_stats,0)=0 AND created_at >= ?
    """, (since,)).fetchone()
    wins = row["wins"] or 0
    losses = row["losses"] or 0
    staked = row["staked"] or 0
    profit = row["profit"] or 0
    total_closed = wins + losses
    roi = (profit / staked * 100) if staked else 0
    winrate = (wins / total_closed * 100) if total_closed else 0
    return {
        "wins": wins, "losses": losses, "pending": row["pending"] or 0,
        "staked": round(staked, 2), "profit": round(profit, 2),
        "roi": round(roi, 2), "winrate": round(winrate, 1),
        "pending_sum": round(row["pending_sum"] or 0, 2),
    }

HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0">
<title>BETAGENT PRO V2</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');
:root{
  --bg:#070910;--bg2:#0b0f1c;--card:#101728;--card2:#141d31;--line:#1e2a42;
  --text:#edf3ff;--muted:#6a7a96;--accent:#5b6bff;--accent2:#19d3b4;--green:#1dde87;
  --red:#ff4d6a;--yellow:#ffc857;--purple:#b28cff;--shadow:0 8px 24px rgba(0,0,0,.3);
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;background:var(--bg);color:var(--text);font-family:'Space Grotesk',sans-serif;overflow-x:hidden}

/* ── HEADER ── */
.header{
  position:sticky;top:0;z-index:100;
  display:flex;align-items:center;gap:12px;
  padding:12px 16px;
  background:rgba(7,9,16,.92);
  border-bottom:1px solid var(--line);
  backdrop-filter:blur(16px);
}
.brand{display:flex;align-items:center;gap:8px;flex-shrink:0}
.bolt{font-size:22px}
.logo{font-size:22px;font-weight:800;letter-spacing:-0.5px;background:linear-gradient(135deg,#5b6bff,#8b5cf6,#ff356f);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--accent2);box-shadow:0 0 8px var(--accent2);flex-shrink:0}

/* ── BOTTOM NAV (mobile) ── */
.bottom-nav{
  position:fixed;bottom:0;left:0;right:0;z-index:100;
  display:flex;
  background:rgba(10,13,22,.96);
  border-top:1px solid var(--line);
  backdrop-filter:blur(16px);
  padding:0 0 env(safe-area-inset-bottom,0) 0;
}
.bottom-nav button{
  flex:1;border:none;background:transparent;color:var(--muted);
  padding:10px 4px 8px;font-size:10px;font-weight:700;
  cursor:pointer;transition:.15s;display:flex;flex-direction:column;align-items:center;gap:3px;
  letter-spacing:.3px;text-transform:uppercase;
}
.bottom-nav button .nav-icon{font-size:18px;line-height:1}
.bottom-nav button.active{color:var(--accent)}
.bottom-nav button.active .nav-icon{filter:drop-shadow(0 0 6px var(--accent))}

/* ── DESKTOP NAV ── */
.desktop-nav{margin-left:auto;display:none;gap:8px}
.desktop-nav button{
  border:1px solid var(--line);background:rgba(255,255,255,.02);
  color:#c6d2eb;padding:8px 14px;border-radius:10px;
  font-size:13px;font-weight:700;cursor:pointer;transition:.15s;
}
.desktop-nav button:hover,.desktop-nav button.active{
  background:linear-gradient(135deg,#4a54df,#6540ef);
  color:#fff;border-color:transparent;
}
@media(min-width:768px){
  .bottom-nav{display:none}
  .desktop-nav{display:flex}
  .wrap{padding-bottom:22px}
}

/* ── LAYOUT ── */
.wrap{max-width:1600px;margin:0 auto;padding:16px 12px 80px}
@media(min-width:768px){.wrap{padding:20px 22px 22px}}
.section{display:none}.section.active{display:block}
.grid-5,.grid-4,.grid-3,.grid-2{display:grid;gap:12px;margin-bottom:14px}
.grid-5{grid-template-columns:repeat(2,1fr)}
.grid-4{grid-template-columns:repeat(2,1fr)}
.grid-3{grid-template-columns:repeat(2,1fr)}
.grid-2{grid-template-columns:1fr}
@media(min-width:600px){
  .grid-2{grid-template-columns:repeat(2,1fr)}
  .grid-3{grid-template-columns:repeat(3,1fr)}
}
@media(min-width:900px){
  .grid-4{grid-template-columns:repeat(4,1fr)}
  .grid-5{grid-template-columns:repeat(5,1fr)}
}

/* ── CARDS ── */
.card{
  background:linear-gradient(160deg,var(--card),var(--card2));
  border:1px solid var(--line);border-radius:18px;
  padding:16px;box-shadow:var(--shadow);
}
.card-title{font-size:10px;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted);margin-bottom:6px;font-weight:700}
.card-value{font-size:34px;font-weight:800;letter-spacing:-1px}
.card-sub{margin-top:6px;color:var(--muted);font-size:12px}
@media(min-width:768px){.card-value{font-size:40px}}

/* ── GOLDEN ── */
.golden-hero{background:linear-gradient(135deg,#1a1040,#0f1e35,#1a1040);border:1px solid rgba(255,197,0,.2);border-radius:20px;padding:22px;position:relative;overflow:hidden;box-shadow:0 0 40px rgba(255,197,0,.06)}
.golden-hero::before{content:'';position:absolute;top:-60px;right:-60px;width:180px;height:180px;background:radial-gradient(circle,rgba(255,197,0,.1),transparent 70%);pointer-events:none}
.golden-badge{display:inline-flex;align-items:center;gap:6px;background:linear-gradient(135deg,rgba(255,197,0,.12),rgba(255,150,0,.08));border:1px solid rgba(255,197,0,.25);border-radius:999px;padding:5px 12px;font-size:11px;font-weight:800;color:#ffc857;text-transform:uppercase;letter-spacing:1px;margin-bottom:14px}
.golden-match{font-size:18px;font-weight:800;color:#fff;margin-bottom:8px;line-height:1.3}
.golden-bet{font-size:28px;font-weight:800;background:linear-gradient(135deg,#ffd700,#ffaa00);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:6px}
.golden-meta{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.golden-pill{display:inline-flex;align-items:center;gap:5px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:8px;padding:5px 10px;font-size:12px;font-weight:600}
.golden-reasoning{background:rgba(255,255,255,.03);border-left:3px solid rgba(255,197,0,.4);border-radius:0 10px 10px 0;padding:12px 14px;font-size:13px;line-height:1.6;color:#c8d8f0;font-style:italic;margin-top:10px}
.golden-stat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
.golden-stat{background:rgba(255,197,0,.05);border:1px solid rgba(255,197,0,.12);border-radius:14px;padding:14px;text-align:center}
.golden-stat-val{font-size:24px;font-weight:800;color:#ffc857}
.golden-stat-lbl{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-top:4px;font-weight:700}
.no-golden{text-align:center;padding:32px 20px;color:var(--muted)}
.no-golden-icon{font-size:40px;margin-bottom:10px}

/* ── STRATEGY TAB ── */
.strategy-controls{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin-bottom:14px}
.ctrl-row{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px;align-items:center}
.ctrl-label{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);font-weight:700;width:100%}
.ctrl-chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid var(--line);background:rgba(255,255,255,.02);color:var(--muted);padding:6px 12px;border-radius:999px;font-size:12px;font-weight:700;cursor:pointer;transition:.15s;user-select:none}
.chip.on{background:linear-gradient(135deg,#4a54df,#6540ef);color:#fff;border-color:transparent}
.chip-sport.football.on{background:linear-gradient(135deg,#2563eb,#1d4ed8)}
.chip-sport.hockey.on{background:linear-gradient(135deg,#7c3aed,#6d28d9)}
.ctrl-inputs{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
.ctrl-input-group{display:flex;flex-direction:column;gap:4px}
.ctrl-input-group label{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);font-weight:700}
.ctrl-input-group input{background:rgba(255,255,255,.04);border:1px solid var(--line);color:var(--text);padding:8px 12px;border-radius:10px;font-size:13px;font-family:'JetBrains Mono',monospace;width:120px}
.btn-apply{background:linear-gradient(135deg,#4a54df,#6540ef);color:#fff;border:none;border-radius:10px;padding:9px 16px;font-size:13px;font-weight:800;cursor:pointer}

.strategy-cards{display:grid;grid-template-columns:1fr;gap:10px;margin-bottom:14px}
@media(min-width:600px){.strategy-cards{grid-template-columns:repeat(2,1fr)}}
@media(min-width:900px){.strategy-cards{grid-template-columns:repeat(3,1fr)}}

.s-card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;cursor:pointer;transition:.15s;position:relative}
.s-card:hover{border-color:var(--accent);transform:translateY(-1px)}
.s-card.selected{border-color:var(--accent);background:linear-gradient(160deg,#0f1728,#131e35)}
.s-card-name{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:#fff;margin-bottom:8px}
.s-card-sport{position:absolute;top:12px;right:12px;font-size:10px;font-weight:700;padding:3px 8px;border-radius:999px}
.s-card-sport.football{background:#1e3a8a33;color:#60a5fa}
.s-card-sport.hockey{background:#4c1d9533;color:#c084fc}
.s-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px}
.s-metric{text-align:center}
.s-metric-val{font-size:16px;font-weight:800}
.s-metric-lbl{font-size:9px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-top:2px}
.s-check{position:absolute;top:10px;left:10px;width:16px;height:16px;border-radius:4px;border:1.5px solid var(--line);background:transparent;transition:.15s}
.s-card.selected .s-check{background:var(--accent);border-color:var(--accent)}
.s-card.selected .s-check::after{content:'✓';position:absolute;font-size:10px;color:#fff;top:-1px;left:2px}

.chart-area{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin-bottom:14px}
.chart-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:8px}
.chart-title{font-size:13px;font-weight:800;text-transform:uppercase;letter-spacing:1px}
.chart-stats{display:flex;gap:14px;flex-wrap:wrap}
.chart-stat{text-align:right}
.chart-stat-val{font-size:18px;font-weight:800}
.chart-stat-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
canvas{max-height:300px}
@media(min-width:768px){canvas{max-height:360px}}

/* ── MISC ── */
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}
.btn{border:none;border-radius:12px;padding:11px 16px;font-size:13px;font-weight:800;cursor:pointer;font-family:inherit}
.btn-primary{background:linear-gradient(135deg,#4a54df,#6540ef);color:#fff}
.btn-success{background:linear-gradient(135deg,#0d9e5e,#1dde87);color:#04120a}
.btn-outline{background:rgba(255,255,255,.03);border:1px solid var(--line);color:#dbe7ff}
.table-wrap{overflow:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;min-width:500px}
th,td{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;font-size:12px;vertical-align:top}
th{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--muted)}
tr:hover td{background:rgba(255,255,255,.015)}
.badge{display:inline-block;padding:3px 8px;border-radius:999px;font-size:10px;font-weight:800;text-transform:uppercase}
.b-green{background:#0d3320;color:#4ade80}.b-red{background:#3b0f1a;color:#f87171}
.b-yellow{background:#3b2c0a;color:#fbbf24}.b-blue{background:#0f2a4a;color:#60a5fa}
.b-purple{background:#2a1052;color:#c084fc}.b-cyan{background:#0a2e2b;color:#67e8f9}
.muted{color:var(--muted)}.mono{font-family:'JetBrains Mono',monospace}
.good{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--yellow)}.accent{color:var(--accent)}
.section-title{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted);margin-bottom:10px;font-weight:800}
.log-box{height:360px;overflow:auto;white-space:pre-wrap;font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.5;background:#070d16;border:1px solid var(--line);border-radius:14px;padding:14px}
.empty{padding:28px;text-align:center;color:var(--muted);font-size:13px}
.toast{position:fixed;right:14px;bottom:74px;z-index:200;background:linear-gradient(180deg,#111a2b,#152036);border:1px solid var(--line);color:#fff;padding:12px 16px;border-radius:12px;opacity:0;transform:translateY(6px);transition:.2s ease;font-size:13px;max-width:260px}
.toast.show{opacity:1;transform:translateY(0)}
@media(min-width:768px){.toast{bottom:20px}}
.divider{height:1px;background:var(--line);margin:14px 0}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="brand">
    <div class="bolt">⚡</div>
    <div class="logo">BETAGENT</div>
  </div>
  <div class="status-dot"></div>
  <div class="desktop-nav">
    <button class="active" onclick="showTab('dashboard',this)">Dashboard</button>
    <button onclick="showTab('bets',this)">Ставки</button>
    <button onclick="showTab('strategies',this)">📊 Стратегии</button>
    <button onclick="showTab('stats',this)">Статистика</button>
    <button onclick="showTab('golden',this)">💎 ЖБ</button>
    <button onclick="showTab('shadow',this)">Shadow</button>
    <button onclick="showTab('logs',this)">Логи</button>
  </div>
</div>

<!-- BOTTOM NAV (mobile) -->
<div class="bottom-nav">
  <button class="active" onclick="showTab('dashboard',this)">
    <span class="nav-icon">🏠</span>Главная
  </button>
  <button onclick="showTab('bets',this)">
    <span class="nav-icon">🎯</span>Ставки
  </button>
  <button onclick="showTab('strategies',this)">
    <span class="nav-icon">📊</span>Стратегии
  </button>
  <button onclick="showTab('golden',this)">
    <span class="nav-icon">💎</span>ЖБ
  </button>
  <button onclick="showTab('logs',this)">
    <span class="nav-icon">📋</span>Логи
  </button>
</div>

<div class="wrap">

  <!-- ══ DASHBOARD ══ -->
  <div id="tab-dashboard" class="section active">
    <div class="grid-5">
      <div class="card"><div class="card-title">Банкролл</div><div class="card-value accent" id="bankroll">—</div><div class="card-sub">старт: 100,000 ₽</div></div>
      <div class="card"><div class="card-title">ROI (30д)</div><div class="card-value" id="roi30">—</div><div class="card-sub" id="profit30">—</div></div>
      <div class="card"><div class="card-title">Pending</div><div class="card-value warn" id="pendingCount">—</div><div class="card-sub" id="pendingSum">—</div></div>
      <div class="card"><div class="card-title">Винрейт</div><div class="card-value" id="winrate">—</div><div class="card-sub" id="wlText">—</div></div>
      <div class="card"><div class="card-title">Сервисы</div><div class="card-value" id="servicesState">—</div><div class="card-sub" id="servicesSub">—</div></div>
    </div>

    <div class="actions">
      <button class="btn btn-primary" onclick="runPipeline()">🚀 Пайплайн</button>
      <button class="btn btn-success" onclick="settleNow()">✅ Settle</button>
      <button class="btn btn-outline" onclick="loadAll()">🔄 Refresh</button>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="section-title">Активные ставки</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Матч</th><th>Рынок</th><th>БК</th><th>Коэф</th><th>Ставка</th><th>EV</th></tr></thead>
            <tbody id="pendingTable"><tr><td colspan="6" class="empty">Загрузка...</td></tr></tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <div class="section-title">Последние результаты</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Матч</th><th>Счёт</th><th>Ставка</th><th>Прибыль</th></tr></thead>
            <tbody id="resultsTable"><tr><td colspan="4" class="empty">Загрузка...</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card"><div class="section-title">Bankroll curve</div><canvas id="bankrollChart"></canvas></div>
      <div class="card"><div class="section-title">ROI по дням</div><canvas id="dailyChart"></canvas></div>
    </div>
  </div>

  <!-- ══ СТАВКИ ══ -->
  <div id="tab-bets" class="section">
    <div class="card">
      <div class="section-title">Все ставки</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Дата</th><th>Спорт</th><th>Матч</th><th>Рынок</th><th>БК</th><th>Коэф</th><th>Ставка</th><th>EV</th><th>Результат</th><th>Прибыль</th></tr></thead>
          <tbody id="betsTable"><tr><td colspan="10" class="empty">Загрузка...</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ══ СТРАТЕГИИ ══ -->
  <div id="tab-strategies" class="section">

    <!-- Фильтры -->
    <div class="strategy-controls">
      <div class="ctrl-row">
        <div class="ctrl-label">Вид спорта</div>
        <div class="ctrl-chips" id="sportChips">
          <div class="chip chip-sport football on" data-sport="football" onclick="toggleSport(this)">⚽ Футбол</div>
          <div class="chip chip-sport hockey on" data-sport="hockey" onclick="toggleSport(this)">🏒 Хоккей</div>
        </div>
      </div>
      <div class="ctrl-row">
        <div class="ctrl-label">Источник данных</div>
        <div class="ctrl-chips">
          <div class="chip on" id="srcBacktest" onclick="toggleSource('backtest',this)">📊 Бэктест</div>
          <div class="chip on" id="srcLive" onclick="toggleSource('live',this)">🎯 Боевые</div>
        </div>
      </div>
      <div class="divider"></div>
      <div class="ctrl-inputs">
        <div class="ctrl-input-group">
          <label>Дата от</label>
          <input type="date" id="dateFrom" value="2021-01-01">
        </div>
        <div class="ctrl-input-group">
          <label>Дата до</label>
          <input type="date" id="dateTo">
        </div>
        <div class="ctrl-input-group">
          <label>Начальный банк ₽</label>
          <input type="number" id="initBank" value="100000" step="10000">
        </div>
        <button class="btn-apply" onclick="loadStrategies()">Применить</button>
      </div>
    </div>

    <!-- Карточки стратегий -->
    <div id="strategyCards" class="strategy-cards"></div>

    <!-- График баланса -->
    <div class="chart-area">
      <div class="chart-header">
        <div class="chart-title">График баланса</div>
        <div class="chart-stats">
          <div class="chart-stat">
            <div class="chart-stat-val good" id="chartROI">—</div>
            <div class="chart-stat-lbl">ROI</div>
          </div>
          <div class="chart-stat">
            <div class="chart-stat-val" id="chartN">—</div>
            <div class="chart-stat-lbl">Ставок</div>
          </div>
          <div class="chart-stat">
            <div class="chart-stat-val" id="chartMaxLS">—</div>
            <div class="chart-stat-lbl">MaxLS</div>
          </div>
          <div class="chart-stat">
            <div class="chart-stat-val good" id="chartProfit">—</div>
            <div class="chart-stat-lbl">Прибыль</div>
          </div>
        </div>
      </div>
      <canvas id="strategyChart"></canvas>
    </div>

    <!-- Мини-таблица по выбранным стратегиям -->
    <div class="card">
      <div class="section-title">Итог по выбранным стратегиям</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Стратегия</th><th>Спорт</th><th>n</th><th>Hit%</th><th>ROI</th><th>MaxLS</th><th>Прибыль</th></tr></thead>
          <tbody id="strategyTable"><tr><td colspan="7" class="empty">Выберите стратегии выше</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ══ СТАТИСТИКА ══ -->
  <div id="tab-stats" class="section">
    <div class="grid-4">
      <div class="card"><div class="card-title">Всего ставок</div><div class="card-value accent" id="totalBets">—</div><div class="card-sub">all time</div></div>
      <div class="card"><div class="card-title">Закрыто</div><div class="card-value" id="closedBets">—</div><div class="card-sub">won + lost</div></div>
      <div class="card"><div class="card-title">Pending EV avg</div><div class="card-value" id="pendingEvAvg">—</div><div class="card-sub">активные</div></div>
      <div class="card"><div class="card-title">Лучший спорт</div><div class="card-value" id="bestSport">—</div><div class="card-sub" id="bestSportSub">—</div></div>
    </div>
    <div class="grid-2">
      <div class="card"><div class="section-title">ROI по спорту</div><canvas id="sportChart"></canvas></div>
      <div class="card">
        <div class="section-title">Сервисы</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Компонент</th><th>Статус</th><th>Инфо</th></tr></thead>
            <tbody id="serviceTable"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ ЖБ ══ -->
  <div id="tab-golden" class="section">
    <div id="goldenHeroWrap"></div>
    <div class="golden-stat-grid" style="margin-top:14px">
      <div class="golden-stat"><div class="golden-stat-val" id="gsTotal">—</div><div class="golden-stat-lbl">Всего</div></div>
      <div class="golden-stat"><div class="golden-stat-val" id="gsWinrate">—</div><div class="golden-stat-lbl">Винрейт</div></div>
      <div class="golden-stat"><div class="golden-stat-val" id="gsROI">—</div><div class="golden-stat-lbl">ROI</div></div>
    </div>
    <div style="display:flex;gap:10px;margin-bottom:14px">
      <div class="golden-stat" style="flex:1"><div class="golden-stat-val" id="gsWins">—</div><div class="golden-stat-lbl">Won</div></div>
      <div class="golden-stat" style="flex:1"><div class="golden-stat-val" id="gsLosses">—</div><div class="golden-stat-lbl">Lost</div></div>
      <div class="golden-stat" style="flex:1"><div class="golden-stat-val" id="gsPending">—</div><div class="golden-stat-lbl">Pending</div></div>
      <div class="golden-stat" style="flex:1"><div class="golden-stat-val" id="gsProfit">—</div><div class="golden-stat-lbl">Прибыль</div></div>
    </div>
    <div class="card">
      <div class="section-title">История ЖБ ставок</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Дата</th><th>Матч</th><th>Рынок</th><th>Коэф</th><th>EV</th><th>Уверенность</th><th>Результат</th><th>Прибыль</th></tr></thead>
          <tbody id="goldenHistoryTable"><tr><td colspan="8" class="empty">Загрузка...</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ══ SHADOW ══ -->
  <div id="tab-shadow" class="section">
    <div class="grid-4">
      <div class="card"><div class="card-title">Всего shadow</div><div class="card-value" id="shadowTotal">—</div><div class="card-sub" id="shadowLast">—</div></div>
      <div class="card"><div class="card-title">OLD valid</div><div class="card-value" id="shadowOldValid">—</div><div class="card-sub" id="shadowOldSub">—</div></div>
      <div class="card"><div class="card-title">NEW valid</div><div class="card-value" id="shadowNewValid">—</div><div class="card-sub" id="shadowNewSub">—</div></div>
      <div class="card"><div class="card-title">Разница</div><div class="card-value" id="shadowDiff">—</div><div class="card-sub">new − old</div></div>
    </div>
    <div class="grid-2">
      <div class="card"><div class="section-title">Shadow сравнение</div><canvas id="shadowChart"></canvas></div>
      <div class="card">
        <div class="section-title">Сводка</div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Метрика</th><th>OLD</th><th>NEW</th></tr></thead>
            <tbody id="shadowSummary"></tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="section-title">Последние shadow записи</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Матч</th><th>OLD</th><th>NEW</th><th>Результат</th></tr></thead>
          <tbody id="shadowTable"><tr><td colspan="4" class="empty">Загрузка...</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ══ ЛОГИ ══ -->
  <div id="tab-logs" class="section">
    <div class="grid-2">
      <div class="card"><div class="section-title">Cron log</div><div class="log-box" id="cronLog">Загрузка...</div></div>
      <div class="card"><div class="section-title">Pipeline log</div><div class="log-box" id="pipelineLog">Загрузка...</div></div>
    </div>
    <div class="grid-2">
      <div class="card"><div class="section-title">Web log</div><div class="log-box" id="webLog">Загрузка...</div></div>
      <div class="card"><div class="section-title">Bot log</div><div class="log-box" id="botLog">Загрузка...</div></div>
    </div>
  </div>

</div><!-- /wrap -->

<div class="toast" id="toast"></div>

<script>
// ── Strategy name mapping ──
const STRATEGY_LABELS = {
  'SA_AWAY_DRAW':           '🇮🇹 Серия А | Ничья аутсайдеров',
  'DRAW_SA':                '🇮🇹 Серия А | Ничья равных',
  'DRAW_BALANCED_LINE_SA':  '🇮🇹 Серия А | Ничья сбалансированных',
  'NLA_BERN_AWAY_DRAW':     '🇨🇭 NLA | Берн в гостях',
  'nla_bern_away_draw':     '🇨🇭 NLA | Берн в гостях',
  'nhl_draw_tight':         '🏒 НХЛ | Ничья',
  'NHL_DRAW_TIGHT':         '🏒 НХЛ | Ничья',
  'intersection':           '🏒 КХЛ | Андердог',
  'hockey_underdog_defensive': '🏒 КХЛ | Андердог',
  'BTTS_YES_CORE':          '🏴󠁧󠁢󠁥󠁮󠁧󠁿🇩🇪 АПЛ + Бундеслига | Обе забьют',
  'FL1_BTTS_DOUBLE':        '🇫🇷 Лига 1 | Обе забьют',
  'PD_BTTS_DOUBLE':         '🇪🇸 Примера | Обе забьют',
  'RPL_OVER25_BTTS':        '🇷🇺 РПЛ | Обе забьют',
  'CZECH_HOME_FAV':         '🇨🇿 Чехия | Домашний фаворит',
  'nhl_draw_tight_czech':   '🇨🇿 Чехия | Домашний фаворит',
};
const sLabel = name => STRATEGY_LABELS[name] || name;

// ── helpers ──
let charts = {};
const fmt = n => (n===null||n===undefined) ? '—' : Number(n).toLocaleString('ru-RU',{maximumFractionDigits:0});
const pct = n => (n===null||n===undefined) ? '—' : (n>=0?'+':'')+Number(n).toFixed(2)+'%';
const pct1 = n => (n===null||n===undefined) ? '—' : Number(n).toFixed(1)+'%';
const money = n => (n===null||n===undefined) ? '—' : (n>=0?'+':'')+fmt(n)+' ₽';
const badge = r => ({won:'<span class="badge b-green">won</span>',lost:'<span class="badge b-red">lost</span>',pending:'<span class="badge b-yellow">pending</span>'})[r] || '<span class="badge b-blue">'+(r||'—')+'</span>';
const sportBadge = s => s==='football' ? '<span class="badge b-blue">⚽</span>' : s==='hockey' ? '<span class="badge b-purple">🏒</span>' : '<span class="badge b-cyan">'+(s||'?')+'</span>';
const mktLabel = m => ({home:'🏠П1',away:'✈️П2',draw:'🤝X',btts_yes:'⚽⚽ОЗ',pass:'PASS'})[m]||m||'—';
const showToast = t => { const el=document.getElementById('toast'); el.textContent=t; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),2600); };
const mountChart = (id,cfg) => { if(charts[id]) charts[id].destroy(); charts[id]=new Chart(document.getElementById(id),cfg); };

// ── chart defaults ──
Chart.defaults.color = '#6a7a96';
Chart.defaults.borderColor = '#1e2a42';
Chart.defaults.font.family = "'Space Grotesk', sans-serif";

function showTab(name, btn) {
  document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.desktop-nav button, .bottom-nav button').forEach(x=>x.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  // activate both nav buttons
  document.querySelectorAll(`[onclick*="'${name}'"]`).forEach(b=>b.classList.add('active'));
  if(name==='logs') loadLogs();
  if(name==='golden') loadGolden();
  if(name==='stats') loadStats();
  if(name==='shadow') loadShadow();
  if(name==='strategies') loadStrategies();
}

// ── dashboard ──
async function loadDashboard(){
  const r=await fetch('/api/dashboard'); const d=await r.json();
  document.getElementById('bankroll').textContent = fmt(d.bankroll)+' ₽';
  const roi=d.roi_30d||0;
  document.getElementById('roi30').textContent = pct(roi);
  document.getElementById('roi30').className = 'card-value '+(roi>=0?'good':'bad');
  document.getElementById('profit30').textContent = 'profit: '+money(d.profit_30d);
  document.getElementById('pendingCount').textContent = d.pending_count;
  document.getElementById('pendingSum').textContent = fmt(d.pending_sum)+' ₽ в игре';
  document.getElementById('winrate').textContent = pct1(d.winrate_30d);
  document.getElementById('wlText').textContent = 'W:'+d.wins_30d+' L:'+d.losses_30d;
  document.getElementById('servicesState').textContent = d.services_summary;
  document.getElementById('servicesSub').textContent = d.services_sub;
  document.getElementById('pendingTable').innerHTML = d.pending_bets.length
    ? d.pending_bets.map(b=>`<tr><td>${sportBadge(b.sport)} ${b.home} — ${b.away}<br><span class="muted mono">${(b.match_date||'').substring(5,16)}</span></td><td>${mktLabel(b.market)}</td><td>${(b.bookmaker||'fonbet').toUpperCase()}</td><td class="mono">${b.odds||'—'}</td><td class="mono">${fmt(b.stake)} ₽</td><td class="good mono">${pct1((b.ev||0)*100)}</td></tr>`).join('')
    : '<tr><td colspan="6" class="empty">Нет pending ставок</td></tr>';
  document.getElementById('resultsTable').innerHTML = d.recent_results.length
    ? d.recent_results.map(b=>`<tr><td>${badge(b.result)} ${b.home} — ${b.away}</td><td class="mono">${b.score||'—'}</td><td>${mktLabel(b.market)}</td><td class="${(b.profit||0)>=0?'good':'bad'} mono">${money(b.profit)}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">Нет закрытых ставок</td></tr>';
  mountChart('bankrollChart',{type:'line',data:{labels:d.bankroll_curve.labels,datasets:[{label:'Bankroll',data:d.bankroll_curve.values,borderColor:'#5b6bff',backgroundColor:'rgba(91,107,255,0.12)',fill:true,tension:0.3,pointRadius:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{maxTicksLimit:6}},y:{ticks:{callback:v=>fmt(v)+' ₽'}}}}});
  mountChart('dailyChart',{type:'bar',data:{labels:d.daily_roi.labels,datasets:[{label:'ROI %',data:d.daily_roi.values,backgroundColor:d.daily_roi.values.map(v=>v>=0?'rgba(29,222,135,0.7)':'rgba(255,77,106,0.7)'),borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{maxTicksLimit:8}}}}});
}

// ── bets ──
async function loadBets(){
  const r=await fetch('/api/bets'); const d=await r.json();
  document.getElementById('betsTable').innerHTML = d.rows.length
    ? d.rows.map(b=>`<tr><td class="mono muted">${(b.created_at||'').substring(5,16)}</td><td>${sportBadge(b.sport)}</td><td>${b.home} — ${b.away}</td><td>${mktLabel(b.market)}</td><td>${(b.bookmaker||'fonbet').toUpperCase()}</td><td class="mono">${b.odds||'—'}</td><td class="mono">${fmt(b.stake)} ₽</td><td class="${(b.ev||0)>=0?'good':'bad'} mono">${pct1((b.ev||0)*100)}</td><td>${badge(b.result)}</td><td class="${(b.profit||0)>=0?'good':'bad'} mono">${money(b.profit)}</td></tr>`).join('')
    : '<tr><td colspan="10" class="empty">Нет ставок</td></tr>';
}

// ── stats ──
async function loadStats(){
  const r=await fetch('/api/stats'); const d=await r.json();
  document.getElementById('totalBets').textContent = d.total_bets;
  document.getElementById('closedBets').textContent = d.closed_bets;
  document.getElementById('pendingEvAvg').textContent = pct1((d.pending_ev_avg||0)*100);
  document.getElementById('bestSport').textContent = d.best_sport.name||'—';
  document.getElementById('bestSportSub').textContent = d.best_sport.name ? pct(d.best_sport.roi) : 'нет данных';
  document.getElementById('serviceTable').innerHTML = d.services.map(s=>`<tr><td>${s.name}</td><td>${s.active==='active'?'<span class="badge b-green">active</span>':'<span class="badge b-red">'+(s.active||'down')+'</span>'}</td><td class="muted">${s.note||''}</td></tr>`).join('');
  mountChart('sportChart',{type:'bar',data:{labels:d.sport_roi.labels,datasets:[{label:'ROI %',data:d.sport_roi.values,backgroundColor:['#5b6bff','#b28cff','#19d3b4','#ffc857','#ff4d6a'],borderRadius:6}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{ticks:{callback:v=>v+'%'}}}}});
}

// ── golden ──
async function loadGolden(){
  const r=await fetch('/api/golden'); const d=await r.json();
  const wrap=document.getElementById('goldenHeroWrap');
  if(d.active){
    const a=d.active;
    const ev=((a.ev||0)*100).toFixed(1);
    const conf=a.golden_confidence||0;
    const sport=a.sport==='football'?'⚽':a.sport==='hockey'?'🏒':'🎯';
    const mkts={home:'🏠 П1',away:'✈️ П2',draw:'🤝 Ничья',btts_yes:'⚽⚽ Оба забьют'};
    const mkt=mkts[a.market]||a.market;
    wrap.innerHTML=`<div class="golden-hero"><div class="golden-badge">💎 ЖБ Ставка дня</div><div class="golden-match">${sport} ${a.home} — ${a.away}</div><div class="golden-bet">${mkt} @ ${a.odds}</div><div class="golden-meta"><div class="golden-pill">📅 ${(a.match_date||'').substring(5,16)}</div><div class="golden-pill">🏆 ${conf}/10</div><div class="golden-pill good">EV +${ev}%</div><div class="golden-pill">💰 ${fmt(a.stake)} ₽</div>${a.league?`<div class="golden-pill muted">${a.league}</div>`:''}</div>${a.golden_reasoning?`<div class="golden-reasoning">📝 ${a.golden_reasoning}</div>`:''}</div>`;
  } else {
    wrap.innerHTML=`<div class="golden-hero"><div class="no-golden"><div class="no-golden-icon">💎</div><div style="font-size:15px;font-weight:700">Нет активной ЖБ ставки</div><div style="font-size:12px;color:var(--muted);margin-top:6px">ЖБ выбирается вечером на матчи следующего дня</div></div></div>`;
  }
  const s=d.stats;
  document.getElementById('gsTotal').textContent=s.total;
  document.getElementById('gsWinrate').textContent=s.winrate?(s.winrate.toFixed(1)+'%'):'—';
  document.getElementById('gsROI').textContent=s.roi?((s.roi>=0?'+':'')+s.roi.toFixed(1)+'%'):'—';
  document.getElementById('gsWins').textContent=s.wins;
  document.getElementById('gsLosses').textContent=s.losses;
  document.getElementById('gsPending').textContent=s.pending;
  const p=s.profit||0;
  document.getElementById('gsProfit').textContent=(p>=0?'+':'')+fmt(p)+' ₽';
  document.getElementById('goldenHistoryTable').innerHTML=d.history.length
    ? d.history.map(b=>{const pr=b.profit||0;const ev=((b.ev||0)*100).toFixed(1);const mkts={home:'🏠П1',away:'✈️П2',draw:'🤝X',btts_yes:'⚽⚽ОЗ'};return`<tr><td class="mono muted">${(b.match_date||'').substring(5,16)}</td><td>${b.sport==='football'?'⚽':'🏒'} ${b.home} — ${b.away}</td><td>${mkts[b.market]||b.market}</td><td class="mono">${b.odds||'—'}</td><td class="good mono">+${ev}%</td><td class="mono">${b.golden_confidence?b.golden_confidence+'/10':'—'}</td><td>${badge(b.result)}</td><td class="${pr>=0?'good':'bad'} mono">${b.result!=='pending'?money(pr):'⏳'}</td></tr>`;}).join('')
    : '<tr><td colspan="8" class="empty">Нет ЖБ ставок</td></tr>';
}

// ── shadow ──
async function loadShadow(){
  const r=await fetch('/api/shadow'); const d=await r.json();
  document.getElementById('shadowTotal').textContent=d.total;
  document.getElementById('shadowLast').textContent=d.last_created_at||'нет записей';
  document.getElementById('shadowOldValid').textContent=d.old_valid;
  document.getElementById('shadowOldSub').textContent=d.total?pct1(d.old_valid_pct):'—';
  document.getElementById('shadowNewValid').textContent=d.new_valid;
  document.getElementById('shadowNewSub').textContent=d.total?pct1(d.new_valid_pct):'—';
  const diff=(d.new_valid||0)-(d.old_valid||0);
  document.getElementById('shadowDiff').textContent=(diff>0?'+':'')+diff;
  document.getElementById('shadowSummary').innerHTML=`<tr><td>Valid</td><td>${d.old_valid}</td><td>${d.new_valid}</td></tr><tr><td>Invalid</td><td>${d.old_invalid}</td><td>${d.new_invalid}</td></tr><tr><td>Won</td><td>${d.old_won}</td><td>${d.new_won}</td></tr><tr><td>Lost</td><td>${d.old_lost}</td><td>${d.new_lost}</td></tr>`;
  document.getElementById('shadowTable').innerHTML=d.rows.length
    ? d.rows.map(r=>`<tr><td>${sportBadge(r.sport)} ${r.home} — ${r.away}<br><span class="muted mono">${r.created_at||''}</span></td><td><span class="badge b-purple">OLD</span> ${mktLabel(r.old_market)} ${r.old_valid?'✅':'—'}</td><td><span class="badge b-cyan">NEW</span> ${mktLabel(r.new_market)} ${r.new_valid?'✅':'—'}</td><td>${r.result_label||'—'}</td></tr>`).join('')
    : '<tr><td colspan="4" class="empty">Нет shadow записей</td></tr>';
  mountChart('shadowChart',{type:'bar',data:{labels:['OLD valid','OLD invalid','NEW valid','NEW invalid'],datasets:[{label:'Count',data:[d.old_valid,d.old_invalid,d.new_valid,d.new_invalid],backgroundColor:['#b28cff','#4b3e70','#19d3b4','#1a4a44'],borderRadius:6}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}}}});
}

// ── logs ──
async function loadLogs(){
  const r=await fetch('/api/logs'); const d=await r.json();
  document.getElementById('cronLog').textContent=d.cron_log||'cron.log не найден';
  document.getElementById('pipelineLog').textContent=d.pipeline_log||'pipeline log не найден';
  document.getElementById('webLog').textContent=d.web_log||'web log пуст';
  document.getElementById('botLog').textContent=d.bot_log||'bot log пуст';
  ['cronLog','pipelineLog','webLog','botLog'].forEach(id=>{const el=document.getElementById(id);el.scrollTop=el.scrollHeight;});
}

// ── pipeline / settle ──
async function runPipeline(){ showToast('Запускаю пайплайн...'); const r=await fetch('/api/run_pipeline',{method:'POST'}); const d=await r.json(); showToast(d.ok?'Пайплайн запущен':'Ошибка: '+(d.error||'unknown')); setTimeout(loadDashboard,1500); }
async function settleNow(){ showToast('Запускаю settle...'); const r=await fetch('/api/settle_now',{method:'POST'}); const d=await r.json(); showToast(d.ok?'Settle выполнен':'Ошибка: '+(d.error||'unknown')); setTimeout(loadDashboard,1500); }

// ══════════════════════════════
// ── STRATEGIES TAB ──
// ══════════════════════════════
let strategyData = [];
let selectedStrategies = new Set();
let activeSports = new Set(['football','hockey']);
let showBacktest = true;
let showLive = true;

const STRATEGY_COLORS = [
  '#5b6bff','#19d3b4','#ffc857','#b28cff','#ff4d6a',
  '#67e8f9','#4ade80','#fb923c','#f472b6','#a78bfa',
  '#34d399','#f87171'
];

function toggleSport(el){
  const s=el.dataset.sport;
  el.classList.toggle('on');
  if(el.classList.contains('on')) activeSports.add(s); else activeSports.delete(s);
}

function toggleSource(src,el){
  el.classList.toggle('on');
  if(src==='backtest') showBacktest=el.classList.contains('on');
  if(src==='live') showLive=el.classList.contains('on');
}

async function loadStrategies(){
  const dateFrom = document.getElementById('dateFrom').value || '2021-01-01';
  const dateTo = document.getElementById('dateTo').value || new Date().toISOString().split('T')[0];
  const initBank = parseFloat(document.getElementById('initBank').value) || 100000;
  const sports = [...activeSports].join(',');

  const params = new URLSearchParams({date_from:dateFrom, date_to:dateTo, sports, show_backtest:showBacktest?1:0, show_live:showLive?1:0});
  const r = await fetch('/api/strategy_chart?'+params);
  const d = await r.json();
  strategyData = d.strategies || [];

  // Render strategy cards
  const container = document.getElementById('strategyCards');
  if(!strategyData.length){
    container.innerHTML = '<div class="card" style="grid-column:1/-1;text-align:center;padding:30px;color:var(--muted)">Нет данных для выбранных фильтров</div>';
    return;
  }

  container.innerHTML = strategyData.map((s,i)=>{
    const roi = s.roi||0;
    const roiColor = roi>=0?'var(--green)':'var(--red)';
    const isSelected = selectedStrategies.size===0 || selectedStrategies.has(s.name);
    return `<div class="s-card ${isSelected?'selected':''}" onclick="toggleStrategy('${s.name}',this)" data-name="${s.name}">
      <div class="s-check"></div>
      <div style="padding-left:22px">
        <div class="s-card-name">${sLabel(s.name)}</div>
        <div class="s-card-sport ${s.sport}">${s.sport==='football'?'⚽ Футбол':'🏒 Хоккей'}</div>
        <div class="s-metrics">
          <div class="s-metric"><div class="s-metric-val" style="color:${roiColor}">${roi>=0?'+':''}${roi.toFixed(1)}%</div><div class="s-metric-lbl">ROI</div></div>
          <div class="s-metric"><div class="s-metric-val">${s.n||0}</div><div class="s-metric-lbl">Ставок</div></div>
          <div class="s-metric"><div class="s-metric-val">${s.hit_rate?s.hit_rate.toFixed(0)+'%':'—'}</div><div class="s-metric-lbl">Hit%</div></div>
        </div>
        <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
          <span style="font-size:10px;color:var(--muted)">MaxLS: ${s.max_ls||'—'}</span>
          <span style="font-size:10px;color:${roi>=0?'var(--green)':'var(--red)'}">${money(s.profit)}</span>
        </div>
      </div>
    </div>`;
  }).join('');

  renderStrategyChart(initBank);
}

function toggleStrategy(name, el){
  el.classList.toggle('selected');
  if(el.classList.contains('selected')) selectedStrategies.add(name);
  else selectedStrategies.delete(name);
  const initBank = parseFloat(document.getElementById('initBank').value)||100000;
  renderStrategyChart(initBank);
}

function renderStrategyChart(initBank){
  const active = selectedStrategies.size===0
    ? strategyData
    : strategyData.filter(s=>selectedStrategies.has(s.name));

  if(!active.length){
    document.getElementById('chartROI').textContent='—';
    document.getElementById('chartN').textContent='—';
    document.getElementById('chartMaxLS').textContent='—';
    document.getElementById('chartProfit').textContent='—';
    return;
  }

  // Собираем все уникальные даты из всех стратегий → единая временная шкала
  const allDatesSet = new Set();
  active.forEach(s=>(s.bets||[]).forEach(b=>allDatesSet.add(b.date)));
  const allDates = [...allDatesSet].sort();

  // Общая кривая (все стратегии вместе)
  let allBets = [];
  active.forEach(s=>(s.bets||[]).forEach(b=>allBets.push({...b})));
  allBets.sort((a,b)=>a.date.localeCompare(b.date));

  let totalStaked=0, totalProfit=0, totalN=0, maxLS=0, curLS=0;
  allBets.forEach(b=>{
    totalStaked+=b.stake||0; totalProfit+=b.profit||0; totalN++;
    if((b.profit||0)<0){curLS++;maxLS=Math.max(maxLS,curLS);}else curLS=0;
  });

  // Строим datasets выровненные по единой шкале дат
  const datasets = active.map((s,i)=>{
    // Группируем ставки по дате → суммарный profit за день
    const byDate = {};
    (s.bets||[]).forEach(b=>{
      byDate[b.date] = (byDate[b.date]||0) + (b.profit||0);
    });
    // Строим кривую банка по всем датам
    let bank = initBank;
    const pts = allDates.map(d=>{
      if(byDate[d] !== undefined) bank += byDate[d];
      return Math.round(bank);
    });
    return {
      label: sLabel(s.name),
      data: pts,
      borderColor: STRATEGY_COLORS[i%STRATEGY_COLORS.length],
      backgroundColor: active.length===1 ? STRATEGY_COLORS[0].replace(')',',0.1)').replace('rgb','rgba') : 'transparent',
      fill: active.length===1,
      tension: 0.3,
      pointRadius: 0,
      borderWidth: active.length===1 ? 2.5 : 1.5,
    };
  });

  // Добавляем общую кривую если несколько стратегий
  if(active.length > 1){
    const combinedByDate = {};
    allBets.forEach(b=>{ combinedByDate[b.date]=(combinedByDate[b.date]||0)+(b.profit||0); });
    let bank2 = initBank;
    const combinedPts = allDates.map(d=>{
      if(combinedByDate[d]!==undefined) bank2+=combinedByDate[d];
      return Math.round(bank2);
    });
    datasets.unshift({
      label: '▶ Всего',
      data: combinedPts,
      borderColor: '#ffffff',
      backgroundColor: 'transparent',
      tension: 0.3,
      pointRadius: 0,
      borderWidth: 3,
      borderDash: [6,3],
    });
  }

  const chartLabels = allDates.map(d=>d.substring(5));

  mountChart('strategyChart',{
    type:'line',
    data:{labels:chartLabels, datasets},
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:active.length>1, labels:{boxWidth:12,font:{size:11}}}},
      scales:{
        x:{ticks:{maxTicksLimit:10}},
        y:{ticks:{callback:v=>fmt(v)+' ₽'}}
      }
    }
  });

  const roi = totalStaked ? (totalProfit/totalStaked*100) : 0;
  document.getElementById('chartROI').textContent = (roi>=0?'+':'')+roi.toFixed(2)+'%';
  document.getElementById('chartROI').className = 'chart-stat-val '+(roi>=0?'good':'bad');
  document.getElementById('chartN').textContent = totalN;
  document.getElementById('chartMaxLS').textContent = maxLS;
  document.getElementById('chartProfit').textContent = money(totalProfit);

  // Strategy table
  document.getElementById('strategyTable').innerHTML = active.map(s=>{
    const r=s.roi||0;
    return `<tr>
      <td><b>${sLabel(s.name)}</b></td>
      <td>${sportBadge(s.sport)}</td>
      <td class="mono">${s.n||0}</td>
      <td class="mono">${s.hit_rate?s.hit_rate.toFixed(1)+'%':'—'}</td>
      <td class="mono ${r>=0?'good':'bad'}">${r>=0?'+':''}${r.toFixed(2)}%</td>
      <td class="mono">${s.max_ls||'—'}</td>
      <td class="mono ${(s.profit||0)>=0?'good':'bad'}">${money(s.profit)}</td>
    </tr>`;
  }).join('');
}

async function loadAll(){
  await loadDashboard();
  await loadBets();
}
loadAll();
setInterval(loadDashboard, 60000);

// Set default dateTo to today
document.getElementById('dateTo').value = new Date().toISOString().split('T')[0];
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/api/dashboard")
def api_dashboard():
    conn = get_conn()
    s30 = stats_30d(conn)
    pending_bets = []
    recent_results = []
    bankroll_labels = []
    bankroll_values = []
    daily_labels = []
    daily_roi_values = []

    if table_exists(conn, "bets") and table_exists(conn, "matches"):
        pending_bets = [dict(r) for r in conn.execute("""
            SELECT m.sport, m.home_team AS home, m.away_team AS away, m.match_date, b.market, b.odds, b.stake, b.ev, COALESCE(b.recommended_bookmaker, 'fonbet') AS bookmaker
            FROM bets b JOIN matches m ON m.id = b.match_id
            WHERE b.result='pending' ORDER BY m.match_date ASC LIMIT 20
        """).fetchall()]

        for r in conn.execute("""
            SELECT m.home_team AS home, m.away_team AS away, b.result, b.market, b.profit, m.home_score, m.away_score
            FROM bets b JOIN matches m ON m.id = b.match_id
            WHERE b.result IN ('won','lost') AND COALESCE(b.excluded_from_stats,0)=0 ORDER BY b.created_at DESC LIMIT 12
        """).fetchall():
            d = dict(r)
            d["score"] = f"{d['home_score']}:{d['away_score']}" if d["home_score"] is not None and d["away_score"] is not None else None
            recent_results.append(d)

        curve = conn.execute("SELECT created_at, profit FROM bets WHERE result IN ('won','lost') AND COALESCE(excluded_from_stats,0)=0 ORDER BY created_at ASC").fetchall()
        bank = START_BANK
        for row in curve:
            bank += row["profit"] or 0
            bankroll_labels.append(str(row["created_at"])[:16])
            bankroll_values.append(round(bank, 2))

        daily = conn.execute("""
            SELECT DATE(created_at) AS d,
                   COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) AS profit,
                   COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) AS stake
            FROM bets WHERE COALESCE(excluded_from_stats,0)=0 AND created_at >= DATETIME('now','-30 day')
            GROUP BY DATE(created_at) ORDER BY d ASC
        """).fetchall()
        for row in daily:
            daily_labels.append(row["d"])
            daily_roi_values.append(round((row["profit"]/row["stake"]*100),2) if row["stake"] else 0)

    web_s = service_status("betagent-web")
    bot_s = service_status("betagent-bot")
    cron_exists = (BASE_DIR / "cron.log").exists()
    services_summary = "OK" if web_s["active"]=="active" and bot_s["active"]=="active" else "CHECK"
    services_sub = f"web={web_s['active']} | bot={bot_s['active']} | cron={'yes' if cron_exists else 'no'}"

    result = {
        "bankroll": current_bankroll(conn),
        "roi_30d": s30["roi"], "profit_30d": s30["profit"],
        "pending_count": s30["pending"], "pending_sum": s30["pending_sum"],
        "winrate_30d": s30["winrate"], "wins_30d": s30["wins"], "losses_30d": s30["losses"],
        "services_summary": services_summary, "services_sub": services_sub,
        "pending_bets": pending_bets, "recent_results": recent_results,
        "bankroll_curve": {"labels": bankroll_labels[-80:], "values": bankroll_values[-80:]},
        "daily_roi": {"labels": daily_labels, "values": daily_roi_values}
    }
    conn.close()
    return jsonify(result)

@app.route("/api/bets")
def api_bets():
    conn = get_conn()
    rows = []
    if table_exists(conn, "bets") and table_exists(conn, "matches"):
        rows = [dict(r) for r in conn.execute("""
            SELECT b.created_at, m.sport, m.home_team AS home, m.away_team AS away,
                   b.market, COALESCE(b.recommended_bookmaker, 'fonbet') AS bookmaker, b.odds, b.stake, b.ev, b.result, b.profit
            FROM bets b JOIN matches m ON m.id=b.match_id
            WHERE COALESCE(b.excluded_from_stats,0)=0
            ORDER BY b.created_at DESC LIMIT 150
        """).fetchall()]
    conn.close()
    return jsonify({"rows": rows})

@app.route("/api/stats")
def api_stats():
    conn = get_conn()
    total_bets = 0; closed_bets = 0; pending_ev_avg = 0
    best_sport = {"name": None, "roi": None}
    sport_labels = []; sport_values = []

    if table_exists(conn, "bets"):
        total_bets = conn.execute("SELECT COUNT(*) AS c FROM bets WHERE COALESCE(excluded_from_stats,0)=0").fetchone()["c"]
        closed_bets = conn.execute("SELECT COUNT(*) AS c FROM bets WHERE result IN ('won','lost') AND COALESCE(excluded_from_stats,0)=0").fetchone()["c"]
        pending_ev_avg = conn.execute("SELECT COALESCE(AVG(ev),0) AS a FROM bets WHERE result='pending' AND COALESCE(excluded_from_stats,0)=0").fetchone()["a"]

    services = [
        {"name":"betagent-web","active":service_status("betagent-web")["active"],"note":"Flask panel"},
        {"name":"betagent-bot","active":service_status("betagent-bot")["active"],"note":"Telegram bot"},
        {"name":"run_pipeline","active":"active" if process_running("python3 run_pipeline.py") else "inactive","note":"scheduler"},
        {"name":"cron.log","active":"active" if (BASE_DIR/"cron.log").exists() else "inactive","note":str(BASE_DIR/"cron.log")},
    ]

    if table_exists(conn, "bets") and table_exists(conn, "matches"):
        sport_rows = conn.execute("""
            SELECT m.sport,
                   COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.stake ELSE 0 END),0) AS staked,
                   COALESCE(SUM(CASE WHEN b.result IN ('won','lost') THEN b.profit ELSE 0 END),0) AS profit
            FROM bets b JOIN matches m ON m.id=b.match_id WHERE COALESCE(b.excluded_from_stats,0)=0 GROUP BY m.sport ORDER BY m.sport
        """).fetchall()
        best_roi = None
        for r in sport_rows:
            roi = round((r["profit"]/r["staked"]*100),2) if r["staked"] else 0
            sport_labels.append(r["sport"]); sport_values.append(roi)
            if best_roi is None or roi > best_roi:
                best_roi = roi; best_sport = {"name": r["sport"], "roi": best_roi}

    conn.close()
    return jsonify({"total_bets":total_bets,"closed_bets":closed_bets,"pending_ev_avg":pending_ev_avg,
                    "best_sport":best_sport,"sport_roi":{"labels":sport_labels,"values":sport_values},"services":services})

@app.route("/api/strategy_chart")
def api_strategy_chart():
    """Данные для вкладки Стратегии — бэктест + боевые ставки."""
    conn = get_conn()
    date_from = request.args.get("date_from", "2021-01-01")
    date_to   = request.args.get("date_to", datetime.now().strftime("%Y-%m-%d"))
    sports    = request.args.get("sports", "football,hockey").split(",")
    show_backtest = request.args.get("show_backtest", "1") == "1"
    show_live     = request.args.get("show_live", "1") == "1"

    strategies = {}

    # ── Боевые ставки из bets ──
    if show_live and table_exists(conn, "bets") and table_exists(conn, "matches"):
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(bets)").fetchall()]
        rule_col = "rule" if "rule" in cols else ("strategy_name" if "strategy_name" in cols else None)
        if rule_col:
            rows = conn.execute(f"""
                SELECT b.created_at AS date, m.sport, b.{rule_col} AS strategy,
                       b.stake, b.profit, b.result, b.odds
                FROM bets b JOIN matches m ON m.id=b.match_id
                WHERE b.result IN ('won','lost')
                  AND COALESCE(b.excluded_from_stats,0)=0
                  AND DATE(b.created_at) BETWEEN ? AND ?
                  AND m.sport IN ({','.join('?'*len(sports))})
                ORDER BY b.created_at ASC
            """, [date_from, date_to] + sports).fetchall()

            for row in rows:
                name = row["strategy"] or "unknown"
                if name not in strategies:
                    strategies[name] = {"name":name,"sport":row["sport"],"bets":[],"source":"live"}
                strategies[name]["bets"].append({
                    "date": row["date"][:10], "stake": row["stake"] or 0,
                    "profit": row["profit"] or 0, "result": row["result"],
                    "odds": row["odds"], "source": "live"
                })

    # ── Бэктестовые данные из backtest_equity ──
    if show_backtest and table_exists(conn, "backtest_equity"):
        sport_filter = f"AND sport IN ({','.join('?'*len(sports))})" if sports else ""
        params = [date_from, date_to] + sports

        rows = conn.execute(f"""
            SELECT match_date AS date, sport, strategy, stake, profit, result
            FROM backtest_equity
            WHERE match_date BETWEEN ? AND ?
              AND result IN ('won','lost')
              {sport_filter}
            ORDER BY match_date ASC
        """, params).fetchall()

        for row in rows:
            name = row["strategy"] or "unknown"
            if name in strategies:
                strategies[name]["bets"].append({
                    "date": str(row["date"])[:10], "stake": row["stake"] or 1000,
                    "profit": row["profit"] or 0, "result": row["result"], "source": "backtest"
                })
            else:
                strategies[name] = {
                    "name": name, "sport": row["sport"] or "unknown",
                    "bets": [{
                        "date": str(row["date"])[:10], "stake": row["stake"] or 1000,
                        "profit": row["profit"] or 0, "result": row["result"], "source": "backtest"
                    }],
                    "source": "backtest"
                }

    # ── Compute stats per strategy ──
    result = []
    for name, s in strategies.items():
        bets = s["bets"]
        if not bets: continue
        n = len(bets)
        wins = sum(1 for b in bets if b["result"]=="won")
        losses = sum(1 for b in bets if b["result"]=="lost")
        staked = sum(b["stake"] for b in bets)
        profit = sum(b["profit"] for b in bets)
        roi = (profit / staked * 100) if staked else 0
        hit_rate = (wins / n * 100) if n else 0
        # max loss streak
        max_ls = cur_ls = 0
        for b in sorted(bets, key=lambda x: x["date"]):
            if b["result"]=="lost": cur_ls+=1; max_ls=max(max_ls,cur_ls)
            else: cur_ls=0
        result.append({
            "name": name, "sport": s["sport"], "source": s["source"],
            "n": n, "wins": wins, "losses": losses,
            "staked": round(staked,2), "profit": round(profit,2),
            "roi": round(roi,2), "hit_rate": round(hit_rate,1),
            "max_ls": max_ls, "bets": sorted(bets, key=lambda x: x["date"])
        })

    # Фильтруем мусорные стратегии
    EXCLUDE = {"unknown", "fp_or_fb", "none", ""}
    result = [s for s in result if s["name"].lower() not in EXCLUDE and s["n"] >= 5]
    result.sort(key=lambda x: x["roi"], reverse=True)
    conn.close()
    return jsonify({"strategies": result})

@app.route("/api/golden")
def api_golden():
    conn = get_conn()
    active = None
    history = []
    stats = {"total":0,"wins":0,"losses":0,"pending":0,"staked":0,"profit":0,"winrate":0,"roi":0}

    if table_exists(conn, "bets") and table_exists(conn, "matches"):
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(bets)").fetchall()]
        has_golden = "is_golden" in cols
        has_reasoning = "golden_reasoning" in cols
        has_confidence = "golden_confidence" in cols

        if has_golden:
            select_cols = "b.id, b.market, b.odds, b.stake, b.ev, b.result, m.sport, m.home_team AS home, m.away_team AS away, m.match_date, m.league"
            if has_reasoning: select_cols += ", b.golden_reasoning"
            if has_confidence: select_cols += ", b.golden_confidence"

            row = conn.execute(f"SELECT {select_cols} FROM bets b JOIN matches m ON m.id=b.match_id WHERE b.is_golden=1 AND b.result='pending' ORDER BY m.match_date ASC LIMIT 1").fetchone()
            if row: active = dict(row)

            history = [dict(r) for r in conn.execute(f"SELECT {select_cols} FROM bets b JOIN matches m ON m.id=b.match_id WHERE b.is_golden=1 AND b.result IN ('won','lost','pending') ORDER BY b.created_at DESC LIMIT 50").fetchall()]

            s = conn.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN result='won' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN result='lost' THEN 1 ELSE 0 END) as losses,
                       SUM(CASE WHEN result='pending' THEN 1 ELSE 0 END) as pending,
                       COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN stake ELSE 0 END),0) as staked,
                       COALESCE(SUM(CASE WHEN result IN ('won','lost') THEN profit ELSE 0 END),0) as profit
                FROM bets WHERE is_golden=1 AND COALESCE(excluded_from_stats,0)=0
            """).fetchone()
            if s:
                wins = s["wins"] or 0; losses = s["losses"] or 0
                staked = s["staked"] or 0; profit = s["profit"] or 0
                closed = wins + losses
                stats = {
                    "total": s["total"] or 0, "wins": wins, "losses": losses,
                    "pending": s["pending"] or 0, "staked": round(staked,2),
                    "profit": round(profit,2),
                    "winrate": round(wins/closed*100,1) if closed else 0,
                    "roi": round(profit/staked*100,2) if staked else 0,
                }

    conn.close()
    return jsonify({"active": active, "history": history, "stats": stats})

@app.route("/api/shadow")
def api_shadow():
    conn = get_conn()
    if not table_exists(conn, "shadow_recommendations"):
        conn.close()
        return jsonify({"total":0,"last_created_at":None,"old_valid":0,"new_valid":0,"old_invalid":0,"new_invalid":0,"old_won":0,"new_won":0,"old_lost":0,"new_lost":0,"old_valid_pct":0,"new_valid_pct":0,"rows":[]})

    sport_col = pick_col(conn, "shadow_recommendations", ["sport"])
    home_col  = pick_col(conn, "shadow_recommendations", ["home_team","home"])
    away_col  = pick_col(conn, "shadow_recommendations", ["away_team","away"])
    created_col = pick_col(conn, "shadow_recommendations", ["created_at","match_date","created"])
    old_market_col = pick_col(conn, "shadow_recommendations", ["old_market","old_pick"])
    new_market_col = pick_col(conn, "shadow_recommendations", ["new_market","new_pick"])
    old_valid_col  = pick_col(conn, "shadow_recommendations", ["old_valid","valid_old","old_is_valid"])
    new_valid_col  = pick_col(conn, "shadow_recommendations", ["new_valid","valid_new","new_is_valid"])
    old_result_col = pick_col(conn, "shadow_recommendations", ["old_result"])
    new_result_col = pick_col(conn, "shadow_recommendations", ["new_result"])
    result_col     = pick_col(conn, "shadow_recommendations", ["result"])

    total = conn.execute("SELECT COUNT(*) AS c FROM shadow_recommendations").fetchone()["c"]

    def truthy_count(col):
        if not col: return 0
        return conn.execute(f"SELECT COUNT(*) AS c FROM shadow_recommendations WHERE {col} IN (1,'1','true','TRUE','True','yes','YES')").fetchone()["c"]
    def eq_count(col, val):
        if not col: return 0
        return conn.execute(f"SELECT COUNT(*) AS c FROM shadow_recommendations WHERE {col}=?", (val,)).fetchone()["c"]

    old_valid = truthy_count(old_valid_col); new_valid = truthy_count(new_valid_col)
    old_won = eq_count(old_result_col,"won"); new_won = eq_count(new_result_col,"won")
    old_lost = eq_count(old_result_col,"lost"); new_lost = eq_count(new_result_col,"lost")

    cols = [c for c in [sport_col,home_col,away_col,created_col,old_market_col,new_market_col,old_valid_col,new_valid_col,old_result_col,new_result_col,result_col] if c]
    rows = []
    if cols:
        for r in conn.execute("SELECT "+",".join(cols)+" FROM shadow_recommendations ORDER BY ROWID DESC LIMIT 50").fetchall():
            d = dict(r)
            rows.append({"sport":d.get(sport_col),"home":d.get(home_col),"away":d.get(away_col),"created_at":d.get(created_col),"old_market":d.get(old_market_col),"new_market":d.get(new_market_col),"old_valid":str(d.get(old_valid_col)).lower() in ("1","true","yes") if old_valid_col else False,"new_valid":str(d.get(new_valid_col)).lower() in ("1","true","yes") if new_valid_col else False,"result_label":d.get(result_col) or d.get(new_result_col) or d.get(old_result_col) or "—"})

    last_created_at = rows[0]["created_at"] if rows else None
    conn.close()
    return jsonify({"total":total,"last_created_at":last_created_at,"old_valid":old_valid,"new_valid":new_valid,"old_invalid":max(total-old_valid,0),"new_invalid":max(total-new_valid,0),"old_won":old_won,"new_won":new_won,"old_lost":old_lost,"new_lost":new_lost,"old_valid_pct":round(old_valid/total*100,1) if total else 0,"new_valid_pct":round(new_valid/total*100,1) if total else 0,"rows":rows})

@app.route("/api/logs")
def api_logs():
    logs_dir = BASE_DIR / "logs"
    pipeline_latest = latest_matching_file(logs_dir, "pipeline_*.log")
    cron_log = BASE_DIR / "cron.log"
    pipeline_log = pipeline_latest if pipeline_latest else (BASE_DIR / "pipeline.log")
    try:
        web_log = subprocess.run(["journalctl","-u","betagent-web","-n","80","--no-pager"],capture_output=True,text=True,timeout=12).stdout
    except Exception as e:
        web_log = f"journalctl error: {e}"
    try:
        bot_log = subprocess.run(["journalctl","-u","betagent-bot","-n","80","--no-pager"],capture_output=True,text=True,timeout=12).stdout
    except Exception as e:
        bot_log = f"journalctl error: {e}"
    return jsonify({"cron_log":safe_read(cron_log,25000),"pipeline_log":safe_read(pipeline_log,25000),"web_log":web_log[-25000:],"bot_log":bot_log[-25000:]})

@app.route("/api/run_pipeline", methods=["POST"])
def api_run_pipeline():
    try:
        run_server = BASE_DIR / "run_server.sh"
        if not run_server.exists():
            return jsonify({"ok":False,"error":"run_server.sh not found"})
        subprocess.Popen(["/bin/bash",str(run_server)],cwd=str(BASE_DIR),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=os.environ.copy())
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

@app.route("/api/settle_now", methods=["POST"])
def api_settle_now():
    try:
        env = os.environ.copy()
        for script, args in [
            (BASE_DIR/"repair_pending_bets_v2.py", []),
            (BASE_DIR/"tennis_results_updater.py", ["--days", "3"]),
            (BASE_DIR/"updater_results.py", ["--settle"]),
            (BASE_DIR/"settler.py", []),
        ]:
            if script.exists():
                subprocess.run(["python3",str(script)]+args,cwd=str(BASE_DIR),env=env,timeout=240)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
