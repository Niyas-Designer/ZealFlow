#!/bin/bash
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "🔧 Setting up ZealFlow..."

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

cd "$ROOT/frontend"
npm install

echo ""
echo "✅ PROJECT SETUP COMPLETE"
echo "▶️  Run: ./START_PROJECT.sh"
