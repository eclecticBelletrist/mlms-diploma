# Key Architectural Decisions — MLMS

Этот файл фиксирует все значимые решения, принятые в ходе разработки.
Каждая запись содержит: что решено, почему, какие альтернативы отклонены.

---

## Decision 3: EMBEDDING_DIM = 1536 (Matryoshka truncation)

- **Причина:** pgvector 0.8.2 не поддерживает HNSW/IVFFlat для dim > 2000
- **Альтернатива:** sequential scan (recall 100%, O(n) — не масштабируется)
- **Решение:** Qwen3-Embedding-8B поддерживает Matryoshka — усечение до 1536 даёт < 1% потери recall
- **Следствие:** HNSW индекс возможен, O(log n), halfvec не подошёл (лимит 4000 < 4096)
- **EMBEDDING_DIM = 1536** — новое иммутабельное значение

Затронутые таблицы: `facts.embedding`, `session_log.embedding` (оба — `vector(4096)` → `vector(1536)`).
Миграция: `alembic/versions/006_change_embedding_dim.py`

---

## 2026-05-09 — Замена HNSW на IVFFlat для векторных индексов

**Решение:** Векторные индексы на колонках `embedding` в таблицах `facts` и `session_log`
используют **IVFFlat** (`lists = 100`) вместо HNSW.

**Причина:** pgvector (включая актуальную версию 0.8.2) ограничивает HNSW максимум
**2000 измерениями** для типа `vector`. `EMBEDDING_DIM = 4096` — константа, которую
нельзя изменять. Конфликт неразрешим на стороне HNSW.

Проверенные альтернативы:
- `halfvec` HNSW: максимум 4000 измерений — 4096 > 4000, не подходит.
- Снижение EMBEDDING_DIM: противоречит CLAUDE.md ("non-negotiable").
- Без индекса: неприемлемо для production (sequential scan).

**IVFFlat** не имеет ограничения по размерности для типа `vector`, поддерживает
`vector_cosine_ops` и обеспечивает ANN-поиск с разумной точностью при `lists = 100`.

**Затронутые файлы:**
- `alembic/versions/002_create_facts.py`
- `alembic/versions/004_create_session_log.py`
- `.claude/skills/mlms-schemas/SKILL.md`

**Компромисс:** IVFFlat даёт чуть ниже recall, чем HNSW при том же числе соседей,
и чувствителен к параметру `probes` на запрос (`SET ivfflat.probes = 10`).
Рекомендуется настроить `probes` при реализации `storage/facts.py`.

---

## 2026-05-09 — Отказ от ANN-индекса на embedding, переход к sequential scan

**Решение:** Колонки `embedding VECTOR(4096)` в `facts` и `session_log` **не имеют
ANN-индекса** в миграциях. Поиск ближайших соседей работает через sequential scan:
`ORDER BY embedding <=> $query LIMIT k`.

**Причина:** pgvector 0.8.2 ограничивает как HNSW, так и IVFFlat максимумом
**2000 измерений** для типа `vector`. `halfvec` поддерживает до 4000 измерений —
что также меньше 4096. Ни один ANN-индекс не работает с `VECTOR(4096)`.

Проверенные альтернативы:
- HNSW `vector(4096)`: максимум 2000 — нет.
- IVFFlat `vector(4096)`: максимум 2000 — нет.
- HNSW `halfvec(4096)`: максимум 4000 — нет (4096 > 4000).
- IVFFlat `halfvec(4096)`: максимум 4000 — нет.
- Expression index `embedding[:1536]::halfvec(1536)`: технически работает, но семантически
  ошибочно (только половина вектора), неприемлемо для production.

**Последствия:**
- Recall: 100% (нет аппроксимации) — превышает `PRECISION_AT_5_TARGET = 0.80`.
- Latency: O(n) по числу строк. Приемлемо для таблиц до ~100K строк (target SLA 200ms p99).
- При росте данных: рассмотреть внешний вектор-стор (Qdrant) или дождаться pgvector с
  повышенными лимитами.

**Затронутые файлы:**
- `alembic/versions/002_create_facts.py`
- `alembic/versions/004_create_session_log.py`
- `.claude/skills/mlms-schemas/SKILL.md`

---
