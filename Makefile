# Thin aliases over docker compose. Docker is the source of truth for running
# this project; `make` is a convenience for people who have it. Every target
# below has a plain `docker compose` equivalent shown in the README, because
# `make` is not present on a default Windows install.

.PHONY: up down setup test logs psql fmt check-layers

up:
	docker compose up -d --build

down:
	docker compose down

# Migrate + ingest. Equivalent: docker compose run --rm setup
setup:
	docker compose run --rm setup

test:
	docker compose run --rm api pytest -q

# The four layer-import greps from the build spec section 4.2.
check-layers:
	docker compose run --rm api python -m scripts.check_layers

logs:
	docker compose logs -f api

psql:
	docker compose exec db psql -U parcelpilot -d parcelpilot
