.PHONY: research-eval decision-eval memory-lifecycle-eval memory-eval context-eval backend-test backend-lint backend-build frontend-test frontend-lint frontend-typecheck frontend-build run-backend run-frontend
.DEFAULT_GOAL := backend-test

backend-build:

	cd backend && uv build --no-build-isolation

frontend-build:

	cd frontend && pnpm run build

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

context-eval:

	cd backend && python -m personal_ai.evaluation.context

memory-eval:

	cd backend && python -m personal_ai.evaluation.memory

memory-lifecycle-eval:

	cd backend && python -m personal_ai.evaluation.memory_lifecycle

research-eval:

	cd backend && python -m personal_ai.evaluation.research

decision-eval:

	cd backend && python -m personal_ai.evaluation.decision
