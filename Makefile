.PHONY: setup test lint fmt dev-api dev-web check

setup:
	uv sync
	cd apps/web && pnpm install

test:
	uv run pytest
	cd apps/web && pnpm test

lint:
	uv run ruff check .
	uv run ruff format --check .
	cd apps/web && pnpm lint && pnpm typecheck

fmt:
	uv run ruff check --fix .
	uv run ruff format .

dev-api:
	uv run nr serve --reload

dev-web:
	cd apps/web && pnpm dev

check: lint test
