# Demo Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy MLMS to Railway with SSE transport so MCPJam can connect from any browser on the teacher's PC during the diploma defense.

**Architecture:** Add `MCP_TRANSPORT` env var support to server.py (stdio for local dev, sse for cloud). Deploy on Railway using three services: timescaledb+pgvector Postgres, Redis, and the app. Improve tool docstrings to reduce LLM parameter confusion. Add a demo seed script that pre-loads the "агент который взрослеет" scenario.

**Tech Stack:** FastMCP SSE transport, Railway, timescale/timescaledb-ha Docker image (includes pgvector), uvicorn, MCPJam hosted web UI.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/mlms/config.py` | Modify | Add `mcp_transport`, `host`, `port` settings |
| `src/mlms/server.py` | Modify | SSE transport in `__main__`, improved tool docstrings |
| `Dockerfile` | Create | App image for Railway |
| `railway.toml` | Create | Railway service config |
| `scripts/seed_demo.py` | Create | Pre-seed demo scenario into DB |
| `docs/demo-scenario.md` | Create | 3-minute spoken script for defense |

---

## Task 1: SSE Transport Support

**Files:**
- Modify: `src/mlms/config.py`
- Modify: `src/mlms/server.py` (lines 212–213, `__main__` block)

- [ ] **Step 1: Add transport settings to config.py**

```python
# add inside class Settings, after redis_url:
mcp_transport: str = Field(default="stdio", alias="MCP_TRANSPORT")
mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")
mcp_port: int = Field(default=8000, alias="MCP_PORT")
```

- [ ] **Step 2: Update `__main__` in server.py**

Replace:
```python
if __name__ == "__main__":
    mcp.run()
```

With:
```python
if __name__ == "__main__":
    transport = settings.mcp_transport
    if transport == "sse":
        mcp.run(transport="sse", host=settings.mcp_host, port=settings.mcp_port)
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http", host=settings.mcp_host, port=settings.mcp_port)
    else:
        mcp.run()
```

- [ ] **Step 3: Smoke-test SSE locally**

```powershell
$env:MCP_TRANSPORT="sse"; uv run python -m mlms.server
```

Expected: uvicorn starts on `http://0.0.0.0:8000`, no crash. Ctrl+C to stop.

- [ ] **Step 4: Commit**

```
git add src/mlms/config.py src/mlms/server.py
git commit -m "feat: SSE transport support via MCP_TRANSPORT env var"
```

---

## Task 2: Improve Tool Descriptions

**Files:**
- Modify: `src/mlms/server.py` (all tool docstrings)

Goal: LLM stops sending wrong UUIDs and misformatted params. Rules: (a) note which IDs are auto-generated server-side, (b) give a concrete example for every required field.

- [ ] **Step 1: Update `memorize` docstring**

Replace existing docstring with:

```python
"""Store a memory in the long-term memory system.

type: "fact" | "event" | "skill" | "session_log"

metadata by type — copy these templates exactly:

fact:
  {"project_id": "a1b2c3d4-0000-0000-0000-000000000001"}
  optional: "tags": ["list","of","strings"], "category": "string", "chat_id": "any-string-you-choose"

event:
  {"project_id": "a1b2c3d4-0000-0000-0000-000000000001",
   "title": "Short title under 100 chars",
   "event_type": "phase"}
  event_type values: "phase" | "action" | "decision"
  optional: "chat_id": "any-string"

skill:
  {"name": "skill name"}
  optional: "domain": "string", "trigger_conditions": "string",
            "chat_id": "any-string", "project_id": "a1b2c3d4-0000-0000-0000-000000000001"

session_log:
  {"chat_id": "any-string-you-choose",
   "label": "Short label under 100 chars",
   "type": "topic"}
  type values: "topic"|"decision"|"problem"|"solution"|"insight"|"action"|"source"|"context"|"result"
  optional: "project_id": "a1b2c3d4-0000-0000-0000-000000000001"

NOTE: Never invent project_id UUIDs. Always use the one shown above for demo.
Returns: {"ok": true, "memory_id": "<server-generated-id>"}
"""
```

- [ ] **Step 2: Update `get_facts` docstring**

```python
"""Retrieve current facts from semantic memory.

about: natural-language query for vector search, e.g. "what is the project deadline"
project_id: use "a1b2c3d4-0000-0000-0000-000000000001" for demo. Optional — omit to search all.
tags: optional list of tag strings to filter, e.g. ["backend", "auth"]
limit: max results, default 10

Returns list of fact objects with id, content, tags, category, version, created_at.
"""
```

- [ ] **Step 3: Update `get_timeline` docstring**

```python
"""Query timeline events (phases, actions, decisions).

project_id: "a1b2c3d4-0000-0000-0000-000000000001" for demo
time_range: {"start": "2025-01-01T00:00:00Z", "end": "2026-12-31T23:59:59Z"} — ISO8601, both optional
event_type: "phase" | "action" | "decision" — optional filter
limit: default 20
"""
```

- [ ] **Step 4: Update `get_session_log` docstring**

```python
"""Retrieve session log entries. Two exclusive modes — do not combine chat_id and semantic_query.

Mode 1 — current session: provide chat_id, omit semantic_query
  chat_id: the session string you used when calling memorize
  entry_type: optional filter string

Mode 2 — cross-session search: provide semantic_query, omit chat_id
  semantic_query: natural-language search, e.g. "authentication decisions"
  project_id: optional scope — "a1b2c3d4-0000-0000-0000-000000000001"
  limit: default 50
"""
```

- [ ] **Step 5: Update `search_memory` docstring**

```python
"""Search across ALL memory layers simultaneously (facts + timeline + session_log + skills).

query: natural-language search string, e.g. "what did we decide about the database"
filters (optional dict):
  "project_id": "a1b2c3d4-0000-0000-0000-000000000001"
  "memory_type": "fact" | "event" | "skill" | "session_log"
  "time_range": {"start": "ISO8601", "end": "ISO8601"}

Returns ranked list from all layers with layer field indicating source.
"""
```

- [ ] **Step 6: Commit**

```
git add src/mlms/server.py
git commit -m "docs: improve tool descriptions with examples and param guidance"
```

---

## Task 3: Dockerfile + Railway Config

**Files:**
- Create: `Dockerfile`
- Create: `railway.toml`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY src/ src/

RUN uv pip install --system -e .

ENV MCP_TRANSPORT=sse
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "mlms.server"]
```

- [ ] **Step 2: Create railway.toml**

```toml
[build]
builder = "dockerfile"

[deploy]
startCommand = "python -m mlms.server"
healthcheckPath = "/"
healthcheckTimeout = 30
restartPolicyType = "on-failure"

[[services]]
name = "mlms"

[services.variables]
MCP_TRANSPORT = "sse"
MCP_HOST = "0.0.0.0"
MCP_PORT = "8000"
```

- [ ] **Step 3: Create Railway project**

In Railway dashboard:
1. New Project → Deploy from GitHub repo
2. Add PostgreSQL service: use custom image `timescale/timescaledb-ha:pg16-all` (includes pgvector + timescaledb)
3. Add Redis service (Railway managed Redis)
4. In the app service, set env vars:
   - `DATABASE_URL` = Railway Postgres internal URL (replace `postgresql://` with `postgresql+psycopg://`)
   - `REDIS_URL` = Railway Redis internal URL
   - `EMBEDDING_API_KEY` = your OpenRouter key
   - `MCP_TRANSPORT` = `sse`

- [ ] **Step 4: Run migrations on Railway**

After deploy, open Railway shell for the app service:
```bash
uv run alembic upgrade head
```

- [ ] **Step 5: Verify SSE endpoint**

Open MCPJam at https://inspector.mcpjam.com, paste the Railway app URL + `/sse` path, connect. Should show all 9 tools listed.

- [ ] **Step 6: Commit**

```
git add Dockerfile railway.toml
git commit -m "feat: add Dockerfile and Railway deployment config"
```

---

## Task 4: Demo Seed Script

**Files:**
- Create: `scripts/seed_demo.py`

Pre-seeds the "агент который взрослеет" scenario. Run once after `alembic upgrade head`. Uses project_id `a1b2c3d4-0000-0000-0000-000000000001`.

- [ ] **Step 1: Create seed script**

```python
#!/usr/bin/env python3
"""Seed demo scenario: 'The agent that grows up'.

Run once after alembic upgrade head:
    uv run python scripts/seed_demo.py

Scenario:
  Session 1 (past): agent learns facts about a redesign project.
  Session 2 (live demo): agent recalls from new session, then we introduce
  a contradiction to trigger conflict detection live.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import psycopg
import redis.asyncio as aioredis

from mlms.config import settings
from mlms.tools.memorize import memorize

DEMO_PROJECT = "a1b2c3d4-0000-0000-0000-000000000001"
SESSION_1 = "demo-session-past"


def _pg_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


async def seed() -> None:
    conn = await psycopg.AsyncConnection.connect(_pg_dsn(settings.database_url), autocommit=True)
    r = aioredis.from_url(settings.redis_url)

    facts = [
        ("Команда разработки: Иван (бэкенд), Маша (дизайн), Антон (фронтенд)", ["team"]),
        ("Дедлайн проекта — 1 сентября 2026 года", ["deadline", "planning"]),
        ("Стек: FastAPI + PostgreSQL + React. Redis для кэша.", ["tech", "backend"]),
        ("Бюджет проекта утверждён: 500 000 рублей", ["budget", "planning"]),
        ("Основной заказчик — ООО «Горизонт», контакт — Петров Сергей", ["client"]),
    ]

    print("Seeding facts (session 1)...")
    for content, tags in facts:
        result = await memorize(
            content=content,
            type="fact",
            metadata={"project_id": DEMO_PROJECT, "tags": tags, "chat_id": SESSION_1},
            conn=conn,
            redis=r,
        )
        print(f"  ✓ {content[:60]}... → {result['memory_id']}")

    events = [
        ("Старт проекта: кикофф-встреча с заказчиком", "phase"),
        ("Выбран стек технологий на архитектурном ревью", "decision"),
        ("Завершён дизайн главной страницы", "action"),
    ]

    print("\nSeeding timeline events...")
    for title, etype in events:
        result = await memorize(
            content=title,
            type="event",
            metadata={
                "project_id": DEMO_PROJECT,
                "title": title,
                "event_type": etype,
                "chat_id": SESSION_1,
            },
            conn=conn,
            redis=r,
        )
        print(f"  ✓ [{etype}] {title}")

    skills = [
        ("Оценка задач по методу Planning Poker", "planning",
         "Когда нужно оценить сложность задачи в команде"),
        ("Code Review чеклист: типы, тесты, безопасность, производительность", "engineering",
         "Перед каждым merge request"),
    ]

    print("\nSeeding skills...")
    for content, domain, trigger in skills:
        result = await memorize(
            content=content,
            type="skill",
            metadata={
                "name": content[:50],
                "domain": domain,
                "trigger_conditions": trigger,
                "project_id": DEMO_PROJECT,
            },
            conn=conn,
            redis=r,
        )
        print(f"  ✓ [{domain}] {content[:60]}")

    await conn.close()
    await r.aclose()
    print("\nDemo seed complete. Project ID:", DEMO_PROJECT)
    print("Use SESSION_2 = 'demo-session-live' for the live demo session.")


if __name__ == "__main__":
    asyncio.run(seed())
```

- [ ] **Step 2: Run seed against Railway DB**

Locally, set env to point at Railway DB:
```powershell
$env:DATABASE_URL="postgresql+psycopg://<railway-pg-url>"
$env:REDIS_URL="redis://<railway-redis-url>"
uv run python scripts/seed_demo.py
```

Expected output: 5 facts, 3 events, 2 skills seeded with ✓ per line.

- [ ] **Step 3: Verify via MCPJam**

In MCPJam, call `get_facts` with `project_id = "a1b2c3d4-0000-0000-0000-000000000001"`. Should return 5 facts.

- [ ] **Step 4: Commit**

```
git add scripts/seed_demo.py
git commit -m "feat: add demo seed script for defense scenario"
```

---

## Task 5: Demo Scenario Document

**Files:**
- Create: `docs/demo-scenario.md`

- [ ] **Step 1: Create scenario script**

```markdown
# Demo Scenario — MLMS Defense (3 min)

## Setup (before entering auditorium)
1. Open MCPJam: https://inspector.mcpjam.com
2. Connect to: https://<your-railway-url>/sse
3. Verify 9 tools are listed
4. Run seed_demo.py if not done yet

---

## Act 1 — Cross-Session Memory (45 sec)

**Say:** "В прошлой сессии агент узнал факты о проекте. Сейчас — новая сессия, чистый контекст.
Посмотрим, помнит ли система."

**Do in MCPJam:** call `get_facts`
```json
{
  "about": "дедлайн проекта",
  "project_id": "a1b2c3d4-0000-0000-0000-000000000001"
}
```

**Expected response:** факт "Дедлайн проекта — 1 сентября 2026" возвращается.

**Say:** "Агент не хранит это в контексте диалога — он читает из персистентной БД.
Закрой браузер, открой заново — факт не пропадёт."

---

## Act 2 — Conflict Detection (60 sec)

**Say:** "Теперь — самое интересное. Представим, дедлайн сдвинули."

**Do:** call `memorize`
```json
{
  "content": "Дедлайн проекта перенесён — теперь 1 декабря 2026",
  "type": "fact",
  "metadata": {
    "project_id": "a1b2c3d4-0000-0000-0000-000000000001",
    "tags": ["deadline", "planning"]
  }
}
```

**Do:** call `get_facts` again с `about = "дедлайн"`

**Expected:** возвращается НОВЫЙ факт (декабрь), старый (сентябрь) — is_current=FALSE.

**Say:** "Система не накопила противоречие — она его обнаружила через косинусное сходство
и автоматически устарела старую версию. Это — версионирование фактов.
В ChatGPT такого нет — там просто копится всё подряд."

---

## Act 3 — Cross-Layer Search (45 sec)

**Say:** "И последнее — поиск по всем слоям памяти одновременно."

**Do:** call `search_memory`
```json
{
  "query": "что решили по технологиям и когда это произошло",
  "filters": {"project_id": "a1b2c3d4-0000-0000-0000-000000000001"}
}
```

**Expected:** результаты из facts (стек) + timeline (decision о стеке) + skills (code review).

**Say:** "Один запрос — ответ из семантической памяти, эпизодической и процедурной.
Это архитектура CoALA — четыре слоя памяти из когнитивной науки."

---

## Fallback (если нет интернета)
Запустить заранее записанное видео (то же сценарий, 3 мин).

## Ответы на вопросы

**Разраб-практик:** "Как работает конфликт-детекция?"
→ "Косинусное расстояние между векторами. Порог 0.96 — эмпирически калибруется.
При совпадении — UPDATE is_current=FALSE + INSERT new в одной транзакции (ACID)."

**Препод БД:** "Почему pgvector а не отдельная векторная БД?"
→ "Меньше инфраструктуры, JOIN с реляционными данными без сетевого хопа.
pgvector 0.8.x поддерживает HNSW до dim=2000, у нас 1536 — укладываемся."

**Заведующая:** "А что такое нейросеть здесь?"
→ "Нейросеть превращает текст в 1536 чисел — вектор. Похожие тексты дают близкие векторы.
Мы не используем нейросеть для ответов — только для поиска похожих воспоминаний."
```

- [ ] **Step 2: Commit**

```
git add docs/demo-scenario.md
git commit -m "docs: add 3-minute defense demo scenario script"
```

---

## Post-Deploy Checklist

- [ ] MCPJam connects to Railway URL and lists 9 tools
- [ ] `seed_demo.py` runs clean (no errors)
- [ ] Act 1: `get_facts` returns seeded deadline fact
- [ ] Act 2: new `memorize` triggers conflict, old fact is_current=FALSE
- [ ] Act 3: `search_memory` returns results from 2+ layers
- [ ] Backup video recorded
