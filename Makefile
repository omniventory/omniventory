# Omniventory · Makefile
# Thin aliases so humans and CI call the same commands.
# All targets delegate to the toolchain inside backend/ or frontend/.

.PHONY: check lint test codegen

# Run all quality gates (lint + type-check + tests on both sides)
check: lint test

# Lint + type-check both sides
lint:
	@echo "==> Backend: ruff check"
	cd backend && uv run ruff check .
	@echo "==> Backend: ruff format --check"
	cd backend && uv run ruff format --check .
	@echo "==> Backend: mypy"
	cd backend && uv run mypy app
	@echo "==> Frontend: eslint"
	cd frontend && pnpm lint
	@echo "==> Frontend: tsc"
	cd frontend && pnpm typecheck

# Run tests on both sides
test:
	@echo "==> Backend: pytest"
	cd backend && uv run pytest
	@echo "==> Frontend: vitest"
	cd frontend && pnpm test

# Contract-first codegen: OpenAPI → TS types
# Stub until Step 5 wires up the full flow (requires the backend app + endpoints).
codegen:
	@echo "codegen: stub — will be implemented in Step 5"
