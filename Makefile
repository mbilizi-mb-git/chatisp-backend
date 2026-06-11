.PHONY: help install dev-install lint format test run docker-build docker-run clean

help:
	@echo "Available targets:"
	@echo "  install       Install production dependencies"
	@echo "  dev-install   Install development dependencies"
	@echo "  lint          Run linters (mypy)"
	@echo "  format        Format code with black and isort"
	@echo "  test          Run tests"
	@echo "  run           Run the application locally"
	@echo "  docker-build  Build Docker image"
	@echo "  docker-run    Run Docker container"
	@echo "  clean         Remove cache files"

install:
	pip install -r requirements.txt

dev-install:
	pip install -e .[dev]

lint:
	mypy app/

format:
	black app/ tests/ scripts/
	isort app/ tests/ scripts/

test:
	pytest tests/ -v --cov=app

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

docker-build:
	docker build -t chatisp-backend .

docker-run:
	docker run -p 8000:8000 --env-file .env chatisp-backend

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete