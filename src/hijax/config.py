"""Typed access to ``config/default.yaml`` (plan Section 7).

Every URL and constant in the config file was verified against a live download in
Phase 0; see ``docs/data-sources.md``. Nothing here guesses a value.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_CONFIG_PATH = Path("config/default.yaml")


class _Strict(BaseModel):
    """Reject unknown keys, so a typo in the YAML fails loudly instead of silently."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectConfig(_Strict):
    name: str
    user_agent: str
    """Sent on every download. Plan Section 16 asks for a contact address so that
    archive operators can reach the owner if a job misbehaves."""


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
    ``hijax.ingest.rpki.CANONICAL_TA``."""
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


def load_config(path: Path | None = None) -> Config:
    """Read and validate the YAML config.

    Raises ``pydantic.ValidationError`` if a key is missing, misspelled or the wrong type.
    """
    target = path or DEFAULT_CONFIG_PATH
    with target.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return Config.model_validate(raw)
