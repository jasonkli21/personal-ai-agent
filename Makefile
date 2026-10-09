.PHONY: research-eval decision-eval domain-eval iterative-research-eval itinerary-proposal-eval quota-scarcity-eval memory-lifecycle-eval memory-eval context-eval context-plan-eval backend-test backend-lint backend-build frontend-test frontend-lint frontend-typecheck frontend-build run-backend run-frontend persistence-up persistence-down persistence-ready persistence-bootstrap persistence-clean persistence-test-up persistence-test-down persistence-test
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

context-plan-eval:

	cd backend && python -m personal_ai.evaluation.context_planner

memory-eval:

	cd backend && python -m personal_ai.evaluation.memory

memory-lifecycle-eval:

	cd backend && python -m personal_ai.evaluation.memory_lifecycle

research-eval:

	cd backend && python -m personal_ai.evaluation.research

decision-eval:

	cd backend && python -m personal_ai.evaluation.decision

domain-eval:
	cd backend && python -m personal_ai.evaluation.domain

iterative-research-eval:
	cd backend && python -m personal_ai.evaluation.iterative_research

itinerary-proposal-eval:
	cd backend && python -m personal_ai.evaluation.itinerary_proposals

quota-scarcity-eval:
	cd backend && python -m personal_ai.evaluation.quota_scarcity

persistence-up:
	docker compose -f docker-compose.persistence.yml up -d --wait postgres dynamodb-local

persistence-down:
	docker compose -f docker-compose.persistence.yml down

persistence-ready:
	cd backend && PERSISTENCE_POSTGRES_DSN='postgresql://personal_ai:personal_ai_local_only@127.0.0.1:54329/personal_ai' DYNAMODB_LOCAL_ENDPOINT='http://127.0.0.1:8000' AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1 python -m personal_ai.persistence.local_stack ready

persistence-bootstrap:
	cd backend && PERSISTENCE_POSTGRES_DSN='postgresql://personal_ai:personal_ai_local_only@127.0.0.1:54329/personal_ai' DYNAMODB_LOCAL_ENDPOINT='http://127.0.0.1:8000' AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1 python -m personal_ai.persistence.local_stack bootstrap

persistence-clean:
	docker compose -f docker-compose.persistence.yml down -v

persistence-test-up:
	docker compose -f docker-compose.persistence.yml --profile integration up -d --wait postgres-test dynamodb-local-test

persistence-test-down:
	docker compose -f docker-compose.persistence.yml --profile integration stop postgres-test dynamodb-local-test
	docker compose -f docker-compose.persistence.yml --profile integration rm -f postgres-test dynamodb-local-test

persistence-test:
	cd backend && PERSISTENCE_TEST_POSTGRES_DSN='postgresql://personal_ai:personal_ai_test_only@127.0.0.1:54330/personal_ai_test' PERSISTENCE_TEST_DYNAMODB_ENDPOINT='http://127.0.0.1:8001' AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1 python -m pytest -m persistence_integration tests/persistence
