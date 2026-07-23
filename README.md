# AI-Nutriologist

[![CI](https://github.com/Andrew82mm/AI-Nutriologist/actions/workflows/ci.yml/badge.svg)](https://github.com/Andrew82mm/AI-Nutriologist/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![Tests](https://img.shields.io/badge/tests-37%20passing-brightgreen)
![Status](https://img.shields.io/badge/status-в%20разработке-yellow)

Пет-проект: ИИ-агент, который следит за питанием — знает, что есть дома, а что уже съедено, считает БЖУ и помогает планировать покупки и меню.

## Содержание

- [Что уже реализовано](#что-уже-реализовано)
- [Хранение данных](#хранение-данных)
- [LLM — любой провайдер, без хардкода](#llm--любой-провайдер-без-хардкода)
- [Как запустить](#как-запустить)
- [CI/CD](#cicd)
- [Структура](#структура)
- [Дальше по плану](#дальше-по-плану)

## Что уже реализовано

**Парсинг кассовых чеков** — превращаем PDF чека (пересланное письмо от ОФД) в структурированные данные: магазин, дата, ФД/ФПД, список позиций (название, количество, цена, сумма, НДС, единица измерения).

Два независимых пути парсинга:

1. **Детерминированный парсер** (`nutriologist.receipts.ofdru`) — для чеков от OFD.RU (проверено на Лента и О'КЕЙ). Работает на регулярках без обращения к сети, бесплатно и стабильно. Автоматически определяет, что чек этого формата, по маркеру `check.ofd.ru` в тексте.
2. **LLM-fallback** (`nutriologist.receipts.llm_fallback`) — если формат чека не распознан детерминированным парсером (другой ОФД, другая страна, другая вёрстка), тот же текст отдаётся LLM со строгой JSON-схемой на выходе.

Диспетчер (`nutriologist.receipts.parse.parse_receipt_pdf`) сам решает, каким путём идти: сначала пробует детерминированный парсер, и только если он не подошёл — использует LLM (если она передана).

## Хранение данных

Всё хранится локально в SQLite (`data/nutriologist.db`, вне репозитория — см. `.gitignore`).

- **`nutriologist.db`** — подключение и схема (`get_connection()`, `schema.sql`). Простая миграционная стратегия: версия схемы в таблице `schema_version`, миграции — пронумерованные `.sql`-файлы в `db/migrations/`.
- **`nutriologist.receipts.storage.save_receipt()`** — сохраняет разобранный чек в `receipts`/`receipt_items` с дедупликацией по паре `(fd_number, fpd)`: повторный импорт одного и того же чека не создаёт вторую запись. Чек без этих полей (LLM не смогла их извлечь) сохраняется без проверки дублей.

## LLM — любой провайдер, без хардкода

Код нигде не завязан на конкретного вендора LLM. Есть только абстракция — протокол `StructuredLLMClient` (`nutriologist.llm.client`) с одним методом `generate_json(system, user, json_schema) -> dict`. У неё два адаптера:

- `anthropic_client.py` — нативный Claude API;
- `openai_compatible_client.py` — любой сервис с OpenAI-совместимым Chat Completions API (сам OpenAI, Google Gemini через их openai-compat эндпоинт, Mistral, локальные модели через Ollama/vLLM и т.д.).

Какой провайдер использовать — решает **только конфигурация**, не код. Настройка через `.env` (шаблон — `.env.example`):

```
LLM_PROVIDER=anthropic        # или openai_compatible
LLM_API_KEY=...
LLM_MODEL=claude-fable-5
LLM_BASE_URL=                 # только для openai_compatible — эндпоинт провайдера
```

Оба SDK (`anthropic`, `openai`) — опциональные зависимости, ставятся отдельно (`pip install -e ".[llm-anthropic]"` или `".[llm-openai-compatible]"`), базовый пакет работает без них.

## Как запустить

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# тесты
.venv/bin/pytest

# ручной прогон парсера на PDF (без LLM — только детерминированный парсер)
.venv/bin/python -m nutriologist.receipts.cli path/to/receipt.pdf

# то же самое, но с LLM-fallback для нераспознанных чеков
cp .env.example .env   # заполнить LLM_PROVIDER / LLM_API_KEY / LLM_MODEL
.venv/bin/python -m nutriologist.receipts.cli --llm path/to/receipt.pdf
```

Для работы с PDF нужен `pdftotext` (пакет `poppler-utils`): `sudo apt install poppler-utils`.

## Веб-интерфейс

Веб-приложение состоит из двух частей, которые в разработке запускаются как два
процесса:

**1. HTTP-API (FastAPI) поверх ядра `nutriologist`** — модуль `nutriologist.api`.
Это тонкий адаптер: каждый эндпоинт открывает соединение с БД и вызывает
существующие доменные модули (`inventory`, `products`, ...).

```bash
.venv/bin/pip install -e ".[api]"     # fastapi + uvicorn
.venv/bin/python -m nutriologist.api    # http://127.0.0.1:8000
```

Порт/хост — через переменные окружения (`NUTRIOLOGIST_API_PORT`,
`NUTRIOLOGIST_API_HOST`, `NUTRIOLOGIST_API_RELOAD=1` для автоперезагрузки).

Эндпоинты:

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/api/health` | health-check |
| GET | `/api/inventory` | холодильник (остатки из ledger) |
| POST | `/api/inventory` | добавить купленное (приход в ledger) |
| GET | `/api/diary/today` | приёмы пищи за сегодня + БЖУ + цель |
| POST | `/api/meals` | записать съеденное |
| GET/PUT | `/api/profile` | цели, ограничения, метрики тела |
| POST | `/api/chat` | разбор фразы («съел…», «купил…», «отчёт») |

**2. Фронтенд (Vite + React)** — в `web/app/`. Переиспользует дизайн-систему
Organic из `web/_ds/`. В дев-режиме `/api` проксируется на бэкенд (см.
`web/app/vite.config.js`).

```bash
cd web/app
npm install
npm run dev        # http://localhost:5173
```

Прототип-эталон дизайна (экспорт из дизайн-инструмента) лежит рядом —
`web/Трекер питания.dc.html`; фронт в `web/app/` собран по нему заново.

Экран «План» пока показывает демо-данные: движка планирования меню на бэкенде
ещё нет (см. [Дальше по плану](#дальше-по-плану)).

## Бенчмарки качества пайплайна

Метрики для DA-нарратива «из сырых чеков → чистые данные»: сколько пайплайн делает
бесплатными правилами до платного LLM (покрытие), насколько корректно парсит чеки
(сходимость Σ позиций с печатным ИТОГ) и почему доверяет справочнику БЖУ больше, чем
LLM (ошибка оценки против Скурихина). Витрина — [`benchmarks/REPORT.md`](benchmarks/REPORT.md),
как запускать и что меряется — [`benchmarks/README.md`](benchmarks/README.md).

```bash
python -m benchmarks.run_all   # пересобрать витрину (#3 — из кэша, без обращения к LLM)
```

## CI/CD

На каждый push и pull request в `main` GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)) прогоняет тесты на Python 3.12 и 3.13:

1. Устанавливает `poppler-utils` (для `pdftotext`).
2. Ставит пакет в editable-режиме с dev-зависимостями (`pip install -e ".[dev]"`).
3. Запускает `pytest`.

Тесты не зависят от реальных чеков или сети — все фикстуры синтетические (`tests/receipt_fixtures.py`), а обращения к LLM в тестах подменены фейковым клиентом (`FakeLLMClient`), поэтому пайплайн детерминированный и не требует секретов.

## Структура

```
src/nutriologist/
  receipts/
    models.py         # ReceiptItem, ParsedReceipt
    pdf_text.py        # извлечение текста из PDF (pdftotext)
    ofdru.py           # детерминированный парсер формата OFD.RU
    llm_fallback.py    # LLM-парсер для незнакомых форматов
    parse.py           # диспетчер: детерминированный парсер → LLM-fallback → ошибка
    storage.py         # save_receipt() — сохранение в SQLite с дедупликацией
    cli.py             # ручной прогон парсера на файлах
  llm/
    client.py          # Protocol StructuredLLMClient — единая точка расширения
    anthropic_client.py
    openai_compatible_client.py
    config.py          # сборка клиента из переменных окружения / .env
  db/
    connection.py       # get_connection(), применение схемы и миграций
    schema.sql           # DDL всех таблиц
  api/                  # HTTP-слой (FastAPI) поверх ядра — см. «Веб-интерфейс»
    app.py               # фабрика приложения, CORS, соединение на запрос
    inventory.py / diary.py / profile.py / actions.py  # роутеры
    foods.py             # rule-based разбор фраз для /api/chat
web/
  app/                  # фронтенд Vite + React (экраны + слой api.js)
  _ds/                  # дизайн-система Organic (общие стили/токены)
  Трекер питания.dc.html # прототип-эталон дизайна
tests/                  # тесты на синтетических фикстурах + фейковом LLM-клиенте
.github/workflows/ci.yml # тесты на Python 3.12/3.13 при каждом push и PR
```

## Дальше по плану

Нормализация названий продуктов и БЖУ-резолвер, инвентарь остатков дома, Telegram-бот для лога питания, планировщик меню. Подробности — в `PLAN.md`.
