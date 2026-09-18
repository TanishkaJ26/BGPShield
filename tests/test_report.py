"""Figure-building tests (plan Section 11 Phase 6, and Section 12).

These do not check what the charts look like. They check the promise the report command
makes: every figure is either drawn or *named* as skipped, so a missing input can never pass
as "nothing to do" (docs/decisions.md D-049).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hijax.config import Config, load_config
from hijax.report import build_all


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    base = load_config(Path("config/default.yaml"))
    loaded = base.model_copy(
        update={"paths": base.paths.model_copy(update={"processed": tmp_path / "processed"})}
    )
    loaded.paths.processed.mkdir(parents=True)
    return loaded


def test_an_empty_tree_draws_nothing_and_names_every_reason(cfg: Config, tmp_path: Path) -> None:
    result = build_all(cfg, destination=tmp_path / "figures")
    assert result.written == []
    assert result.skipped, "an empty tree must report skips, not silence"
    for name, reason in result.skipped:
        assert name and reason, f"skip entry {name!r} has no reason"


def test_a_routes_partition_with_no_readable_table_is_named(cfg: Config, tmp_path: Path) -> None:
    """The bug this pins down: an interrupted ingest leaves the partition directory behind
    with no table in it. That branch used to draw nothing and report nothing, so the command
    said "0 skipped" while quietly omitting two figures."""
    partition = cfg.paths.processed / "routes" / "snapshot_date=2026-09-01" / "collector=x"
    partition.mkdir(parents=True)

    result = build_all(cfg, destination=tmp_path / "figures")
    reasons = {name: reason for name, reason in result.skipped}
    assert "path coverage and regional" in reasons
    assert "2026-09-01" in reasons["path coverage and regional"]
