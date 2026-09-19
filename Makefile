# BGPShield — common tasks (plan Section 11, Phase 7).
#
# Everything here runs through `uv` so a clone needs no other setup than `uv sync`.
# `reproduce-small` is the one that matters: it is the project's acceptance criterion for
# Phase 7, and the claim that any number in the write-up can be checked by someone else.

.PHONY: help install check lint format types test reproduce-small reproduce-fixture \
        figures export adoption clean-derived site-install site-check site site-pages site-serve

help:
	@echo "BGPShield tasks"
	@echo ""
	@echo "  make install           install the locked dependencies"
	@echo "  make check             lint, format check, types and tests (run before committing)"
	@echo "  make reproduce-small   one date, one collector, compared against the fixtures"
	@echo "  make figures           regenerate every figure into figures/"
	@echo "  make export            write the dashboard JSON into web/public/data/"
	@echo ""
	@echo "  make site-check        type-check, lint and build the dashboard (as CI does)"
	@echo "  make site              build the static dashboard into web/out/"
	@echo "  make site-pages        build it for GitHub Pages, under /<repository name>"
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
# also a first-class command: `bgpshield reproduce`. Both run the same code.
reproduce-small:
	uv run bgpshield reproduce

# Record a new baseline. Deliberately separate from the check above: a comparison that
# rewrites what it compares against proves nothing.
reproduce-fixture:
	uv run bgpshield reproduce --update-fixture

figures:
	uv run bgpshield report

export:
	uv run bgpshield export

adoption:
	uv run bgpshield adoption --export web/public/data/aspa_adoption.json

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
	cd web && npm ci

site-check:
	cd web && npm run check

site: export adoption
	cd web && npm run build
	@echo "static site in web/out/"

# GitHub Pages serves a project site from /<repository name>. The name is read from the
# origin remote (the GitHub repository is not called the same thing as this folder), so a
# rename cannot leave a stale value here. Override with BASE_PATH=/name if needed.
BASE_PATH ?= /$(shell git remote get-url origin 2>/dev/null | sed -E 's#.*/([^/]+?)(\.git)?$$#\1#')

site-pages: export adoption
	cd web && NEXT_PUBLIC_BASE_PATH=$(BASE_PATH) npm run build
	@echo "static site in web/out/, built for $(BASE_PATH)/"

site-serve: site
	cd web/out && python -m http.server 8000
