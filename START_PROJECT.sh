#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -d ".venv" ]; then
  echo "❌ .venv not found. Run ./SETUP_PROJECT.sh first."
  exit 1
fi
if [ ! -f ".env" ]; then
  cp .env.example .env
fi
if [ ! -d "frontend/node_modules" ]; then
  echo "❌ frontend dependencies not found. Run ./SETUP_PROJECT.sh first."
  exit 1
fi

if lsof -iTCP:8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "❌ Port 8000 is already in use. Stop the old backend first, then run this again."
  exit 1
fi

source .venv/bin/activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 > "$ROOT/backend.log" 2>&1 &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

sleep 2
if ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
  echo "❌ Backend failed to start. Check backend.log"
  cat "$ROOT/backend.log" || true
  exit 1
fi

echo "✅ Backend running: http://127.0.0.1:8000"
echo "🚀 Starting frontend..."
echo "🌐 Open the Local URL shown below in Chrome."
cd "$ROOT/frontend"
npm run dev
