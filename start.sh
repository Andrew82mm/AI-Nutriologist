#!/usr/bin/env bash
# Поднимает бэкенд (FastAPI, :8000) и фронт (Vite, :5173) одной командой.
# Остановить оба — Ctrl+C.
set -e
cd "$(dirname "$0")"

API_PORT="${NUTRIOLOGIST_API_PORT:-8000}"

# venv с зависимостями API
if [ ! -x .venv/bin/python ]; then
  echo "Нет .venv — создаю и ставлю зависимости…"
  python3 -m venv .venv
  .venv/bin/pip install -e ".[api]"
fi

# зависимости фронта
if [ ! -d web/app/node_modules ]; then
  echo "Ставлю зависимости фронта…"
  (cd web/app && npm install)
fi

# Освобождаем порты от прошлых запусков. Без этого новый бэкенд не займёт порт,
# а старый процесс продолжит отдавать устаревший код/конфиг (например, старую
# LLM_MODEL из .env, прочитанную при его запуске) — типичная причина «перезапустил,
# а поведение не поменялось».
for P in "$API_PORT" 5173; do
  fuser -k "${P}/tcp" 2>/dev/null || true
done
sleep 1

# при выходе гасим оба процесса
cleanup() { kill "$API_PID" "$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "Бэкенд → http://127.0.0.1:${API_PORT}"
NUTRIOLOGIST_API_PORT="$API_PORT" .venv/bin/python -m nutriologist.api &
API_PID=$!

echo "Фронт  → http://localhost:5173"
(cd web/app && npm run dev) &
WEB_PID=$!

wait
