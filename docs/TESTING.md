# Тестирование

## Локальная проверка

```bash
bash scripts/install.sh --dev
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q .
.venv/bin/python scripts/check_public.py
.venv/bin/pip-audit -r requirements.txt
```

Smoke-набор проверяет:

- компиляцию Python-файлов;
- CLI оркестратора;
- EV/Kelly validation gate;
- сохранение run summary;
- `/health` FastAPI;
- авторизацию и рендер Flask-панели.

## Что CI намеренно не проверяет

- реальные букмекерские сайты и изменение их HTML/API;
- действительность пользовательских API-ключей;
- Telegram, YooKassa, SMTP и PostgreSQL пользователя;
- прибыльность стратегий;
- production scheduler и reverse proxy.

Эти проверки зависят от локальных секретов, внешних аккаунтов и актуальных данных. Выполняйте их отдельно в staging-окружении.
