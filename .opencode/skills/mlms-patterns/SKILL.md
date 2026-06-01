# SKILL: mlms-patterns

Load this skill when: implementing conflict detection, Session-Augmented RAG, hybrid search, or any business logic in `storage/` or `search/`.

---

## Pattern 1 — Conflict Detection (FR-7)

Triggered automatically inside `memorize(type="fact")`.

```mermaid
sequenceDiagram
  participant M as memorize()
  participant PG as PostgreSQL
  participant TX as Transaction

  M->>PG: embed(content) → vector
  M->>TX: BEGIN
  TX->>PG: SELECT id, version FROM facts\nWHERE project_id=? AND is_current=TRUE\nORDER BY embedding <=> new_vector LIMIT 1
  PG-->>TX: top_match (or empty)
  alt cosine_similarity(new_vector, top_match.embedding) >= 0.96
    TX->>PG: UPDATE facts SET is_current=FALSE, updated_at=NOW()\nWHERE id=top_match.id
    TX->>PG: INSERT facts (is_current=TRUE, version=top_match.version+1)
  else no conflict
    TX->>PG: INSERT facts (is_current=TRUE, version=1)
  end
  TX->>PG: COMMIT
```

Critical: the UPDATE + INSERT must be atomic (single transaction). Non-atomic = race condition.
`COSINE_CONFLICT_THRESHOLD = 0.96` is a starting calibration point — add a config override for tuning in section 2.4 tests.

---

## Pattern 2 — Session-Augmented RAG (original pattern)

The naive approach causes semantic drift: agent queries facts with user-message vocabulary, which may not match stored fact vocabulary → wrong results.

```mermaid
sequenceDiagram
  participant A as Agent
  participant MCP as MCP Server
  participant SL as session_log
  participant F as facts

  Note over A,F: WRONG (naive RAG)
  A->>MCP: get_facts(about=raw_user_message)
  MCP->>F: cosine search with user vocabulary
  F-->>A: semantically drifted results ❌

  Note over A,F: CORRECT (Session-Augmented RAG)
  A->>MCP: get_session_log(chat_id=current_chat)
  MCP->>SL: SELECT WHERE chat_id=? ORDER BY time DESC
  SL-->>A: session terms + active context
  A->>MCP: get_facts(about=query_enriched_with_session_terms)
  MCP->>F: cosine search aligned with session vocabulary
  F-->>A: relevant results ✅
```

Step 1 (`get_session_log`) is mandatory before Step 2 (`get_facts`) whenever the agent needs semantic memory in an active session. The session log acts as a vocabulary bridge between user intent and stored facts.

---

## Pattern 3 — Hybrid Search Routing (FR-6)

Three independent mechanisms, combinable in any subset:

```mermaid
flowchart TD
  Q[search query] --> V{has semantic\nmeaning?}
  V -->|yes| VS[vector search\npgvector cosine\nANN via HNSW]
  Q --> E{has exact terms\nIDs or versions?}
  E -->|yes| FTS[full-text search\ntsvector / tsquery\nPostgreSQL native]
  Q --> TR{has time\nconstraint?}
  TR -->|yes| TP[temporal filter\nTimescaleDB chunks\nskip irrelevant partitions]

  VS --> M[merge + rank results\nby score]
  FTS --> M
  TP --> M
  M --> PF{project_id\nfilter?}
  PF -->|yes| WH[WHERE project_id = ?\napplied to all mechanisms]
  PF -->|no| OUT[return results]
  WH --> OUT
```

Implementation note: each mechanism is independently applied, then results are merged. The `project_id` WHERE clause is always applied at SQL level — never filter in Python after the query.

---

## Pattern 4 — Embedding Cache

Semantic caching reduces API calls by 61-68% depending on query category.

```mermaid
flowchart LR
  T[text to embed] --> HC{hash in\nlocal cache?}
  HC -->|hit| CE[return cached vector]
  HC -->|miss| API[call Qwen3-Embedding-8B API]
  API --> FS{API available?}
  FS -->|yes| VEC[get 1536-dim vector]
  FS -->|no| FB[fallback: Qwen3-Embedding-0.6B\nlocal inference]
  VEC --> STORE[store in cache]
  FB --> STORE
  STORE --> CE
```

Cache key: `sha256(text + model_name)`. Store in Redis with same TTL as session or longer.
Always log which path was taken (API vs fallback) — needed for NFR-1 latency split reporting.

---

## Acceptance Criteria (for test verification loops)

| Check | How to verify |
|---|---|
| All 7 tools return JSON Schema-valid responses | `pytest tests/integration/test_tool_schemas.py` |
| Latency p99 < 200ms cached path | `pytest tests/benchmark/ --benchmark-only` |
| Latency cold path measured separately | same benchmark, separate fixture with cache cleared |
| Recall@5 > 80% | `pytest tests/benchmark/test_precision.py --dataset fixtures/synthetic_100.json` |
| Conflict detection is atomic | `pytest tests/unit/test_conflict_detection.py` — includes concurrent write test |
| FR-8 export/import 0 loss | `pytest tests/integration/test_export_import.py` |
| Docker Compose cold start works | `./scripts/init_db.sh && pytest tests/smoke/` |
