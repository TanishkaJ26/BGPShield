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

## What is here and what is not

Phase 4 needs only the shape test, to tell a genuinely leaked path from a legitimate one
while measuring how often ASPA's Invalid verdict is caused by an incomplete record rather
than a real leak. So this module provides direction classification and the valley test.

The rest of plan Section 10.4, meaning the RFC 7908 leak typing and the precision guards that
require a candidate to be seen from several vantage points or matched to a curated incident,
belongs to Phase 5 and is not here yet. Nothing in this module should be read as a claim that
a path is a confirmed leak.

Paths are **origin first**, as everywhere else in this project. Edge ``i`` is the step from
``path[i]`` to ``path[i+1]``, which is the direction the route travelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


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


class RelSource(Protocol):
    def rel(self, x: int, y: int) -> str | None: ...


class SiblingSource(Protocol):
    def are_siblings(self, x: int, y: int) -> bool: ...


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
