# Установка BetAgent

## 1. Требования

- Python 3.10 или новее (рекомендуется 3.11/3.12);
- Git;
- 2 ГБ свободной памяти, 4 ГБ рекомендуется для ML-задач;
- 2–5 ГБ свободного диска;
- PostgreSQL 14+ — только для кабинета, подписок и биллинга;
- Chromium — только для браузерных парсеров Playwright.

SQLite входит в Python и не требует отдельной установки.

## 2. Автоматическая установка

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
git clone https://github.com/Samopal88/BetAgent.git
cd BetAgent
bash scripts/install.sh
python scripts/betagent.py doctor
```

Чтобы установить Chromium для browser-based парсеров:

```bash
bash scripts/install.sh --playwright
```

### Windows 10/11

Установите Git и Python 3.10+ с включённой опцией `Add Python to PATH`, затем откройте PowerShell:

```powershell
git clone https://github.com/Samopal88/BetAgent.git
cd BetAgent
powershell -ExecutionPolicy Bypass -File scripts/install.ps1
python scripts/betagent.py doctor
```

### macOS

```bash
brew install git python@3.12
git clone https://github.com/Samopal88/BetAgent.git
cd BetAgent
bash scripts/install.sh
python scripts/betagent.py doctor
```

## 3. Настройка `.env`

Установщик создаёт `.env` автоматически. Откройте его и заполните только используемые интеграции. Полный справочник находится в [CONFIGURATION.md](CONFIGURATION.md).

Обязательно сохраните сгенерированный `PANEL_PASS`. Не публикуйте `.env` и не пересылайте его вместе с логами.

## 4. PostgreSQL для SaaS-слоя

Этот шаг не нужен для исследовательского pipeline и админ-панели. Он требуется для пользователей, подписок, рефералов и платежей.

```bash
sudo apt install -y postgresql
sudo -u postgres createuser --pwprompt betagent
sudo -u postgres createdb --owner=betagent betagent
psql "postgresql://betagent:PASSWORD@127.0.0.1:5432/betagent" -f db/init.sql
```

Затем укажите строку подключения в `DATABASE_URL`.

## 5. Проверка компонентов

```bash
python scripts/betagent.py doctor
python scripts/betagent.py api
```

В другом терминале:

```bash
curl http://127.0.0.1:8001/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

Панель:

```bash
python scripts/betagent.py panel
```

Откройте адрес, показанный Flask, и войдите с `PANEL_USER`/`PANEL_PASS`.

## 6. Первый pipeline

Сначала используйте dry-run:

```bash
python scripts/betagent.py pipeline -- --dry-run --now
```

Проверяйте `pipeline.log`, каталог `run_summaries/` и отсутствие ошибок источников. Только после этого запускайте обычный режим:

```bash
python scripts/betagent.py pipeline -- --now
```

## 7. Обновление

```bash
git pull --ff-only
bash scripts/install.sh
python scripts/betagent.py doctor
```

Перед обновлением сохраните `.env` и рабочие базы данных. Они не отслеживаются Git.
