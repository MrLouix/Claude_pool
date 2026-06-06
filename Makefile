.PHONY: install format lint test run clean help

help:
	@echo "Available commands:"
	@echo "  make install  - Install package and dependencies"
	@echo "  make format   - Format code with black and isort"
	@echo "  make lint     - Run type checking and format check"
	@echo "  make test     - Run tests with coverage"
	@echo "  make run      - Run the application"
	@echo "  make clean    - Remove build artifacts and cache"

install:
	pip install -e ".[dev]"

format:
	black team_cli/ tests/
	isort team_cli/ tests/

lint:
	mypy team_cli/
	black --check team_cli/ tests/
	isort --check-only team_cli/ tests/

test:
	# Use --tb=short for concise tracebacks
	pytest tests/ -v --cov=team_cli --tb=short

run:
	python -m team_cli --pool pool.json

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .coverage build/ dist/ *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
