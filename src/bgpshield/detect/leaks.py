"""Path direction and the valley-free rule (plan Section 10.4).

## What a route leak is, in plain English

Money decides where routes are allowed to go. A network will carry traffic for its own
customers to anyone, because it is paid to. It will not carry traffic *between* two of its
providers, or between two peers, because that would be paying to move somebody else's
traffic for free. Gao and Rexford turned this into a shape rule: a legitimate path goes
**up** the hierarchy zero or more times, **across** between peers at most once, then **down**
zero or more times. Nothing else.

A path that goes down or across and then climbs again has a "valley". That is a route leak
(RFC 7908), and it is how traffic ends up flowing through a network that never agreed to
carry it.

## What is here

Direction classification, the valley test, the RFC 7908 leak taxonomy as far as a path can
reveal it, and the multi-vantage guard that plan Section 10.4 requires before a candidate is
treated as a finding.

Two things are deliberately out of reach. RFC 7908 types 5 and 6, prefix re-origination and
leaks of internal more-specifics, cannot be told from path direction: one needs data-plane
evidence this project never collects (plan Section 4) and the other needs to know what the
operator meant to announce. And a *corroborated* finding here is still a candidate, not a
confirmed event, because the relationships underneath it are inferred and carry errors
(plan Section 15).

Paths are **origin first**, as everywhere else in this project. Edge ``i`` is the step from
``path[i]`` to ``path[i+1]``, which is the direction the route travelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bgpshield.topology import RelSource, SiblingSource


class Direction(StrEnum):
    """Which way a route stepped between two adjacent networks."""

    UP = "up"
    """The next network is this one's provider, so the route is climbing."""
    DOWN = "down"
    """The next network is this one's customer, so the route is descending."""
    FLAT = "flat"
    """The two are peers, so the route is crossing."""
    SIBLING = "sibling"
    """Both AS numbers belong to one organisation. Treated as transparent."""
    UNKNOWN = "unknown"
    """No relationship was inferred for this pair."""


class Shape(StrEnum):
    """Verdict of the valley-free test."""

    VALLEY_FREE = "valley_free"
    """The path matches up, then optionally across, then down."""
    VALLEY = "valley"
    """The path climbs again after descending or crossing."""
    UNDETERMINED = "undetermined"
    """A missing relationship sits where it could change the answer, so no claim is made."""


class _NoSiblings:
    def are_siblings(self, x: int, y: int) -> bool:
        return False


def path_directions(
    path: tuple[int, ...] | list[int],
    relationships: RelSource,
    siblings: SiblingSource | None = None,
) -> list[Direction]:
    """Classify every step of a path (plan Section 10.4).

    Sibling links are checked first: two AS numbers run by the same organisation are one
    network for this purpose, and a route moving between them is not going anywhere in the
    hierarchy.
    """
    sib = siblings or _NoSiblings()
    out: list[Direction] = []
    for left, right in zip(path, path[1:], strict=False):
        if sib.are_siblings(left, right):
            out.append(Direction.SIBLING)
            continue
        relation = relationships.rel(left, right)
        if relation == "c2p":
            out.append(Direction.UP)
        elif relation == "p2c":
            out.append(Direction.DOWN)
        elif relation == "p2p":
            out.append(Direction.FLAT)
        else:
            out.append(Direction.UNKNOWN)
    return out


def classify_shape(directions: list[Direction]) -> Shape:
    """Test the direction sequence against ``up* flat? down*``.

    Siblings are dropped first, because an organisation's internal hop says nothing about the
    hierarchy. An unknown step is only fatal to the verdict when it could change it: if the
    known steps already form a valley, that stands regardless.
    """
    steps = [d for d in directions if d is not Direction.SIBLING]
    if not steps:
        return Shape.VALLEY_FREE

    if _has_valley([d for d in steps if d is not Direction.UNKNOWN]):
        return Shape.VALLEY
    if Direction.UNKNOWN in steps:
        return Shape.UNDETERMINED
    return Shape.VALLEY_FREE


def _has_valley(steps: list[Direction]) -> bool:
    """True when the sequence does not match ``up* flat? down*``."""
    phase = 0  # 0 while climbing, 1 after the single crossing, 2 once descending
    for step in steps:
        if step is Direction.UP:
            if phase != 0:
                return True  # climbing again after crossing or descending
        elif step is Direction.FLAT:
            if phase != 0:
                return True  # a second crossing, or crossing after descending
            phase = 1
        elif step is Direction.DOWN:
            phase = 2
    return False


@dataclass(frozen=True, slots=True)
class LeakCandidate:
    """A network that appears to have passed on a route it should not have.

    This is a *candidate*, not a finding. Plan Section 10.4 requires a candidate to be seen
    from at least two collector peers, or matched to a curated incident, before it counts.
    Those guards arrive in Phase 5.
    """

    leaker_asn: int
    position: int
    """1-based index of the leaker along the origin-first path."""
    incoming: Direction
    outgoing: Direction


def find_leakers(
    path: tuple[int, ...] | list[int], directions: list[Direction]
) -> list[LeakCandidate]:
    """Find the networks that turned the path around (plan Section 10.4).

    A leaker is a network whose incoming step was down or across, and whose outgoing step was
    up or across: it took a route from a provider or a peer and handed it to another provider
    or peer. The origin and the final network cannot be leakers, having only one step each.
    """
    out: list[LeakCandidate] = []
    for index in range(1, len(path) - 1):
        incoming, outgoing = directions[index - 1], directions[index]
        if incoming in (Direction.DOWN, Direction.FLAT) and outgoing in (
            Direction.UP,
            Direction.FLAT,
        ):
            out.append(
                LeakCandidate(
                    leaker_asn=path[index],
                    position=index + 1,
                    incoming=incoming,
                    outgoing=outgoing,
                )
            )
    return out


# ---------------------------------------------------------------------------------------
# Leak classification and the precision guard (plan Section 10.4, completed in Phase 5)
# ---------------------------------------------------------------------------------------


class LeakType(StrEnum):
    """The route-leak taxonomy of RFC 7908 Section 3, as far as a path can reveal it.

    All four of these are the same mistake seen from different angles: a network passing on a
    route it was not paid to carry. Which type it is depends on where the route came from and
    where it went.
    """

    HAIRPIN = "hairpin"
    """Type 1. Learned from one transit provider and sent to another. The route makes a
    U-turn through a network that is paying for both sides of it."""
    LATERAL = "lateral"
    """Type 2. Learned from one lateral peer and passed to another peer."""
    PROVIDER_TO_PEER = "provider_to_peer"
    """Type 3. Learned from a provider and leaked to a peer."""
    PEER_TO_PROVIDER = "peer_to_provider"
    """Type 4. Learned from a peer and leaked to a provider."""


#: Types 5 and 6 of RFC 7908, prefix re-origination and leaks of internal more-specifics,
#: cannot be told from path direction alone. Type 5 needs data-plane evidence, which this
#: project never collects (plan Section 4), and type 6 needs to know what the operator
#: intended to announce. Neither is claimed here.
UNDETECTABLE_TYPES = ("re-origination (type 5)", "internal more-specifics (type 6)")


def leak_type(incoming: Direction, outgoing: Direction) -> LeakType | None:
    """Classify a leak from the directions either side of the leaker (RFC 7908 Section 3)."""
    if incoming is Direction.DOWN and outgoing is Direction.UP:
        return LeakType.HAIRPIN
    if incoming is Direction.FLAT and outgoing is Direction.FLAT:
        return LeakType.LATERAL
    if incoming is Direction.DOWN and outgoing is Direction.FLAT:
        return LeakType.PROVIDER_TO_PEER
    if incoming is Direction.FLAT and outgoing is Direction.UP:
        return LeakType.PEER_TO_PROVIDER
    return None


@dataclass(frozen=True, slots=True)
class LeakObservation:
    """One collector peer's sighting of one leaked route."""

    collector: str
    peer_ip: str
    prefix: str
    leaker_asn: int
    leak_type: LeakType
    position: int
    path: tuple[int, ...]


@dataclass(slots=True)
class LeakFinding:
    """A leak candidate after the precision guard, with the evidence behind it.

    Plan Section 10.4 requires a candidate to be corroborated before it counts, because the
    inferred relationships it rests on contain errors. A single peer seeing an odd path is
    just as likely to be a mistake in the topology data as a real event.
    """

    prefix: str
    leaker_asn: int
    leak_type: LeakType
    observations: int
    distinct_peers: int
    distinct_collectors: int
    paths: tuple[tuple[int, ...], ...]
    corroborated: bool
    """True when seen from at least the required number of distinct collector peers."""


def collect_findings(
    observations: list[LeakObservation], *, min_peers: int = 2
) -> list[LeakFinding]:
    """Group sightings and apply the multi-vantage guard (plan Section 10.4).

    Grouping is by (prefix, leaker, type), because the same leak seen by twenty peers is one
    event, not twenty. Uncorroborated candidates are kept and marked rather than discarded,
    so both the raw and the filtered counts can be reported, as the plan requires.
    """
    grouped: dict[tuple[str, int, LeakType], list[LeakObservation]] = {}
    for observation in observations:
        key = (observation.prefix, observation.leaker_asn, observation.leak_type)
        grouped.setdefault(key, []).append(observation)

    findings: list[LeakFinding] = []
    for (prefix, leaker, kind), group in grouped.items():
        peers = {(o.collector, o.peer_ip) for o in group}
        findings.append(
            LeakFinding(
                prefix=prefix,
                leaker_asn=leaker,
                leak_type=kind,
                observations=len(group),
                distinct_peers=len(peers),
                distinct_collectors=len({o.collector for o in group}),
                paths=tuple(sorted({o.path for o in group})),
                corroborated=len(peers) >= min_peers,
            )
        )
    return sorted(
        findings, key=lambda f: (-f.distinct_peers, -f.observations, f.prefix, f.leaker_asn)
    )


def detect_in_path(
    collector: str,
    peer_ip: str,
    prefix: str,
    path: tuple[int, ...] | list[int],
    relationships: RelSource,
    siblings: SiblingSource | None = None,
) -> list[LeakObservation]:
    """Find every leak this one path shows, if the shape test can judge it at all.

    A path whose shape is undetermined, because a relationship next to the suspected turn is
    missing, yields nothing. Plan Section 10.4 is explicit that those are marked undetermined
    rather than counted as leaks.
    """
    directions = path_directions(path, relationships, siblings)
    if classify_shape(directions) is not Shape.VALLEY:
        return []

    out: list[LeakObservation] = []
    for candidate in find_leakers(path, directions):
        kind = leak_type(candidate.incoming, candidate.outgoing)
        if kind is None:
            continue
        out.append(
            LeakObservation(
                collector=collector,
                peer_ip=peer_ip,
                prefix=prefix,
                leaker_asn=candidate.leaker_asn,
                leak_type=kind,
                position=candidate.position,
                path=tuple(path),
            )
        )
    return out
