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

- The wordmark in the site header linked to `/`, which is the wrong address on GitHub Pages
  where the site lives under the repository name.
- Workflow inputs are passed through environment variables rather than interpolated into
  shell, closing a script-injection path on manual runs.

[1.0.0]: https://github.com/TanishkaJ26/BGPShield/releases/tag/v1.0.0
