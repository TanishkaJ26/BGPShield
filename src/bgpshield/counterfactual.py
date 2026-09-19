"""Would ASPA have stopped this leak, and where? (plan Section 10.6)

## The question

Take a route that leaked. Ask what would have happened if more networks had published ASPA
records, and if the networks along its path had actually dropped Invalid routes. Two knobs,
so two families of scenarios:

* **Publication** decides who has published a record at all, from today's real ones up to a
  hypothetical world where everybody has.
* **Filtering** decides who acts on what they find. Publishing a record protects other
  people; dropping Invalid routes is what protects you and everyone downstream.

For each combination the route is walked hop by hop, and the first filtering network that
would call it Invalid is where it dies.

## The circularity warning, which must travel with every S3 number

Scenarios S1 to S3 invent ASPA records by copying the providers CAIDA *inferred* for each
network. The leaks being tested were detected using those same inferred relationships. So in
S3, where every network gets a synthetic record, the test is close to asking whether a rule
derived from CAIDA's topology catches violations of CAIDA's topology. It largely does, by
construction.

**S3 is an upper bound, not a prediction.** The same caution applies in weaker form to S1 and
S2, where only the largest networks get synthetic records. The credible numbers are S0, which
uses only records that operators really published, and the curated incidents, which have
external evidence behind them. Plan Section 10.6 requires this warning in the code and in the
paper, and Section 15 lists it as a threat to validity.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from statistics import median

import polars as pl

from bgpshield.topology import RelSource, TopologySource
from bgpshield.validate.aspa import AspaRegistry, first_block_point


class Publication(StrEnum):
    """Who has published an ASPA record (plan Section 10.6)."""

    S0 = "S0"
    """Only the records operators really published on the date in question."""
    S1 = "S1"
    """S0 plus synthetic records for the 100 largest networks by customer cone."""
    S2 = "S2"
    """S0 plus synthetic records for the largest 1000."""
    S3 = "S3"
    """Synthetic records for every network. Upper bound only: see the module docstring."""


class Filtering(StrEnum):
    """Who actually drops Invalid routes."""

    F_ALL = "F-all"
    """Every network on the path filters."""
    F_TOP20 = "F-top20"
    """Only the 20 largest transit networks filter."""
    F_TOP100 = "F-top100"
    """Only the largest 100."""


@dataclass(frozen=True, slots=True)
class Scenario:
    """One publication world, with a note of how much of it is invented."""

    publication: Publication
    registry: AspaRegistry
    real_records: int
    synthetic_records: int

    @property
    def is_upper_bound(self) -> bool:
        """True when the answer must be presented as an upper bound, not a prediction."""
        return self.publication is Publication.S3

    @property
    def synthetic_share(self) -> float:
        total = self.real_records + self.synthetic_records
        return self.synthetic_records / total if total else 0.0


def top_by_cone(as_meta: pl.DataFrame, count: int) -> list[int]:
    """The ``count`` largest networks by customer cone.

    Customer cone is the number of networks reachable through this one as customers, so it
    measures how much of the Internet sits behind a network rather than how many addresses it
    holds. Plan Section 10.6 uses it to choose the "top N".
    """
    ranked = (
        as_meta.filter(pl.col("cone_size").is_not_null() & (pl.col("cone_size") > 0))
        .sort("cone_size", descending=True)
        .head(count)
    )
    return [int(a) for a in ranked["asn"]]


def build_scenario(
    publication: Publication,
    real_aspas: dict[int, frozenset[int]],
    relationships: TopologySource,
    as_meta: pl.DataFrame,
) -> Scenario:
    """Construct one publication world.

    A synthetic record for a network is its inferred provider set. A network the topology
    knows about but for which it infers *no* providers is a network at the top of the
    hierarchy, and the right synthetic record for it is an AS0 record, meaning "I have no
    providers at all". Skipping those would badly understate what ASPA can do, because an
    AS0 record is the most informative kind: it contradicts every claim that somebody sits
    above that network. The real tier-1 operators publish exactly this.

    Candidates are drawn from ``as_meta``, which is built from the same topology data, so a
    candidate is by construction a network the inference knows about. A network absent from
    it gets no record, because "no providers inferred" and "never heard of it" are different
    statements and only the first justifies an AS0 record.

    Real records always win over synthetic ones, so S1 to S3 only ever *add* publishers and
    never overwrite what an operator actually said.

    Plan Section 10.6 specifies that synthetic records come from the CAIDA file of the month
    *before* the event, which is the caller's responsibility when choosing which relationship
    month to load.
    """
    combined = dict(real_aspas)
    synthetic = 0

    if publication is not Publication.S0:
        if publication is Publication.S1:
            candidates: Iterable[int] = top_by_cone(as_meta, 100)
        elif publication is Publication.S2:
            candidates = top_by_cone(as_meta, 1000)
        else:
            candidates = (int(a) for a in as_meta["asn"])

        for asn in candidates:
            if asn in combined:
                continue
            providers = frozenset(relationships.providers(asn))
            # No inferred providers means the top of the hierarchy, so the synthetic record
            # is an AS0 one rather than nothing at all.
            combined[asn] = providers or frozenset({0})
            synthetic += 1

    return Scenario(
        publication=publication,
        registry=AspaRegistry(combined),
        real_records=len(real_aspas),
        synthetic_records=synthetic,
    )


def filtering_set(filtering: Filtering, as_meta: pl.DataFrame) -> set[int] | None:
    """Which networks drop Invalid routes. ``None`` means every network does."""
    if filtering is Filtering.F_ALL:
        return None
    count = 20 if filtering is Filtering.F_TOP20 else 100
    return set(top_by_cone(as_meta, count))


@dataclass(frozen=True, slots=True)
class Outcome:
    """What one scenario combination did to one route."""

    publication: Publication
    filtering: Filtering
    blocked: bool
    blocking_asn: int | None = None
    blocking_position: int | None = None
    """1-based index along the origin-first path of the network that dropped it."""
    relative_position: float | None = None
    """Blocking position as a fraction of path length, which is what the plan reports."""
    upper_bound_only: bool = False
    """Set for S3, where the synthetic records largely restate the topology the leak was
    detected with. Carried on the result so a table cannot lose the caveat."""


def evaluate_route(
    path: Sequence[int],
    scenarios: Sequence[Scenario],
    filterings: Sequence[Filtering],
    relationships: RelSource,
    as_meta: pl.DataFrame,
    *,
    has_as_set: bool = False,
) -> list[Outcome]:
    """Run every scenario combination against one route."""
    outcomes: list[Outcome] = []
    filters = {f: filtering_set(f, as_meta) for f in filterings}
    for scenario in scenarios:
        for filtering in filterings:
            block = first_block_point(
                path,
                scenario.registry,
                relationships,
                filtering=filters[filtering],
                has_as_set=has_as_set,
            )
            outcomes.append(
                Outcome(
                    publication=scenario.publication,
                    filtering=filtering,
                    blocked=block is not None,
                    blocking_asn=block.blocking_asn if block else None,
                    blocking_position=block.position if block else None,
                    relative_position=(block.relative_position(len(path)) if block else None),
                    upper_bound_only=scenario.is_upper_bound,
                )
            )
    return outcomes


def summarise(outcomes: Iterable[Outcome]) -> pl.DataFrame:
    """Blocked share and median blocking position per scenario combination.

    These are the RQ3 metrics from plan Section 13. The upper-bound flag is carried through
    so a reader of the table cannot miss which rows are S3.
    """
    rows: dict[tuple[str, str], dict[str, object]] = {}
    positions: dict[tuple[str, str], list[float]] = {}
    for outcome in outcomes:
        key = (str(outcome.publication), str(outcome.filtering))
        row = rows.setdefault(
            key,
            {
                "publication": str(outcome.publication),
                "filtering": str(outcome.filtering),
                "routes": 0,
                "blocked": 0,
                "upper_bound_only": outcome.upper_bound_only,
            },
        )
        row["routes"] = int(row["routes"]) + 1  # type: ignore[call-overload]
        if outcome.blocked:
            row["blocked"] = int(row["blocked"]) + 1  # type: ignore[call-overload]
            if outcome.relative_position is not None:
                positions.setdefault(key, []).append(outcome.relative_position)

    out = []
    for key, row in rows.items():
        seen = positions.get(key, [])
        blocked = int(row["blocked"])  # type: ignore[call-overload]
        routes = int(row["routes"])  # type: ignore[call-overload]
        out.append(
            {
                **row,
                "blocked_share": blocked / routes if routes else 0.0,
                "median_blocking_position": (median(seen) if seen else None),
            }
        )
    return pl.DataFrame(out).sort(["publication", "filtering"])
