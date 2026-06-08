#!/usr/bin/env python3
"""Seed demo scenario: 'The agent that grows up'.

Run once after alembic upgrade head:
    uv run python scripts/seed_demo.py

Scenario:
  Session 1 (past): agent learns facts about a redesign project.
  Session 2 (live demo): new session recalls from DB, then contradiction
  triggers conflict detection live.
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
        print(f"  ok  {content[:60]}...")

    events = [
        ("Старт проекта: кикофф-встреча с заказчиком", "phase"),
        ("Выбран стек технологий на архитектурном ревью", "decision"),
        ("Завершён дизайн главной страницы", "action"),
    ]

    print("\nSeeding timeline events...")
    for title, etype in events:
        await memorize(
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
        print(f"  ok  [{etype}] {title}")

    skills = [
        (
            "Оценка задач по методу Planning Poker",
            "planning",
            "Когда нужно оценить сложность задачи в команде",
        ),
        (
            "Code Review чеклист: типы, тесты, безопасность, производительность",
            "engineering",
            "Перед каждым merge request",
        ),
    ]

    print("\nSeeding skills...")
    for content, domain, trigger in skills:
        await memorize(
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
        print(f"  ok  [{domain}] {content[:60]}")

    await conn.close()
    await r.aclose()

    print(f"\nDemo seed complete.")
    print(f"Project ID: {DEMO_PROJECT}")
    print(f"Use 'demo-session-live' as chat_id for the live demo session.")


if __name__ == "__main__":
    asyncio.run(seed())
