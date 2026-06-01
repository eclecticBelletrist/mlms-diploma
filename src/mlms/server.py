from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, cast

import psycopg
import redis.asyncio as aioredis
from mcp.server.fastmcp import Context, FastMCP

from mlms.config import settings
from mlms.tools.export_project import export_project as _export_project
from mlms.tools.get_facts import get_facts as _get_facts
from mlms.tools.get_session_ctx import get_session_context as _get_session_ctx
from mlms.tools.get_session_log import get_session_log as _get_session_log
from mlms.tools.get_skills import get_skills as _get_skills
from mlms.tools.get_timeline import get_timeline as _get_timeline
from mlms.tools.memorize import memorize as _memorize
from mlms.tools.revert_fact import revert_fact as _revert_fact
from mlms.tools.search_memory import search_memory as _search_memory


@dataclass
class _AppCtx:
    conn: psycopg.AsyncConnection[Any]
    redis: Any


def _pg_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[_AppCtx]:
    conn = await psycopg.AsyncConnection.connect(_pg_dsn(settings.database_url), autocommit=True)
    r = aioredis.from_url(settings.redis_url)
    try:
        yield _AppCtx(conn=conn, redis=r)
    finally:
        await conn.close()
        await r.aclose()


mcp: FastMCP = FastMCP("mlms", lifespan=_lifespan)


_MemType = Literal["fact", "event", "skill", "session_log"]
_EventType = Literal["phase", "action", "decision"]


@mcp.tool()
async def memorize(
    content: str,
    type: str,
    metadata: dict[str, Any],
    ctx: Context[Any, Any, Any],
) -> dict[str, Any]:
    """Store a memory in the long-term memory system.

    type must be one of: fact | event | skill | session_log

    metadata required fields by type:
    - fact:       {"project_id": "<uuid>"}
                  optional: "tags" (list[str]), "category" (str), "chat_id" (str)
    - event:      {"project_id": "<uuid>", "title": "<short title>", "event_type": "<phase|action|decision>"}
                  optional: "chat_id" (str)
    - skill:      {"name": "<skill name>"}
                  optional: "domain" (str), "trigger_conditions" (str), "chat_id" (str), "project_id" (str)
    - session_log:{"chat_id": "<str>", "label": "<str max 100 chars>", "type": "<str>"}
                  optional: "project_id" (str)

    project_id for demo: always use "a1b2c3d4-0000-0000-0000-000000000001" (pre-seeded in DB).
    event_type values: "phase" | "action" | "decision"
    session_log type values: "topic" | "decision" | "problem" | "solution" | "insight" | "action" | "source" | "context" | "result"
    """
    app: _AppCtx = ctx.request_context.lifespan_context
    return await _memorize(
        content=content,
        type=cast(_MemType, type),
        metadata=metadata,
        conn=app.conn,
        redis=app.redis,
    )


@mcp.tool()
async def get_facts(
    ctx: Context[Any, Any, Any],
    about: str | None = None,
    project_id: str | None = None,
    tags: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Retrieve facts from semantic memory. Hybrid search when about is provided."""
    app: _AppCtx = ctx.request_context.lifespan_context
    rows = await _get_facts(
        about=about,
        project_id=project_id,
        tags=tags,
        limit=limit,
        conn=app.conn,
        redis=app.redis,
    )
    return [r.model_dump(mode="json") for r in rows]


@mcp.tool()
async def get_timeline(
    ctx: Context[Any, Any, Any],
    project_id: str | None = None,
    time_range: dict[str, str] | None = None,
    event_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Query timeline events. time_range: {start, end} as ISO8601 strings."""
    app: _AppCtx = ctx.request_context.lifespan_context
    rows = await _get_timeline(
        project_id=project_id,
        time_range=time_range,
        event_type=cast(_EventType, event_type),
        limit=limit,
        conn=app.conn,
    )
    return [r.model_dump(mode="json") for r in rows]


@mcp.tool()
async def get_session_log(
    ctx: Context[Any, Any, Any],
    chat_id: str | None = None,
    limit: int = 50,
    entry_type: str | None = None,
    semantic_query: str | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """In-session (chat_id) or cross-session (semantic_query) log retrieval. Modes are mutually exclusive. project_id scopes cross-session search."""
    app: _AppCtx = ctx.request_context.lifespan_context
    rows = await _get_session_log(
        chat_id=chat_id,
        limit=limit,
        entry_type=entry_type,
        semantic_query=semantic_query,
        project_id=project_id,
        conn=app.conn,
        redis=app.redis,
    )
    return [r.model_dump(mode="json") for r in rows]


@mcp.tool()
async def get_session_context(
    chat_id: str,
    ctx: Context[Any, Any, Any],
) -> dict[str, Any] | None:
    """Read working memory for a chat session from Redis. Returns None if session missing."""
    app: _AppCtx = ctx.request_context.lifespan_context
    result = await _get_session_ctx(chat_id=chat_id, redis=app.redis)
    return result.model_dump(mode="json") if result is not None else None


@mcp.tool()
async def get_skills(
    ctx: Context[Any, Any, Any],
    domain: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get procedural skills, optionally filtered by domain."""
    app: _AppCtx = ctx.request_context.lifespan_context
    rows = await _get_skills(domain=domain, limit=limit, conn=app.conn)
    return [r.model_dump(mode="json") for r in rows]


@mcp.tool()
async def revert_fact(
    fact_id: str,
    ctx: Context[Any, Any, Any],
) -> dict[str, Any]:
    """Revert a fact to its previous version. fact_id must be the current version."""
    from uuid import UUID
    app: _AppCtx = ctx.request_context.lifespan_context
    return await _revert_fact(fact_id=UUID(fact_id), conn=app.conn)


@mcp.tool()
async def search_memory(
    query: str,
    ctx: Context[Any, Any, Any],
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search across all memory layers simultaneously. filters: project_id, time_range, memory_type."""
    app: _AppCtx = ctx.request_context.lifespan_context
    rows = await _search_memory(query=query, filters=filters, conn=app.conn, redis=app.redis)
    return [r.model_dump(mode="json") for r in rows]


@mcp.tool()
async def export_project(
    project_id: str,
    ctx: Context[Any, Any, Any],
) -> str:
    """Export all current facts, timeline events, and skills for a project as JSON."""
    app: _AppCtx = ctx.request_context.lifespan_context
    return await _export_project(project_id=project_id, conn=app.conn)


if __name__ == "__main__":
    mcp.run()
