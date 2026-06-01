# 🍒 ДЕМО — Cherry Studio + MLMS MCP
## Замена Claude Desktop | Не нужен аккаунт | Простая настройка

---

## ПОЧЕМУ Cherry Studio (не Claude Desktop)

| | Claude Desktop | Cherry Studio |
|--|--|--|
| Нужен аккаунт Claude | Да (основной = плохо для демо) | Нет — только API-ключ |
| Чистая история | Сложно (memories) | Всегда — новый чат = чистый |
| MCP поддержка | ✅ | ✅ |
| Настройка | JSON-файл вручную | GUI, 3 клика |
| Видимость вызовов | ✅ | ✅ |

---

## ШАГ 1: Установка Cherry Studio

```
1. Идти на: https://cherry-ai.com
2. Download → Windows → скачать .exe (~200MB)
3. Установить, запустить
```

---

## ШАГ 2: Настройка API-провайдера

```
Settings (шестерёнка) → Model Providers → Add Provider
  Provider: Anthropic
  API Key: [твой ключ Anthropic]
  Model: claude-sonnet-4-6   ← лучший tool calling

  ИЛИ используй DeepSeek/любой с tool calling если нет ключа Anthropic
```

---

## ШАГ 3: Запустить базы данных

```bash
cd C:\путь\к\mlms
docker compose up -d

# Проверить:
docker compose ps
# Должно быть: postgres и redis — Status = running
```

> ℹ️ docker-compose поднимает только PostgreSQL (5432) и Redis (6379).
> MCP-сервер запускает Cherry Studio сам как stdio-процесс — HTTP-порт не нужен.

---

## ШАГ 4: Подключить MLMS как MCP-сервер

```
Settings → MCP Servers → + Add Server

  Name: MLMS
  Type: stdio
  Command: uv
  Args: run python -m mlms.server
  Working Dir: C:\полный\путь\к\mlms   ← вставить реальный путь!
  
  Пример Working Dir: C:\Users\eb\Documents\Repos\mlms

→ Save → включить тоггл рядом с MLMS
→ Нажать на MLMS → увидеть список инструментов (memorize, get_facts, и т.д.) ✅
```

---

## ШАГ 5: Запись демо-видео

### Инструмент записи:
- Windows: **Win + G** (Xbox Game Bar) → записать окно
- Или OBS, или любой screen recorder

### Что записывать:

**[0:00–0:30] Сцена 1: Старт системы**
```bash
# Терминал (показать крупно):
docker compose ps
# Должно быть: все сервисы Status = running
```

**[0:30–1:10] Сцена 2: Запись в память**
```
Открой Cherry Studio → новый чат → убедись что MLMS активен (🔧 иконка)

Напечатай:
"Запомни: я работаю над дипломным проектом MLMS — это система
долговременной памяти для AI-агентов на основе протокола MCP.
Стек: Python, FastAPI, PostgreSQL с pgvector, TimescaleDB, Redis.
Тестирование завершено — Recall@5 = 83%, все тесты пройдены."

→ Cherry Studio показывает: "Using MLMS: memorize..." → JSON параметры
→ Ответ: "Информация сохранена в долговременную память"
```

**[1:10–2:00] Сцена 3: КУЛЬМИНАЦИЯ — новый чат**
```
!!! Это главный момент — сделай паузу, покажи мышью что создаёшь НОВЫЙ чат !!!

Нажать: + Новый чат (история ПУСТАЯ — показать)

Напечатай:
"Расскажи о проекте, над которым я работаю."

→ Cherry Studio: "Using MLMS: get_facts..."
→ AI рассказывает об MLMS — хотя в этом чате ни слова не было!

[ПАУЗА 3 секунды — дай зрителю осознать эффект]

Напечатай:
"Что происходило с проектом в мае 2026?"

→ Cherry Studio: "Using MLMS: get_timeline..."
→ AI возвращает событие тестирования из памяти
```

**[2:00–2:20] Сцена 4: Тесты**
```bash
# Терминал:
uv run pytest tests/unit -v
# → финальная строка: "213 passed in Ys"
```

**СТОП — видео готово.**

---

## Что говорить на защите если спросят про видео

> «Для демонстрации подготовлена видеозапись работы системы, поскольку она требует
> специализированного серверного окружения: PostgreSQL с расширением pgvector,
> TimescaleDB, Redis и MCP-сервер — четыре сервиса одновременно.
> При необходимости готов запустить систему прямо сейчас.»

---

## Запасной план (если Cherry Studio не успеваешь настроить)

Используй уже готовый Claude Desktop, но:
1. Создай новую беседу (новый chat — НЕ та же)
2. Убедись что MLMS в конфиге
3. Для демо "новой сессии" — просто покажи что начинаешь новый чат

Конфиг для Claude Desktop (файл `%APPDATA%\Claude\claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "mlms": {
      "command": "uv",
      "args": ["run", "python", "-m", "mlms.server"],
      "cwd": "C:\\Users\\eb\\Documents\\Repos\\mlms"
    }
  }
}
```
