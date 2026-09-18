"""Longitudinal aggregation tests (plan Sections 11 Phase 6, and 12).

Hand-built partitions written to a temporary tree. AS numbers come from the documentation
range (RFC 5398).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from hijax.analysis.longitudinal import build_series, publisher_series
from hijax.config import Config, load_config


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    base = load_config(Path("config/default.yaml"))
    loaded = base.model_copy(
        update={"paths": base.paths.model_copy(update={"processed": tmp_path / "processed"})}
    )
    loaded.paths.processed.mkdir(parents=True)
    return loaded


def _write(root: Path, day: str, leaf: str, frame: pl.DataFrame, collector: str | None) -> None:
    base = root / f"snapshot_date={day}"
    if collector is not None:
        base = base / f"collector={collector}"
    base.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(base / leaf)


def _rov(valid: int, invalid: int, not_found: int) -> pl.DataFrame:
    return pl.DataFrame(
        {"rov_state": ["valid"] * valid + ["invalid"] * invalid + ["not_found"] * not_found}
    )


def test_a_series_has_one_row_per_date_in_order(cfg: Config) -> None:
    root = cfg.paths.processed / "rov_results"
    _write(root, "2024-07-03", "rov_results.parquet", _rov(1, 1, 2), "route-views2")
    _write(root, "2024-01-03", "rov_results.parquet", _rov(2, 0, 2), "route-views2")

    series = build_series(cfg)
    assert series["snapshot_date"].to_list() == [date(2024, 1, 3), date(2024, 7, 3)]


def test_states_are_reported_as_shares_of_the_routes(cfg: Config) -> None:
    root = cfg.paths.processed / "rov_results"
    _write(root, "2024-01-03", "rov_results.parquet", _rov(1, 1, 2), "route-views2")

    row = build_series(cfg).row(0, named=True)
    assert row["routes"] == 4
    assert row["rov_valid"] == pytest.approx(0.25)
    assert row["rov_invalid"] == pytest.approx(0.25)
    assert row["rov_not_found"] == pytest.approx(0.5)


def test_several_collectors_on_one_date_are_combined(cfg: Config) -> None:
    root = cfg.paths.processed / "rov_results"
    _write(root, "2024-01-03", "rov_results.parquet", _rov(2, 0, 0), "route-views2")
    _write(root, "2024-01-03", "rov_results.parquet", _rov(0, 0, 2), "rrc00")

    row = build_series(cfg).row(0, named=True)
    assert row["routes"] == 4
    assert row["rov_valid"] == pytest.approx(0.5)


def test_a_date_missing_one_input_still_appears_with_nulls(cfg: Config) -> None:
    """A gap in the expensive BGP sweep must be visible, not silently dropped."""
    _write(
        cfg.paths.processed / "rov_results",
        "2024-01-03",
        "rov_results.parquet",
        _rov(1, 0, 1),
        "route-views2",
    )
    _write(
        cfg.paths.processed / "aspa_results",
        "2024-07-03",
        "aspa_results.parquet",
        pl.DataFrame({"aspa_state": ["unknown", "valid"]}),
        "route-views2",
    )

    series = build_series(cfg)
    assert series.height == 2
    first, second = series.row(0, named=True), series.row(1, named=True)
    assert first["rov_valid"] == pytest.approx(0.5)
    assert first["aspa_rows"] is None
    assert second["routes"] is None
    assert second["aspa_valid"] == pytest.approx(0.5)


def test_leak_counts_come_from_an_unpartitioned_leaf(cfg: Config) -> None:
    """The leaks table stores one file per date rather than one per collector."""
    _write(
        cfg.paths.processed / "rov_results",
        "2024-01-03",
        "rov_results.parquet",
        _rov(1, 0, 0),
        "route-views2",
    )
    _write(
        cfg.paths.processed / "leaks",
        "2024-01-03",
        "leaks.parquet",
        pl.DataFrame(
            {
                "leaker_asn": [64496, 64496, 64497],
                "corroborated": [True, False, True],
            }
        ),
        None,
    )

    row = build_series(cfg).row(0, named=True)
    assert row["leak_findings"] == 3
    assert row["leak_leakers"] == 2
    assert row["leak_corroborated"] == 2


def test_an_empty_tree_gives_an_empty_series(cfg: Config) -> None:
    assert build_series(cfg).height == 0


def test_publisher_series_counts_distinct_customers(cfg: Config) -> None:
    root = cfg.paths.processed / "aspas"
    _write(
        root,
        "2024-01-03",
        "aspas.parquet",
        pl.DataFrame({"customer_asn": [64496, 64496, 64497]}),
        None,
    )
    frame = publisher_series(cfg)
    assert frame.row(0, named=True)["publishers"] == 2
