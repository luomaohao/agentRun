.PHONY: help install dev test lint format clean docker-build docker-up docker-down

# Default target
help:
	@echo "Available commands:"
	@echo "  make install      - Install dependencies"
	@echo "  make dev          - Run development server"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linting"
	@echo "  make format       - Format code"
	@echo "  make clean        - Clean temporary files"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-up    - Start services with Docker Compose"
	@echo "  make docker-down  - Stop Docker Compose services"
	@echo "  make db-setup     - Initialize database"
	@echo "  make api-docs     - Generate API documentation"

# Install dependencies
install:
	pip install -r requirements.txt
	pip install -e .

# Run development server
dev:
	python main.py

# Run tests
test:
	pytest tests/ -v --cov=src/workflow_engine --cov-report=html

# Run linting
lint:
	flake8 src/ --max-line-length=100 --ignore=E203,W503
	mypy src/ --ignore-missing-imports

# Format code
format:
	black src/ tests/ --line-length=100
	isort src/ tests/ --profile=black

# Clean temporary files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".coverage" -delete
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/

# Docker commands
docker-build:
	docker build -t agent-workflow-runtime:latest .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

# Database setup
db-setup:
	@echo "Setting up database..."
	@if [ -z "$(DATABASE_URL)" ]; then \
		echo "Using default local database"; \
		createdb workflow_db 2>/dev/null || echo "Database already exists"; \
		psql -d workflow_db -f src/workflow_engine/storage/database_schema.sql; \
	else \
		echo "Using DATABASE_URL"; \
		psql $(DATABASE_URL) -f src/workflow_engine/storage/database_schema.sql; \
	fi

# API documentation
api-docs:
	@echo "Starting API server for documentation..."
	@echo "Swagger UI: http://localhost:8000/docs"
	@echo "ReDoc: http://localhost:8000/redoc"
	python main.py

# Development database
dev-db:
	docker run --name workflow-postgres -e POSTGRES_PASSWORD=password -e POSTGRES_DB=workflow_db -p 5432:5432 -d postgres:15

dev-redis:
	docker run --name workflow-redis -p 6379:6379 -d redis:7

# Quick start for development
quickstart: install dev-db dev-redis db-setup
	@echo "Development environment ready!"
	@echo "Run 'make dev' to start the API server"
