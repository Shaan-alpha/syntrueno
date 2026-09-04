#!/usr/bin/env bash
# Syntrueno - Concurrent Local Development Runner

echo "======================================================="
echo "⚡ Starting Syntrueno (ThorForja) Full-Stack Development"
echo "======================================================="

# Trap cleanup on exit
trap 'kill $(jobs -p)' EXIT

# Start Backend
# Windows venvs put entrypoints in Scripts/, POSIX venvs in bin/.
VENV_BIN=$([ -d backend/.venv/bin ] && echo bin || echo Scripts)
(cd backend && ".venv/$VENV_BIN/uvicorn" app.main:app --reload --port 8000) &

# Start Frontend
(cd frontend && npm run dev) &

wait
