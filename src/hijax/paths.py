"""AS_PATH normalization (plan Section 10.1).

## Direction, which is the single most important thing in this file

A BGP AS_PATH as received reads **neighbour first, origin last**. Each AS prepends its own
number as the route passes, so the leftmost entry is the most recent hop and the rightmost
is the network that originated the prefix (RFC 4271 Section 4.3).

The ASPA verification draft numbers paths **the other way round**: it writes
``COMPRESSED_AS_PATH {AS(N), ... AS(1)}`` where **AS(1) is the origin** and AS(N) is the
neighbour that handed the route over
(``draft-ietf-sidrops-aspa-verification-28`` Section 5.2).

So this module **reverses** the path. Everywhere in this project, a normalized
``as_path`` is **origin first**: ``as_path[0]`` is the origin AS, ``as_path[-1]`` is the
collector peer. Mixing this up is the most likely bug in the whole project, which is why it
is stated here, in the plan at Section 10.1, and in ``CLAUDE.md``.

## What the input looks like

``pybgpkit`` hands back the AS_PATH as a string. Verified against the parser's own source
and against real MRT files in Phase 2:

* segments are separated by spaces, and a sequence is just its numbers: ``"3741 6461 36352"``
* an AS_SET is written in braces with commas: ``"1 2 {3,4} 5 6 {7} 8"``
* **a confederation segment is formatted exactly like an ordinary one**, so the string form
  cannot tell them apart. See ``docs/decisions.md`` D-017 for what that costs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: AS 23456 is AS_TRANS, the placeholder a two-octet-only speaker puts in the path in place
#: of a real 4-byte AS number (RFC 6793 Section 4.1). Seeing it means the path has been
#: through an old speaker and cannot be trusted hop by hop.
AS_TRANS = 23456


class PathFlag(StrEnum):
    """Why a route is excluded from analysis. Counted, never silently dropped."""

    EMPTY = "empty"
    LOOP = "loop"
    PRIVATE_ASN = "private_asn"
    RESERVED_ASN = "reserved_asn"
    AS_TRANS = "as_trans"
    PEER_MISMATCH = "peer_mismatch"
    AS_SET = "as_set"


@dataclass(frozen=True, slots=True)
class NormalizedPath:
    """A cleaned AS_PATH, **origin first**.

    ``as_path[0]`` is the origin AS and ``as_path[-1]`` is the collector peer. ``origin_asn``
    is ``None`` when the path ended in an AS_SET, because in that case the true origin is
    genuinely unknown rather than being any one member of the set.
    """

    as_path: tuple[int, ...]
    has_as_set: bool
    origin_asn: int | None
    flags: frozenset[PathFlag]

    @property
    def usable(self) -> bool:
        """True when nothing disqualifies this path from relationship analysis.

        An AS_SET does not disqualify a path here: the plan keeps the sequence part for
        relationship analysis and lets ASPA verification return Invalid separately
        (plan Section 10.1 step 2).
        """
        blocking = {
            PathFlag.EMPTY,
            PathFlag.LOOP,
            PathFlag.PRIVATE_ASN,
            PathFlag.RESERVED_ASN,
            PathFlag.AS_TRANS,
        }
        return not (self.flags & blocking)


#: A token is either a brace group, which may contain spaces, or a bare AS number.
#: Scanning for brace groups first means ``"{2, 3}"`` stays one segment.
_TOKEN = re.compile(r"\{[^{}]*\}|\S+")


def is_private_asn(asn: int) -> bool:
    """AS numbers set aside for private use: RFC 6996 Section 5."""
    return 64512 <= asn <= 65534 or 4_200_000_000 <= asn <= 4_294_967_294


def is_reserved_asn(asn: int) -> bool:
    """AS numbers that must not appear in a real path.

    AS 0 is reserved and must never be used as an origin or appear in a path (RFC 7607
    Section 4). AS 65535 and AS 4294967295 are reserved as the last of each range
    (RFC 7300 Section 3). The documentation ranges are RFC 5398 Section 4.
    """
    return (
        asn == 0
        or asn == 65535
        or asn == 4_294_967_295
        or 64496 <= asn <= 64511
        or 65536 <= asn <= 65551
    )


def parse_segments(raw: str) -> list[tuple[bool, list[int]]]:
    """Split the string form into ``(is_set, asns)`` segments.

    A confederation segment is indistinguishable from an ordinary one in this
    representation, so it is parsed as an ordinary one (D-017).
    """
    segments: list[tuple[bool, list[int]]] = []
    for token in _TOKEN.findall(raw):
        if token.startswith("{"):
            body = token[1:-1]
            members = [int(x) for x in re.split(r"[,\s]+", body) if x]
            segments.append((True, members))
        else:
            segments.append((False, [int(token)]))
    return segments


def collapse_prepending(asns: list[int]) -> list[int]:
    """Collapse runs of the same AS into one entry (plan Section 10.1 step 3).

    An AS may repeat its own number several times to make a route look longer and so less
    attractive, a practice called prepending. It says nothing about the topology, so a run
    of the same number counts once.
    """
    out: list[int] = []
    for asn in asns:
        if not out or out[-1] != asn:
            out.append(asn)
    return out


_NO_FLAGS: frozenset[PathFlag] = frozenset()
_EMPTY_PATH = NormalizedPath((), False, None, frozenset({PathFlag.EMPTY}))


def _classify(asn: int) -> PathFlag | None:
    """Flag for one AS number, or ``None`` when it is an ordinary public one.

    Ordered so that the common cases cost one or two comparisons: an ordinary 4-byte AS
    number exits on the first branch, an ordinary 2-byte one on the second.
    """
    if asn > 65551:
        if asn >= 4_200_000_000:
            return PathFlag.RESERVED_ASN if asn == 4_294_967_295 else PathFlag.PRIVATE_ASN
        return None
    if asn >= 64496:
        if asn == 65535:
            return PathFlag.RESERVED_ASN
        if asn <= 64511:
            return PathFlag.RESERVED_ASN
        if asn <= 65534:
            return PathFlag.PRIVATE_ASN
        return PathFlag.RESERVED_ASN  # 65536..65551, documentation (RFC 5398)
    if asn == AS_TRANS:
        return PathFlag.AS_TRANS
    if asn == 0:
        return PathFlag.RESERVED_ASN
    return None


def normalize(raw: str | None, peer_asn: int | None = None) -> NormalizedPath:
    """Normalize one raw AS_PATH into the project's origin-first form.

    Steps follow plan Section 10.1: drop AS_SET members from the numeric path but record
    that a set was present, collapse prepending, reverse to origin-first, then flag loops,
    private or reserved AS numbers, AS_TRANS, and a leftmost AS that disagrees with the
    peer the collector says sent the route.

    Paths without an AS_SET take a faster route through this function. Both produce the
    same result; ``test_fast_and_general_paths_agree`` holds them to that.
    """
    if raw is None:
        return _EMPTY_PATH
    if "{" in raw:
        return _normalize_general(raw, peer_asn)

    tokens = raw.split()
    if not tokens:
        return _EMPTY_PATH

    # Collapse prepending while converting, so the path is walked once.
    sequence: list[int] = []
    previous = -1
    for token in tokens:
        asn = int(token)
        if asn != previous:
            sequence.append(asn)
            previous = asn
    sequence.reverse()

    flags: set[PathFlag] | None = None
    if peer_asn is not None and sequence[-1] != peer_asn:
        flags = {PathFlag.PEER_MISMATCH}
    if len(set(sequence)) != len(sequence):
        flags = flags or set()
        flags.add(PathFlag.LOOP)
    for asn in sequence:
        flag = _classify(asn)
        if flag is not None:
            flags = flags or set()
            flags.add(flag)

    return NormalizedPath(
        as_path=tuple(sequence),
        has_as_set=False,
        origin_asn=sequence[0],
        flags=frozenset(flags) if flags else _NO_FLAGS,
    )


def _normalize_general(raw: str, peer_asn: int | None) -> NormalizedPath:
    """The full implementation, used when the path contains an AS_SET."""
    flags: set[PathFlag] = set()
    segments = parse_segments(raw)
    if not segments:
        return _EMPTY_PATH

    has_as_set = False
    for is_set, _ in segments:
        if is_set:
            has_as_set = True
            break
    if has_as_set:
        flags.add(PathFlag.AS_SET)

    # The leftmost entry as received should be the neighbour that sent us the route
    # (RFC 4271 Section 6.3). Some collectors and transparent route servers strip their own
    # AS (RFC 7947 Section 2.2.2), so this is recorded rather than treated as fatal
    # (plan Section 10.1 step 5).
    first_segment_is_set, first_members = segments[0]
    if peer_asn is not None:
        leftmost = first_members[0] if first_members else None
        if first_segment_is_set or leftmost != peer_asn:
            flags.add(PathFlag.PEER_MISMATCH)

    # Keep only AS_SEQUENCE members in the numeric path; the set is noted via has_as_set.
    sequence = [asn for is_set, members in segments if not is_set for asn in members]
    if not sequence:
        return NormalizedPath((), has_as_set, None, frozenset(flags | {PathFlag.EMPTY}))

    origin_first = tuple(reversed(collapse_prepending(sequence)))

    # After collapsing prepends, any repeat is a genuine loop rather than padding.
    if len(set(origin_first)) != len(origin_first):
        flags.add(PathFlag.LOOP)

    for asn in origin_first:
        flag = _classify(asn)
        if flag is not None:
            flags.add(flag)

    # If the path ends in an AS_SET the real origin is unknown, so do not guess one.
    # Note that pybgpkit's own ``origin_asn`` *does* guess: it reports a member of the set.
    origin_asn = None if segments[-1][0] else origin_first[0]

    return NormalizedPath(
        as_path=origin_first,
        has_as_set=has_as_set,
        origin_asn=origin_asn,
        flags=frozenset(flags),
    )
