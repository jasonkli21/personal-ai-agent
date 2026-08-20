.PHONY: backend-test backend-lint frontend-test frontend-lint frontend-typecheck run-backend run-frontend

backend-test:

	cd backend && python -m pytest

backend-lint:

	cd backend && python -m ruff check .

frontend-test:

	cd frontend && pnpm run test

frontend-lint:

	cd frontend && pnpm run lint

frontend-typecheck:

	cd frontend && pnpm run typecheck

run-backend:

	cd backend && python -m uvicorn personal_ai.main:app --reload --port 8000

run-frontend:

	cd frontend && pnpm run dev
