# Changelog

All notable changes to BGPShield. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-09-19

First release. Phases 0 to 7 of `implementation.md` are complete, `bgpshield reproduce` matches the
committed fixtures, and the dashboard deploys daily to GitHub Pages.

### Added

- `bgpshield` works from any directory: the config is found through `$BGPSHIELD_CONFIG`, then
  `config/default.yaml` upwards from the working directory, then the source checkout. Relative
  data paths resolve against the project root (D-064).
- `bgpshield --verbose` logs every download attempt and retry to stderr.
- `python -m bgpshield` as an alternative to the console script.
- Web: a 404 page, `robots.txt`, `sitemap.xml`, a favicon, Open Graph metadata, and per-page
  titles. `npm run check` runs the type check, lint and build together.
- CI builds and lints the site as well as the Python package. Dependabot keeps the GitHub
  Actions, uv and npm toolchains current.

### Changed

- The project, package, CLI and site are named **BGPShield**, matching the GitHub repository
  (D-066). The package was `hijax`; `HIJAX_CONFIG` is now `BGPSHIELD_CONFIG`.
- The package version is read from the installed metadata, so `pyproject.toml` is the only
  place it is written, and the User-Agent carries it.
- Downloads back off exponentially and honour `Retry-After` on `429` and `503`.
- A missing or invalid config file, or an archive that will not serve a file, is reported as
  one line with a non-zero exit instead of a traceback.
- Partition paths are built by shared helpers in `bgpshield.tables` rather than by hand at each
  call site.

### Fixed

Found by running every command and driving the site before release (D-067, D-068).

Measurements:

- Figures could describe a different set of ASPA publishers than the dashboard. `report`
  matched publishers on the exact routing date and otherwise fell back to the union across
  every snapshot ever ingested; since RPKI snapshots are weekly and routing tables daily,
  that fallback was the normal path. Both sides now take the newest snapshot at or before
  the routing date.
- `validate` reported `distinct origins` from a cache keyed on (prefix, origin), roughly two
  orders of magnitude too high.
- Provider sets are unioned across trust anchors, as
  `draft-ietf-sidrops-aspa-verification-28` Section 5.3 requires. Both consumers previously
  kept only the last row, which would report a legitimate hop as Invalid.
- A truncated AS Rank walk from `--asrank-pages` is no longer cached as though complete.
- `median_blocking_position` is a median rather than the upper of the two middle values.
- The incidents page showed no primary sources and used raw ids as headings: the exporter
  read `title` and `source`, neither of which exists on the curated record, and `getattr`'s
  default published empty strings. It now reads `description` and `sources`, and raises on a
  field name that does not exist.

Interface:

- A missing input file printed a stack trace instead of one line naming the command to run.
- `ingest-bgp` reported `total rows: 0` when every collector was already cached.
- `make site-pages` built with a base path of `/BGPShield.git`, which would 404 every asset.

Site:

- Every headline rendered its words run together, because the space between them sat inside
  an `overflow: hidden` inline-block that collapsed it.
- With JavaScript disabled, every headline and revealed block stayed invisible. The
  `<noscript>` fallback the code documented was never implemented.
- On a phone the last two sections of the navigation were clipped off the screen with no way
  to reach them, and the networks page scrolled sideways.
- The network table could not be paged past its first 100 rows without typing a search.
- A network listing one upstream was labelled "1 providers".
- The wordmark in the site header linked to `/`, which is the wrong address on GitHub Pages
  where the site lives under the repository name.

Workflows:

- The daily site job derived the topology month with `date -d "$day -1 month"`, which
  overflows: 31 March minus one month is 31 February, which normalises to 3 March. On the
  handful of days a year when yesterday is the 29th to 31st of a month following a shorter
  one, the job fetched the current month's topology and then failed in `validate`, which
  correctly wants the month before. It now steps back one day from the first of the month.
- Workflow inputs are passed through environment variables rather than interpolated into
  shell, closing a script-injection path on manual runs.

Documentation:

- The front page attributed the one-in-five false-positive finding to ROV-Invalid routes; it
  is measured on ASPA-Invalid routes.
- The Phase 2 acceptance table presented numbers the project had already retracted, with no
  marker. It now carries a "superseded, do not quote" banner naming the corrected figures.
- Corrected: eleven counts to twelve, six figures to seven, the BGPShield rename date, two
  `ingest-bgp` flags that do not exist, a claim that CI runs the reproduction, and "155
  weekly snapshots" where 154 are weekly.

[1.0.0]: https://github.com/TanishkaJ26/BGPShield/releases/tag/v1.0.0
