.PHONY: up down reset migrate api worker corpus seed test e2e eval rebuild-index

up:
	docker compose up -d --wait

down:
	docker compose down

reset:
	docker compose down -v
	docker compose up -d --wait
	$(MAKE) migrate

migrate:
	docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U dms -d dms < db/migrations/001_init.sql
	docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U dms -d dms < db/migrations/002_folders.sql

api:
	uv run uvicorn dms_api.main:app --host 0.0.0.0 --port 8000 --reload

worker:
	uv run python -m dms_workers.run

corpus:
	uv run python scripts/make_corpus.py

seed:
	uv run python scripts/seed_demo.py

test:
	uv run pytest tests/unit

e2e:
	E2E=1 uv run pytest tests/acceptance tests/integration

eval:
	uv run python scripts/eval_search.py

rebuild-index:
	uv run python scripts/rebuild_index.py
