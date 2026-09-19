"""Unit tests for the delegated-stats parser (plan Sections 8 and 12).

The sample below is hand-built in the RIR statistics exchange format, using AS numbers
reserved for documentation (RFC 5398) and the real quirks seen in Phase 0: a comment
header, a version line, summary lines, ARIN's ``assigned`` instead of ``allocated``, and
unissued rows that must be skipped.
"""

from __future__ import annotations

import pytest

from bgpshield.ingest.meta import (
    AsnBlock,
    DelegatedFormatError,
    expand,
    parse_delegated,
    registry_frame,
)

SAMPLE = """\
# this is a comment header, as APNIC's file has
2.3|apnic|20260918|190026||20260917|+1000
apnic|*|asn|*|14747|summary
apnic|JP|asn|173|1|20020801|allocated|A91A4B1A
apnic|IN|asn|64496|4|20200101|allocated|DEADBEEF
apnic|AU|asn|64500|1|20200101|reserved|CAFE
apnic||asn|64501|1|20200101|available|
arin|US|asn|64510|1|20010920|assigned|e5e3b9c13678
apnic|IN|ipv4|203.0.113.0|256|20200101|allocated|FEED
"""


def test_parse_delegated_keeps_only_delegated_asn_rows() -> None:
    blocks = parse_delegated(SAMPLE.splitlines())
    assert blocks == [
        AsnBlock(first=173, count=1, country="JP", rir="apnic", status="allocated"),
        AsnBlock(first=64496, count=4, country="IN", rir="apnic", status="allocated"),
        AsnBlock(first=64510, count=1, country="US", rir="arin", status="assigned"),
    ]


def test_reserved_available_and_non_asn_rows_are_skipped() -> None:
    blocks = parse_delegated(SAMPLE.splitlines())
    kinds = {b.status for b in blocks}
    assert kinds == {"allocated", "assigned"}
    assert all(b.first != 64500 for b in blocks)  # reserved
    assert all(b.first != 64501 for b in blocks)  # available


def test_expand_turns_a_count_into_one_row_per_as_number() -> None:
    rows = list(expand([AsnBlock(64496, 4, "IN", "apnic", "allocated")]))
    assert [r[0] for r in rows] == [64496, 64497, 64498, 64499]
    assert {r[1] for r in rows} == {"IN"}


def test_registry_frame_shape_and_lookup() -> None:
    frame = registry_frame(parse_delegated(SAMPLE.splitlines()))
    assert frame.columns == ["asn", "country", "rir", "status"]
    assert frame.height == 6  # 1 + 4 + 1
    row = frame.filter(frame["asn"] == 64498).to_dicts()[0]
    assert row["country"] == "IN"
    assert row["rir"] == "apnic"


def test_registry_frame_keeps_one_row_per_as_number() -> None:
    """Two registries listing the same AS number must not double it."""
    blocks = [
        AsnBlock(64496, 1, "IN", "apnic", "allocated"),
        AsnBlock(64496, 1, "US", "arin", "assigned"),
    ]
    assert registry_frame(blocks).height == 1


@pytest.mark.parametrize(
    "line",
    [
        "apnic|IN|asn|notanumber|1|20200101|allocated|X",
        "apnic|IN|asn|64496|0|20200101|allocated|X",
        "apnic|IN|asn|4294967295|2|20200101|allocated|X",
    ],
)
def test_malformed_rows_raise_instead_of_being_guessed(line: str) -> None:
    with pytest.raises(DelegatedFormatError):
        parse_delegated([line])


def test_empty_input() -> None:
    assert parse_delegated([]) == []
    assert registry_frame([]).height == 0
