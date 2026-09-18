# CLAUDE.md — rules for working on this repo

Project: **Hijax** (formerly "Disha", and before that titled "ASPA Watch"), a BGP route-security measurement project. The Python package and CLI are both `hijax`.
The full plan is in `implementation.md`; it is the source of truth. Section numbers below refer to it.

This is a **research measurement project**, not a product. Correctness and reproducibility matter more than features.

## Rules (from implementation.md, Section 0)

1. **Work one phase at a time** (Section 11). Do not start a phase until the previous phase's acceptance criteria pass.
2. **Verify every external fact before you depend on it.** URLs, file formats, JSON field names and library APIs in the plan were written from research and may have changed. Items marked `VERIFY` must be checked against live docs or a real downloaded sample. Write what you found into `docs/data-sources.md`.
3. **Never invent data or results.** If a download fails or a format differs from the plan, stop and report it. Do not fabricate sample data, except in clearly named test fixtures under `tests/fixtures/`.
4. **Every algorithm gets unit tests with hand-built examples** before it runs on real data (Section 12).
5. **Never commit raw data.** Commit code, small fixtures, and small aggregated outputs only. Everything under `data/` is gitignored.
6. **Passive data only.** This project never scans, probes or sends traffic to any network.
7. **Explain as you go.** The owner is learning BGP while building this. When you implement a routing concept, add a short plain-English docstring saying what it means and cite the RFC or draft section.
8. **Ask the owner** before adding a new dependency that needs a system package, or before any step that downloads more than 5 GB.

## Working conventions

- Python 3.12, `uv` for env/lockfile, `ruff` for lint+format, `mypy --strict` on `src/`, `pytest` for tests.
- Run `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` before declaring anything done.
- **Never run `git commit` or `git push`** (the owner's instruction, 2026-09-18). Make changes in
  the working tree, run the full check suite, and leave committing to the owner. Report what
  changed and let them decide what lands. This replaces the earlier rules about branches and
  about committing to `main`.
- Path direction convention: normalized `as_path` is **origin first** (Section 10.1). Say so loudly wherever paths are handled.
- Pinned spec versions live in `docs/references.md`; design decisions (dated) in `docs/decisions.md`.
- Set a descriptive `User-Agent` with a contact email on every download; cache downloads under `data/raw/`.
