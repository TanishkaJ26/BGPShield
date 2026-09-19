# BGPShield

BGPShield (formerly Hijax) measures BGP route-security adoption and impact: RPKI Route Origin Validation (ROV) and
Autonomous System Provider Authorization (ASPA). A reproducible, passive-measurement pipeline
built for a master's application; full plan in [implementation.md](implementation.md).

**Status:** Phases 0-7 are built. See `docs/data-sources.md` for the verified URLs, formats and
sample records, `docs/references.md` for the pinned specs, `docs/decisions.md` for the dated
decisions, and `docs/methodology.md` for every reported number and the command that reproduces
it.

Two acceptance criteria are still outstanding and are reported as misses rather than glossed:

- **Phase 1** needs the daily job to have run seven days in a row. The streak is computed from
  the published series by `bgpshield adoption` and by the workflow, but seven calendar days have to
  elapse with the schedule enabled, which starts when the workflow is pushed.
- **Phase 2** wants one day across all six collectors in under an hour. On verified-complete
  data it takes **64.2 minutes** (memory, at 1.80 GB against an 8 GB bar, passes). The binding
  constraint is the laptop's link: 818 MB has to arrive, at a measured 232-490 KB/s.

## Running it

The environment is a `uv` virtual environment in `.venv/`. Activate it once per terminal and
every command below is available as `bgpshield`:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
bgpshield --help
```

```bash
# Git Bash / macOS / Linux
source .venv/Scripts/activate     # .venv/bin/activate on macOS and Linux
bgpshield --help
```

Without activating, call it by path: `.venv\Scripts\bgpshield.exe --help`, or run
`python -m bgpshield`.

The command works from any directory. It finds `config/default.yaml` by looking upwards from
where it was started, falling back to the checkout it was installed from; `--config` or the
`BGPSHIELD_CONFIG` environment variable override that. Data paths in the config are resolved
against the project root, so `data/` never ends up somewhere unexpected. Add `--verbose` to
any command to see every download attempt and retry on stderr.

Setting the environment up from scratch, or after changing dependencies, needs `uv`:

```bash
uv sync
```

`make` is a convenience for machines that have it and is not required for anything.

## Reproducing the numbers

```bash
bgpshield reproduce
```

One date, one collector: it ingests, validates and detects, then compares twelve counts and
five normalization drop rates against `tests/fixtures/reproduce_small.json`. Archive files for
a past date do not change, so an honest rerun matches exactly. About four minutes of compute,
plus roughly 66 MB of downloads on a fresh clone, against a thirty-minute budget.

Add `--skip-pipeline` to check what is already stored without re-running anything.

## Deploying it with daily data

`.github/workflows/daily-site.yml` refreshes the numbers every day and publishes the site to
GitHub Pages. To turn it on, once:

1. Push the repository.
2. In the repository settings, enable **Pages** with the source set to **GitHub Actions**.
3. From the **Actions** tab, run **Daily site** by hand so the first deployment exists.

It then runs daily after the RPKI job. Each run ingests one collector (rrc06, ~43 MB), so
**the live site describes one collector while the write-up describes six** - every page says
so in its footer.

The site is served under `/<repository name>` on GitHub Pages. The workflow reads the name
from the repository, so nothing needs editing when it differs from this folder's name. If the
site is put behind a custom domain, set a repository variable `SITE_URL` to the full address
so the sitemap and link previews point at the right place.

## Launch checklist

1. `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`
   is green (CI runs the same).
2. `cd web && npm run check` is green: type check, lint and a production build.
3. `bgpshield reproduce` matches the fixtures, so the published numbers are the real ones.
4. Pages is enabled with the source set to GitHub Actions, and **Daily site** has been run
   once by hand.
5. Dependabot is on (`.github/dependabot.yml`), so the toolchains keep getting updates.

## The dashboard

```bash
bgpshield export                                        # write the JSON the site reads
cd web && npm ci && npm run check                   # type check, lint, static site into web/out/
npm run serve                                       # then open http://localhost:8000
```

## Headline findings

- **2.87%** of routed networks publish an ASPA record. But only **5.4%** of routes contain two
  *adjacent* publishers, which is the first point at which ASPA can judge a hop, and 0.05% are
  covered end to end. Those two numbers have to be read together.
- **None of India's twelve largest transit networks publishes an ASPA record.** The largest
  Indian network that does has a customer cone of 85 and ranks 536th globally; the largest
  Indian network overall ranks 20th. Adoption is happening where it does the least good.
- Roughly **one in five** ASPA-Invalid routes is better explained by an incomplete published
  record than by anything wrong with the routing. This is a statement about ASPA, not about
  origin validation: ROV-Invalid is a different and much smaller set.
- Leak-detection precision measured **46%**, and of seven well-documented incidents only two
  could be judged at a single collector at all.

## Setup

```bash
uv sync
uv run bgpshield version
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
cd web && npm ci && npm run check
```

Releases are recorded in [CHANGELOG.md](CHANGELOG.md); the version lives only in
`pyproject.toml` and is read from the installed package at runtime.

Raw data lives under `data/` and is never committed.

## Using it

Fetch the published RPKI records for one day into the `vrps` and `aspas` tables:

```bash
uv run bgpshield ingest-rpki --date 2026-09-16
```

Backfill weekly from the first ASPA record ever published:

```bash
uv run bgpshield ingest-rpki --from 2023-10-11 --to 2026-09-18 --every 7d
```

Report adoption over time and refresh the dashboard aggregate:

```bash
uv run bgpshield adoption --export web/public/data/aspa_adoption.json
```

Downloads are cached under `data/raw/`, carry a contact address in the User-Agent, and retry a
dropped transfer without ever caching a truncated file.

## Layout

See plan Section 7. `src/bgpshield/` is the package, `scripts/` holds one-off Phase 0 probes,
`docs/` the verified facts and decisions, `config/` the run configuration.
