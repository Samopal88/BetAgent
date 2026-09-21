# APPLY_PATCHES.md

Ниже 2 простых шага.

## 1) Добавь CLV в пайплайн

Положи файл `run_pipeline_clv_patch.diff` рядом с `run_pipeline.py`, потом выполни:

```bash
cd /root/betagent
git apply run_pipeline_clv_patch.diff
```

Если проект не под git, можно так:

```bash
cd /root/betagent
patch -p0 < run_pipeline_clv_patch.diff
```

Что это даст:
- добавит `task_clv()`
- будет считать CLV после archive snapshot
- добавит команды:
  - `python3 run_pipeline.py --clv`
  - `python3 run_pipeline.py --clv --clv-days 120 --clv-rebuild`

---

## 2) Убери дублирующееся notify bets из run_server.sh

Положи файл `run_server_notify_fix.diff` рядом с `run_server.sh`, потом выполни:

```bash
cd /root/betagent
git apply run_server_notify_fix.diff
```

или:

```bash
cd /root/betagent
patch -p0 < run_server_notify_fix.diff
```

Это уберёт лишнее повторное уведомление `tg_bot.py --notify bets`, потому что `run_pipeline.py` уже сам шлёт уведомления в morning/evening.

---

## 3) Проверь

```bash
cd /root/betagent

python3 clv_tracker.py --days 30
python3 run_pipeline.py --clv --clv-days 30
python3 run_pipeline.py --run afternoon
```

---

## 4) Что должно быть в .env

Добавь строку:

```bash
ENABLE_CLV=1
```

Если захочешь временно отключить CLV:

```bash
ENABLE_CLV=0
```

---

## 5) Самая короткая инструкция

Если совсем коротко, делай так:

```bash
cd /root/betagent
cp run_pipeline.py run_pipeline.py.bak
cp run_server.sh run_server.sh.bak
git apply run_pipeline_clv_patch.diff || patch -p0 < run_pipeline_clv_patch.diff
git apply run_server_notify_fix.diff || patch -p0 < run_server_notify_fix.diff
python3 clv_tracker.py --days 30
python3 run_pipeline.py --clv --clv-days 30
```
