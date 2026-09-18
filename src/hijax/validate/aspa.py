"""ASPA-based AS_PATH verification (plan Section 10.3).

Implemented from the text of **draft-ietf-sidrops-aspa-verification-28**, Sections 5.3 to
5.6. Where the plan's pseudocode and the draft disagree, the draft wins; the differences are
noted below and in ``docs/decisions.md``.

## What this is for, in plain English

An ASPA record is a network's signed statement listing its upstream providers. Given a
route's AS_PATH, you can walk it and ask at each step "is the next network really the
provider of this one?". A legitimate route climbs from the origin up to some peak, optionally
crosses once between peers, then descends. A route that climbs, descends and climbs again has
a "valley", which is the signature of a route leak (RFC 7908). ASPA turns that intuition into
a check backed by signatures.

## The two ramps

The draft (Section 5.2) describes the path as an **up-ramp** rising from the origin and a
**down-ramp** descending to the receiver. It computes four numbers: the largest and smallest
each ramp could be, given that a missing ASPA record tells you nothing.

* ``max_*`` counts a hop as fine unless an ASPA positively contradicts it.
* ``min_*`` counts a hop as fine only when an ASPA positively confirms it.

If even the optimistic reading cannot span the path, the path is Invalid. If the optimistic
reading spans it but the pessimistic one does not, there is not enough information and the
answer is Unknown. Otherwise it is Valid.

## Indexing

The draft numbers the path from the origin: ``AS(1)`` is the origin and ``AS(N)`` is the
neighbour that sent the route. This project stores paths that way too, so ``path[0]`` is
``AS(1)``. See ``hijax.paths`` for why that convention exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

#: The draft version this implements. Recorded here and in docs/references.md so a spec
#: change cannot silently invalidate the results (plan Section 10.3).
SPEC_VERSION = "draft-ietf-sidrops-aspa-verification-28"


class Authorized(StrEnum):
    """Outcome of the provider authorization function (draft Section 5.3, Figure 2)."""

    PROVIDER_PLUS = "provider_plus"
    """The customer's ASPA lists this AS as a provider."""
    NOT_PROVIDER_PLUS = "not_provider_plus"
    """The customer has an ASPA and this AS is *not* in it. A positive contradiction."""
    NO_ATTESTATION = "no_attestation"
    """The customer published no ASPA, so nothing is known either way."""


class AspaState(StrEnum):
    """Verification outcome (draft Sections 5.5 and 5.6)."""

    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class Procedure(StrEnum):
    """Which procedure applies, decided by the relationship to the sending neighbour."""

    UPSTREAM = "upstream"
    """Route received from a customer, a lateral peer, or across a route server."""
    DOWNSTREAM = "downstream"
    """Route received from a provider."""


class AspaRegistry:
    """The U-SPAS table: each customer AS mapped to its effective provider set.

    "U-SPAS" is the draft's term (Section 5.3) for the union of all of a customer's valid
    ASPAs. The ingester already performs that union and applies the AS 0 rule, so what
    arrives here is one provider set per customer.
    """

    __slots__ = ("_providers",)

    def __init__(self, providers: Mapping[int, frozenset[int] | set[int] | tuple[int, ...]]):
        self._providers: dict[int, frozenset[int]] = {
            int(customer): frozenset(int(p) for p in provs) for customer, provs in providers.items()
        }

    def __len__(self) -> int:
        return len(self._providers)

    def __contains__(self, asn: int) -> bool:
        return asn in self._providers

    def providers_of(self, asn: int) -> frozenset[int]:
        return self._providers.get(asn, frozenset())

    def authorized(self, customer: int, candidate: int) -> Authorized:
        """Is ``candidate`` an attested provider of ``customer``? (draft Section 5.3)

        Returns "No Attestation" only when the customer published nothing at all. A customer
        that published an AS0 ASPA, meaning "I have no providers", *has* attested, so every
        candidate comes back as a positive contradiction.
        """
        provs = self._providers.get(customer)
        if provs is None:
            return Authorized.NO_ATTESTATION
        if candidate in provs:
            return Authorized.PROVIDER_PLUS
        return Authorized.NOT_PROVIDER_PLUS


@dataclass(frozen=True, slots=True)
class RampBounds:
    """The four ramp lengths from draft Section 5.4."""

    max_up: int
    min_up: int
    max_down: int
    min_down: int


@dataclass(frozen=True, slots=True)
class AspaResult:
    """A verification outcome, with enough detail to trace it by hand."""

    state: AspaState
    procedure: Procedure
    bounds: RampBounds | None = None
    first_bad_hop: tuple[int, int] | None = None
    """The (customer, claimed-provider) pair that positively contradicted the path, which is
    what plan Section 10.3 asks for so RQ2 can be debugged."""
    reason: str = ""


def ramp_bounds(path: Sequence[int], registry: AspaRegistry) -> RampBounds:
    """Compute the four ramp lengths for an origin-first path (draft Section 5.4).

    Up-ramp, reading away from the origin: ``max_up`` is the first index I where
    ``authorized(A(I), A(I+1))`` positively contradicts, else N. ``min_up`` is the first
    index where it contradicts *or* says nothing, else N.

    Down-ramp, reading back from the neighbour: the same, using ``authorized(A(J), A(J-1))``
    and the largest qualifying J, converted to a length as ``N - J + 1``.
    """
    n = len(path)
    if n == 0:
        return RampBounds(0, 0, 0, 0)

    # Up-ramp. Walk away from the origin. min_up stops at the first hop that is not a
    # positive confirmation; max_up stops only at a positive contradiction.
    max_up = min_up = n
    for i in range(1, n):  # i is the draft's I, 1-based; the hop is A(I) -> A(I+1)
        verdict = registry.authorized(path[i - 1], path[i])
        if verdict is not Authorized.PROVIDER_PLUS and min_up == n:
            min_up = i
        if verdict is Authorized.NOT_PROVIDER_PLUS:
            max_up = i
            break

    # Down-ramp. Walk back from the neighbour. Iterating downwards means the first hop that
    # qualifies is the largest J, which is what the draft asks for.
    max_down = min_down = n
    for j in range(n, 1, -1):  # j is the draft's J; the hop is A(J) -> A(J-1)
        verdict = registry.authorized(path[j - 1], path[j - 2])
        if verdict is not Authorized.PROVIDER_PLUS and min_down == n:
            min_down = n - j + 1
        if verdict is Authorized.NOT_PROVIDER_PLUS:
            max_down = n - j + 1
            break

    return RampBounds(max_up=max_up, min_up=min_up, max_down=max_down, min_down=min_down)


def _first_contradiction(path: Sequence[int], registry: AspaRegistry) -> tuple[int, int] | None:
    for i in range(1, len(path)):
        if registry.authorized(path[i - 1], path[i]) is Authorized.NOT_PROVIDER_PLUS:
            return path[i - 1], path[i]
    return None


def verify_upstream(
    path: Sequence[int],
    registry: AspaRegistry,
    *,
    has_as_set: bool = False,
    neighbour_matches: bool = True,
    is_rs_client: bool = False,
) -> AspaResult:
    """Verify a route received from a customer, a lateral peer, or a route server.

    Steps are draft Section 5.5, in order. The receiver expects the path to be one clean
    climb, so the down-ramp is fixed at zero.
    """
    n = len(path)
    if n == 0:
        return AspaResult(AspaState.INVALID, Procedure.UPSTREAM, reason="empty AS_PATH")
    # Step 2. An RS-client is exempt because a transparent route server does not insert
    # itself into the path (RFC 7947 Section 2.2.2), so the leftmost AS legitimately differs
    # from the neighbour the receiver sees.
    if not is_rs_client and not neighbour_matches:
        return AspaResult(
            AspaState.INVALID, Procedure.UPSTREAM, reason="neighbour AS does not match AS_PATH"
        )
    if has_as_set:
        return AspaResult(AspaState.INVALID, Procedure.UPSTREAM, reason="AS_SET in AS_PATH")

    bounds = ramp_bounds(path, registry)
    if bounds.max_up < n:
        return AspaResult(
            AspaState.INVALID,
            Procedure.UPSTREAM,
            bounds=bounds,
            first_bad_hop=_first_contradiction(path, registry),
            reason="up-ramp cannot span the path",
        )
    if bounds.min_up < n:
        return AspaResult(
            AspaState.UNKNOWN, Procedure.UPSTREAM, bounds=bounds, reason="not enough attestations"
        )
    return AspaResult(AspaState.VALID, Procedure.UPSTREAM, bounds=bounds)


def verify_downstream(
    path: Sequence[int],
    registry: AspaRegistry,
    *,
    has_as_set: bool = False,
    neighbour_matches: bool = True,
) -> AspaResult:
    """Verify a route received from a provider (draft Section 5.6).

    Here the path may legitimately climb and then descend, so both ramps count.
    """
    n = len(path)
    if n == 0:
        return AspaResult(AspaState.INVALID, Procedure.DOWNSTREAM, reason="empty AS_PATH")
    if not neighbour_matches:
        return AspaResult(
            AspaState.INVALID, Procedure.DOWNSTREAM, reason="neighbour AS does not match AS_PATH"
        )
    if has_as_set:
        return AspaResult(AspaState.INVALID, Procedure.DOWNSTREAM, reason="AS_SET in AS_PATH")

    bounds = ramp_bounds(path, registry)
    if bounds.max_up + bounds.max_down < n:
        return AspaResult(
            AspaState.INVALID,
            Procedure.DOWNSTREAM,
            bounds=bounds,
            first_bad_hop=_first_contradiction(path, registry),
            reason="ramps cannot span the path",
        )
    if bounds.min_up + bounds.min_down < n:
        return AspaResult(
            AspaState.UNKNOWN,
            Procedure.DOWNSTREAM,
            bounds=bounds,
            reason="not enough attestations",
        )
    return AspaResult(AspaState.VALID, Procedure.DOWNSTREAM, bounds=bounds)


def verify(
    path: Sequence[int],
    registry: AspaRegistry,
    procedure: Procedure,
    *,
    has_as_set: bool = False,
    neighbour_matches: bool = True,
    is_rs_client: bool = False,
) -> AspaResult:
    """Run whichever procedure the relationship to the neighbour calls for."""
    if procedure is Procedure.DOWNSTREAM:
        return verify_downstream(
            path, registry, has_as_set=has_as_set, neighbour_matches=neighbour_matches
        )
    return verify_upstream(
        path,
        registry,
        has_as_set=has_as_set,
        neighbour_matches=neighbour_matches,
        is_rs_client=is_rs_client,
    )


# ---------------------------------------------------------------------------------------
# Applying the procedures to route-collector data (plan Section 10.3)
# ---------------------------------------------------------------------------------------


class RelSource(Protocol):
    """Anything that can answer "what is y to x?" as c2p, p2c, p2p or None.

    Declared structurally so this module does not import the ingestion package.
    ``hijax.ingest.meta.RelationshipLookup`` satisfies it.
    """

    def rel(self, x: int, y: int) -> str | None: ...


def procedure_for(relationship: str | None) -> Procedure | None:
    """Pick the procedure from the receiver's relationship to the neighbour that sent it.

    The draft chooses by how the route arrived (Sections 5.5 and 5.6): from a customer, a
    lateral peer or a route server it must be a pure climb, so the upstream procedure
    applies; from a provider it may climb and then descend, so the downstream one does.

    ``None`` means the relationship is unknown, and the caller should run both and say so,
    rather than guessing one and reporting a number that looks certain.
    """
    if relationship in ("p2c", "p2p"):
        return Procedure.UPSTREAM
    if relationship == "c2p":
        return Procedure.DOWNSTREAM
    return None


@dataclass(frozen=True, slots=True)
class CollectorVerification:
    """What the collector's peer would have concluded about a route.

    A route collector is not a router and applies no policy, so nothing here is what the
    collector did. It is what its peer would have decided, reconstructed from the path the
    collector recorded (plan Section 10.3).
    """

    state: AspaState
    procedure: str
    """``upstream``, ``downstream``, or ``both`` when the relationship is unknown."""
    upstream: AspaResult | None = None
    downstream: AspaResult | None = None

    @property
    def relationship_known(self) -> bool:
        return self.procedure != "both"


def verify_at_collector(
    path: Sequence[int],
    registry: AspaRegistry,
    relationships: RelSource,
    *,
    has_as_set: bool = False,
) -> CollectorVerification:
    """Evaluate the check the collector's own peer would have performed.

    The collector peer is ``A(N)``, the last entry of an origin-first path. It received the
    route from ``A(N-1)`` carrying the path ``A(1..N-1)``, so that shorter path is what gets
    verified, and the procedure follows the relationship between those two.

    When the relationship is unknown both procedures are run and both results kept, with the
    combined state being the more severe of the two. Plan Section 10.3 requires these routes
    to be reported separately, which ``procedure == "both"`` makes possible.
    """
    if len(path) < 2:
        # Nothing was relayed to the peer, so there is no check to reconstruct.
        return CollectorVerification(AspaState.UNKNOWN, "both")

    received = path[:-1]
    receiver, neighbour = path[-1], path[-2]
    chosen = procedure_for(relationships.rel(receiver, neighbour))

    if chosen is Procedure.UPSTREAM:
        result = verify_upstream(received, registry, has_as_set=has_as_set)
        return CollectorVerification(result.state, "upstream", upstream=result)
    if chosen is Procedure.DOWNSTREAM:
        result = verify_downstream(received, registry, has_as_set=has_as_set)
        return CollectorVerification(result.state, "downstream", downstream=result)

    up = verify_upstream(received, registry, has_as_set=has_as_set)
    down = verify_downstream(received, registry, has_as_set=has_as_set)
    return CollectorVerification(
        _more_severe(up.state, down.state), "both", upstream=up, downstream=down
    )


def _more_severe(left: AspaState, right: AspaState) -> AspaState:
    """Invalid beats Unknown beats Valid, so an ambiguous route is never reported as clean."""
    order = {AspaState.VALID: 0, AspaState.UNKNOWN: 1, AspaState.INVALID: 2}
    return left if order[left] >= order[right] else right


@dataclass(frozen=True, slots=True)
class BlockPoint:
    """Where along a path an ASPA-filtering network would first have dropped the route."""

    position: int
    """1-based index of the network that would drop it, counting from the origin."""
    blocking_asn: int
    result: AspaResult

    def relative_position(self, path_length: int) -> float:
        """Position as a fraction of the path, which is what plan Section 10.6 reports."""
        return self.position / path_length if path_length else 0.0


def first_block_point(
    path: Sequence[int],
    registry: AspaRegistry,
    relationships: RelSource,
    *,
    filtering: set[int] | None = None,
    has_as_set: bool = False,
) -> BlockPoint | None:
    """Walk the path and find the earliest network that would have rejected the route.

    For each position ``k`` from 2 to N, the network ``A(k)`` received the path ``A(1..k-1)``
    from ``A(k-1)``. Running the right procedure at each step answers the counterfactual
    question in plan Section 10.6: if these networks filtered on ASPA, where would this route
    have stopped?

    ``filtering`` restricts the answer to networks that actually drop Invalid routes, which
    is how the F-all and F-topN scenarios differ. ``None`` means every network filters.
    Returns ``None`` when the route travels the whole path unchallenged.
    """
    for k in range(2, len(path) + 1):
        receiver, neighbour = path[k - 1], path[k - 2]
        if filtering is not None and receiver not in filtering:
            continue
        received = path[: k - 1]
        chosen = procedure_for(relationships.rel(receiver, neighbour))
        if chosen is Procedure.DOWNSTREAM:
            result = verify_downstream(received, registry, has_as_set=has_as_set)
        else:
            # Unknown relationships are treated as upstream here. That is the stricter
            # reading, so it can overstate blocking; scenarios that care report the
            # relationship-unknown share separately.
            result = verify_upstream(received, registry, has_as_set=has_as_set)
        if result.state is AspaState.INVALID:
            return BlockPoint(position=k, blocking_asn=receiver, result=result)
    return None
