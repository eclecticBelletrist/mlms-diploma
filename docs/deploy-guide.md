# Deploy Guide — MLMS на Railway + MCPJam

## Что понадобится
- Аккаунт Railway (railway.app) — вход через GitHub
- Репо на GitHub (запушить текущую ветку)
- OpenRouter API key (для embeddings)

---

## Шаг 1 — Push на GitHub

```powershell
git remote add origin https://github.com/<твой-username>/mlms.git
git push -u origin main
```

Если remote уже есть:
```powershell
git push
```

---

## Шаг 2 — Создать проект на Railway

1. Открыть https://railway.app → **New Project**
2. Выбрать **Deploy from GitHub repo** → выбрать `mlms`
3. Railway предложит сразу задеплоить — **не жми Deploy**, сначала добавим базы

---

## Шаг 3 — Добавить PostgreSQL (с pgvector + TimescaleDB)

В том же проекте Railway:

1. **+ New** → **Docker Image**
2. Image: `timescale/timescaledb-ha:pg16-all`
3. После создания сервиса → вкладка **Variables** → добавить:
   ```
   POSTGRES_DB=mlms
   POSTGRES_USER=mlms
   POSTGRES_PASSWORD=mlms_secret
   ```
4. Вкладка **Settings** → **Networking** → запомни внутренний hostname (вида `postgres.railway.internal`) и порт `5432`

---

## Шаг 4 — Добавить Redis

1. **+ New** → **Redis** (Railway managed, выбирай из шаблонов)
2. После создания → **Variables** → скопируй значение `REDIS_URL` (вида `redis://default:...@redis.railway.internal:6379`)

---

## Шаг 5 — Настроить env vars для app-сервиса

Перейди в сервис `mlms` (основное приложение) → **Variables** → добавить:

| Variable | Значение |
|----------|----------|
| `DATABASE_URL` | `postgresql+psycopg://mlms:mlms_secret@<postgres-hostname>:5432/mlms` |
| `REDIS_URL` | значение из шага 4 |
| `EMBEDDING_API_KEY` | твой OpenRouter ключ |
| `EMBEDDING_API_BASE` | `https://openrouter.ai/api/v1` |
| `MCP_TRANSPORT` | `sse` |
| `MCP_HOST` | `0.0.0.0` |
| `MCP_PORT` | `8000` |

> `<postgres-hostname>` — internal hostname из шага 3. Пример полного URL:
> `postgresql+psycopg://mlms:mlms_secret@postgres.railway.internal:5432/mlms`

---

## Шаг 6 — Deploy

В сервисе `mlms` → **Deploy**. Ждёшь ~2 мин пока соберётся Dockerfile.

Логи смотреть: вкладка **Deployments** → кликнуть на деплой → **View Logs**.

Успех выглядит так:
```
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8000
```

---

## Шаг 7 — Запустить миграции

В сервисе `mlms` → **Settings** → **Shell** (или кнопка Terminal):

```bash
alembic upgrade head
```

Ожидаемый вывод: `Running upgrade ... -> 005_create_skills, create skills table`

---

## Шаг 8 — Получить публичный URL

В сервисе `mlms` → **Settings** → **Networking** → **Generate Domain**.

Получишь URL вида: `https://mlms-production-xxxx.up.railway.app`

Проверь SSE endpoint:
```
https://mlms-production-xxxx.up.railway.app/sse
```

Браузер должен показать бесконечно висящий поток (это нормально — SSE держит соединение).

---

## Шаг 9 — Засидить демо-данные

Локально, с Railway переменными:

```powershell
$env:DATABASE_URL="postgresql+psycopg://mlms:mlms_secret@<railway-public-pg-host>:5432/mlms"
$env:REDIS_URL="redis://default:...@<railway-public-redis-host>:6379"
$env:EMBEDDING_API_KEY="sk-or-..."
uv run python scripts/seed_demo.py
```

> Для публичного доступа к Postgres/Redis извне Railway: в каждом сервисе баз →
> **Settings** → **Networking** → **Add Public Networking** → получишь host:port.

Ожидаемый вывод:
```
Seeding facts (session 1)...
  ok  Команда разработки: Иван (бэкенд), Маша (дизайн)...
  ok  Дедлайн проекта — 1 сентября 2026 года...
  ...
Demo seed complete.
```

---

## Шаг 10 — Подключить MCPJam

1. Открыть https://inspector.mcpjam.com
2. В поле **Server URL** вставить:
   ```
   https://mlms-production-xxxx.up.railway.app/sse
   ```
3. Нажать **Connect**
4. В левой панели должны появиться 9 инструментов:
   `memorize`, `get_facts`, `get_timeline`, `get_session_log`,
   `get_session_context`, `get_skills`, `revert_fact`, `search_memory`, `export_project`

---

## Шаг 11 — Проверить сценарий

Выполнить три вызова из `docs/demo-scenario.md` (Acts 1–3). Убедиться что:
- [ ] `get_facts` возвращает сидированный дедлайн
- [ ] повторный `memorize` с новым дедлайном не дублирует — старый уходит в is_current=FALSE
- [ ] `search_memory` возвращает результаты из 2+ слоёв

---

## Шаг 12 — Записать резервное видео

Пройти сценарий ещё раз с записью экрана (OBS / Windows Game Bar `Win+G`).
Сохранить как `demo-backup.mp4`. На флешку.

---

## Если что-то сломалось

| Симптом | Что делать |
|---------|-----------|
| Деплой падает с ошибкой сборки | Проверь логи Dockerfile — скорее всего `uv pip install` не нашёл зависимость |
| `alembic upgrade head` — ошибка соединения | DATABASE_URL неверный, проверь hostname и порт |
| MCPJam не подключается | Проверь `/sse` endpoint в браузере — должен висеть, не 404 |
| `seed_demo.py` — ошибка UUID | Миграции не запущены, повтори шаг 7 |
| Railway Railway останавливает сервис | Free tier засыпает — перейди на Hobby план ($5/мес) или передеплой перед защитой |
