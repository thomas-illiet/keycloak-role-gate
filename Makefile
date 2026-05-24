VALIDATION_DIR ?= validation
COMPOSE_FILE ?= $(VALIDATION_DIR)/docker-compose.yml
ROLEGATE_KEYCLOAK_URL ?= http://localhost:8080
ROLEGATE_ADMIN_USERNAME ?= admin
ROLEGATE_ADMIN_PASSWORD ?= admin
ROLEGATE_REALM ?= role-gate-validation
ROLEGATE_TARGET_CLIENT_ID ?= python-app
ROLEGATE_REQUIRED_ROLE ?= app-access
ROLEGATE_DENY_MESSAGE ?= Access denied: missing required role
ROLEGATE_VALIDATION_APP_URL ?= http://localhost:8000
ROLEGATE_VALIDATION_REDIRECT_URI ?= $(ROLEGATE_VALIDATION_APP_URL)/auth/callback
ROLEGATE_VALIDATION_CLIENT_SECRET ?= python-app-secret
ROLEGATE_VALIDATION_USER_PASSWORD ?= password

export VALIDATION_DIR
export COMPOSE_FILE
export ROLEGATE_KEYCLOAK_URL
export ROLEGATE_ADMIN_USERNAME
export ROLEGATE_ADMIN_PASSWORD
export ROLEGATE_REALM
export ROLEGATE_TARGET_CLIENT_ID
export ROLEGATE_REQUIRED_ROLE
export ROLEGATE_DENY_MESSAGE
export ROLEGATE_VALIDATION_APP_URL
export ROLEGATE_VALIDATION_REDIRECT_URI
export ROLEGATE_VALIDATION_CLIENT_SECRET
export ROLEGATE_VALIDATION_USER_PASSWORD

.PHONY: dev dev-ci validation-up validation-setup validation-test validation validation-ci validation-down validation-clean validation-logs lint

dev:
	cd $(VALIDATION_DIR) && uv sync --all-groups
	cd $(VALIDATION_DIR) && uv run playwright install chromium

dev-ci:
	cd $(VALIDATION_DIR) && uv sync --all-groups
	cd $(VALIDATION_DIR) && uv run playwright install --with-deps chromium

validation-up:
	docker compose up -d --build --wait

validation-setup:
	./$(VALIDATION_DIR)/scripts/keycloak-validation-setup.sh

validation-test:
	cd $(VALIDATION_DIR) && uv run pytest tests/browser

validation: dev validation-up validation-setup validation-test

validation-ci: dev-ci validation-up validation-setup validation-test

validation-down:
	docker compose down

validation-clean:
	docker compose down -v --remove-orphans
	rm -rf $(VALIDATION_DIR)/.pytest_cache $(VALIDATION_DIR)/.ruff_cache
	rm -rf $(VALIDATION_DIR)/test-results $(VALIDATION_DIR)/playwright-report

validation-logs:
	docker compose logs -f

lint:
	cd $(VALIDATION_DIR) && uv run ruff format --check .
	cd $(VALIDATION_DIR) && uv run ruff check .
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/*.sh $(VALIDATION_DIR)/scripts/*.sh; \
	else \
		echo "shellcheck not installed; skipping shell script lint"; \
	fi
