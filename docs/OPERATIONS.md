# Эксплуатация

## Команды

```bash
python scripts/betagent.py doctor
python scripts/betagent.py api
python scripts/betagent.py panel
python scripts/betagent.py bot
python scripts/betagent.py client-bot
python scripts/betagent.py pipeline -- --run morning --dry-run
```

## Расписание pipeline

Встроенное расписание `run_pipeline.py`:

| Время сервера | Режим |
|---|---|
| 02:00 | tennis settle |
| 08:00 | morning |
| 14:00 | afternoon |
| 20:00 | tennis settle |
| 21:00 | evening |
| 23:30 | night |

Проверьте часовой пояс сервера командой `timedatectl`. При необходимости запускайте конкретные режимы через cron/systemd вместо фонового scheduler.

Пример cron:

```cron
0 8 * * * cd /opt/BetAgent && .venv/bin/python run_pipeline.py --run morning >> logs/cron.log 2>&1
0 14 * * * cd /opt/BetAgent && .venv/bin/python run_pipeline.py --run afternoon >> logs/cron.log 2>&1
0 21 * * * cd /opt/BetAgent && .venv/bin/python run_pipeline.py --run evening >> logs/cron.log 2>&1
30 23 * * * cd /opt/BetAgent && .venv/bin/python run_pipeline.py --run night >> logs/cron.log 2>&1
```

Замените `/opt/BetAgent` на реальный путь.

## Логи и состояние

- `pipeline.log` — основной pipeline;
- `logs/` — сервисные логи;
- `run_summaries/` — JSON/TXT результат каждого запуска;
- `betagent.db` — рабочая SQLite-база.

## Резервное копирование

Для согласованной копии SQLite:

```bash
sqlite3 betagent.db ".backup 'backups/betagent-$(date +%F).db'"
```

PostgreSQL:

```bash
pg_dump "$DATABASE_URL" | gzip > "backups/postgres-$(date +%F).sql.gz"
```

Не помещайте backup-файлы в Git.

## Обновление и откат

Перед обновлением сохраните commit SHA и базы. После `git pull --ff-only` повторите установщик и `doctor`, затем сделайте dry-run. Для отката переключитесь на предыдущий проверенный тег/commit и восстановите только совместимую базу.
