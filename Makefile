.PHONY: test test-backend build-frontend run-backend run-frontend

test:
	cd backend && .venv\Scripts\pytest -v

test-backend:
	cd backend && .venv\Scripts\pytest -v

build-frontend:
	cd frontend && npm run build

run-backend:
	cd backend && .venv\Scripts\uvicorn app.main:app --reload --port 8000

run-frontend:
	cd frontend && npm run dev
