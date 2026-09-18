"""ASPA verification tests (plan Sections 10.3 and 12).

The plan requires **every worked example from the draft** as a test case. The draft
(draft-ietf-sidrops-aspa-verification-28 Section 6.1) publishes them separately, as
"ASPA-based AS Path Verification Examples" by Sriram, Borchert and Matejka, August 2025:
https://github.com/ksriram25/IETF/blob/main/ASPA_path_verification_examples.pdf

All 23 examples from that document are below: 9 upstream, 10 downstream, and 4 on a topology
with complex relationships. Each case also pins the four ramp lengths the document states,
not just the verdict, so a wrong answer reached by two cancelling mistakes still fails.

The document writes paths in wire order, neighbour first. This project stores them origin
first, so each case is reversed on the way in. That reversal is itself part of what these
tests check.
"""

from __future__ import annotations

import pytest

from hijax.validate.aspa import (
    AspaRegistry,
    AspaState,
    Authorized,
    Procedure,
    ramp_bounds,
    verify,
    verify_downstream,
    verify_upstream,
)

# Letters from the document, given arbitrary distinct AS numbers.
A, B, C, D, E, F, G = 101, 102, 103, 104, 105, 106, 107
H, J, K, L = 201, 202, 203, 204
P, Q, R, S = 205, 206, 207, 208

#: Topology 1 (document page 2). E and F publish nothing. G publishes an AS0 ASPA, which
#: states "I have no providers at all".
TOPOLOGY_1 = AspaRegistry(
    {
        A: {C, D},
        B: {E},
        C: {F},
        D: {F, G},
        G: {0},
    }
)

#: Topology 2 (document page 9), which has complex relationships. J publishes nothing.
TOPOLOGY_2 = AspaRegistry(
    {
        H: {0},
        K: {0},
        L: {K},
        P: {0},
        Q: {0},
        R: {Q},
        S: {R},
    }
)


def origin_first(wire_order: list[int]) -> tuple[int, ...]:
    """The document lists paths neighbour first; this project stores them origin first."""
    return tuple(reversed(wire_order))


# ---------------------------------------------------------------------------------------
# The provider authorization function (draft Section 5.3)
# ---------------------------------------------------------------------------------------


def test_authorized_three_outcomes() -> None:
    assert TOPOLOGY_1.authorized(A, C) is Authorized.PROVIDER_PLUS
    assert TOPOLOGY_1.authorized(A, E) is Authorized.NOT_PROVIDER_PLUS
    assert TOPOLOGY_1.authorized(E, A) is Authorized.NO_ATTESTATION


def test_an_as0_aspa_contradicts_every_candidate() -> None:
    """G says it has no providers, so naming any provider for G is a contradiction, not a
    gap in knowledge. This is the difference between having attested and not having."""
    assert TOPOLOGY_1.authorized(G, F) is Authorized.NOT_PROVIDER_PLUS
    assert TOPOLOGY_1.authorized(G, D) is Authorized.NOT_PROVIDER_PLUS
    assert TOPOLOGY_1.authorized(F, G) is Authorized.NO_ATTESTATION  # F published nothing


# ---------------------------------------------------------------------------------------
# Table 1: upstream path verification (document page 3)
# ---------------------------------------------------------------------------------------

UPSTREAM_CASES = [
    # (case number, wire-order path, N, max_up, min_up, expected)
    (1, [F, C, A], 3, 3, 3, AspaState.VALID),
    (2, [D, C, A], 3, 2, 2, AspaState.INVALID),
    (3, [D, F, C, A], 4, 4, 3, AspaState.UNKNOWN),
    (4, [D, E, B], 3, 3, 2, AspaState.UNKNOWN),
    (5, [A, D, E, B], 4, 3, 2, AspaState.INVALID),
    (6, [A, D, G, E, B], 5, 3, 2, AspaState.INVALID),
    (7, [A, C, F], 3, 2, 1, AspaState.INVALID),
    (8, [A, C, F, G], 4, 1, 1, AspaState.INVALID),
    (9, [E, B], 2, 2, 2, AspaState.VALID),
]


@pytest.mark.parametrize(("case", "wire", "length", "max_up", "min_up", "expected"), UPSTREAM_CASES)
def test_table_1_upstream(
    case: int, wire: list[int], length: int, max_up: int, min_up: int, expected: AspaState
) -> None:
    """Table 1 of the examples document, all nine rows."""
    path = origin_first(wire)
    assert len(path) == length, f"case {case}: path length"
    bounds = ramp_bounds(path, TOPOLOGY_1)
    assert bounds.max_up == max_up, f"case {case}: max_up_ramp"
    assert bounds.min_up == min_up, f"case {case}: min_up_ramp"
    assert verify_upstream(path, TOPOLOGY_1).state is expected, f"case {case}: verdict"


# ---------------------------------------------------------------------------------------
# Table 2: downstream path verification (document page 6)
# ---------------------------------------------------------------------------------------

DOWNSTREAM_CASES = [
    # (case, wire-order path, N, max_up, max_down, min_up, min_down, expected)
    (1, [E, G, F, C, A], 5, 4, 2, 3, 1, AspaState.UNKNOWN),
    (2, [E, G, D, A], 4, 3, 2, 3, 1, AspaState.VALID),
    (3, [E, D, C, A], 4, 2, 2, 2, 1, AspaState.UNKNOWN),
    (4, [E, G, D, C, A], 5, 2, 2, 2, 1, AspaState.INVALID),
    (5, [C, F, D, G], 4, 1, 4, 1, 2, AspaState.UNKNOWN),
    (6, [D, G, E, B], 4, 3, 2, 2, 2, AspaState.VALID),
    (7, [C, D, G, E, B], 5, 3, 1, 2, 1, AspaState.INVALID),
    (8, [F, C, A], 3, 3, 2, 3, 1, AspaState.VALID),
    (9, [E, A], 2, 1, 2, 1, 1, AspaState.VALID),
    (10, [E, C, A], 3, 2, 2, 2, 1, AspaState.VALID),
]


@pytest.mark.parametrize(
    ("case", "wire", "length", "max_up", "max_down", "min_up", "min_down", "expected"),
    DOWNSTREAM_CASES,
)
def test_table_2_downstream(
    case: int,
    wire: list[int],
    length: int,
    max_up: int,
    max_down: int,
    min_up: int,
    min_down: int,
    expected: AspaState,
) -> None:
    """Table 2 of the examples document, all ten rows."""
    path = origin_first(wire)
    assert len(path) == length, f"case {case}: path length"
    bounds = ramp_bounds(path, TOPOLOGY_1)
    assert bounds.max_up == max_up, f"case {case}: max_up_ramp"
    assert bounds.max_down == max_down, f"case {case}: max_down_ramp"
    assert bounds.min_up == min_up, f"case {case}: min_up_ramp"
    assert bounds.min_down == min_down, f"case {case}: min_down_ramp"
    assert verify_downstream(path, TOPOLOGY_1).state is expected, f"case {case}: verdict"


def test_cases_9_and_10_are_the_documented_blind_spot() -> None:
    """The document marks these Valid with a footnote: a provider forging the origin or a
    path segment towards its own customer is undetectable by ASPA (draft Section 7.3).
    Recording it as a test keeps the limitation visible rather than looking like a pass."""
    assert verify_downstream(origin_first([E, A]), TOPOLOGY_1).state is AspaState.VALID
    assert verify_downstream(origin_first([E, C, A]), TOPOLOGY_1).state is AspaState.VALID


# ---------------------------------------------------------------------------------------
# Table 3: complex relationships (document page 10)
# ---------------------------------------------------------------------------------------

COMPLEX_CASES = [
    (1, [J, H], Procedure.UPSTREAM, 2, 1, 1, AspaState.INVALID),
    (2, [J, H], Procedure.UPSTREAM, 2, 1, 1, AspaState.INVALID),
    (3, [K, J, H], Procedure.DOWNSTREAM, 3, 1, 1, AspaState.INVALID),
    (4, [Q, P], Procedure.UPSTREAM, 2, 1, 1, AspaState.INVALID),
]


@pytest.mark.parametrize(
    ("case", "wire", "procedure", "length", "max_up", "min_up", "expected"), COMPLEX_CASES
)
def test_table_3_complex_relationships(
    case: int,
    wire: list[int],
    procedure: Procedure,
    length: int,
    max_up: int,
    min_up: int,
    expected: AspaState,
) -> None:
    """Table 3, where the same pair of networks has different relationships on different
    sessions. The verdicts come out Invalid whichever procedure applies."""
    path = origin_first(wire)
    assert len(path) == length, f"case {case}: path length"
    bounds = ramp_bounds(path, TOPOLOGY_2)
    assert bounds.max_up == max_up, f"case {case}: max_up_ramp"
    assert bounds.min_up == min_up, f"case {case}: min_up_ramp"
    assert verify(path, TOPOLOGY_2, procedure).state is expected, f"case {case}: verdict"


def test_case_3_down_ramp() -> None:
    """Table 3 case 3 also states both down-ramp lengths."""
    bounds = ramp_bounds(origin_first([K, J, H]), TOPOLOGY_2)
    assert bounds.max_down == 1
    assert bounds.min_down == 1


# ---------------------------------------------------------------------------------------
# The procedure steps that the examples do not cover (draft Sections 5.5 and 5.6)
# ---------------------------------------------------------------------------------------


def test_empty_path_is_invalid() -> None:
    """Step 1 of both procedures."""
    assert verify_upstream((), TOPOLOGY_1).state is AspaState.INVALID
    assert verify_downstream((), TOPOLOGY_1).state is AspaState.INVALID


def test_as_set_makes_a_path_invalid() -> None:
    """Step 3 of both procedures. RFC 9774 deprecates AS_SET, and the draft (Section 5.1)
    says a route carrying one evaluates as Invalid if it was not already dropped."""
    path = origin_first([F, C, A])
    assert verify_upstream(path, TOPOLOGY_1).state is AspaState.VALID
    assert verify_upstream(path, TOPOLOGY_1, has_as_set=True).state is AspaState.INVALID
    assert verify_downstream(path, TOPOLOGY_1, has_as_set=True).state is AspaState.INVALID


def test_neighbour_mismatch_makes_a_path_invalid() -> None:
    """Step 2 of both procedures. The plan's pseudocode omitted this step entirely."""
    path = origin_first([F, C, A])
    assert verify_upstream(path, TOPOLOGY_1, neighbour_matches=False).state is AspaState.INVALID
    assert verify_downstream(path, TOPOLOGY_1, neighbour_matches=False).state is AspaState.INVALID


def test_a_route_server_client_is_exempt_from_the_neighbour_check() -> None:
    """Draft Section 5.5 step 2 exempts an RS-client, because a transparent route server
    does not insert itself into the path (RFC 7947 Section 2.2.2). This is the case Phase 2
    found at the Jakarta exchange collector."""
    path = origin_first([F, C, A])
    result = verify_upstream(path, TOPOLOGY_1, neighbour_matches=False, is_rs_client=True)
    assert result.state is AspaState.VALID


def test_single_as_path_is_valid() -> None:
    """A route straight from its origin has no hops to contradict."""
    assert verify_upstream((A,), TOPOLOGY_1).state is AspaState.VALID
    assert verify_downstream((A,), TOPOLOGY_1).state is AspaState.VALID


def test_first_bad_hop_is_reported_for_debugging() -> None:
    """Plan Section 10.3 asks for the pair that caused an Invalid, so RQ2 can chase it."""
    result = verify_upstream(origin_first([D, C, A]), TOPOLOGY_1)
    assert result.state is AspaState.INVALID
    # A says its providers are C and D; the path claims C's provider is D, which C denies.
    assert result.first_bad_hop == (C, D)


def test_unknown_carries_no_bad_hop() -> None:
    result = verify_upstream(origin_first([D, F, C, A]), TOPOLOGY_1)
    assert result.state is AspaState.UNKNOWN
    assert result.first_bad_hop is None


def test_empty_registry_gives_unknown_not_valid() -> None:
    """With no ASPA records at all, nothing can be confirmed, so a multi-hop path is
    Unknown. Reporting Valid here would overstate what the data supports."""
    empty = AspaRegistry({})
    assert verify_upstream(origin_first([F, C, A]), empty).state is AspaState.UNKNOWN
    assert verify_downstream(origin_first([F, C, A]), empty).state is AspaState.UNKNOWN
