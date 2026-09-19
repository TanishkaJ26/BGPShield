"""Dashboard export tests (plan Sections 11 Phase 7, and 12).

Hand-built tables written to a temporary tree. AS numbers come from the documentation range
(RFC 5398). These check the promises the export makes: a missing input is named rather than
silently producing an empty file, the caveats travel with the numbers, and the payload stays
inside the size budget the plan sets.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from bgpshield.config import Config, load_config
from bgpshield.export import BUDGET_BYTES, build_all, export_networks, export_regional

DAY = date(2026, 9, 1)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    base = load_config(Path("config/default.yaml"))
    loaded = base.model_copy(
        update={"paths": base.paths.model_copy(update={"processed": tmp_path / "processed"})}
    )
    loaded.paths.processed.mkdir(parents=True)
    return loaded


def _write(cfg: Config, name: str, leaf: str, frame: pl.DataFrame, collector: str | None) -> None:
    base = cfg.paths.processed / name / f"snapshot_date={DAY:%Y-%m-%d}"
    if collector is not None:
        base = base / f"collector={collector}"
    base.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(base / leaf)


def _seed(cfg: Config) -> None:
    """A tiny but complete world: four networks, two of which publish."""
    _write(
        cfg,
        "rov_results",
        "rov_results.parquet",
        pl.DataFrame(
            {
                "origin_asn": [64496, 64496, 64497, 64498, 64499],
                "rov_state": ["valid", "invalid", "valid", "not_found", "valid"],
            }
        ),
        "rrc06",
    )
    _write(
        cfg,
        "aspas",
        "aspas.parquet",
        pl.DataFrame({"customer_asn": [64496, 64498], "provider_asns": [[64500], [64500, 64501]]}),
        None,
    )
    _write(
        cfg,
        "routes",
        "routes.parquet",
        pl.DataFrame({"origin_asn": [64496, 64497, 64498, 64499], "as_path": [[64496]] * 4}),
        "rrc06",
    )
    meta = cfg.paths.processed / "as_meta" / "month=2026-08"
    meta.mkdir(parents=True)
    pl.DataFrame(
        {
            "asn": [64496, 64497, 64498, 64499],
            "country": ["IN", "IN", "US", "IN"],
            "rir": ["apnic", "apnic", "arin", "apnic"],
            "cone_size": [500, 120, 900, 30],
            "rank": [10, 40, 5, 90],
        }
    ).write_parquet(meta / "as_meta.parquet")


def test_an_empty_tree_writes_nothing_and_names_every_reason(cfg: Config, tmp_path: Path) -> None:
    result = build_all(cfg, destination=tmp_path / "out")
    assert result.written == []
    assert result.skipped
    for name, reason in result.skipped:
        assert name and reason, f"skip entry {name!r} has no reason"


def test_a_missing_input_is_reported_rather_than_exported_empty(
    cfg: Config, tmp_path: Path
) -> None:
    """An empty file would read as 'no networks publish', which is a measurement, not a gap."""
    with pytest.raises(FileNotFoundError):
        export_networks(cfg, tmp_path / "networks.json")


def test_networks_keeps_publishers_and_records_their_state(cfg: Config, tmp_path: Path) -> None:
    _seed(cfg)
    path = export_networks(cfg, tmp_path / "networks.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    rows = {row["asn"]: row for row in payload["rows"]}
    assert rows[64496]["publishes_aspa"] is True
    assert rows[64496]["providers_listed"] == 1
    assert rows[64498]["providers_listed"] == 2
    assert rows[64497]["publishes_aspa"] is False
    assert rows[64496]["routes_valid"] == 1
    assert rows[64496]["routes_invalid"] == 1
    assert payload["notes"], "the table must carry its caveats"


def test_regional_shares_are_measured_against_routed_networks(cfg: Config, tmp_path: Path) -> None:
    _seed(cfg)
    payload = json.loads(
        export_regional(cfg, tmp_path / "regional.json").read_text(encoding="utf-8")
    )
    regions = {row["region"]: row for row in payload["regions"]}

    # Three IN networks route; one of them (64496) publishes.
    india = regions["registered IN"]
    assert india["routed_networks"] == 3
    assert india["publishers_that_route"] == 1
    assert india["share_of_routed"] == pytest.approx(1 / 3)


def test_the_country_caveat_is_present_in_the_regional_export(cfg: Config, tmp_path: Path) -> None:
    """A number that travels without this caveat invites being read as where networks
    operate, which is not what the registries record."""
    _seed(cfg)
    payload = json.loads(
        export_regional(cfg, tmp_path / "regional.json").read_text(encoding="utf-8")
    )
    joined = " ".join(payload["notes"]).lower()
    assert "registration" in joined
    assert "collectors" in joined


def test_a_seeded_world_exports_within_budget(cfg: Config, tmp_path: Path) -> None:
    _seed(cfg)
    result = build_all(cfg, destination=tmp_path / "out")
    assert result.written
    assert result.within_budget
    assert result.total_bytes == sum(p.stat().st_size for p in result.written)


def test_the_budget_is_the_five_megabytes_the_plan_allows() -> None:
    assert BUDGET_BYTES == 5_000_000


# --- One date for the whole export (docs/decisions.md D-059) -----------------------------


def test_every_export_describes_the_same_snapshot_date(cfg: Config, tmp_path: Path) -> None:
    """An earlier version let each exporter pick its own latest snapshot, so the network
    table could describe one day while the regional comparison described another, and the
    summary would have combined them into a single headline."""
    _seed(cfg)
    # A newer validation result with no routes behind it: the old code would have pulled the
    # network table onto this date and left the regional comparison on the seeded one.
    later = cfg.paths.processed / "rov_results" / "snapshot_date=2026-09-08" / "collector=rrc06"
    later.mkdir(parents=True)
    pl.DataFrame({"origin_asn": [64496], "rov_state": ["valid"]}).write_parquet(
        later / "rov_results.parquet"
    )

    build_all(cfg, destination=tmp_path / "out")
    dates = {
        name: json.loads((tmp_path / "out" / name).read_text(encoding="utf-8"))["snapshot_date"]
        for name in ("networks.json", "regional.json", "path_coverage.json")
    }
    assert len(set(dates.values())) == 1, f"exports disagree about the date: {dates}"
    assert set(dates.values()) == {"2026-09-01"}, "routes should set the date, not validation"


def test_a_weekly_aspa_snapshot_is_matched_to_a_daily_routing_date(
    cfg: Config, tmp_path: Path
) -> None:
    """ASPA snapshots are backfilled weekly and routing tables are per day, so an exact match
    is the exception. The newest snapshot at or before the routing date is the right one, and
    the export has to say which it used rather than implying they lined up."""
    _seed(cfg)
    # Move the ASPA records to a few days earlier, as the weekly backfill would leave them.
    aspa_dir = cfg.paths.processed / "aspas"
    (aspa_dir / "snapshot_date=2026-09-01").rename(aspa_dir / "snapshot_date=2026-08-26")

    payload = json.loads(
        export_regional(cfg, tmp_path / "regional.json").read_text(encoding="utf-8")
    )
    assert payload["snapshot_date"] == "2026-09-01"
    assert payload["aspa_snapshot_date"] == "2026-08-26"
    # The publisher counts still come through rather than collapsing to zero.
    regions = {row["region"]: row for row in payload["regions"]}
    assert regions["registered IN"]["publishers_that_route"] == 1


def test_an_aspa_snapshot_after_the_routing_date_is_not_used(cfg: Config, tmp_path: Path) -> None:
    """Records published later cannot describe an earlier routing table."""
    _seed(cfg)
    aspa_dir = cfg.paths.processed / "aspas"
    (aspa_dir / "snapshot_date=2026-09-01").rename(aspa_dir / "snapshot_date=2026-09-20")

    with pytest.raises(FileNotFoundError):
        export_regional(cfg, tmp_path / "regional.json")


def test_the_summary_names_its_collectors_and_date(cfg: Config, tmp_path: Path) -> None:
    """A site refreshed daily from one collector must say so; the write-up uses six, and a
    reader must be able to tell which they are looking at."""
    _seed(cfg)
    build_all(cfg, destination=tmp_path / "out")
    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["snapshot_date"] == "2026-09-01"
    assert summary["collectors"] == ["rrc06"]
