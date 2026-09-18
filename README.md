# Hijax

Hijax measures BGP route-security adoption and impact: RPKI Route Origin Validation (ROV) and
Autonomous System Provider Authorization (ASPA). A reproducible, passive-measurement pipeline
built for a master's application; full plan in [implementation.md](implementation.md).

**Status:** Phase 0 (verify the ground) is complete. Phase 1 (RPKI ingestion and the adoption
baseline) is in progress. See `docs/data-sources.md` for the verified URLs, formats and sample
records, `docs/references.md` for the pinned specs, `docs/decisions.md` for the dated decisions,
and `docs/methodology.md` for every reported number and the command that reproduces it.

## Setup

```bash
uv sync
uv run hijax version
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

Raw data lives under `data/` and is never committed.

## Using it

Fetch the published RPKI records for one day into the `vrps` and `aspas` tables:

```bash
uv run hijax ingest-rpki --date 2026-09-16
```

Backfill weekly from the first ASPA record ever published:

```bash
uv run hijax ingest-rpki --from 2023-10-11 --to 2026-09-18 --every 7d
```

Report adoption over time and refresh the dashboard aggregate:

```bash
uv run hijax adoption --export web/public/data/aspa_adoption.json
```

Downloads are cached under `data/raw/`, carry a contact address in the User-Agent, and retry a
dropped transfer without ever caching a truncated file.

## Layout

See plan Section 7. `src/hijax/` is the package, `scripts/` holds one-off Phase 0 probes,
`docs/` the verified facts and decisions, `config/` the run configuration.
