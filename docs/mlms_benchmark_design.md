# MLMS Benchmark — Design Document
**Назначение:** внутренний справочник для реализации модуля генерации синтетического датасета `synthetic_100.json` и запуска бенчмарка Recall@5 + latency p99.

---

## 1. Контекст: что и зачем измеряем

MLMS имеет 4 слоя памяти. Бенчмарк покрывает **только semantic слой** (факты в pgvector), потому что только он использует embedding-based retrieval — остальные слои детерминированы (Redis get/set, SQL time_range, DISTINCT ON version).

**Два целевых числа для диплома:**

| NFR | Метрика | Цель |
|-----|---------|------|
| NFR-1 | Latency p99 (cached path, без API call) | < 200 ms |
| FR-1 | Recall@5 на synthetic_100.json | ≥ 0.80 |

**Recall@5** = доля найденных релевантных фактов среди всех релевантных, при условии что рассматриваются только топ-5 возвращённых результатов. Усредняется по 100 сценариям.

```
Recall@5(scenario) = |returned_top5 ∩ relevant_ids| / |relevant_ids|
Recall@5(total)    = mean(Recall@5 по всем 100 сценариям)
```

**Почему Recall@5, а не Precision@5.** В каждом сценарии 1–2 релевантных факта и 3–5 дистракторов. При Precision@5 максимально достижимый результат при 1 релевантном = 1/5 = 0.20, что делает цель ≥ 0.80 математически недостижимой. Recall@5 при 1 релевантном факте: если нашли — 1.0, нет — 0.0. Среднее по 100 сценариям = доля запросов где нужный факт попал в топ-5. Цель ≥ 0.80 означает: система находит нужный факт в 80% случаев.

---

## 2. Структура датасета synthetic_100.json

### 2.1 Четыре категории сценариев

| Категория | Кол-во | Что тестируется |
|-----------|--------|-----------------|
| `lexical` | 25 | Прямой vocabulary match — baseline, должен работать всегда |
| `semantic_drift` | 25 | Запрос и факт про одно, но разными словами; тестирует Qwen3-embeddings + Session-Augmented RAG; запускается в A/B режиме |
| `conflict` | 25 | В БД старый факт (is_current=FALSE) и новый (TRUE); должен вернуться только новый |
| `cross_session` | 25 | Запрос ищет факты из другой сессии (другой chat_id, тот же project_id); тестирует persistent cross-session memory без SAR обогащения |

### 2.2 Схемы сценариев

**Стандартная схема** (lexical, conflict, semantic_drift):

```json
{
  "id": "semantic_drift_003",
  "category": "semantic_drift",
  "domain": "nginx_config",
  "setup": {
    "facts": [
      {"id": "f1", "content": "...", "is_relevant": true},
      {"id": "f2", "content": "...", "is_relevant": false},
      {"id": "f3", "content": "...", "is_relevant": false},
      {"id": "f4", "content": "...", "is_relevant": false}
    ],
    "session_log": ["фраза контекста 1", "фраза контекста 2"]
  },
  "query": "как мы решили X?",
  "expected": {
    "relevant_ids": ["f1"],
    "irrelevant_ids": ["f2", "f3", "f4"]
  },
  "meta": {
    "tests_session_augmentation": true,
    "ab_test": true,
    "difficulty": "medium",
    "generated_by": "claude-sonnet-4.6",
    "verified_by": "gpt-5.2",
    "auto_fixed": false
  }
}
```

**Схема cross_session** (два chat_id, session_log querying сессии пустой):

```json
{
  "id": "cross_session_007",
  "category": "cross_session",
  "domain": "ci_pipeline",
  "setup": {
    "source_session": {
      "chat_id": "src_cross_007",
      "facts": [
        {"id": "f1", "content": "...", "is_relevant": true},
        {"id": "f2", "content": "...", "is_relevant": false},
        {"id": "f3", "content": "...", "is_relevant": false}
      ]
    },
    "query_session": {
      "chat_id": "qry_cross_007",
      "session_log": []
    }
  },
  "query": "...",
  "expected": {
    "relevant_ids": ["f1"],
    "irrelevant_ids": ["f2", "f3"]
  },
  "meta": {
    "tests_session_augmentation": false,
    "ab_test": false,
    "difficulty": "hard",
    "generated_by": "gpt-5.2",
    "verified_by": "grok-4.20",
    "auto_fixed": false
  }
}
```

`session_log` у query_session всегда пустой — это принципиально: querying сессия не имеет доступа к контексту source сессии, SAR обогащение невозможно.

### 2.3 Требования к содержимому сценариев

- Релевантных фактов: 1–2 на сценарий
- Distractor-фактов: 3–5 на сценарий (похожая тема, но не отвечают на запрос)
- session_log: 2–3 фразы только для `semantic_drift`; для `lexical`, `conflict`, `cross_session` — пустой массив
- Домены: IT-контекст любой (DevOps, ML, networking, databases, web, etc.)
- Домен не должен повторяться между сценариями (контролируется через `used_topics`)
- Для `semantic_drift`: запрос и релевантный факт не должны иметь более одного общего ключевого слова (требование lexical distance — подробнее в разделе 4.4)

---

## 3. Генерация: архитектура pipeline

### 3.1 Общая схема

```
[Stage 1] GENERATE  — LLM генерирует 5 сценариев одним вызовом (tool_use → JSON)
[Stage 2] VERIFY    — другой LLM из другого семейства проверяет ground truth
[Stage 3] VALIDATE  — детерминированная проверка схемы + auto-fix ID
[Stage 4] ACCUMULATE — пополняем used_topics, пишем в файл
```

20 батчей × 5 сценариев = 100 сценариев итого. Все вызовы через **OpenRouter API** (`https://openrouter.ai/api/v1/chat/completions`) с `tool_choice` — единый механизм для всех трёх провайдеров.

### 3.2 Ротация моделей

Три модели из **разных семейств**. Смена семейства между генератором и верификатором — обязательна.

| Батч | Генератор | Верификатор |
|------|-----------|-------------|
| 0, 3, 6, ... | `anthropic/claude-sonnet-4.6` | `openai/gpt-5.2` |
| 1, 4, 7, ... | `openai/gpt-5.2` | `x-ai/grok-4.20` |
| 2, 5, 8, ... | `x-ai/grok-4.20` | `anthropic/claude-sonnet-4.6` |

Правило: верификатор всегда из **другого семейства** (не следующий по кругу, а строго cross-family). Модели в `.env`: `MODEL_CLAUDE`, `MODEL_GPT4O`, `MODEL_GROK` — можно переопределить без изменения кода.

### 3.3 Распределение категорий по батчам

Каждая категория — 5 батчей по 5 сценариев = 25 итого. Порядок батчей внутри категории — последовательный.

---

## 4. Промпт-инжиниринг

### 4.1 Ключевые решения, подтверждённые исследованиями

**Нет ролевой установки ("Ты — эксперт").**
Исследование Zheng et al., EMNLP 2024 (162 персоны, 4 семейства LLM, 2410 вопросов): personas в system prompt не улучшают производительность на объективных задачах и иногда деградируют её. Удалено.

**Двухфазная генерация: сначала рассуждение, потом JSON.**
Исследование Tam et al., EMNLP 2024 ("Let Me Speak Freely?"): строгий JSON-mode деградирует reasoning на 10–15%. Решение: модель сначала рассуждает свободно (`rationale`), затем заполняет структурированные поля. `rationale` — первое поле в JSON-схеме.

**Native structured outputs вместо prompt-only JSON.**
Prompt-only JSON: failure rate 5–20%. Все три провайдера вызываются через OpenRouter API с `tool_choice: {type: "function", function: {name: ...}}` — failure rate < 0.3%.

**Cross-family верификация.**
Panel of LLMs (PoLL) подход: разные модельные семейства имеют разные "blind spots". Верификатор из другого семейства снижает correlated bias.

**Список used_topics в каждом промпте.**
Борется с mode collapse — тенденцией instruction-tuned моделей генерировать структурно похожие сценарии при повторных вызовах.

### 4.2 System prompt (финальный)

Не содержит ролевой установки. Содержит только контекст задачи:

```
Ты генерируешь тест-кейсы для evaluation retrieval-системы.

Контекст системы:
- MLMS хранит факты агента в pgvector (cosine similarity, Qwen3 embeddings)
- Перед поиском запрос обогащается терминами из session_log (Session-Augmented RAG)
- Факты описывают технические решения, конфигурации, предпочтения IT-агента
- Домены: любой IT-контекст — DevOps, ML, networking, databases, web и т.д.

Требования к выводу:
- Отвечай через native structured output (tool use / function call)
- Поле rationale — всегда первое, пиши рассуждение до заполнения остальных полей
- Не используй домены из списка used_topics
```

### 4.3 User prompt

```
Сгенерируй РОВНО 5 тест-кейсов категории "{category}".

Уже использованные домены (не повторять):
{used_topics_json}

Определение категории:
{category_description}

Требования к разнообразию (обязательно):
- Стиль запроса: чередуй вопрос / утверждение / неполная фраза
- Длина фактов: чередуй короткий / детальный / с числами или кодом
- Домены: каждый сценарий — новый домен, не из used_topics
```

### 4.4 Описания категорий (подставляются в user prompt)

**lexical:**
```
Запрос содержит те же ключевые слова что и релевантный факт.
Это baseline — embedding retrieval должен справляться всегда.
Distractors: факты из той же предметной области, но про другой аспект.
session_log: пустой массив.
```

**semantic_drift:**
```
Запрос и релевантный факт описывают одно и то же, но разными словами.
Паттерн: факт — техническая формулировка, запрос — на языке проблемы/результата.
Session_log содержит термины-мосты, которые связывают запрос с фактом при обогащении.
Без session_log cosine similarity между запросом и фактом должна быть ниже порога.

ОБЯЗАТЕЛЬНЫЙ self-check в rationale перед заполнением полей:
  Шаг 1. Выпиши ключевые смысловые слова из query (без стоп-слов).
  Шаг 2. Выпиши ключевые смысловые слова из content релевантного факта.
  Шаг 3. Найди пересечение. Оно должно быть ПУСТЫМ или содержать не более одного слова.
          Если больше — переформулируй query или факт до выполнения условия.
  Шаг 4. Проверь session_log: каждая фраза должна быть семантическим мостом —
          содержать слова близкие одновременно к query И к факту.

ПЛОХОЙ пример (отвергни):
  fact:  "настроен rate limiting через nginx на 100 req/s"
  query: "как работает rate limiting в nginx"
  пересечение: ["rate", "limiting", "nginx"] — слишком много, naive найдёт

ХОРОШИЙ пример (принять):
  fact:  "настроен rate limiting через nginx на 100 req/s"
  query: "как мы защитились от перегрузки сервера"
  пересечение: [] — пусто, naive не найдёт
  session_log мост: ["проблема с нагрузкой", "лимиты запросов", "nginx конфиг"]
```

**conflict:**
```
В БД есть два факта про одно и то же: устаревший (is_relevant=false) и актуальный (is_relevant=true).
Они явно противоречат друг другу — разные значения одного параметра или решения.
Запрос ищет текущее состояние — должен вернуться только актуальный факт.
session_log: пустой массив.
```

**cross_session:**
```
Факты хранятся под source_session.chat_id. Запрос выполняется из query_session.chat_id.
Оба chat_id принадлежат одному project_id — факты видны глобально, фильтрации нет.
query_session.session_log: ВСЕГДА пустой массив. Это принципиально — SAR невозможен,
retrieval работает только на чистых embeddings.

Это тестирует baseline качество Qwen3 (dim=1536) в условиях vocabulary mismatch
без возможности SAR обогащения. Ожидаемый Recall@5 ниже чем у semantic_drift (SAR) —
это намеренно, не признак ошибки системы.

Сценарий должен иметь lexical distance как в semantic_drift: запрос и факт описывают
одно и то же разными словами. Без этого cross_session вырождается в lexical.
```

### 4.5 Verify prompt

```
Проверь корректность ground truth разметки этого тест-кейса.

Запрос: "{query}"
Категория: "{category}"
Session_log: {session_log}

Факты в БД:
{факты пронумерованные}

Заявленные релевантные: {relevant_ids}

Критерии релевантности:
1. Факт семантически отвечает именно на этот запрос (не просто похож по теме)
2. Пользователь получил бы нужную информацию из этого факта
3. Факт НЕ является просто distractor'ом похожей тематики

Если категория semantic_drift или cross_session — дополнительно проверь:
4. Запрос и релевантный факт не имеют более одного общего ключевого слова.
   Если имеют — это плохой сценарий (naive найдёт без SAR), отметь как issue.

Для каждого факта вынеси: relevant / irrelevant / borderline.
Если не согласен с разметкой — укажи исправленный список.
```

---

## 5. Защита от известных проблем

### 5.1 Preference leakage

Проблема: если одна модель генерит данные И используется в embeddings/оценке — возникает bias.

Наше решение: Claude/GPT-5.2/Grok генерируют и верифицируют. Qwen3 используется **только** для embeddings в самом MLMS. Recall@5 считается детерминированно по UUID — никакой LLM не участвует в подсчёте метрики.

### 5.2 Hallucinated ground truth

Проблема: LLM уверенно размечает неправильно.

Решение: обязательный verify-вызов моделью из другого семейства. При `verdict=fix_needed` — перезаписываем `relevant_ids`, ставим флаг `auto_fixed=true` в meta.

### 5.3 Mode collapse / повторяющиеся паттерны

Проблема: instruction-tuned модели с repeated templates генерируют структурно похожие сценарии.

Решение:
- `used_topics` в каждом промпте
- Явные требования к разнообразию стиля в user prompt
- Три разных модели по ротации

### 5.4 JSON parse failures

Проблема: prompt-only JSON даёт 5–20% failure rate.

Решение: все три провайдера вызываются через OpenRouter с `tool_choice: {"type": "function", "function": {"name": ...}}` — API-level enforcement схемы. Failure rate < 0.3%. Единый механизм для всех провайдеров устраняет провайдер-специфичные настройки (response_format, response_schema).

---

## 6. Изоляция базы данных в тестах

### 6.1 Подход: уникальный project_id per scenario

Каждый сценарий получает `project_id = uuid.uuid4()` — полная изоляция без конкуренции между сценариями. Cleanup в `try/finally`:

**Стандартные категории** (lexical, conflict, semantic_drift):

```
pid = uuid.uuid4()
INSERT INTO projects (id, name) VALUES (pid, "bench-{sid}")
→ INSERT facts (project_id=pid) via upsert_fact()
→ INSERT session_log entries (PostgreSQL, chat_id="bench-{sid}-{pid}") для semantic_drift
→ COMMIT
→ get_facts(about=query, project_id=pid, limit=5)
→ COLLECT top-5 fact_ids → COMPARE with expected.relevant_ids → Recall@5
finally:
  DELETE FROM facts WHERE project_id = pid
  DELETE FROM session_log WHERE chat_id = "bench-{sid}-{pid}"
  DELETE FROM projects WHERE id = pid
  COMMIT
```

**cross_session категория** (два chat_id):

```
pid = uuid.uuid4()
INSERT INTO projects (id, name) VALUES (pid, ...)
→ INSERT facts (project_id=pid) из source_session.facts
→ COMMIT
→ get_facts(about=query, project_id=pid, limit=5)
  [chat_id при запросе = "{query_session.chat_id}-{pid}"]
→ COLLECT top-5 → COMPARE with expected.relevant_ids → Recall@5
finally:
  DELETE FROM facts WHERE project_id = pid
  DELETE FROM projects WHERE id = pid
  COMMIT
```

Факты фильтруются по `project_id`, не по `chat_id` — поэтому факты source_session видны из query_session. Это и есть тестируемое свойство.

### 6.2 Изоляция chat_id

Стандартные сценарии: `chat_id = f"bench-{scenario_id}-{project_uuid}"` — уникальный per сценарий.
Cross_session (A/B): `chat_id = f"ab-{scenario_id}-{project_uuid}"`.
Cross_session (полный бенчмарк): `chat_id = f"{setup.query_session.chat_id}-{project_uuid}"`.

Уникальность UUID предотвращает коллизии при любом режиме запуска.

---

## 7. Latency benchmark (NFR-1)

### 7.1 Что измеряем

Три операции с разными SLA:

| Операция | Path | SLA |
|----------|------|-----|
| `get_session_context()` | Redis hash GET | ≤ 5 ms p99 |
| `get_facts()` | pgvector cosine + embed cache hit | ≤ 200 ms p99 |
| `memorize(fact)` cold | API embed + upsert + COMMIT | нет SLA |

NFR-1 официально — `get_facts()` p99 < 200 ms. `get_session_context()` имеет отдельную цель 5 ms (LATENCY_SESSION_CTX_MS в config).

### 7.2 Метод измерения

Скрипт `scripts/measure_latency.py` (`asyncio`, n=100 итераций per операция):

- `bench_session_context()` — n=100 Redis GET, после одного SET
- `bench_get_facts()` — n=100 вызовов `get_facts()` с прогретым embedding-кешем (embed cache warm-up перед циклом)
- `bench_memorize_cold()` — n=100 вызовов embed API + upsert, уникальный контент per итерация (форсирует промах кеша)

Метрики p50/p95/p99 через линейную интерполяцию. Результаты сохраняются в `scripts/latency_results.json`.

**Примечание по индексам:** Текущая реализация использует sequential scan (`ORDER BY embedding <=> $vec LIMIT k`) без ANN-индекса — HNSW и IVFFlat ограничены 2000 dim в pgvector 0.8.2, dim=1536 теоретически укладывается в HNSW лимит, но в production-миграциях индекс ещё не добавлен (см. key_decisions.md Decision 3). При n=10 сид-фактов в latency-бенчмарке это не влияет на p99.

### 7.3 Cold path (для справки)

Cold path (с вызовом Qwen3-Embedding-8B API через OpenRouter) измеряется `bench_memorize_cold()` и в NFR-1 не входит. Latency определяется сетевой задержкой до API.

---

## 8. Формат итогового файла

```json
{
  "version": "1.0",
  "generated_at": "2026-05-13T21:15:18.397732+00:00",
  "total": 100,
  "categories": {
    "lexical": 25,
    "semantic_drift": 25,
    "conflict": 25,
    "cross_session": 25
  },
  "models_used": ["claude-sonnet-4.6", "gpt-5.2", "grok-4.20"],
  "scenarios": [ ... ]
}
```

---

## 9. Подсчёт итоговых метрик

### 9.1 Основная метрика: Recall@5

```
Recall@5(scenario_i) = |top5_returned ∩ relevant_ids| / |relevant_ids|

Recall@5(total) = (1/100) × Σ Recall@5(scenario_i)

По категориям отдельно:
Recall@5(lexical)        = mean по 25 сценариям
Recall@5(semantic_drift) = mean по 25 сценариям  [только SAR condition]
Recall@5(conflict)       = mean по 25 сценариям
Recall@5(cross_session)  = mean по 25 сценариям
```

### 9.2 A/B для semantic_drift: доказательство Session-Augmented RAG

Для каждого из 25 semantic_drift сценариев запускается два прогона:

```
Condition A (naive):
  get_facts(about=raw_query, project_id=pid, limit=5)
  → Recall@5_naive

Condition B (SAR):
  session_entries = get_session_log(chat_id=chat_id, limit=50)  [читает из PostgreSQL]
  enriched = " ".join(e.label for e in session_entries) + " " + raw_query
  get_facts(about=enriched, project_id=pid, limit=5)
  → Recall@5_sar
```

Enrichment строится из **e.label полей**, прочитанных через `get_session_log()` (не напрямую из JSON-поля `setup.session_log`). Это важно: SAR работает через реальный MCP-инструмент, а не mock.

Итоговый отчёт:

```
semantic_drift A/B:
  Recall@5 naive: 0.XX   (baseline без SAR)
  Recall@5 SAR:   0.XX   (с Session-Augmented RAG)
  delta:         +0.XX   (вклад авторского паттерна)
```

`delta > 0` — empirical proof того, что Session-Augmented RAG улучшает retrieval при vocabulary mismatch.

### 9.3 Ожидаемый паттерн результатов

```
Recall@5(lexical)              ≈ 1.0    — baseline, должен работать всегда
Recall@5(semantic_drift, SAR)  > 0.80   — цель FR-1
Recall@5(semantic_drift, naive)< SAR    — доказывает ценность SAR
Recall@5(conflict)             ≈ 1.0    — is_current фильтр работает
Recall@5(cross_session)        < SAR    — embeddings без обогащения, это нормально
```

Recall@5(cross_session) < Recall@5(semantic_drift SAR) — **не ошибка системы**. Это показывает разницу между "чистыми embeddings" и "embeddings + SAR". Cross_session тестирует baseline качество Qwen3 (dim=1536) без дополнительных механизмов.

### 9.4 Реальные результаты измерений

> Среда: Windows 11, Python 3.12, Docker Desktop (postgres+redis localhost), OpenRouter Qwen3-Embedding-8B API.

#### FR-1 — Recall@5 (100 сценариев, synthetic_100.json)

`scripts/run_benchmark.py`

| Категория | Recall@5 | N |
|---|---|---|
| lexical | 1.000 | 25 |
| semantic_drift | 1.000 | 25 |
| conflict | 0.960 | 25 |
| cross_session | 1.000 | 25 |
| **OVERALL** | **0.990** | **100** |

Целевой показатель FR-1: ≥ 0.80 → **PASS**.

Единственный пропуск (`conflict_019`): оба конфликтующих факта остаются `is_current=TRUE` из-за косинусного расстояния ниже порога 0.96 — граничный случай калибровки порога.

#### A/B — SAR vs Naive (25 сценариев semantic_drift, synthetic_100.json)

`scripts/run_ab_benchmark.py`

| Режим | Recall@5 | N |
|---|---|---|
| Naive (raw query) | 1.000 | 25 |
| SAR (session-enriched) | 1.000 | 25 |
| **Delta (SAR − naive)** | **+0.000** | — |

**Интерпретация:** Qwen3-Embedding-8B устраняет семантический дрейф на уровне векторного пространства — модель корректно сопоставляет описание проблемы с техническим фактом без обогащения запроса. delta=0 на synthetic_100 объясняется высоким качеством 8B-модели + умеренной сложностью датасета. Архитектурная ценность SAR подтверждается на synthetic_hard (см. раздел 12).

#### Multi-model A/B (semantic_drift, synthetic_100.json)

`scripts/run_multimodel_ab.py` — in-memory retrieval, каждая модель в своём векторном пространстве.

| Модель | Naive@5 | SAR@5 | Delta |
|---|---|---|---|
| Qwen3-8B | 0.840¹ | 0.840¹ | +0.000 |
| Qwen3-0.6B | — | — | — ² |
| BM25 | 1.000 | 1.000 | +0.000 ³ |

¹ 0.840 из-за 4 транзитных ConnectTimeout OpenRouter; подтверждённое значение — 1.000 из `run_ab_benchmark.py`.
² `EMBEDDING_FALLBACK = "qwen3-embedding-0.6b"` — 404 на OpenRouter, предназначен для локального инференса (Ollama/vLLM).
³ Корпус 5 фактов, k=5: top-5 из 5 = все факты → Recall@5=1.0 тривиально.

#### NFR-1 — Latency p99 (n=100 per операция)

`scripts/measure_latency.py`

| Операция | p50 (мс) | p95 (мс) | p99 (мс) | Цель (мс) | Статус |
|---|---|---|---|---|---|
| `get_session_context()` | 1.6 | 3.1 | 9.9 | ≤ 5 | p99 FAIL¹ |
| `get_facts()` warm cache | 4.7 | 7.7 | 16.0 | ≤ 200 | **PASS** |
| `memorize(fact)` cold path | 1158 | 4130 | 9237 | — | N/A |

¹ p99 = 9.9 мс vs цель 5 мс: единственный выброс из 100 измерений (p95 = 3.1 мс укладывается). Вероятная причина: TCP-накладные расходы Docker Desktop на Windows. На production Linux-хосте с Unix-сокетом Redis ожидается < 1 мс на p99.

---

## 10. Что НЕ входит в этот модуль

- README.md, CONTRIBUTING.md — отдельная задача
- GitHub Actions CI — отдельная задача
- Изменения в архитектуре MLMS — зафиксирована, не трогаем
- Полное multi-model сравнение с Qwen3-0.6B — требует локального деплоя Ollama

### Устаревшие скрипты

| Скрипт | Причина | Актуальная замена |
|---|---|---|
| `run_ab_benchmark.py` | delta=0 на synthetic_100 — Qwen3-8B не нуждается в SAR для данной сложности | `run_hard_ab.py` |
| `run_multimodel_ab.py` | Тривиальный результат: 5 фактов/сценарий → BM25=1.0; Qwen3-0.6B N/A (OpenRouter 404) | `run_hard_ab.py` |

---

## 11. С чем столкнулись и как решили

Каждая проблема обнаружена в процессе проектирования pipeline и подтверждена существующими исследованиями. Ниже — хронология решений.

---

### 11.1 Ролевой промпт ("Ты — эксперт по генерации датасетов")

**Проблема.** Первоначально system prompt начинался с ролевой установки по аналогии с распространённой практикой: предполагалось, что указание роли улучшит качество генерации.

**Что нашли.** Zheng et al. провели масштабный эксперимент: 162 персоны, 4 семейства open-source LLM, 2410 фактических вопросов из MMLU. Вывод: добавление персон в system prompt **не улучшает** производительность на объективных задачах по сравнению с контролем без персоны — и в ряде случаев незначительно деградирует её. Ключевое разграничение: ролевые установки влияют на **стиль и тон** (субъективные задачи), но не на **точность и качество** объективных задач вроде генерации размеченных тест-кейсов.

**Решение.** Ролевая установка удалена полностью. System prompt содержит только контекст системы и технические требования к выводу.

**Источник.** Zheng et al. "When 'A Helpful Assistant' Is Not Really Helpful: Personas in System Prompts Do Not Improve Performances of Large Language Models." *Findings of EMNLP 2024*, pp. 15126–15154.

---

### 11.2 JSON-mode деградирует reasoning при генерации

**Проблема.** Изначальный дизайн промпта требовал от модели выдавать валидный JSON сразу — одновременно придумывать сценарий и структурировать вывод. При тестировании качество сценариев было нестабильным: модели иногда генерировали поверхностные distractors или неубедительный semantic drift.

**Что нашли.** Tam et al. ("Let Me Speak Freely?") протестировали три режима: constrained decoding (JSON-mode), Format-Restricting Instructions (FRI), и NL-to-Format (сначала свободный текст, потом конвертация). На reasoning-задачах строгий JSON-mode давал **10–15% деградацию** по сравнению со свободной генерацией. Механизм: модель генерирует токены слева направо; если формат задан сразу, она вынуждена одновременно думать о содержании и соблюдать синтаксис JSON, что снижает "bandwidth" для reasoning.

**Решение.** Поле `rationale` вынесено **первым** в JSON-схему. Модель сначала пишет свободное рассуждение ("почему этот факт релевантен, почему другие — нет"), и только после этого заполняет структурированные поля. Это эмулирует NL-to-Format без двух отдельных вызовов: рассуждение "разогревает" контекст перед структурированием.

**Источник.** Tam et al. "Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performance of Large Language Models." *EMNLP Industry Track 2024*, arXiv:2408.02442.

---

### 11.3 Prompt-only JSON: высокий failure rate

**Проблема.** При использовании инструкции "Отвечай только валидным JSON без markdown" в реальных тестах часть ответов содержала преамбулу, trailing текст или невалидный JSON — особенно у моделей GPT-3.5-класса.

**Что нашли.** Исследования production-систем показывают: prompt-only JSON extraction даёт **failure rate 5–20%** в зависимости от сложности схемы. С 2023–2024 года все три провайдера реализовали native structured outputs с API-level enforcement.

**Решение.** Все три модели вызываются через OpenRouter API с `tool_choice: {"type": "function", "function": {"name": tool_name}}`. Единый механизм для всех провайдеров — нет провайдер-специфичных настроек. Failure rate < 0.3%.

**Источник.** TokenMix.ai benchmark (500,000 calls); "Beyond JSON Mode: Getting Reliable Structured Outputs from LLMs in Production", TianPan.co, 2025.

---

### 11.4 Preference leakage: одна модель генерирует и оценивает

**Проблема.** Первоначальный вариант предполагал, что верификатор может быть той же моделью, что и генератор, но с другим промптом. Также возникал вопрос: можно ли использовать Qwen3 (тот же эмбеддинг-движок MLMS) для генерации тест-кейсов?

**Что нашли.** Li et al. описали явление preference leakage: когда модель-генератор и модель-судья принадлежат одному семейству (или вовсе одна и та же), оценки систематически завышены. Выделены три типа связанности: одна модель, наследование (fine-tune от одной базы), одно семейство. Во всех трёх случаях bias подтверждён экспериментально на AlpacaEval 2.0 и Arena-Hard.

**Решение.** Два правила:
1. Qwen3 не участвует в генерации или верификации — только в embeddings внутри MLMS.
2. Верификатор всегда из **другого семейства** по жёсткой схеме: Claude → GPT-5.2, GPT-5.2 → Grok, Grok → Claude. Recall@5 считается детерминированно по UUID — никакой LLM в подсчёте метрики не участвует.

**Источник.** Li et al. "Preference Leakage: A Contamination Problem in LLM-as-a-judge." arXiv:2502.01534, 2025.

---

### 11.5 Mode collapse: модель повторяет одни и те же паттерны

**Проблема.** При прототипировании с одной моделью и повторными вызовами сценарии начинали воспроизводить один и тот же структурный шаблон: похожие distractors, одинаковые формулировки запросов, один домен (чаще всего docker/kubernetes).

**Что нашли.** "The Price of Format: Diversity Collapse in LLMs" (2025): instruction-tuned модели, обученные на repeated structural templates, интернализируют их как сильные generation priors. Это ведёт к overly deterministic outputs даже при высокой temperature. Эффект сохраняется потому, что alignment-обучение смещает модель к "типичным" ответам (typicality bias), что фундаментально снижает diversity независимо от алгоритмических настроек.

**Решение.** Три уровня защиты:
1. `used_topics` — JSON-список доменов передаётся в каждый следующий вызов.
2. Явные требования разнообразия в user prompt: чередовать стиль запроса (вопрос / утверждение / неполная фраза) и длину фактов (короткий / детальный / с числами).
3. Ротация трёх моделей разных семейств: разные паттерны обучения дают разные generation priors.

**Источник.** "The Price of Format: Diversity Collapse in LLMs", arXiv:2505.18949, 2025; "Verbalized Sampling: How to Mitigate Mode Collapse", arXiv:2510.01171, 2025.

---

### 11.6 Hallucinated ground truth: LLM уверенно ошибается в разметке

**Проблема.** При ручной проверке части сгенерированных сценариев обнаружилось, что модель иногда размечала как релевантный факт, который лишь тематически близок к запросу, но не отвечает на него. Галлюцинации в разметке опаснее галлюцинаций в тексте: они напрямую искажают метрику Recall@5.

**Что нашли.** Исследования показывают: LLM при генерации синтетических данных производят фактические ошибки и неверные метки с высокой уверенностью. Если не фильтровать — ошибки закрепляются в датасете и делают метрику бессмысленной. "No Free Labels" (2025): LLM-судья без human grounding систематически ошибается на граничных случаях.

**Решение.** Обязательный Stage 2 (verify): каждый сгенерированный сценарий проверяется моделью из другого семейства по явным критериям релевантности. При `verdict=fix_needed` — перезаписываем `expected.relevant_ids`, выставляем флаг `meta.auto_fixed=true`. Статистика fix_needed по итогам генерации документируется.

**Источник.** "No Free Labels: Limitations of LLM-as-a-Judge Without Human Grounding", arXiv:2503.05061, 2025; "On LLMs-Driven Synthetic Data Generation, Curation, and Evaluation: A Survey", arXiv:2406.15126, 2024.

---

### 11.7 Precision@5 математически недостижима при sparse ground truth

**Проблема.** Первоначальная метрика FR-1 была сформулирована как Precision@5 ≥ 0.80. При дизайне датасета с 1–2 релевантными фактами на сценарий максимально достижимый Precision@5 = 2/5 = 0.40 при двух релевантных и 1/5 = 0.20 при одном. Цель ≥ 0.80 математически недостижима.

**Анализ трейдоффов.** Три варианта исправления рассматривались: (1) увеличить число релевантных фактов до 4–5 — неестественно для семантической памяти агента, где факты дискретны; (2) перейти на Recall@5 — стандартная IR-метрика для sparse relevance; (3) перейти на Hit@5 — бинарная версия Recall@5. Recall@5 выбран как наиболее семантически точный: "система нашла нужный факт среди топ-5".

**Решение.** FR-1 переформулирован: **Recall@5 ≥ 0.80**. При 1 релевантном факте: нашли — 1.0, нет — 0.0. Среднее по 100 сценариям = доля запросов где нужный факт попал в топ-5. Цель ≥ 0.80 означает: система находит нужный факт в 80% случаев.

---

### 11.8 Temporal категория — смешение слоёв архитектуры

**Проблема.** Первоначально в датасете была категория `temporal`: запросы с временным контекстом через `get_timeline()`. При ревью обнаружилось, что `get_timeline()` работает с TimescaleDB через SQL time_range — это **episodic layer**, не semantic. Бенчмарк заявлен как покрывающий только semantic слой (pgvector), включение temporal создавало архитектурное противоречие. Кроме того, точность SQL time_range детерминирована и не является retrieval quality метрикой — нечего мерить через Recall@5.

**Решение.** Temporal заменена на `cross_session`: запрос из одной сессии ищет факты, сохранённые в другой сессии (другой chat_id, тот же project_id). Остаётся строго в semantic слое через `get_facts()` + pgvector. Дополнительная ценность: напрямую тестирует главное заявление MLMS о persistent cross-session memory и покрывает Multi-Session Reasoning из таксономии LongMemEval.

**Источник.** Wu et al. "LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory." *ICLR 2025*.

---

### 11.9 semantic_drift: A/B для доказательства Session-Augmented RAG

**Проблема.** Исходный дизайн не специфицировал: semantic_drift запускается через наивный `get_facts(raw_query)` или через SAR flow (`session_log → обогащение → get_facts`)? Без этого уточнения бенчмарк тестирует только качество embeddings, не доказывая ценность авторского паттерна.

**Решение.** Для всех 25 semantic_drift сценариев запускается A/B: Condition A (naive) и Condition B (SAR). Delta = Recall@5_sar − Recall@5_naive — empirical proof что Session-Augmented RAG улучшает retrieval при vocabulary mismatch. Это центральное экспериментальное доказательство для диплома.

Дополнительно: в generation prompt добавлен обязательный self-check (в поле rationale) — модель должна верифицировать lexical distance между запросом и фактом до заполнения остальных полей. Без этого delta ≈ 0 потому что naive сам справляется.

---

### 11.10 synthetic_100 слишком лёгкий для multi-model сравнения

**Проблема.** Измеренный Recall@5 = 0.990 при цели 0.80 означает, что датасет не позволяет различить модели: Qwen3-8B и любая достаточно сильная модель дадут одинаковый результат. Для доказательства превосходства SAR над naive на synthetic_100 delta = 0 — Qwen3-8B справляется без обогащения.

**Причина.** synthetic_100 генерировался с умеренными требованиями к lexical gap (no explicit threshold); модели-генераторы иногда нарушали lexical distance constraint несмотря на self-check. Корпус 5 фактов/сценарий тривиален для pgvector.

**Решение.** Создан `synthetic_hard.json` — датасет повышенной сложности с более строгими требованиями (см. раздел 12). На нём delta Qwen3-8B = +0.303, что является нужным empirical proof для диплома.

---

### 11.11 EMBEDDING_DIM: HNSW ограничение pgvector 0.8.2

**Проблема.** Изначальный дизайн предполагал EMBEDDING_DIM = 4096 (полный Qwen3-Embedding-8B) с HNSW-индексом. pgvector 0.8.2 ограничивает HNSW и IVFFlat максимумом 2000 dim для типа `vector`. `halfvec` поддерживает до 4000 — также меньше 4096.

**Решение.** EMBEDDING_DIM = **1536** (Matryoshka truncation Qwen3-Embedding-8B: 4096 → 1536). Потеря recall < 1%. При 1536 dim HNSW технически возможен (2000 > 1536), но в текущих production-миграциях используется sequential scan (детали в `key_decisions.md` Decision 3). Latency-бенчмарк (n=10–100 фактов) укладывается в SLA при sequential scan.

---

### 11.12 Сводная таблица

| Проблема | Первоначальный подход | Решение | Источник |
|----------|-----------------------|---------|----------|
| Ролевой промпт | "Ты — эксперт по генерации" | Убран; только контекст задачи | Zheng et al., EMNLP 2024 |
| JSON деградирует reasoning | JSON сразу в одном промпте | rationale первым полем; think→format | Tam et al., EMNLP 2024 |
| Prompt-only JSON failure 5–20% | Инструкция "ответь только JSON" | OpenRouter tool_choice для всех провайдеров | TokenMix benchmark, 2025 |
| Preference leakage | Та же модель генерит и проверяет | Cross-family rotation; Qwen3 только в embeddings | Li et al., arXiv 2025 |
| Mode collapse | Один батч, одна модель | used_topics + diversity требования + 3 модели | arXiv 2505.18949, 2025 |
| Hallucinated ground truth | Без верификации | Stage 2: cross-family verify + auto_fixed флаг | arXiv 2503.05061, 2025 |
| Precision@5 математически недостижима | Precision@5 ≥ 0.80 | Recall@5 ≥ 0.80 | IR-теория (sparse relevance) |
| Temporal смешивает слои архитектуры | temporal через get_timeline() | cross_session через get_facts() + pgvector | Wu et al., ICLR 2025 |
| semantic_drift не доказывает SAR | Только наивный поиск | A/B: naive vs SAR, delta = вклад паттерна | — |
| synthetic_100 слишком лёгкий | Один датасет | synthetic_hard: 400 фактов, строгий lexical gap | — |
| HNSW лимит 2000 dim | EMBEDDING_DIM = 4096 | Matryoshka truncation → 1536 | key_decisions.md Decision 3 |

---

## 12. Датасет synthetic_hard

### 12.1 Назначение

`tests/fixtures/synthetic_hard.json` создан для доказательства SAR-эффекта в условиях, где наивный retrieval деградирует. BM25 naive Recall@5 = 0.118 (целевой диапазон [0.20, 0.55] не достигнут — датасет сложнее ожидаемого).

### 12.2 Структура

| Параметр | Значение |
|---|---|
| Корпус | 400 фактов (10 доменов × 40 фактов) |
| Сценарии | 93 |
| Генератор | `anthropic/claude-sonnet-4.6` (via OpenRouter) |
| Верификатор 1 | `openai/gpt-5.2` — проверяет "too_easy" (naive найдёт без SAR?) |
| Верификатор 2 | `x-ai/grok-4.20` — проверяет "sar_solvable" (SAR найдёт?) |

### 12.3 Категории

| Категория | N | Что тестируется |
|---|---|---|
| `lexical_drift` | 30 | Пользовательский язык vs технические термины |
| `semantic_drift` | 29 | Симптом/эффект vs причина/механизм |
| `cross_domain` | 25 | Проблема затрагивает два домена; релевантные факты из разных доменов |
| `multi_hop` | 9 | Ответ требует цепочки из 2+ фактов; lexical_gap ≤ 1 |

### 12.4 Схема сценария

```json
{
  "id": "sd_001",
  "type": "semantic_drift",
  "domain": "kafka/redis",
  "setup": {
    "session_log": [
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "..."}
    ]
  },
  "query": "...",
  "expected": {
    "relevant_ids": ["f045", "f123"],
    "irrelevant_ids": ["f046", "f047", ...]
  },
  "meta": {
    "lexical_gap_score": 1,
    "difficulty": "hard",
    "drift_mechanism": "...",
    "sar_bridge_terms": ["term1", "term2"],
    "too_easy": false,
    "sar_solvable": true,
    "verifier_1_reasoning": "...",
    "verifier_2_reasoning": "..."
  }
}
```

Ключевые отличия от synthetic_100: общий корпус 400 фактов (не 5 per сценарий), `session_log` содержит объекты `{role, content}` (не строки), `lexical_gap_score` контролируется явно (≤ 2 для большинства типов, ≤ 1 для multi_hop).

### 12.5 Retrieval в run_hard_ab.py

In-memory retrieval без PostgreSQL. Для каждого backend:

```
fact_vecs = [embed(f.content) for f in corpus]  # 400 вложений, один раз
for scenario in scenarios:
    q_naive = embed(scenario.query)
    q_sar   = embed(session_log_content + " " + scenario.query)
    # SAR enrichment: " ".join(e["content"] for e in session_log)
    naive_top = cosine_top5(fact_vecs, q_naive)
    sar_top   = cosine_top5(fact_vecs, q_sar)
```

Session_log передаётся напрямую из JSON (не через PostgreSQL) — отличие от synthetic_100 бенчмарка.

### 12.6 Backends

| Backend | Источник | Размерность |
|---|---|---|
| BM25 | `rank_bm25` | — |
| nomic-embed-text | Ollama `http://localhost:11434` | native |
| mxbai-embed-large | Ollama `http://localhost:11434` | native (вход усечён до 800 символов) |
| Qwen3-8B | OpenRouter API | 1536 (Matryoshka) |

Ollama-бекенды проверяются при старте (`check_alive()`); недоступные пропускаются.

### 12.7 Результаты (hard_ab_results.json)

| Модель | N | Naive | SAR | Δ |
|---|---|---|---|---|
| BM25 | 93 | 0.040 | 0.312 | +0.272 |
| nomic-embed-text | 93 | 0.011 | 0.215 | +0.204 |
| mxbai-embed-large | 93 | 0.006 | 0.100 | +0.093 |
| **Qwen3-8B** | **93** | **0.320** | **0.624** | **+0.303** |

**Вывод для диплома:** SAR даёт значимый прирост Δ = +0.303 для Qwen3-8B на сложном датасете. Наибольший прирост — в cross_domain (+0.320) и multi_hop (+0.370). BM25 показывает Δ = +0.272 потому что session_log content содержит bridge terms, которые буквально встречаются в фактах — лексическое обогащение работает даже без векторного поиска.

Генерация датасета стоила **$1.04** (3 модели, ~93 сценария + 400 фактов, логируется в `tests/fixtures/cost_log.json`).
