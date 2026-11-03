.DEFAULT_GOAL := help
COMPOSE ?= docker compose -f deploy/docker-compose.yml
GAMMA ?= $(if $(wildcard .venv/bin/gamma),.venv/bin/gamma,gamma)

help: ## Show targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

dev: ## Create .venv with the package and dev tools
	python3 -m venv .venv && .venv/bin/pip install -q -e '.[dev]'

check: ## Validate experiment definitions and the metric catalog
	$(GAMMA) check

up: ## Start ClickHouse and apply the schema
	$(COMPOSE) up -d --wait
	$(GAMMA) migrate

sim: ## Generate the synthetic casino (200k players) and build the marts
	$(GAMMA) simulate
	$(GAMMA) mart

plan: ## Players per arm and days needed: make plan E=welcome_bonus
	$(GAMMA) plan $(E)

analyze: ## Checks, then estimates: make analyze E=welcome_bonus
	$(GAMMA) analyze $(E)

validate: ## Check the statistics by simulation (about 80 s), writes docs/validation.md
	$(GAMMA) validate --out docs/validation.md

status: ## Row counts and the arms of every experiment
	$(GAMMA) status

test: ## Unit tests
	.venv/bin/pytest

e2e: ## End-to-end tests against the running database (make up first)
	.venv/bin/pytest -m e2e tests/e2e -v

lint: ## Ruff
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

down: ## Stop ClickHouse, keep data
	$(COMPOSE) down

clean: ## Stop ClickHouse and delete all data
	$(COMPOSE) down -v
