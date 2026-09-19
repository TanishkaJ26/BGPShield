"""Unit tests for the RPKI snapshot adapters (plan Sections 9 and 12).

The two fixtures below are hand-built miniatures of the shapes Phase 0 verified against
real downloads. They are not copies of real data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from bgpshield.ingest.rpki import (
    _Parsed,
    aspas_frame,
    canonical_ta,
    date_range,
    deduplicate,
    detect_format,
    parse_routinator,
    parse_rpki_client,
    parse_snapshot,
    vrps_frame,
)
from bgpshield.models import Aspa, RecordFormatError, Vrp

ROUTINATOR_SNAPSHOT: dict[str, Any] = {
    "metadata": {"generated": 1789533333, "generatedTime": "2026-09-16T04:35:33Z"},
    "roas": [
        {"asn": "AS64496", "prefix": "203.0.113.0/24", "maxLength": 24, "ta": "ripencc"},
        {"asn": "AS64496", "prefix": "2001:db8::/32", "maxLength": 48, "ta": "ripencc"},
        # the identical VRP twice, as two different ROAs can produce
        {"asn": "AS64496", "prefix": "203.0.113.0/24", "maxLength": 24, "ta": "ripencc"},
    ],
    "routerKeys": [],
    "aspas": [
        {"customer": "AS64497", "providers": ["AS64499", "AS64498"], "ta": "ripencc"},
        {"customer": "AS64500", "providers": ["AS64499"], "ta": "ripencc"},
    ],
}

RPKI_CLIENT_SNAPSHOT: dict[str, Any] = {
    "metadata": {"buildtime": "2026-09-16T00:06:05Z", "vrps": 2, "aspas": 2},
    "roas": [
        {
            "asn": 64496,
            "prefix": "203.0.113.0/24",
            "maxLength": 24,
            "ta": "ripe",
            "expires": 1790000255,
        },
        {
            "asn": 64496,
            "prefix": "198.51.100.0/24",
            "maxLength": 25,
            "ta": "apnic",
            "expires": 1790000255,
        },
    ],
    "bgpsec_keys": [],
    "aspas": [
        {"customer_asid": 64497, "expires": 1789657200, "providers": [64499, 64498]},
        {"customer_asid": 64501, "expires": 1789657200, "providers": [0]},
    ],
    "signedprefixlists": [],
}


def test_detect_format_from_metadata() -> None:
    assert detect_format(ROUTINATOR_SNAPSHOT) == "routinator"
    assert detect_format(RPKI_CLIENT_SNAPSHOT) == "rpki-client"


def test_detect_format_falls_back_to_record_shape() -> None:
    assert detect_format({"aspas": [{"customer_asid": 1, "providers": [2]}]}) == "rpki-client"
    assert detect_format({"aspas": [{"customer": "AS1", "providers": ["AS2"]}]}) == "routinator"


def test_detect_format_refuses_to_guess() -> None:
    with pytest.raises(RecordFormatError):
        detect_format({"roas": []})


def test_canonical_ta_maps_routinator_spelling() -> None:
    """Routinator says 'ripencc'; the plan's Section 9 table says 'ripe'."""
    assert canonical_ta("ripencc") == "ripe"
    assert canonical_ta("ripe") == "ripe"
    assert canonical_ta("apnic.tal") == "apnic"
    assert canonical_ta(None) is None
    with pytest.raises(RecordFormatError):
        canonical_ta("not-a-trust-anchor")


def test_routinator_adapter() -> None:
    parsed = parse_routinator(ROUTINATOR_SNAPSHOT)
    assert parsed.vrps[0] == Vrp("203.0.113.0/24", 4, 24, 64496, "ripe")
    assert parsed.vrps[1].afi == 6
    # providers come back sorted even though the fixture lists them out of order
    assert parsed.aspas[0] == Aspa(64497, (64498, 64499), "ripe", None)


def test_rpki_client_adapter() -> None:
    parsed = parse_rpki_client(RPKI_CLIENT_SNAPSHOT)
    assert parsed.vrps[0] == Vrp("203.0.113.0/24", 4, 24, 64496, "ripe")
    assert parsed.vrps[1].ta == "apnic"
    first = parsed.aspas[0]
    assert first.customer_asn == 64497
    assert first.provider_asns == (64498, 64499)
    assert first.expires == datetime(2026, 9, 17, 15, 0, tzinfo=UTC)
    # rpki-client does not label ASPA records with a trust anchor
    assert first.ta is None
    # AS 0 as the only provider means "I have no providers"
    assert parsed.aspas[1].provider_asns == (0,)


def test_rpki_client_ta_fallback_is_used_when_the_file_omits_it() -> None:
    parsed = parse_rpki_client(RPKI_CLIENT_SNAPSHOT, ta_fallback="lacnic")
    assert parsed.aspas[0].ta == "lacnic"


def test_parse_snapshot_dispatches_on_format() -> None:
    assert parse_snapshot(ROUTINATOR_SNAPSHOT).aspas[0].customer_asn == 64497
    assert parse_snapshot(RPKI_CLIENT_SNAPSHOT).aspas[0].customer_asn == 64497


def test_adapter_reports_a_missing_field_instead_of_guessing() -> None:
    with pytest.raises(RecordFormatError, match="customer"):
        parse_routinator({"aspas": [{"providers": ["AS1"]}]})
    with pytest.raises(RecordFormatError, match="maxLength"):
        parse_routinator({"roas": [{"asn": "AS1", "prefix": "203.0.113.0/24", "ta": "ripe"}]})


def test_deduplicate_collapses_identical_vrps() -> None:
    vrps, _, stats = deduplicate(parse_routinator(ROUTINATOR_SNAPSHOT))
    assert stats.roa_rows == 3
    assert stats.vrps_unique == 2
    assert len(vrps) == 2


def test_deduplicate_unions_a_customers_multiple_aspas() -> None:
    """draft-ietf-sidrops-aspa-verification-28 Section 5.3: when a customer AS has several
    valid ASPAs, the effective provider set is the union of them all (the "U-SPAS")."""
    parsed = _Parsed(
        vrps=[],
        aspas=[
            Aspa(64497, (64498,), "ripe", datetime(2027, 1, 1, tzinfo=UTC)),
            Aspa(64497, (64499,), "ripe", datetime(2026, 12, 1, tzinfo=UTC)),
        ],
    )
    _, aspas, stats = deduplicate(parsed)
    assert len(aspas) == 1
    assert aspas[0].provider_asns == (64498, 64499)
    assert stats.aspas_merged == 1
    # the earlier expiry wins, because that is when the union stops being fully backed
    assert aspas[0].expires == datetime(2026, 12, 1, tzinfo=UTC)


def test_deduplicate_keeps_different_trust_anchors_apart() -> None:
    parsed = _Parsed(
        vrps=[],
        aspas=[Aspa(64497, (64498,), "ripe", None), Aspa(64497, (64499,), "apnic", None)],
    )
    _, aspas, stats = deduplicate(parsed)
    assert len(aspas) == 2
    assert stats.aspas_merged == 0


def test_deduplicate_counts_as0_records() -> None:
    _, _, stats = deduplicate(parse_rpki_client(RPKI_CLIENT_SNAPSHOT))
    assert stats.providers_as0 == 1


def test_frames_match_the_section_9_schema() -> None:
    day = date(2026, 9, 16)
    vrps, aspas, _ = deduplicate(parse_routinator(ROUTINATOR_SNAPSHOT))
    vframe = vrps_frame(vrps, day)
    aframe = aspas_frame(aspas, day)
    assert vframe.columns == ["prefix", "afi", "max_length", "asn", "ta", "snapshot_date"]
    assert aframe.columns == ["customer_asn", "provider_asns", "ta", "expires", "snapshot_date"]
    assert str(vframe.schema["afi"]) == "Int8"
    assert str(aframe.schema["provider_asns"]) == "List(Int64)"
    assert vframe["snapshot_date"].to_list() == [day, day]
    assert aframe["provider_asns"].to_list() == [[64498, 64499], [64499]]


def test_empty_snapshot_produces_empty_but_typed_frames() -> None:
    frame = aspas_frame([], date(2026, 9, 16))
    assert frame.height == 0
    assert str(frame.schema["provider_asns"]) == "List(Int64)"


def test_date_range_weekly_backfill() -> None:
    days = date_range(date(2023, 10, 11), date(2023, 11, 1), 7)
    assert days == [date(2023, 10, 11), date(2023, 10, 18), date(2023, 10, 25), date(2023, 11, 1)]


def test_date_range_single_day_and_bad_input() -> None:
    assert date_range(date(2026, 9, 1), date(2026, 9, 1), 7) == [date(2026, 9, 1)]
    with pytest.raises(ValueError, match="--to"):
        date_range(date(2026, 9, 2), date(2026, 9, 1), 1)
    with pytest.raises(ValueError, match="--every"):
        date_range(date(2026, 9, 1), date(2026, 9, 2), 0)


def test_as0_alongside_real_providers_is_dropped_and_counted() -> None:
    """Profile Section 5.2 requires AS 0 to be removed from a provider set that has other
    members. Both validators emitted such records in the real 2026-09-16 snapshot."""
    snapshot = {
        "metadata": {"generatedTime": "2026-09-16T04:35:33Z"},
        "aspas": [
            {"customer": "AS64497", "providers": ["AS0", "AS64498"], "ta": "ripencc"},
            {"customer": "AS64501", "providers": ["AS0"], "ta": "ripencc"},
        ],
    }
    parsed = parse_routinator(snapshot)
    assert parsed.aspas[0].provider_asns == (64498,)
    assert parsed.aspas[1].provider_asns == (0,)
    assert parsed.as0_dropped == 1
    _, aspas, stats = deduplicate(parsed)
    assert stats.as0_dropped == 1
    assert stats.providers_as0 == 1  # only the genuine AS0 ASPA is counted as such


def test_union_of_an_as0_aspa_and_a_normal_one_drops_as0() -> None:
    """If a customer publishes both an AS0 ASPA and a normal one, the union has other
    members, so AS 0 goes (profile Section 5.2)."""
    parsed = _Parsed(
        vrps=[],
        aspas=[Aspa(64497, (0,), "ripe", None), Aspa(64497, (64498,), "ripe", None)],
    )
    _, aspas, stats = deduplicate(parsed)
    assert aspas[0].provider_asns == (64498,)
    assert stats.as0_dropped == 1
    assert stats.providers_as0 == 0


def test_ingest_date_combines_every_trust_anchor(tmp_path: Path, monkeypatch: Any) -> None:
    """End-to-end for one day with the network stubbed out.

    This also pins a bug worth not repeating: the per-registry AS 0 counts have to be
    summed across trust anchors, not thrown away when the parsed records are combined.
    """
    import json

    from bgpshield import config as config_module
    from bgpshield.ingest import rpki as rpki_module

    files: dict[str, Path] = {}
    for ta, customer in (("apnic", 64497), ("ripencc", 64500)):
        payload = {
            "metadata": {"generatedTime": "2026-09-16T04:35:33Z"},
            "roas": [{"asn": "AS64496", "prefix": "203.0.113.0/24", "maxLength": 24, "ta": ta}],
            # each registry contributes one record that breaks the AS 0 rule
            "aspas": [{"customer": f"AS{customer}", "providers": ["AS0", "AS64498"], "ta": ta}],
        }
        path = tmp_path / f"{ta}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        files[ta] = path

    cfg = config_module.load_config(Path("config/default.yaml")).model_copy(
        update={
            "paths": config_module.PathsConfig(
                raw=tmp_path / "raw",
                interim=tmp_path / "interim",
                processed=tmp_path / "processed",
                figures=tmp_path / "figures",
                web_data=tmp_path / "web",
            ),
            "rpki": config_module.load_config(Path("config/default.yaml")).rpki.model_copy(
                update={"trust_anchors": ["apnic", "ripencc"]}
            ),
        }
    )

    def fake_fetch(_cfg: Any, ta: str, _day: date, **_kw: Any) -> Path:
        return files[ta]

    monkeypatch.setattr(rpki_module, "fetch_archive_file", fake_fetch)
    result = rpki_module.ingest_date(cfg, date(2026, 9, 16))

    assert result.trust_anchors == ["apnic", "ripencc"]
    assert result.aspas == 2
    assert result.vrps == 2  # same prefix, different trust anchor, so both are kept
    assert result.as0_dropped == 2  # one from each registry, summed
    assert result.vrps_path is not None and result.vrps_path.exists()

    stored = pl.read_parquet(result.aspas_path)
    assert sorted(stored["provider_asns"].to_list()) == [[64498], [64498]]
