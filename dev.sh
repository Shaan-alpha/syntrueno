#!/usr/bin/env bash
# Syntrueno - Concurrent Local Development Runner

echo "======================================================="
echo "⚡ Starting Syntrueno (ThorForja) Full-Stack Development"
echo "======================================================="

# Trap cleanup on exit
trap 'kill $(jobs -p)' EXIT

# Start Backend
(cd backend && .venv/Scripts/uvicorn app.main:app --reload --port 8000) &

# Start Frontend
(cd frontend && npm run dev) &

wait
