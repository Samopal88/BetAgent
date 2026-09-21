# BetAgent

[![CI](https://github.com/Samopal88/BetAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/Samopal88/BetAgent/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB.svg)](https://www.python.org/)

BetAgent — платформа алгоритмической аналитики спортивных событий. Она собирает линии и результаты, обогащает матчи статистикой, применяет правила и ML-модели, формирует аналитические сигналы, отслеживает результаты и отправляет уведомления в Telegram.

> BetAgent не является букмекерской компанией и не гарантирует прибыль. Ставки связаны с риском потери средств. Проект предназначен только для совершеннолетних пользователей и исследовательского применения.

## Возможности

- футбол, хоккей и теннис;
- сбор линий и результатов из нескольких источников;
- rule-based и ML-стратегии;
- расчёт EV, Kelly и ограничений экспозиции;
- backtesting, CLV и shadow-сравнение стратегий;
- SQLite для аналитического ядра;
- PostgreSQL для пользователей, подписок и биллинга;
- FastAPI, административная веб-панель и Telegram-боты;
- плановые запуски, журналирование и сводки выполнения.

## Быстрый старт

### Linux/macOS

```bash
git clone https://github.com/Samopal88/BetAgent.git
cd BetAgent
bash scripts/install.sh
```

Для парсеров, использующих браузер:

```bash
bash scripts/install.sh --playwright
```

### Windows PowerShell

```powershell
git clone https://github.com/Samopal88/BetAgent.git
cd BetAgent
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
```

Установщик создаёт `.venv`, устанавливает зависимости, копирует `.env.example` в `.env`, создаёт рабочие каталоги и генерирует локальные `JWT_SECRET` и пароль панели.

После установки:

```bash
python scripts/betagent.py doctor
```

Запуск отдельных компонентов:

```bash
python scripts/betagent.py api
python scripts/betagent.py panel
python scripts/betagent.py bot
python scripts/betagent.py client-bot
python scripts/betagent.py pipeline -- --dry-run --now
```

На Linux/macOS вместо системного Python можно использовать `.venv/bin/python`, на Windows — `.venv\Scripts\python.exe`.

## Что необходимо настроить

Минимальная установка позволяет запустить API, панель и локальные проверки. Для полного pipeline нужны ключи выбранных поставщиков данных и Telegram.

| Функция | Переменные |
|---|---|
| Админ-панель | `PANEL_USER`, `PANEL_PASS` |
| LLM-анализ | `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL` |
| Админ Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Клиентский бот | `CLIENT_BOT_TOKEN`, `API_BASE_URL` |
| Публичный канал | `CHANNEL_BOT_TOKEN`, `CHANNEL_ID` |
| Личный кабинет | `DATABASE_URL`, `JWT_SECRET` |
| Платежи | `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY` |
| Дополнительные данные | `FOOTBALL_DATA_API_KEY`, `ALLSPORTS_API_KEY`, `ODDS_API_KEY` |

Все секреты хранятся только в локальном `.env`, который исключён из Git.

## Архитектура

```text
источники данных
      ↓
парсеры → SQLite → обогащение → правила / ML → validator
      ↓                                      ↓
результаты → settlement                сигналы / snapshots
                                              ↓
                              Telegram / FastAPI / веб-панель
                                              ↓
                                  PostgreSQL SaaS-слоя
```

Главный оркестратор — `run_pipeline.py`. Канонический валидатор — `validator.py`. Административная панель находится в `web_panel.py`, HTTP API — в `api/`, клиентские уведомления — в `bot/`.

## Документация

- [Полная установка](docs/INSTALLATION.md)
- [Настройка переменных](docs/CONFIGURATION.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Эксплуатация и расписание](docs/OPERATIONS.md)
- [Тестирование](docs/TESTING.md)
- [Безопасность](SECURITY.md)
- [English overview](docs/README.en.md)

## Проверка проекта

```bash
bash scripts/install.sh --dev
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q .
.venv/bin/python scripts/check_public.py
.venv/bin/pip-audit -r requirements.txt
```

CI повторяет эти проверки на Python 3.11 и 3.12. Тесты не обращаются к букмекерским сайтам, платёжным системам или реальным Telegram-аккаунтам.

## Состояние проекта

BetAgent — работающий прототип с большим исследовательским слоем. Основные модули запускаются и покрыты smoke-тестами, однако production-развёртывание требует собственных ключей, PostgreSQL и проверки источников данных. Перед реальным использованием обязательно проведите dry-run и сверку результатов на своей базе.

## Лицензирование

Публичное размещение исходного кода само по себе не предоставляет права на коммерческое копирование или перепродажу. Отдельная открытая лицензия для проекта пока не объявлена.
