.PHONY: setup download analyze windows export all test

setup:
	uv sync --extra dev

download:
	uv run python scripts/01_download.py

analyze:
	uv run python scripts/02_analyze.py

windows:
	uv run python scripts/03_build_windows.py

export:
	uv run python scripts/04_export.py

all: download analyze windows export

pilot-ids:
	uv run python scripts/05_select_pilot_2k.py

pilot-label:
	uv run python scripts/06_silver_label_pilot.py

test:
	uv run pytest
