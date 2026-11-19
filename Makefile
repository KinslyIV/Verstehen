.PHONY: setup check check-backend check-frontend test fmt lock-migrations dev verify verify-run app app-image

setup:
	uv sync --project backend --locked
	npm ci --prefix app
	cd app && npx playwright install chromium

check:
	$(MAKE) check-backend
	$(MAKE) check-frontend

check-backend:
	uv run --project backend ruff check .
	uv run --project backend ruff format --check .
	uv run --project backend pyrefly check --config pyrefly.toml
	cd backend && uv run lint-imports
	uv run --project backend python tools/check_comments.py
	uv run --project backend python tools/check_migrations.py
	uv run --project backend python tools/check_versions.py
	uv run --project backend pytest -c backend/pyproject.toml

check-frontend:
	npm run check --prefix app
	cd app && npx eslint .
	cd app && npx prettier --check .
	npm run test --prefix app

test:
	uv run --project backend pytest -c backend/pyproject.toml
	npm run test --prefix app

fmt:
	uv run --project backend ruff check --fix .
	uv run --project backend ruff format .
	cd app && npx prettier --write .

lock-migrations:
	uv run --project backend python tools/check_migrations.py --lock

dev:
	uv run --project backend python tools/dev.py

verify:
	uv run --project backend python tools/verify_build.py build
	cd app && npx playwright test $(FLOW)

verify-run:
	uv run --project backend python tools/verify_build.py check
	cd app && npx playwright test $(FLOW)

app:
	bash packaging/build.sh

app-image:
	docker build --pull --no-cache --tag verstehen-build - < packaging/Dockerfile
