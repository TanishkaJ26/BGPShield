"""RQ2: are published ASPA records complete, and what does it cost when they are not?

## The question, in plain English

An ASPA record is only useful if it lists *all* of a network's providers. If one is missing,
every legitimate route that arrives through that missing provider looks like a forgery, and a
network filtering on ASPA would throw it away. So an incomplete record is not a harmless gap.
It is a self-inflicted outage waiting for someone to switch on enforcement.

This module measures that in two ways:

1. Compare each publisher's list against the providers CAIDA infers for it from public
   routing data. A provider that CAIDA sees and the record omits is a candidate omission.
2. Count the routes that ASPA calls Invalid but whose path is perfectly well shaped under
   the independent valley-free test. Those are the likely false positives.

## The caveat that has to travel with every number here

CAIDA's relationships are *inferred*, not declared, and they have errors of their own (plan
Section 15). A disagreement between a published record and an inference is evidence that one
of them is wrong, not proof that the record is. That is why the output calls them candidates,
why the counts are reported alongside the disagreements in the other direction, and why plan
Section 11 asks for the largest cases to be reviewed by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from hijax.detect.leaks import Shape, classify_shape, path_directions
from hijax.topology import RelSource, SiblingSource, TopologySource

COMPARISON_SCHEMA: dict[str, pl.DataType] = {
    "asn": pl.Int64(),
    "published": pl.List(pl.Int64()),
    "inferred": pl.List(pl.Int64()),
    "missing": pl.List(pl.Int64()),
    "extra": pl.List(pl.Int64()),
    "n_published": pl.Int64(),
    "n_inferred": pl.Int64(),
    "n_missing": pl.Int64(),
    "n_extra": pl.Int64(),
    "is_as0": pl.Boolean(),
    "agrees": pl.Boolean(),
}


def compare_providers(aspas: pl.DataFrame, relationships: TopologySource) -> pl.DataFrame:
    """Compare every publisher's declared provider list with the inferred one.

    ``missing`` holds providers CAIDA infers that the record does not name, which is the
    direction that causes false positives. ``extra`` holds the reverse, which usually means
    CAIDA has not seen the link rather than that the operator invented it.

    An AS0 record declares "I have no providers at all", so its effective published set is
    empty and every inferred provider counts as missing. Those are the strongest
    disagreements in the table and the first thing to review by hand.
    """
    rows: list[dict[str, Any]] = []
    for customer, providers in zip(aspas["customer_asn"], aspas["provider_asns"], strict=True):
        asn = int(customer)
        declared = {int(p) for p in providers}
        is_as0 = declared == {0}
        effective = set() if is_as0 else declared - {0}
        inferred = {int(p) for p in relationships.providers(asn)}

        missing = sorted(inferred - effective)
        extra = sorted(effective - inferred)
        rows.append(
            {
                "asn": asn,
                "published": sorted(effective),
                "inferred": sorted(inferred),
                "missing": missing,
                "extra": extra,
                "n_published": len(effective),
                "n_inferred": len(inferred),
                "n_missing": len(missing),
                "n_extra": len(extra),
                "is_as0": is_as0,
                "agrees": not missing and not extra,
            }
        )
    return pl.DataFrame(rows, schema=COMPARISON_SCHEMA).sort(
        ["n_missing", "asn"], descending=[True, False]
    )


def completeness_summary(comparison: pl.DataFrame) -> dict[str, Any]:
    """Headline numbers for RQ2, as plan Section 13 lists them."""
    total = comparison.height
    if total == 0:
        return {"publishers": 0}
    missing_any = comparison.filter(pl.col("n_missing") > 0)
    return {
        "publishers": total,
        "agree_exactly": comparison.filter(pl.col("agrees")).height,
        "missing_at_least_one": missing_any.height,
        "missing_share": missing_any.height / total,
        "extra_at_least_one": comparison.filter(pl.col("n_extra") > 0).height,
        "as0_records": comparison.filter(pl.col("is_as0")).height,
        "as0_contradicted": comparison.filter(pl.col("is_as0") & (pl.col("n_missing") > 0)).height,
        # A publisher with no inferred providers is only unjudgeable when it claims to have
        # some. When it published an AS0 record, "no providers" is exactly what the inference
        # says too, so the two agree and it must not be counted as a gap in the evidence.
        "as0_corroborated": comparison.filter(
            pl.col("is_as0") & (pl.col("n_inferred") == 0)
        ).height,
        "cannot_judge": comparison.filter((pl.col("n_inferred") == 0) & ~pl.col("is_as0")).height,
    }


@dataclass(slots=True)
class FalsePositiveEstimate:
    """How many ASPA-Invalid routes look legitimate under the independent shape test."""

    invalid_routes: int = 0
    valley: int = 0
    """Invalid and genuinely mis-shaped: ASPA and the relationship data agree."""
    valley_free: int = 0
    """Invalid but well shaped: a likely false positive."""
    undetermined: int = 0
    """Invalid, but a missing relationship means the shape test cannot say."""
    as_set: int = 0
    """Invalid only because the path carries an AS_SET, which is a different matter."""

    @property
    def likely_false_positive_share(self) -> float:
        """Of the Invalid routes the shape test can judge, the share that look legitimate."""
        judged = self.valley + self.valley_free
        return self.valley_free / judged if judged else 0.0


def estimate_false_positives(
    invalid_routes: pl.DataFrame,
    relationships: RelSource,
    siblings: SiblingSource | None = None,
) -> FalsePositiveEstimate:
    """Classify ASPA-Invalid routes by whether their path is actually mis-shaped.

    ``invalid_routes`` needs an ``as_path`` column and a ``has_as_set`` column. An AS_SET
    path is counted separately: the draft rejects it outright (Section 5.5 step 3), so it is
    neither evidence of a leak nor evidence of a bad record.
    """
    estimate = FalsePositiveEstimate()
    for path, has_as_set in invalid_routes.select(["as_path", "has_as_set"]).iter_rows():
        estimate.invalid_routes += 1
        if has_as_set:
            estimate.as_set += 1
            continue
        shape = classify_shape(path_directions(list(path), relationships, siblings))
        if shape is Shape.VALLEY:
            estimate.valley += 1
        elif shape is Shape.VALLEY_FREE:
            estimate.valley_free += 1
        else:
            estimate.undetermined += 1
    return estimate


def blame_by_as(invalid_routes: pl.DataFrame, top: int = 20) -> pl.DataFrame:
    """Which networks' records are behind the most Invalid routes.

    Keyed on the *customer* side of the contradicted hop, because that is the network whose
    published record did the contradicting. Plan Section 11 asks for the top 20 of these to
    be reviewed by hand.
    """
    return (
        invalid_routes.filter(pl.col("first_bad_hop_from").is_not_null())
        .group_by("first_bad_hop_from")
        .agg(
            pl.len().alias("invalid_routes"),
            pl.col("first_bad_hop_to").n_unique().alias("distinct_claimed_providers"),
            pl.col("first_bad_hop_to").unique().sort().alias("claimed_providers"),
            pl.col("prefix").n_unique().alias("distinct_prefixes"),
        )
        .rename({"first_bad_hop_from": "asn"})
        .sort("invalid_routes", descending=True)
        .head(top)
    )
