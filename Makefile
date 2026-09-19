# Hijax — common tasks (plan Section 11, Phase 7).
#
# Everything here runs through `uv` so a clone needs no other setup than `uv sync`.
# `reproduce-small` is the one that matters: it is the project's acceptance criterion for
# Phase 7, and the claim that any number in the write-up can be checked by someone else.

.PHONY: help install check lint format types test reproduce-small reproduce-fixture \
        figures export adoption clean-derived

help:
	@echo "Hijax tasks"
	@echo ""
	@echo "  make install           install the locked dependencies"
	@echo "  make check             lint, format check, types and tests (run before committing)"
	@echo "  make reproduce-small   one date, one collector, compared against the fixtures"
	@echo "  make figures           regenerate every figure into figures/"
	@echo "  make export            write the dashboard JSON into web/public/data/"
	@echo ""
	@echo "  make site              build the static dashboard into web/out/"
	@echo ""
	@echo "  reproduce-small downloads about 66 MB on a fresh clone; about 4 minutes of"
	@echo "  compute on top, well inside the 30-minute budget."

install:
	uv sync --locked

# The full suite, exactly as CLAUDE.md requires before anything is called done.
check: lint types test
	uv run ruff format --check .

lint:
	uv run ruff check .

format:
	uv run ruff format .

types:
	uv run mypy src

test:
	uv run pytest

# --- Phase 7 acceptance ------------------------------------------------------------------
#
# Clone the repository, `make install`, then `make reproduce-small`. It ingests one RPKI
# snapshot, one month of topology data and one collector's routing table for 2026-09-01,
# validates and detects over them, and compares the counts against
# tests/fixtures/reproduce_small.json. Archive files for a past date do not change, so the
# numbers should match exactly.
# `make` is not present on every machine this project is worked on, so the reproduction is
# also a first-class command: `hijax reproduce`. Both run the same code.
reproduce-small:
	uv run hijax reproduce

# Record a new baseline. Deliberately separate from the check above: a comparison that
# rewrites what it compares against proves nothing.
reproduce-fixture:
	uv run hijax reproduce --update-fixture

figures:
	uv run hijax report

export:
	uv run hijax export

adoption:
	uv run hijax adoption --export web/public/data/aspa_adoption.json

# Remove derived tables for the reproduction date, keeping the downloaded archives, so a
# rerun re-does the work without re-downloading. Used to check that the pipeline is
# deterministic rather than just cached.
clean-derived:
	rm -rf data/processed/rov_results/snapshot_date=2026-09-01/collector=rrc06
	rm -rf data/processed/aspa_results/snapshot_date=2026-09-01/collector=rrc06
	rm -rf data/processed/routes/snapshot_date=2026-09-01/collector=rrc06

# --- Dashboard ---------------------------------------------------------------------------
#
# The site reads only the JSON that `make export` writes, so build the data first.

site-install:
	cd web && npm install

site: export adoption
	cd web && npm run build
	@echo "static site in web/out/"

# GitHub Pages serves a project site from /<repo>, so the base path has to be set at build
# time. Change the value to match the repository name if it differs.
site-pages: export adoption
	cd web && NEXT_PUBLIC_BASE_PATH=/Hijax npm run build

site-serve: site
	cd web/out && python -m http.server 8000
