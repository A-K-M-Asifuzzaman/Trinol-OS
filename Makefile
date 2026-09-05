.PHONY: help dev test lint check migrate seed openapi

help:
	@echo "make dev       - start postgres+api+web via docker compose"
	@echo "make test      - run backend and frontend test suites"
	@echo "make lint      - ruff + eslint + prettier --check"
	@echo "make check     - full local gate list (lint, typecheck, tests, build)"
	@echo "make migrate   - run Alembic migrations to head (trinol_migrator)"
	@echo "make seed      - seed the local database"
	@echo "make openapi   - regenerate apps/web/lib/api/types.gen.ts from the API schema"

dev:
	docker compose up

test:
	cd apps/api && uv run pytest
	cd apps/web && pnpm test

lint:
	cd apps/api && uv run ruff check . && uv run ruff format --check .
	cd apps/web && pnpm lint && pnpm exec prettier --check .

check: lint
	cd apps/api && uv run mypy src
	cd apps/api && uv run pytest
	cd apps/web && pnpm typecheck
	cd apps/web && pnpm test
	cd apps/web && pnpm build
	$(MAKE) openapi
	git diff --exit-code apps/web/lib/api/types.gen.ts

migrate:
	cd apps/api && uv run alembic upgrade head

seed:
	cd apps/api && uv run python -m trinol.scripts.seed

openapi:
	cd apps/api && uv run python -c "import json, trinol.main as m; json.dump(m.app.openapi(), open('openapi.json', 'w'))"
	cd apps/web && pnpm generate:types
