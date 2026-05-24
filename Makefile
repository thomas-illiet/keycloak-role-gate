VALIDATION_DIR ?= validation
COMPOSE_FILE ?= $(VALIDATION_DIR)/docker-compose.yml
KEYCLOAK_ADMIN ?= admin
KEYCLOAK_ADMIN_PASSWORD ?= admin
REALM ?= role-gate-e2e
TARGET_CLIENT_ID ?= python-app
REQUIRED_ROLE ?= app-access
OIDC_CLIENT_SECRET ?= python-app-secret
APP_BASE_URL ?= http://localhost:8000
E2E_USER_PASSWORD ?= password

export VALIDATION_DIR
export COMPOSE_FILE
export KEYCLOAK_ADMIN
export KEYCLOAK_ADMIN_PASSWORD
export REALM
export TARGET_CLIENT_ID
export REQUIRED_ROLE
export OIDC_CLIENT_SECRET
export APP_BASE_URL
export E2E_USER_PASSWORD

.PHONY: dev dev-ci e2e-up e2e-setup e2e-test e2e e2e-ci e2e-down e2e-clean e2e-logs lint

dev:
	cd $(VALIDATION_DIR) && uv sync --all-groups
	cd $(VALIDATION_DIR) && uv run playwright install chromium

dev-ci:
	cd $(VALIDATION_DIR) && uv sync --all-groups
	cd $(VALIDATION_DIR) && uv run playwright install --with-deps chromium

e2e-up:
	docker compose up -d --build --wait

e2e-setup:
	./$(VALIDATION_DIR)/scripts/keycloak-e2e-setup.sh

e2e-test:
	cd $(VALIDATION_DIR) && uv run pytest tests/e2e

e2e: dev e2e-up e2e-setup e2e-test

e2e-ci: dev-ci e2e-up e2e-setup e2e-test

e2e-down:
	docker compose down

e2e-clean:
	docker compose down -v --remove-orphans
	rm -rf $(VALIDATION_DIR)/.pytest_cache $(VALIDATION_DIR)/.ruff_cache
	rm -rf $(VALIDATION_DIR)/test-results $(VALIDATION_DIR)/playwright-report

e2e-logs:
	docker compose logs -f

lint:
	cd $(VALIDATION_DIR) && uv run ruff format --check .
	cd $(VALIDATION_DIR) && uv run ruff check .
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/*.sh $(VALIDATION_DIR)/scripts/*.sh; \
	else \
		echo "shellcheck not installed; skipping shell script lint"; \
	fi
