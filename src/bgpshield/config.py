"""Typed access to ``config/default.yaml`` (plan Section 7).

Every URL and constant in the config file was verified against a live download in
Phase 0; see ``docs/data-sources.md``. Nothing here guesses a value.

## Finding the file

The CLI used to assume it was run from the repository root, so ``bgpshield`` from any other
directory failed with a bare ``FileNotFoundError``. ``find_config`` now looks in three
places, in order: the ``BGPSHIELD_CONFIG`` environment variable, then ``config/default.yaml``
in the working directory or any directory above it, then the source checkout the package
was installed from. Relative ``paths.*`` entries are resolved against the directory that
holds ``config/``, so the data lands in the same place whichever directory the command
was started in (D-064).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from bgpshield import __version__

#: Environment variable naming the config file, for deployments that keep it elsewhere.
CONFIG_ENV_VAR = "BGPSHIELD_CONFIG"

#: Where the config lives relative to the project root.
CONFIG_RELATIVE = Path("config") / "default.yaml"

#: Kept for callers that predate ``find_config``; it is only correct from the repo root.
DEFAULT_CONFIG_PATH = CONFIG_RELATIVE


class ConfigError(RuntimeError):
    """The config file could not be found or did not validate."""


class _Strict(BaseModel):
    """Reject unknown keys, so a typo in the YAML fails loudly instead of silently."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectConfig(_Strict):
    name: str
    user_agent: str
    """Sent on every download. Plan Section 16 asks for a contact address so that
    archive operators can reach the owner if a job misbehaves. A literal ``{version}``
    in the YAML is replaced with the installed package version."""


class PathsConfig(_Strict):
    raw: Path
    interim: Path
    processed: Path
    figures: Path
    web_data: Path


class RpkiConfig(_Strict):
    archive_base: str
    trust_anchors: list[str]
    """Directory names used by the RIPE NCC archive, e.g. ``ripencc`` for ``ripencc.tal``.
    These are not the canonical trust-anchor labels used in the Parquet tables; see
    ``bgpshield.ingest.rpki.CANONICAL_TA``."""
    file: str
    earliest_aspa_date: date
    rpkiviews_mirror: str


class BgpConfig(_Strict):
    broker_api: str
    collectors: list[str]
    rib_time_utc: str


class MetaConfig(_Strict):
    caida_as_rel_base: str
    caida_as_rel_pattern: str
    caida_as2org_base: str
    caida_as2org_pattern: str
    asrank_graphql: str
    delegated: dict[str, str]


class ScenariosConfig(_Strict):
    publication: list[str]
    top_n: dict[str, int]
    filtering: list[str]


class Config(_Strict):
    project: ProjectConfig
    paths: PathsConfig
    rpki: RpkiConfig
    bgp: BgpConfig
    meta: MetaConfig
    scenarios: ScenariosConfig
    root: Path = Path(".")
    """The project root: the directory that holds ``config/``. Set by ``load_config``, not
    read from the YAML. Fixtures, incident lists and the reproduction runner are found
    relative to it."""


def find_config(start: Path | None = None) -> Path:
    """Locate the config file without assuming the working directory.

    Order: ``$BGPSHIELD_CONFIG`` if set, then ``config/default.yaml`` in ``start`` (default: the
    working directory) or any parent of it, then the checkout this package was imported
    from. The last candidate is returned even if it does not exist, so ``load_config`` can
    name it in its error.
    """
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return Path(override).expanduser()

    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        found = candidate / CONFIG_RELATIVE
        if found.is_file():
            return found

    # src/bgpshield/config.py -> src/bgpshield -> src -> checkout root
    checkout = Path(__file__).resolve().parents[2] / CONFIG_RELATIVE
    return checkout


def _project_root(config_file: Path) -> Path:
    """The directory that relative ``paths.*`` entries are resolved against.

    For the normal layout, ``<root>/config/default.yaml``, that is ``<root>``. A config
    given with ``--config`` or ``$BGPSHIELD_CONFIG`` need not sit in a ``config`` directory
    at all, and assuming it does put the data one level too high: ``--config ./my.yaml`` in
    the repo root would have written ``data/raw`` beside the repo instead of inside it.
    """
    parent = config_file.parent
    return parent.parent if parent.name == "config" else parent


def _resolve_paths(paths: dict[str, object], root: Path) -> dict[str, object]:
    """Make every relative path absolute against the project root."""
    resolved: dict[str, object] = {}
    for key, value in paths.items():
        if isinstance(value, str | Path):
            candidate = Path(value).expanduser()
            resolved[key] = candidate if candidate.is_absolute() else root / candidate
        else:
            resolved[key] = value
    return resolved


def load_config(path: Path | None = None) -> Config:
    """Read and validate the YAML config.

    ``path`` defaults to whatever ``find_config`` locates. Raises ``ConfigError`` when the
    file is missing or a key is absent, misspelled or the wrong type, with a message that
    says which file was read and what was wrong with it.
    """
    target = (path or find_config()).expanduser()
    if not target.is_file():
        raise ConfigError(
            f"config file not found: {target}\n"
            f"Run from inside the repository, pass --config, or set {CONFIG_ENV_VAR}."
        )

    try:
        with target.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{target} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{target} must hold a mapping at the top level")

    root = _project_root(target.resolve())
    raw = dict(raw)
    raw["root"] = root
    if isinstance(raw.get("paths"), dict):
        raw["paths"] = _resolve_paths(raw["paths"], root)
    project = raw.get("project")
    if isinstance(project, dict) and isinstance(project.get("user_agent"), str):
        raw["project"] = {
            **project,
            "user_agent": project["user_agent"].replace("{version}", __version__),
        }

    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{target} failed validation:\n{exc}") from exc
