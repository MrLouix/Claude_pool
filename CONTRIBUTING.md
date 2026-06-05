# Contributing to TeamCLI TUI

## Development Setup

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   . venv/bin/activate
   ```
3. Install in development mode:
   ```bash
   make install
   ```

## Running Tests

```bash
# Run all tests
make test

# Run specific test file
pytest tests/test_models.py -v

# Run with coverage
pytest tests/ --cov=team_cli --cov-report=html
```

## Code Quality

```bash
# Format code
make format

# Type check
make lint

# Run all checks
make format && make lint && make test
```

## Project Structure

```
team_cli/
├── __init__.py         # Package initialization
├── __main__.py         # CLI entry point
├── models.py           # Task dataclass
├── storage.py          # JSON persistence
├── parser.py           # Claude output parsing
├── executor.py         # Task execution engine
└── tui.py             # Textual UI

tests/
├── test_models.py      # Model tests
├── test_storage.py     # Storage tests
├── test_parser.py      # Parser tests
├── test_executor.py    # Executor tests
└── test_e2e.py        # End-to-end tests
```

## Adding Features

1. Write tests first (TDD approach)
2. Implement the feature
3. Ensure all tests pass
4. Format and type check
5. Update documentation

## Release Process

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Run full test suite
4. Create git tag
5. Build and publish to PyPI
