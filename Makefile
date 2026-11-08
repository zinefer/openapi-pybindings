.PHONY: all lint typecheck test format golden

# Everything CI runs.
all: lint typecheck test

lint:
	uv run ruff check
	uv run ruff format --check

typecheck:
	uv run mypy

# End-to-end tests, including the README's code blocks.
test:
	uv run pytest

format:
	uv run ruff check --fix
	uv run ruff format

golden:
	UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py
