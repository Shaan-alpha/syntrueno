@echo off
echo =======================================================
echo ⚡ Starting Syntrueno (ThorForja) Full-Stack Development
echo =======================================================
echo.
start "Syntrueno Backend (FastAPI)" cmd /k "cd backend && .venv\Scripts\uvicorn app.main:app --reload --port 8000"
start "Syntrueno Frontend (Vite UI)" cmd /k "cd frontend && npm run dev"
echo.
echo ✅ Servers launching in separate windows:
echo - Backend API:  http://localhost:8000 (Swagger: http://localhost:8000/docs)
echo - Frontend UI:  http://localhost:5173
echo.
