"""Unit tests for AS_PATH normalization (plan Sections 10.1 and 12).

Every path here is hand-built, except where a docstring says it was copied from a real
sample, in which case it is quoted exactly so the test pins observed behaviour.

The convention under test: a normalized path is **origin first**.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bgpshield.paths import (
    AS_TRANS,
    NormalizedPath,
    PathFlag,
    _normalize_general,
    collapse_prepending,
    is_private_asn,
    is_reserved_asn,
    normalize,
    parse_segments,
)


def test_direction_is_origin_first() -> None:
    """The raw path reads neighbour first; the normalized one reads origin first."""
    result = normalize("57866 5511 57976", peer_asn=57866)
    assert result.as_path == (57976, 5511, 57866)
    assert result.as_path[0] == result.origin_asn == 57976
    assert result.as_path[-1] == 57866  # the collector's peer


def test_single_as_path() -> None:
    """A route from a peer that originates the prefix itself."""
    result = normalize("13335", peer_asn=13335)
    assert result.as_path == (13335,)
    assert result.origin_asn == 13335
    assert result.flags == frozenset()
    assert result.usable


def test_prepending_is_collapsed() -> None:
    """Real path from the RIS sample: AS 147094 prepends itself four times."""
    raw = "59919 9002 3356 58453 147094 147094 147094 147094 38496 10217 4800 7717 38759 7587"
    result = normalize(raw, peer_asn=59919)
    assert result.as_path.count(147094) == 1
    assert result.origin_asn == 7587
    assert result.as_path[-1] == 59919
    assert PathFlag.LOOP not in result.flags


def test_prepending_at_both_ends() -> None:
    result = normalize("100 100 200 300 300 300", peer_asn=100)
    assert result.as_path == (300, 200, 100)


def test_four_byte_asn() -> None:
    result = normalize("59919 396998", peer_asn=59919)
    assert result.origin_asn == 396998


def test_as_set_at_the_end_leaves_the_origin_unknown() -> None:
    """Real path from the Jakarta RIB sample. The plan (Section 10.1 step 2) says the
    origin is null when the path ends in an AS_SET, because no single member of the set is
    the origin. pybgpkit disagrees and reports a member; we deliberately do not."""
    result = normalize("32787 10100 {10100}", peer_asn=32787)
    assert result.has_as_set
    assert result.origin_asn is None
    assert PathFlag.AS_SET in result.flags
    # the set member is not part of the numeric path; the sequence part is kept
    assert result.as_path == (10100, 32787)


def test_as_set_in_the_middle() -> None:
    """The parser's own doctest uses this shape: '1 2 {3,4} 5 6 {7} 8'."""
    result = normalize("1 2 {3,4} 5 6 {7} 8", peer_asn=1)
    assert result.has_as_set
    # sets are dropped from the numeric path, sequence members are kept, origin first
    assert result.as_path == (8, 6, 5, 2, 1)
    # the path does not end in a set, so the origin is known
    assert result.origin_asn == 8


def test_multi_member_as_set_is_parsed_with_commas() -> None:
    segments = parse_segments("1 {2,3,4} 5")
    assert segments == [(False, [1]), (True, [2, 3, 4]), (False, [5])]


def test_as_set_with_spaces_inside_is_tolerated() -> None:
    """Defensive: the parser writes commas, but a space-separated set must not crash."""
    assert parse_segments("{2, 3}") == [(True, [2, 3])]


def test_loop_is_flagged() -> None:
    """A non-consecutive repeat is a real loop, unlike prepending."""
    result = normalize("100 200 100", peer_asn=100)
    assert PathFlag.LOOP in result.flags
    assert not result.usable


def test_prepending_is_not_mistaken_for_a_loop() -> None:
    result = normalize("100 200 200 300", peer_asn=100)
    assert PathFlag.LOOP not in result.flags
    assert result.usable


@pytest.mark.parametrize("asn", [64512, 65000, 65534, 4_200_000_000, 4_294_967_294])
def test_private_asns(asn: int) -> None:
    """RFC 6996 Section 5."""
    assert is_private_asn(asn)
    assert PathFlag.PRIVATE_ASN in normalize(f"100 {asn} 300", peer_asn=100).flags


@pytest.mark.parametrize("asn", [1, 13335, 64511, 65535, 65536, 4_294_967_295])
def test_non_private_asns(asn: int) -> None:
    assert not is_private_asn(asn)


@pytest.mark.parametrize("asn", [0, 65535, 4_294_967_295, 64496, 64511, 65536, 65551])
def test_reserved_asns(asn: int) -> None:
    """AS 0 is RFC 7607; the last of each range is RFC 7300; documentation is RFC 5398."""
    assert is_reserved_asn(asn)
    assert PathFlag.RESERVED_ASN in normalize(f"100 {asn} 300", peer_asn=100).flags


def test_as_trans_is_flagged_separately() -> None:
    """AS 23456 stands in for a 4-byte AS number at an old speaker (RFC 6793 Section 4.1)."""
    result = normalize(f"100 {AS_TRANS} 300", peer_asn=100)
    assert PathFlag.AS_TRANS in result.flags
    assert PathFlag.PRIVATE_ASN not in result.flags
    assert not result.usable


def test_peer_mismatch_is_recorded_not_dropped() -> None:
    """Some collectors and route servers strip their own AS, so this is a flag, not a
    fatal error (plan Section 10.1 step 5)."""
    result = normalize("5511 57976", peer_asn=57866)
    assert PathFlag.PEER_MISMATCH in result.flags
    assert result.usable  # still usable for relationship analysis
    assert result.origin_asn == 57976


def test_peer_match_sets_no_flag() -> None:
    assert PathFlag.PEER_MISMATCH not in normalize("57866 5511", peer_asn=57866).flags


def test_peer_asn_unknown_means_no_mismatch_check() -> None:
    assert PathFlag.PEER_MISMATCH not in normalize("5511 57976").flags


def test_empty_and_missing_paths() -> None:
    """Withdrawals carry no AS_PATH at all; pybgpkit reports None for them."""
    for raw in (None, "", "   "):
        result = normalize(raw)
        assert result.flags == frozenset({PathFlag.EMPTY})
        assert result.as_path == ()
        assert result.origin_asn is None
        assert not result.usable


def test_path_of_only_a_set() -> None:
    result = normalize("{1,2}")
    assert result.has_as_set
    assert result.as_path == ()
    assert PathFlag.EMPTY in result.flags
    assert result.origin_asn is None


def test_collapse_prepending_directly() -> None:
    assert collapse_prepending([1, 1, 2, 2, 2, 3]) == [1, 2, 3]
    assert collapse_prepending([1, 2, 1]) == [1, 2, 1]  # a loop survives collapsing
    assert collapse_prepending([]) == []


def test_normalized_path_is_hashable_and_frozen() -> None:
    result = normalize("100 200", peer_asn=100)
    assert isinstance(result, NormalizedPath)
    assert {result}  # usable as a dict key, so results can be counted


def test_transparent_route_server_looks_like_a_peer_mismatch() -> None:
    """A transparent IXP route server does not insert its own AS into the path
    (RFC 7947 Section 2.2.2), so the leftmost AS is the network behind it, not the peer the
    collector recorded. In the Jakarta RIB sample, two peers show this on every route and
    every other peer matches on every route.

    The ASPA verification draft handles the same case explicitly: its neighbour check has an
    exception for routes received from a transparent route server
    (draft-ietf-sidrops-aspa-verification-28 Sections 5.1 and 5.5 step 2).
    """
    result = normalize("20940", peer_asn=7597)
    assert PathFlag.PEER_MISMATCH in result.flags
    assert result.usable  # the path itself is fine; only the neighbour check is affected
    assert result.origin_asn == 20940


@given(
    asns=st.lists(st.integers(min_value=0, max_value=4_294_967_295), min_size=1, max_size=12),
    peer=st.one_of(st.none(), st.integers(min_value=0, max_value=4_294_967_295)),
)
def test_fast_and_general_paths_agree(asns: list[int], peer: int | None) -> None:
    """normalize() has a fast route for paths with no AS_SET. It must return exactly what
    the general implementation returns, for any path."""
    raw = " ".join(str(a) for a in asns)
    assert normalize(raw, peer_asn=peer) == _normalize_general(raw, peer)


@given(asns=st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=10))
def test_normalized_path_never_has_consecutive_duplicates(asns: list[int]) -> None:
    result = normalize(" ".join(str(a) for a in asns))
    pairs = zip(result.as_path, result.as_path[1:], strict=False)
    assert all(a != b for a, b in pairs)


@given(asns=st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=10))
def test_origin_first_is_the_reverse_of_the_wire_order(asns: list[int]) -> None:
    """The last AS on the wire is the origin, so it must come first after normalization."""
    result = normalize(" ".join(str(a) for a in asns))
    assert result.as_path[0] == asns[-1]
    assert result.as_path[-1] == asns[0]
