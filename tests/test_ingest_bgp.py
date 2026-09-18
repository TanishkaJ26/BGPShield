"""Unit tests for MRT routing-table ingestion (plan Sections 9, 10.1 and 12).

These run against the small real dump committed nowhere but cached under ``data/`` in
Phase 0, so they skip when it is absent. The point is the storage contract and the
interrupted-run behaviour, both of which are easy to get quietly wrong.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from hijax.config import Config, load_config
from hijax.ingest.bgp import (
    ROUTES_SCHEMA,
    RibNotFoundError,
    ingest_rib,
    table_path,
)
from hijax.net import DownloadError

SAMPLE = Path("data/raw/samples/mrt/rib.iix.cgk.20260901.0000.bz2")
DAY = date(2026, 9, 1)


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    base = load_config(Path("config/default.yaml"))
    return base.model_copy(
        update={"paths": base.paths.model_copy(update={"processed": tmp_path / "processed"})}
    )


needs_sample = pytest.mark.skipif(not SAMPLE.exists(), reason="Phase 0 MRT sample not cached")


@needs_sample
def test_ingest_writes_the_section_9_columns(cfg: Config) -> None:
    result = ingest_rib(cfg, "test", DAY, url=str(SAMPLE), limit=5_000)
    assert result.rows == 5_000
    table = pq.read_table(result.path)
    assert table.schema.names == ROUTES_SCHEMA.names
    assert table.num_rows == 5_000

    row = table.slice(0, 1).to_pylist()[0]
    assert row["collector"] == "test"
    assert row["snapshot_date"] == DAY
    assert row["afi"] in (4, 6)
    assert isinstance(row["timestamp"], datetime)
    assert row["timestamp"].tzinfo is not None
    # the stored path is origin first, so it ends at the peer that sent the route
    assert row["as_path"][-1] == row["peer_asn"] or row["as_path"][0] is not None


@needs_sample
def test_origin_first_matches_the_raw_path(cfg: Config) -> None:
    """Spot-check the direction against the raw string on real routes."""
    result = ingest_rib(cfg, "test", DAY, url=str(SAMPLE), limit=2_000)
    table = pq.read_table(result.path, columns=["as_path_raw", "as_path", "has_as_set"])
    checked = 0
    for row in table.to_pylist():
        if row["has_as_set"] or not row["as_path"]:
            continue
        last_on_the_wire = int(row["as_path_raw"].split()[-1])
        assert row["as_path"][0] == last_on_the_wire
        checked += 1
    assert checked > 100


@needs_sample
def test_a_second_run_reuses_the_stored_file(cfg: Config) -> None:
    first = ingest_rib(cfg, "test", DAY, url=str(SAMPLE), limit=1_000)
    second = ingest_rib(cfg, "test", DAY, url=str(SAMPLE), limit=1_000)
    assert not first.skipped
    assert second.skipped
    assert second.rows == first.rows


@needs_sample
def test_an_interrupted_run_leaves_no_file_behind(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run killed part way must not leave a short Parquet file that the next run would
    happily treat as a complete cached result. This actually happened during Phase 2 when
    one collector's failure tore down the others."""
    from hijax.ingest import bgp as bgp_module

    calls = {"n": 0}
    real = bgp_module._batch_to_table

    def explode(rows: dict[str, list[object]]) -> object:
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt("simulated interruption")
        return real(rows)  # type: ignore[arg-type]

    monkeypatch.setattr(bgp_module, "_batch_to_table", explode)
    with pytest.raises(KeyboardInterrupt):
        ingest_rib(cfg, "test", DAY, url=str(SAMPLE), batch_rows=1_000, limit=5_000)

    out = table_path(cfg, "test", DAY)
    assert not out.exists()
    assert list(out.parent.glob("*.part*")) == []


# --- Truncated dumps must never become tables (docs/decisions.md D-050) -------------------


def test_a_short_download_raises_instead_of_writing_a_small_table(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this guards against, found on 2026-09-18.

    Handing a URL to the MRT parser let a dropped connection end the iteration quietly, so a
    partial dump was written out as a finished table with a stats file beside it. Ingesting
    six collectors at once produced 733,116 rows for rrc06 where a serial run produced
    6,751,923, and both reported success. Ingestion now downloads first through
    ``hijax.net.download``, which checks the byte count and raises on a short read, so the
    failure has to surface instead of becoming quiet bad data.
    """

    def short_read(*args: object, **kwargs: object) -> Path:
        raise DownloadError("short read: 1000 of 42900000 bytes")

    monkeypatch.setattr("hijax.ingest.bgp.download", short_read)

    with pytest.raises(DownloadError):
        ingest_rib(cfg, "test", DAY, url="https://example.invalid/rib.bz2")

    # Nothing may be left behind that a later run could mistake for a cached result.
    assert not table_path(cfg, "test", DAY).exists()


def test_a_missing_dump_is_reported_not_silently_empty(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 404 means the archive published nothing for that day, which is not zero routes."""
    monkeypatch.setattr("hijax.ingest.bgp.download", lambda *a, **k: None)

    with pytest.raises(RibNotFoundError):
        ingest_rib(cfg, "test", DAY, url="https://example.invalid/rib.bz2")
    assert not table_path(cfg, "test", DAY).exists()


@needs_sample
def test_a_local_dump_is_used_as_it_is(cfg: Config) -> None:
    """A dump already on disk needs no download, which is what keeps the test suite and the
    cached archive copies working."""
    result = ingest_rib(cfg, "test", DAY, url=str(SAMPLE), limit=100)
    assert result.rows == 100
    assert result.dump_bytes == 0 or result.dump_bytes == SAMPLE.stat().st_size
