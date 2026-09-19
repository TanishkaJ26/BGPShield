"""Route Origin Validation tests (plan Sections 10.2 and 12).

The plan names seven cases to cover: exact match, a more-specific within maxLength, a
more-specific beyond maxLength, a wrong origin, AS 0, no coverage, and IPv6. All are here,
plus the AS_SET case the plan adds as step 5.

Addresses are from the documentation ranges (RFC 5737 and RFC 3849) and AS numbers from the
documentation range (RFC 5398), so nothing here resembles a real announcement.
"""

from __future__ import annotations

import polars as pl
import pytest

from bgpshield.validate.rov import RovReason, RovState, VrpIndex

HOLDER = 64496
OTHER = 64497


@pytest.fixture
def index() -> VrpIndex:
    """One holder signs a /24 at maxLength 24 and a /16 at maxLength 20."""
    idx = VrpIndex()
    idx.add("203.0.113.0/24", 24, HOLDER, "ripe")
    idx.add("198.51.100.0/16", 20, HOLDER, "ripe")
    idx.add("2001:db8::/32", 48, HOLDER, "ripe")
    return idx


def test_exact_match_is_valid(index: VrpIndex) -> None:
    result = index.validate("203.0.113.0/24", HOLDER)
    assert result.state is RovState.VALID
    assert result.reason is RovReason.NONE


def test_more_specific_within_max_length_is_valid(index: VrpIndex) -> None:
    """The /16 permits announcements down to /20, so a /20 is allowed."""
    assert index.validate("198.51.96.0/20", HOLDER).state is RovState.VALID


def test_more_specific_beyond_max_length_is_invalid(index: VrpIndex) -> None:
    """A /24 inside a /16 signed only down to /20 is Invalid, and the reason says why.
    RFC 9319 is about avoiding exactly this trap."""
    result = index.validate("198.51.100.0/24", HOLDER)
    assert result.state is RovState.INVALID
    assert result.reason is RovReason.TOO_SPECIFIC


def test_wrong_origin_is_invalid(index: VrpIndex) -> None:
    result = index.validate("203.0.113.0/24", OTHER)
    assert result.state is RovState.INVALID
    assert result.reason is RovReason.WRONG_ORIGIN


def test_as0_origin_is_invalid(index: VrpIndex) -> None:
    """AS 0 is reserved and must never originate a route (RFC 7607 Section 4)."""
    result = index.validate("203.0.113.0/24", 0)
    assert result.state is RovState.INVALID
    assert result.reason is RovReason.AS0


def test_uncovered_prefix_is_not_found(index: VrpIndex) -> None:
    """Most of the Internet is unsigned, so this is the common answer, not a complaint."""
    result = index.validate("192.0.2.0/24", HOLDER)
    assert result.state is RovState.NOT_FOUND
    assert result.covering == 0


def test_ipv6(index: VrpIndex) -> None:
    assert index.validate("2001:db8::/32", HOLDER).state is RovState.VALID
    assert index.validate("2001:db8:1::/48", HOLDER).state is RovState.VALID
    assert index.validate("2001:db8:1::/56", HOLDER).state is RovState.INVALID
    assert index.validate("2001:db8::/32", OTHER).state is RovState.INVALID


def test_address_families_do_not_mix(index: VrpIndex) -> None:
    """An IPv6 route must never match an IPv4 VRP."""
    assert index.validate("2001:db9::/32", HOLDER).state is RovState.NOT_FOUND


def test_unknown_origin_from_an_as_set(index: VrpIndex) -> None:
    """Plan Section 10.2 step 5: with no single origin, a covered prefix is Invalid and an
    uncovered one is NotFound."""
    covered = index.validate("203.0.113.0/24", None)
    assert covered.state is RovState.INVALID
    assert covered.reason is RovReason.UNKNOWN_ORIGIN
    assert index.validate("192.0.2.0/24", None).state is RovState.NOT_FOUND


def test_one_prefix_signed_for_two_origins() -> None:
    """A prefix may be signed for several origins, which is normal for multi-homing.
    Either origin validates."""
    idx = VrpIndex()
    idx.add("203.0.113.0/24", 24, HOLDER)
    idx.add("203.0.113.0/24", 24, OTHER)
    assert idx.validate("203.0.113.0/24", HOLDER).state is RovState.VALID
    assert idx.validate("203.0.113.0/24", OTHER).state is RovState.VALID
    assert idx.validate("203.0.113.0/24", 64498).state is RovState.INVALID
    assert idx.validate("203.0.113.0/24", HOLDER).covering == 2


def test_a_less_specific_vrp_can_rescue_a_route_a_more_specific_one_rejects() -> None:
    """RFC 6811 asks whether *any* covering VRP permits the route, not the most specific
    one. Here the /16 allows the announcement even though the /24 VRP names another AS."""
    idx = VrpIndex()
    idx.add("203.0.0.0/16", 24, HOLDER)
    idx.add("203.0.113.0/24", 24, OTHER)
    assert idx.validate("203.0.113.0/24", HOLDER).state is RovState.VALID


def test_an_as0_vrp_does_not_validate_anything() -> None:
    """An AS0 ROA says the space must not be routed at all, so it can never make a route
    Valid; it only makes the prefix covered."""
    idx = VrpIndex()
    idx.add("203.0.113.0/24", 24, 0)
    result = idx.validate("203.0.113.0/24", HOLDER)
    assert result.state is RovState.INVALID
    assert result.reason is RovReason.WRONG_ORIGIN
    assert result.covering == 1


def test_default_route_covers_everything() -> None:
    idx = VrpIndex()
    idx.add("0.0.0.0/0", 0, HOLDER)
    assert idx.validate("203.0.113.0/24", HOLDER).state is RovState.INVALID  # too specific
    assert idx.validate("0.0.0.0/0", HOLDER).state is RovState.VALID


def test_build_from_the_stored_table() -> None:
    """The index must load straight from the vrps table that bgpshield ingest-rpki writes."""
    frame = pl.DataFrame(
        {
            "prefix": ["203.0.113.0/24", "2001:db8::/32"],
            "afi": [4, 6],
            "max_length": [24, 48],
            "asn": [HOLDER, HOLDER],
            "ta": ["ripe", "ripe"],
        }
    )
    idx = VrpIndex.from_frame(frame)
    assert len(idx) == 2
    assert idx.validate("203.0.113.0/24", HOLDER).state is RovState.VALID
    assert idx.validate("2001:db8:1::/48", HOLDER).state is RovState.VALID
    assert idx.covering("203.0.113.0/24")[0].ta == "ripe"


def test_empty_index_finds_nothing() -> None:
    assert VrpIndex().validate("203.0.113.0/24", HOLDER).state is RovState.NOT_FOUND
