"""The partition-path helpers every command shares.

Before these existed the same ``snapshot_date=`` and ``month=`` paths were spelled out by
hand in a dozen places, which is a dozen places for one of them to drift. The layout they
encode is the one documented in ``bgpshield.tables`` and plan Section 9.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from bgpshield.config import load_config
from bgpshield.tables import date_partition, date_table, month_table, table_root

REPO = Path(__file__).resolve().parent.parent


def _cfg(tmp_path: Path):  # type: ignore[no-untyped-def]
    base = load_config(REPO / "config" / "default.yaml")
    return base.model_copy(
        update={"paths": base.paths.model_copy(update={"processed": tmp_path / "processed"})}
    )


def test_date_partition_with_and_without_a_collector(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    day = date(2026, 9, 1)
    assert (
        date_partition(cfg, "routes", day) == table_root(cfg, "routes") / "snapshot_date=2026-09-01"
    )
    assert (
        date_partition(cfg, "routes", day, collector="rrc06")
        == table_root(cfg, "routes") / "snapshot_date=2026-09-01" / "collector=rrc06"
    )


def test_date_table_is_named_after_its_table_unless_told_otherwise(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    day = date(2026, 9, 1)
    assert date_table(cfg, "aspas", day).name == "aspas.parquet"
    assert (
        date_table(cfg, "aspa_results", day, collector="rrc06")
        == date_partition(cfg, "aspa_results", day, collector="rrc06") / "aspa_results.parquet"
    )
    assert date_table(cfg, "routes", day, collector="rrc06", leaf="stats.json").name == "stats.json"


def test_month_table_layout(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert month_table(cfg, "as_rel", "2026-08") == (
        tmp_path / "processed" / "as_rel" / "month=2026-08" / "as_rel.parquet"
    )
    assert month_table(cfg, "as_meta", "2026-08", leaf="extra.parquet").name == "extra.parquet"


def test_helpers_agree_with_the_ingest_modules_own_paths(tmp_path: Path) -> None:
    """The ingest side writes these files; the helpers must point at the same place."""
    from bgpshield.ingest.bgp import table_path

    cfg = _cfg(tmp_path)
    day = date(2026, 9, 1)
    assert table_path(cfg, "rrc06", day) == date_table(cfg, "routes", day, collector="rrc06")
