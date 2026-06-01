# SKILL: mlms-tools

Load this skill when: implementing, testing, or debugging any of the 7 MCP tools.

All tools live in `src/mlms/tools/`. Each tool maps to exactly one file.
`server.py` imports and registers all 7 — do not add tool logic to `server.py` directly.

---

## Tool selection guide

| Intent | Tool |
|---|---|
| Write anything to memory | `memorize` |
| Search facts by meaning | `get_facts` |
| Query events by time range | `get_timeline` |
| Restore session context / cross-session search | `get_session_log` |
| Read working memory (fast) | `get_session_context` |
| Get behavioral instructions by domain | `get_skills` |
| Search across all memory layers at once | `search_memory` |

---

## 1. memorize — `tools/memorize.py`

```python
def memorize(
    content: str,                                              # required
    type: Literal["fact", "event", "skill", "session_log"],   # required
    metadata: dict = {}
    # fact:        tags, project_id, category
    # event:       project_id, event_type ("phase"|"action"|"decision"), title
    # skill:       name, domain, trigger_conditions
    # session_log: chat_id, type (9 values), label (≤100 chars)
) -> dict:  # {"ok": bool, "memory_id": str}
```

FR-5 anchor: this is the **only** write entry point. All storage goes through `memorize`.
Routing: see `memorize() Routing` flowchart in CLAUDE.md.

---

## 2. get_facts — `tools/get_facts.py`

```python
def get_facts(
    about: str = None,        # semantic query → cosine search via pgvector
    project_id: str = None,   # SQL filter: WHERE project_id = ?
    tags: list[str] = None,   # SQL filter: WHERE tags @> ?
    limit: int = 10
) -> list[Fact]:
```

Always filter `is_current = TRUE`. Never return soft-deleted (old versioned) facts.
Hybrid search: if `about` contains exact identifiers (version numbers, file names), run FTS alongside vector search and merge results.

---

## 3. get_timeline — `tools/get_timeline.py`

```python
def get_timeline(
    project_id: str = None,
    time_range: dict = None,   # {"start": "ISO8601", "end": "ISO8601"}
    event_type: Literal["phase", "action", "decision"] = None,
    limit: int = 20
) -> list[TimelineEvent]:
```

TimescaleDB handles chunk pruning — always pass `time_range` when available so chunks are skipped.
Do not use `OFFSET` pagination on hypertables — use `time < last_seen_time` cursor pattern instead.

---

## 4. get_session_log — `tools/get_session_log.py`

```python
def get_session_log(
    chat_id: str = None,           # in-session mode: filter by chat_id, order time DESC
    limit: int = 50,
    type: str = None,              # optional type filter
    semantic_query: str = None     # cross-session mode: cosine search, requires chat_id=None
) -> list[SessionLogEntry]:
```

**Two mutually exclusive modes — never combine:**
- `chat_id` provided → in-session read (fast, index-only scan on `chat_id, time DESC`)
- `chat_id=None + semantic_query` → cross-session cosine search via HNSW

---

## 5. get_session_context — `tools/get_session_ctx.py`

```python
def get_session_context() -> SessionContext:
    # reads Redis only — must complete < 5ms
    # returns: project_id, last_activity, open_todos, active_entities, recent_decisions
```

No Postgres calls. If Redis key missing (TTL expired or new session), return empty context — do not error.

---

## 6. get_skills — `tools/get_skills.py`

```python
def get_skills(
    domain: str = None    # filter by domain field; None returns all skills
) -> list[Skill]:
```

Return all versions where `domain` matches (or all skills if domain=None).
Agent picks the highest version for use; lower versions are for audit only.

---

## 7. search_memory — `tools/search_memory.py`

```python
def search_memory(
    query: str,           # required — natural language
    filters: dict = {}
    # project_id:   str
    # time_range:   {"start": ISO8601, "end": ISO8601}
    # memory_type:  "fact" | "event" | "skill"
) -> list[MemoryResult]:
```

Searches across all layers simultaneously. Use the same `EMBEDDING_DIM=1536` model for query embedding.
Merge and rank results by cosine similarity before returning.
Only available after all storage layers are implemented — implement last (Step 11).

---

## JSON Schema compliance (FR-5 verification criterion)

Every tool must return responses matching its JSON Schema. Tests in `tests/integration/` verify this.
Use Pydantic models for all return types — schema is derived from the model automatically.
