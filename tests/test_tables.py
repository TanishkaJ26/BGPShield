"""Tests for reading the partitioned tables (plan Section 12).

These helpers were duplicated four times across Phases 6 and 7 before being consolidated, so
the behaviour they share is worth pinning down once, properly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from hijax.tables import (
    collectors_stored,
    latest_snapshot,
    nearest_snapshot_on_or_before,
    previous_month,
    read_partition,
    snapshot_dates,
)

FRAME = pl.DataFrame({"value": [1, 2]})


def _partition(root: Path, day: str, leaf: str, collector: str | None = None) -> Path:
    base = root / f"snapshot_date={day}"
    if collector is not None:
        base = base / f"collector={collector}"
    base.mkdir(parents=True, exist_ok=True)
    FRAME.write_parquet(base / leaf)
    return base


def test_dates_come_back_oldest_first(tmp_path: Path) -> None:
    for day in ("2026-09-08", "2026-09-01", "2026-09-15"):
        _partition(tmp_path, day, "t.parquet")
    assert snapshot_dates(tmp_path) == [
        date(2026, 9, 1),
        date(2026, 9, 8),
        date(2026, 9, 15),
    ]
    assert latest_snapshot(tmp_path) == date(2026, 9, 15)


def test_a_directory_that_is_not_a_date_is_ignored_rather_than_fatal(tmp_path: Path) -> None:
    """A stray file in a data directory must not stop an analysis that does not need it."""
    _partition(tmp_path, "2026-09-01", "t.parquet")
    (tmp_path / "snapshot_date=not-a-date").mkdir()
    (tmp_path / "README.txt").write_text("notes", encoding="utf-8")
    assert snapshot_dates(tmp_path) == [date(2026, 9, 1)]


def test_a_missing_table_has_no_dates(tmp_path: Path) -> None:
    assert snapshot_dates(tmp_path / "never-ingested") == []
    assert latest_snapshot(tmp_path / "never-ingested") is None


def test_collectors_are_combined_unless_one_is_asked_for(tmp_path: Path) -> None:
    _partition(tmp_path, "2026-09-01", "t.parquet", "rrc06")
    _partition(tmp_path, "2026-09-01", "t.parquet", "route-views2")

    both = read_partition(tmp_path, date(2026, 9, 1), "t.parquet")
    assert both is not None and both.height == 4

    one = read_partition(tmp_path, date(2026, 9, 1), "t.parquet", collector="rrc06")
    assert one is not None and one.height == 2

    # Alphabetical, so "route-views2" sorts before "rrc06" ("o" < "r").
    assert collectors_stored(tmp_path, date(2026, 9, 1)) == ["route-views2", "rrc06"]


def test_an_unpartitioned_table_is_read_directly(tmp_path: Path) -> None:
    """Some tables, such as the ASPA records, are not split by collector."""
    _partition(tmp_path, "2026-09-01", "t.parquet")
    frame = read_partition(tmp_path, date(2026, 9, 1), "t.parquet")
    assert frame is not None and frame.height == 2


def test_a_partition_directory_with_no_table_reads_as_nothing(tmp_path: Path) -> None:
    """An interrupted ingest leaves the directory behind. That is 'nothing readable', which
    callers must be able to tell apart from 'ingested and empty'."""
    (tmp_path / "snapshot_date=2026-09-01" / "collector=rrc06").mkdir(parents=True)
    assert read_partition(tmp_path, date(2026, 9, 1), "t.parquet") is None


def test_asking_for_a_collector_that_is_not_there(tmp_path: Path) -> None:
    _partition(tmp_path, "2026-09-01", "t.parquet", "rrc06")
    assert read_partition(tmp_path, date(2026, 9, 1), "t.parquet", collector="rrc00") is None


def test_the_nearest_earlier_snapshot_is_found(tmp_path: Path) -> None:
    """RPKI snapshots are weekly and routing tables are daily, so an exact match is the
    exception. Published records persist until replaced, so the newest earlier one applies."""
    for day in ("2026-08-26", "2026-09-02"):
        _partition(tmp_path, day, "t.parquet")
    assert nearest_snapshot_on_or_before(tmp_path, date(2026, 9, 1)) == date(2026, 8, 26)
    assert nearest_snapshot_on_or_before(tmp_path, date(2026, 9, 2)) == date(2026, 9, 2)


def test_nothing_earlier_means_nothing(tmp_path: Path) -> None:
    """Records published later cannot describe an earlier routing table."""
    _partition(tmp_path, "2026-09-20", "t.parquet")
    assert nearest_snapshot_on_or_before(tmp_path, date(2026, 9, 1)) is None


def test_the_previous_month_wraps_the_year() -> None:
    assert previous_month(date(2026, 9, 1)) == "2026-08"
    assert previous_month(date(2026, 1, 3)) == "2025-12"
