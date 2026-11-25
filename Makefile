.PHONY: up down logs test dev-backend dev-frontend clean

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd backend && uv run pytest -v

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev -- --port 3000

clean:
	docker compose down -v

