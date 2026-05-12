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
	black claude_pool/ tests/
	isort claude_pool/ tests/

lint:
	mypy claude_pool/
	black --check claude_pool/ tests/
	isort --check-only claude_pool/ tests/

test:
	pytest tests/ -v --cov=claude_pool

run:
	python -m claude_pool --pool pool.json

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .coverage build/ dist/ *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
