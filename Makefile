.PHONY: help up down logs ps shell migrate status halt resume flush test build pull

help:
	@echo "make up        - bring the stack up (build if needed)"
	@echo "make down      - stop everything (preserves data)"
	@echo "make logs      - tail logs from the app container"
	@echo "make ps        - show container status"
	@echo "make shell     - open a shell in the running app container"
	@echo "make migrate   - run alembic migrations against the running DB"
	@echo "make status    - hit /admin/status"
	@echo "make halt      - kill switch: stop new entries"
	@echo "make resume    - re-arm after halt"
	@echo "make flush     - force-close every open position"
	@echo "make test      - run pytest in the app container"

COMPOSE = docker compose -f docker-compose.prod.yml

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200 app

ps:
	$(COMPOSE) ps

shell:
	$(COMPOSE) exec app sh

migrate:
	$(COMPOSE) exec app alembic upgrade head

build:
	$(COMPOSE) build

pull:
	git pull && $(COMPOSE) up -d --build

status:
	@curl -s http://localhost:8000/admin/status | python -m json.tool

halt:
	@curl -s -X POST http://localhost:8000/admin/halt | python -m json.tool

resume:
	@curl -s -X POST http://localhost:8000/admin/resume | python -m json.tool

flush:
	@curl -s -X POST http://localhost:8000/admin/flush | python -m json.tool

test:
	$(COMPOSE) exec app python -m pytest
