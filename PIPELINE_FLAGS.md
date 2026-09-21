# PIPELINE_FLAGS.md

Новые флаги в `.env`:

```bash
ENABLE_SETTLE=1
ENABLE_NOTIFY=1
ENABLE_CLV=1
ENABLE_SHADOW_FOOTBALL=1
ENABLE_SHADOW_HOCKEY=0
```

Что дают:

- `ENABLE_SETTLE=1` — автоматически запускать закрытие ставок
- `ENABLE_NOTIFY=1` — отправлять telegram-уведомления
- `ENABLE_CLV=1` — считать CLV после snapshot
- `ENABLE_SHADOW_FOOTBALL=1` — включить football shadow
- `ENABLE_SHADOW_HOCKEY=0` — держать hockey shadow выключенным

Что изменено в `run_pipeline.py`:

- settle теперь запускается не только утром/вечером, но и днём/ночью
- CLV report печатается после пересчёта CLV
- football/hockey shadow и notify/settle управляются через `.env`
