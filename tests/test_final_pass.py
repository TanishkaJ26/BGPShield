"""Regressions for the bugs found in the pre-launch testing pass.

Each test here stands for a defect that shipped code actually had. They are grouped in one
file because they share nothing but their origin: a systematic run over every feature
before release.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from bgpshield.config import _project_root, load_config
from bgpshield.counterfactual import Filtering, Outcome, Publication, summarise
from bgpshield.net import _content_length, _retry_delay
from bgpshield.validate.run import load_aspa_registry

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- config root


def test_project_root_for_the_normal_layout(tmp_path: Path) -> None:
    """``<root>/config/default.yaml`` resolves data paths against ``<root>``."""
    assert _project_root(tmp_path / "config" / "default.yaml") == tmp_path


def test_project_root_for_a_config_outside_a_config_directory(tmp_path: Path) -> None:
    """A file passed with --config need not live in a ``config/`` directory.

    Assuming it does put every relative data path one level too high, so an ingest would
    write beside the repository instead of inside it.
    """
    assert _project_root(tmp_path / "my.yaml") == tmp_path


def test_a_config_outside_config_dir_keeps_data_beside_itself(tmp_path: Path) -> None:
    source = (REPO / "config" / "default.yaml").read_text(encoding="utf-8")
    target = tmp_path / "my.yaml"
    target.write_text(source, encoding="utf-8")
    cfg = load_config(target)
    assert cfg.root == tmp_path
    assert cfg.paths.raw == tmp_path / "data" / "raw"


# ------------------------------------------------------------------------------ downloads


def test_a_transfer_encoded_body_is_not_rejected_as_short() -> None:
    """Content-Length counts compressed bytes; iter_content yields decoded ones.

    Comparing the two rejects a good file on every attempt, which would turn a working
    archive into a hard failure. The check is skipped when the server encoded the body.
    """
    from types import SimpleNamespace

    from bgpshield import net

    class Response:
        status_code = 200
        headers = {"Content-Length": "12", "Content-Encoding": "gzip"}

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def iter_content(self, chunk_size: int = 1) -> object:
            yield b"decoded body, longer than twelve bytes"

        def raise_for_status(self) -> None:
            return None

    session = SimpleNamespace(get=lambda *a, **k: Response())
    dest = Path(__file__).parent / "_encoded.tmp"
    try:
        got = net.download(session, "https://example.invalid/f", dest, pause=0)  # type: ignore[arg-type]
        assert got == dest
        assert dest.read_bytes() == b"decoded body, longer than twelve bytes"
    finally:
        dest.unlink(missing_ok=True)


def test_content_length_helper_rejects_nonsense() -> None:
    assert _content_length("12") == 12
    assert _content_length(None) is None
    assert _content_length("banana") is None


def test_backoff_is_exponential_and_retry_after_wins() -> None:
    assert [_retry_delay(None, n, 0.5) for n in (1, 2, 3)] == [0.5, 1.0, 2.0]
    assert _retry_delay("3", 1, 0.5) == 3.0


# ------------------------------------------------------------- U-SPAS across trust anchors


def test_providers_are_unioned_across_trust_anchors(tmp_path: Path) -> None:
    """One customer, two anchors, one effective provider set.

    ``draft-ietf-sidrops-aspa-verification-28`` Section 5.3 defines U-SPAS as the union over
    all of a customer's valid ASPAs. A snapshot stores one row per (customer, anchor), so
    keeping only the last row would drop real providers and report a legitimate hop through
    the dropped provider as Invalid.
    """
    day = date(2026, 9, 1)
    out = tmp_path / "processed" / "aspas" / f"snapshot_date={day:%Y-%m-%d}"
    out.mkdir(parents=True)
    pl.DataFrame(
        {
            "customer_asn": [64500, 64500, 64501],
            "provider_asns": [[65001], [65002, 65003], [65010]],
            "ta": ["ripe", "arin", "ripe"],
        }
    ).write_parquet(out / "aspas.parquet")

    base = load_config(REPO / "config" / "default.yaml")
    cfg = base.model_copy(
        update={"paths": base.paths.model_copy(update={"processed": tmp_path / "processed"})}
    )

    registry = load_aspa_registry(cfg, day)
    assert registry.providers_of(64500) == frozenset({65001, 65002, 65003})
    assert registry.providers_of(64501) == frozenset({65010})


# ------------------------------------------------------------------------- a real median


def _outcome(position: float) -> Outcome:
    return Outcome(
        publication=Publication.S1,
        filtering=Filtering.F_ALL,
        blocked=True,
        blocking_position=1,
        relative_position=position,
    )


def test_median_blocking_position_is_a_real_median() -> None:
    """With an even count the median is the mean of the two middle values.

    Taking ``sorted(seen)[len(seen) // 2]`` returns the upper of the two, which is not a
    median and was published under that name.
    """
    frame = summarise([_outcome(0.2), _outcome(0.4), _outcome(0.6), _outcome(0.8)])
    assert frame["median_blocking_position"][0] == pytest.approx(0.5)


def test_median_blocking_position_with_an_odd_count() -> None:
    frame = summarise([_outcome(0.2), _outcome(0.4), _outcome(0.9)])
    assert frame["median_blocking_position"][0] == pytest.approx(0.4)


def test_no_blocked_routes_reports_no_median() -> None:
    frame = summarise(
        [
            Outcome(
                publication=Publication.S0,
                filtering=Filtering.F_ALL,
                blocked=False,
            )
        ]
    )
    assert frame["median_blocking_position"][0] is None
    assert frame["blocked_share"][0] == 0.0


# ------------------------------------------------------- curated fields are read by real name


def test_reading_an_unknown_incident_field_raises() -> None:
    """``getattr(obj, name, default)`` cannot tell a missing value from a misspelled field.

    That is how the incidents page came to promise a primary post-mortem for every entry and
    link to none: the exporter asked for ``source`` and ``title``, neither of which exists on
    ``Incident``, and the default published an empty string for three years of curation.
    """
    from bgpshield.cli import _incident_field

    with pytest.raises(AttributeError, match="no field 'source'"):
        _incident_field({}, "whatever", "source", "")
    with pytest.raises(AttributeError, match="no field 'title'"):
        _incident_field({}, "whatever", "title", "")


def test_a_real_incident_field_is_returned_and_a_missing_entry_falls_back() -> None:
    from pathlib import Path as _Path

    from bgpshield.cli import _incident_field
    from bgpshield.incidents import load_incidents

    curated = load_incidents(REPO / "config" / "incidents.yaml")
    assert curated, "the curated incident list should not be empty"
    by_id = {incident.id: incident for incident in curated}
    first = curated[0]

    assert _incident_field(by_id, first.id, "description", "") == first.description
    assert _incident_field(by_id, first.id, "sources", ()) == first.sources
    # Every curated entry cites at least one primary source; the site renders them.
    assert all(incident.sources for incident in curated)
    assert _incident_field(by_id, "no-such-incident", "description", "") == ""
    assert isinstance(REPO / "config" / "incidents.yaml", _Path)


# ------------------------------------------------------------------ stale dashboard files


def _empty_cfg(tmp_path: Path):  # type: ignore[no-untyped-def]
    base = load_config(REPO / "config" / "default.yaml")
    return base.model_copy(
        update={"paths": base.paths.model_copy(update={"processed": tmp_path / "empty"})}
    )


def test_a_skipped_export_reports_a_file_describing_another_date(tmp_path: Path) -> None:
    """A skip leaves the previous run's file, describing some other date, still published.

    ``export_date`` exists so every exported file describes one day. A leftover defeats that
    while looking entirely normal on the site, so it has to be named.
    """
    from bgpshield.export import _describes_another_date

    out = tmp_path / "web"
    out.mkdir()
    stale = out / "networks.json"
    stale.write_text('{"snapshot_date": "1999-01-01"}', encoding="utf-8")
    assert _describes_another_date(stale, date(2026, 9, 1))
    assert not _describes_another_date(stale, date(1999, 1, 1))


def test_a_curated_file_with_no_date_is_never_called_stale(tmp_path: Path) -> None:
    """The incident results are a fixed set of historical events, not a view of one day.

    They are deliberately not regenerated by the daily job (D-063) and carry no
    ``snapshot_date``. Flagging them would print a warning on every run and train everyone
    to ignore the one message meant to matter.
    """
    from bgpshield.export import _describes_another_date

    out = tmp_path / "web"
    out.mkdir()
    curated = out / "incidents.json"
    curated.write_text('{"incidents": [], "summary": {}}', encoding="utf-8")
    assert not _describes_another_date(curated, date(2026, 9, 1))
    assert not _describes_another_date(out / "missing.json", date(2026, 9, 1))


def test_the_budget_counts_every_published_file(tmp_path: Path) -> None:
    """Including ones kept from an earlier run: a clone pays for whatever is in the folder."""
    from bgpshield.export import build_all

    out = tmp_path / "web"
    out.mkdir()
    (out / "incidents.json").write_text('{"incidents": []}', encoding="utf-8")
    (out / "aspa_adoption.json").write_text('{"by_day": []}', encoding="utf-8")
    expected = sum(f.stat().st_size for f in out.glob("*.json"))

    result = build_all(_empty_cfg(tmp_path), destination=out)
    assert result.written == []
    assert result.stale == []
    assert result.total_bytes == expected
