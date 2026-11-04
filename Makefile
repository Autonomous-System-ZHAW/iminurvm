.PHONY: install lint test fmt

install:
	python -m pip install -e ".[collector,dev]"

lint:
	ruff check .
	black --check .

test:
	pytest

fmt:
	ruff check --fix .
	black .
