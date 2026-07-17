# AI-Nutriologist

Пет-проект: ИИ-агент, который следит за питанием — знает, что есть дома, а что уже съедено, считает БЖУ и помогает планировать покупки и меню. 

## Что уже реализовано

**Парсинг кассовых чеков** — превращаем PDF чека (пересланное письмо от ОФД) в структурированные данные: магазин, дата, ФД/ФПД, список позиций (название, количество, цена, сумма, НДС, единица измерения).

Два независимых пути парсинга:

1. **Детерминированный парсер** (`nutriologist.receipts.ofdru`) — для чеков от OFD.RU (проверено на Лента и О'КЕЙ). Работает на регулярках без обращения к сети, бесплатно и стабильно. Автоматически определяет, что чек этого формата, по маркеру `check.ofd.ru` в тексте.
2. **LLM-fallback** (`nutriologist.receipts.llm_fallback`) — если формат чека не распознан детерминированным парсером (другой ОФД, другая страна, другая вёрстка), тот же текст отдаётся LLM со строгой JSON-схемой на выходе.

Диспетчер (`nutriologist.receipts.parse.parse_receipt_pdf`) сам решает, каким путём идти: сначала пробует детерминированный парсер, и только если он не подошёл — использует LLM (если она передана).

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

## Структура

```
src/nutriologist/
  receipts/
    models.py        # ReceiptItem, ParsedReceipt
    pdf_text.py       # извлечение текста из PDF (pdftotext)
    ofdru.py          # детерминированный парсер формата OFD.RU
    llm_fallback.py   # LLM-парсер для незнакомых форматов
    parse.py          # диспетчер: детерминированный парсер → LLM-fallback → ошибка
    cli.py            # ручной прогон парсера на файлах
  llm/
    client.py         # Protocol StructuredLLMClient — единая точка расширения
    anthropic_client.py
    openai_compatible_client.py
    config.py         # сборка клиента из переменных окружения / .env
tests/                # 29 тестов на реальных образцах чеков + фейковом LLM-клиенте
```

## Дальше по плану

Дедупликация чеков по ФД/ФПД, нормализация названий продуктов, схема SQLite, Telegram-бот для лога питания. Подробности — в `PLAN.md`.
