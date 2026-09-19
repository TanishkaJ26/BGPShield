# Hijax

Hijax measures BGP route-security adoption and impact: RPKI Route Origin Validation (ROV) and
Autonomous System Provider Authorization (ASPA). A reproducible, passive-measurement pipeline
built for a master's application; full plan in [implementation.md](implementation.md).

**Status:** Phases 0-7 are built. See `docs/data-sources.md` for the verified URLs, formats and
sample records, `docs/references.md` for the pinned specs, `docs/decisions.md` for the dated
decisions, and `docs/methodology.md` for every reported number and the command that reproduces
it.

Two acceptance criteria are still outstanding and are reported as misses rather than glossed:

- **Phase 1** needs the daily job to have run seven days in a row. The streak is computed from
  the published series by `hijax adoption` and by the workflow, but seven calendar days have to
  elapse with the schedule enabled, which starts when the workflow is pushed.
- **Phase 2** wants one day across all six collectors in under an hour. On verified-complete
  data it takes **64.2 minutes** (memory, at 1.80 GB against an 8 GB bar, passes). The binding
  constraint is the laptop's link: 818 MB has to arrive, at a measured 232-490 KB/s.

## Running it

The environment is a `uv` virtual environment in `.venv/`. Activate it once per terminal and
every command below is available as `hijax`:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
hijax --help
```

```bash
# Git Bash / macOS / Linux
source .venv/Scripts/activate     # .venv/bin/activate on macOS and Linux
hijax --help
```

Without activating, call it by path: `.venv\Scripts\hijax.exe --help`.

Setting the environment up from scratch, or after changing dependencies, needs `uv`:

```bash
uv sync
```

`make` is a convenience for machines that have it and is not required for anything.

## Reproducing the numbers

```bash
hijax reproduce
```

One date, one collector: it ingests, validates and detects, then compares twelve counts and
five normalization drop rates against `tests/fixtures/reproduce_small.json`. Archive files for
a past date do not change, so an honest rerun matches exactly. About four minutes of compute,
plus roughly 66 MB of downloads on a fresh clone, against a thirty-minute budget.

Add `--skip-pipeline` to check what is already stored without re-running anything.

## The dashboard

```bash
hijax export                                        # write the JSON the site reads
cd web && npm install && npm run build              # static site into web/out/
cd out && python -m http.server 8000                # then open http://localhost:8000
```

## Headline findings

- **2.87%** of routed networks publish an ASPA record. But only **5.4%** of routes contain two
  *adjacent* publishers, which is the first point at which ASPA can judge a hop, and 0.04% are
  covered end to end. Those two numbers have to be read together.
- **None of India's twelve largest transit networks publishes an ASPA record.** The largest
  Indian network that does has a customer cone of 85 and ranks 536th globally; the largest
  Indian network overall ranks 20th. Adoption is happening where it does the least good.
- Roughly **one in five** ROV-Invalid routes is better explained by an incomplete published
  record than by anything wrong with the routing.
- Leak-detection precision measured **46%**, and of seven well-documented incidents only two
  could be judged at a single collector at all.

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
