-- Пользователи
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE,
    username TEXT,
    first_name TEXT,
    email TEXT,
    created_at TIMESTAMP DEFAULT now(),
    status TEXT DEFAULT 'active'  -- active | blocked
);

-- Подписки
CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'basic',  -- basic | pro | premium
    status TEXT NOT NULL DEFAULT 'active',  -- active | expired | cancelled
    start_date TIMESTAMP DEFAULT now(),
    end_date TIMESTAMP,
    trial BOOLEAN DEFAULT FALSE,
    auto_renew BOOLEAN DEFAULT TRUE,
    payment_provider TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- Платежи
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    amount NUMERIC(10,2),
    currency TEXT DEFAULT 'RUB',
    provider TEXT,  -- yookassa | telegram
    provider_payment_id TEXT,
    status TEXT DEFAULT 'pending',  -- pending | succeeded | cancelled
    plan TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- Публичная таблица сигналов (без стратегической логики)
CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
    sport TEXT,
    league TEXT,
    home_team TEXT,
    away_team TEXT,
    match_date TIMESTAMP,
    market TEXT,
    odds NUMERIC(5,2),
    bookmaker TEXT,
    confidence TEXT DEFAULT 'medium',  -- low | medium | high
    ev_range TEXT,
    visible_from TIMESTAMP DEFAULT now(),
    result TEXT DEFAULT 'pending',  -- pending | won | lost
    profit NUMERIC(10,2),
    updated_at TIMESTAMP DEFAULT now(),
    bet_id INT,
    signal_uid TEXT,  -- hash(sport|home_team|away_team|market|match_date|odds) for dedup
    created_at TIMESTAMP DEFAULT now()
);

-- Уникальный ключ для UPSERT (защита от дублей при повторных запусках notifier)
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_signal_uid ON signals(signal_uid)
    WHERE signal_uid IS NOT NULL;

-- Трекинг выдачи сигналов (антислив)
CREATE TABLE IF NOT EXISTS user_signal_views (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    signal_id INT REFERENCES signals(id),
    shown_at TIMESTAMP DEFAULT now(),
    ip_address TEXT,
    watermark_stake INT,
    UNIQUE(user_id, signal_id)
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    action TEXT,
    ip TEXT,
    detail TEXT,
    created_at TIMESTAMP DEFAULT now()
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at);
CREATE INDEX IF NOT EXISTS idx_signals_result ON signals(result);
CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
