# SKILL: mlms-schemas

Load this skill when: writing migrations, modifying schema, implementing any storage layer function.

---

## Table 1 — projects

```sql
CREATE TABLE projects (
    id          UUID        PRIMARY KEY,
    name        TEXT        NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

Purpose: context isolation. All main tables reference `project_id` with cascade delete.

---

## Table 2 — facts (Semantic Memory, FR-1)

```sql
CREATE TABLE facts (
    id          UUID        PRIMARY KEY,
    content     TEXT        NOT NULL,
    embedding   VECTOR(1536),
    tags        TEXT[],
    category    TEXT,
    project_id  UUID        REFERENCES projects(id),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ,
    version     INT         DEFAULT 1,
    is_current  BOOL        DEFAULT TRUE
);

CREATE INDEX ON facts USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX ON facts (project_id, is_current);
```

Versioning rule: only ONE row per `(content_hash, project_id)` has `is_current = TRUE` at any time.
On conflict: old row → `is_current=FALSE`, new row → `is_current=TRUE, version=old+1`. Never DELETE.

---

## Table 3 — timeline_events (Episodic Memory / project scale, FR-2a)

```sql
CREATE TABLE timeline_events (
    id          UUID        PRIMARY KEY,
    time        TIMESTAMPTZ NOT NULL,
    project_id  UUID        REFERENCES projects(id),
    event_type  TEXT,
    title       TEXT,
    content     TEXT,
    metadata    JSONB
);

SELECT create_hypertable('timeline_events', 'time');
```

`event_type` values: `'phase'` | `'action'` | `'decision'`
`metadata JSONB`: use for all new attributes — never ALTER TABLE for this.
TimescaleDB partitions by `time` → temporal range queries skip irrelevant chunks automatically.

---

## Table 4 — session_log (Episodic Memory / chat scale, FR-2b)

```sql
CREATE TABLE session_log (
    time        TIMESTAMPTZ NOT NULL,
    chat_id     TEXT        NOT NULL,
    type        TEXT        NOT NULL
        CONSTRAINT session_log_type_check CHECK (
            type IN ('topic','decision','problem','solution',
                     'insight','action','source','context','result')
        ),
    label       TEXT        NOT NULL,
    content     TEXT,
    embedding   VECTOR(1536),
    tags        TEXT[],
    meta        JSONB
);

SELECT create_hypertable('session_log', 'time');

CREATE INDEX ON session_log USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX ON session_log (chat_id, time DESC);
```

`label`: max 100 chars, compressed summary.
Two usage modes (never combine in one query):
- **in-session**: filter by `chat_id`, order by `time DESC` — restores work context fast
- **cross-session**: `semantic_query` with cosine search via HNSW index, no `chat_id` filter

---

## Table 5 — skills (Procedural Memory, FR-4)

```sql
CREATE TABLE skills (
    id                 UUID        PRIMARY KEY,
    name               TEXT        NOT NULL,
    domain             TEXT,
    content            TEXT        NOT NULL,
    trigger_conditions JSONB,
    version            INT         DEFAULT 1,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);
```

On update: increment `version`, never DELETE previous versions (history must be preserved for FR-4).

---

## Redis Session Context (Working Memory, FR-3)

```
Key pattern : session:{chat_id}
TTL         : 172800 seconds (48h) — call EXPIRE on every access, not just on create
Value (JSON):
  project_id       : uuid string
  last_activity    : ISO 8601 timestamp
  open_todos       : list of strings
  active_entities  : list of strings (active files, modules)
  recent_decisions : list of strings
```

`get_session_context()` must return within 5ms — Redis only, never touch Postgres for this call.

---

## Migration file naming

```
alembic/versions/
  001_create_projects.py
  002_create_facts.py
  003_create_timeline_events.py
  004_create_session_log.py
  005_create_skills.py
```

Hypertable creation (`create_hypertable`) goes inside the migration, not in init scripts.
