"""Small JSON files for the dashboard (plan Section 11, Phase 7).

Everything here is built from tables already on disk, so exporting downloads nothing and the
same data always produces the same files. That matters more than usual for this phase: the
site is the public face of the measurements, and a number on a web page is the one most
likely to be quoted without its caveats.

Three rules the exporters follow:

* **A budget.** The plan allows under 5 MB for the whole export. These files are committed,
  so an unbounded per-AS table would bloat the repository and every clone of it. `build_all`
  measures the total and reports whether it fits.
* **Caveats travel with the numbers.** Every file carries a ``notes`` field naming the limits
  that apply to it - country of registration rather than operation, inferred relationships,
  single-collector visibility - so the site cannot show a figure without its qualification.
* **Nothing is invented.** A missing input produces a named skip, never a placeholder that
  looks like a measurement.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from hijax.analysis.adoption import aspa_coverage_by_position
from hijax.analysis.longitudinal import build_series
from hijax.analysis.regional import compare_regions, largest_transit
from hijax.config import Config

#: Plan Section 11 Phase 7: the whole exported payload must stay under this.
BUDGET_BYTES = 5_000_000

#: How many networks the searchable table carries. The full set is about 86,000 routed AS
#: numbers, which would blow the budget on its own, so the export keeps the ones a reader
#: would actually look up: every ASPA publisher, plus the largest networks by customer cone.
TOP_BY_CONE = 2_000


@dataclass(slots=True)
class ExportResult:
    """Which files were written, which were skipped, and what the payload weighs."""

    written: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    total_bytes: int = 0

    @property
    def within_budget(self) -> bool:
        return self.total_bytes <= BUDGET_BYTES


def _write(payload: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=1, sort_keys=False, default=str) + "\n", encoding="utf-8"
    )
    return destination


def _latest(root: Path) -> date | None:
    if not root.exists():
        return None
    found: list[date] = []
    for child in root.iterdir():
        if child.name.startswith("snapshot_date="):
            try:
                found.append(date.fromisoformat(child.name.split("=", 1)[1]))
            except ValueError:
                continue
    return max(found) if found else None


def _read_partition(root: Path, day: date, leaf: str, columns: list[str]) -> pl.DataFrame | None:
    """Read one date's rows, concatenating whatever collectors are stored under it."""
    base = root / f"snapshot_date={day:%Y-%m-%d}"
    if not base.exists():
        return None
    direct = base / leaf
    if direct.exists():
        return pl.read_parquet(direct, columns=columns)
    frames = [
        pl.read_parquet(child / leaf, columns=columns)
        for child in sorted(base.iterdir())
        if (child / leaf).exists()
    ]
    return pl.concat(frames) if frames else None


def _previous_month(day: date) -> str:
    year, month = day.year, day.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def export_networks(cfg: Config, destination: Path) -> Path:
    """The searchable per-AS table: origin-validation state, ASPA status, cone and country.

    Plan Section 11 Phase 7 asks for a table a reader can search by network, showing ROA and
    ASPA status.
    """
    day = _latest(cfg.paths.processed / "rov_results")
    if day is None:
        raise FileNotFoundError("no validation results stored")

    rov = _read_partition(
        cfg.paths.processed / "rov_results",
        day,
        "rov_results.parquet",
        ["origin_asn", "rov_state"],
    )
    if rov is None:
        raise FileNotFoundError(f"no readable validation results for {day}")

    # One row per origin AS: how many of its routes fell into each origin-validation state.
    by_as = (
        rov.drop_nulls("origin_asn")
        .group_by("origin_asn", "rov_state")
        .len()
        .pivot(on="rov_state", index="origin_asn", values="len")
        .fill_null(0)
    )

    aspas = _read_partition(
        cfg.paths.processed / "aspas", day, "aspas.parquet", ["customer_asn", "provider_asns"]
    )
    providers_listed: dict[int, int] = {}
    if aspas is not None:
        for row in aspas.iter_rows(named=True):
            providers_listed[int(row["customer_asn"])] = len(row["provider_asns"] or [])

    month = _previous_month(day)
    meta_path = cfg.paths.processed / "as_meta" / f"month={month}" / "as_meta.parquet"
    frame = by_as
    if meta_path.exists():
        frame = frame.join(
            pl.read_parquet(meta_path).select(["asn", "country", "rir", "cone_size", "rank"]),
            left_on="origin_asn",
            right_on="asn",
            how="left",
        )

    frame = frame.with_columns(
        pl.col("origin_asn").is_in(list(providers_listed)).alias("publishes_aspa")
    )

    # Keep every publisher, plus the largest networks by cone: a reader looking a network up
    # is looking for one of those two.
    if "cone_size" in frame.columns:
        largest = frame.sort("cone_size", descending=True, nulls_last=True).head(TOP_BY_CONE)
        kept = pl.concat([largest, frame.filter(pl.col("publishes_aspa"))]).unique(
            subset=["origin_asn"]
        )
        kept = kept.sort("cone_size", descending=True, nulls_last=True)
    else:
        kept = frame.head(TOP_BY_CONE)

    rows: list[dict[str, Any]] = []
    for row in kept.iter_rows(named=True):
        asn = int(row["origin_asn"])
        rows.append(
            {
                "asn": asn,
                "country": row.get("country"),
                "rir": row.get("rir"),
                "cone_size": row.get("cone_size"),
                "rank": row.get("rank"),
                "publishes_aspa": bool(row["publishes_aspa"]),
                "providers_listed": providers_listed.get(asn),
                "routes_valid": int(row.get("valid") or 0),
                "routes_invalid": int(row.get("invalid") or 0),
                "routes_not_found": int(row.get("not_found") or 0),
            }
        )

    return _write(
        {
            "snapshot_date": str(day),
            "metadata_month": month,
            "networks": len(rows),
            "selection": (
                f"every ASPA publisher, plus the {TOP_BY_CONE} largest networks by customer "
                "cone. This is not the whole routing table."
            ),
            "notes": [
                "Country is the country of REGISTRATION, not where the network operates.",
                "Customer cone and rank come from CAIDA AS Rank and are inferred, not observed.",
                "Route counts are per origin AS across the collectors ingested for this date.",
            ],
            "rows": rows,
        },
        destination,
    )


def export_regional(cfg: Config, destination: Path, *, country: str = "IN") -> Path:
    """RQ4: one country and its region against the world."""
    day = _latest(cfg.paths.processed / "routes")
    if day is None:
        raise FileNotFoundError("no ingested routes")

    routes = _read_partition(cfg.paths.processed / "routes", day, "routes.parquet", ["origin_asn"])
    aspas = _read_partition(cfg.paths.processed / "aspas", day, "aspas.parquet", ["customer_asn"])
    if routes is None or aspas is None:
        raise FileNotFoundError(f"missing routes or ASPA records for {day}")

    month = _previous_month(day)
    meta_path = cfg.paths.processed / "as_meta" / f"month={month}" / "as_meta.parquet"
    if not meta_path.exists():
        raise FileNotFoundError(f"no as_meta for {month}")

    meta = pl.read_parquet(meta_path)
    publishers = {int(a) for a in aspas["customer_asn"]}
    routed = {int(a) for a in routes.drop_nulls("origin_asn")["origin_asn"].unique()}

    return _write(
        {
            "snapshot_date": str(day),
            "metadata_month": month,
            "country": country,
            "regions": compare_regions(meta, publishers, routed, country=country).to_dicts(),
            "largest_transit": largest_transit(
                meta, publishers, country=country, top=20
            ).to_dicts(),
            "notes": [
                "Country is the country of REGISTRATION, not where the network operates.",
                "None of this project's collectors is in India; the view is assembled from how "
                "Indian networks appear from Amsterdam, Oregon, Singapore, Tokyo and Sydney.",
                "The APNIC region is selected by allocating registry, not by a list of "
                "countries, so it needs no geographic judgement of its own.",
                "Shares are measured against networks seen ORIGINATING a route, not against "
                "every registered allocation.",
            ],
        },
        destination,
    )


def export_path_coverage(cfg: Config, destination: Path) -> Path:
    """RQ1: where ASPA publishers sit on real paths, which is what adoption actually buys."""
    day = _latest(cfg.paths.processed / "routes")
    if day is None:
        raise FileNotFoundError("no ingested routes")

    routes = _read_partition(cfg.paths.processed / "routes", day, "routes.parquet", ["as_path"])
    aspas = _read_partition(cfg.paths.processed / "aspas", day, "aspas.parquet", ["customer_asn"])
    if routes is None or aspas is None:
        raise FileNotFoundError(f"missing routes or ASPA records for {day}")

    publishers = {int(a) for a in aspas["customer_asn"]}
    coverage = aspa_coverage_by_position(routes, publishers)

    return _write(
        {
            "snapshot_date": str(day),
            "shares": coverage["shares"],
            "notes": [
                "An ASPA record can only judge a hop when BOTH networks either side of it "
                "publish, so 'two publishers adjacent' is the first useful number here.",
                "'anywhere on the path' overstates what is deployable today and should never "
                "be quoted on its own.",
            ],
        },
        destination,
    )


def export_longitudinal(cfg: Config, destination: Path) -> Path:
    """ROV, ASPA and leak aggregates across every validated date."""
    series = build_series(cfg)
    if series.height == 0:
        raise FileNotFoundError("no validated dates stored")
    return _write(
        {
            "dates": series.height,
            "series": series.to_dicts(),
            "notes": [
                "The RPKI half of this series is weekly and complete; the BGP half is sampled "
                "quarterly from route-views2 only (docs/decisions.md D-047).",
                "A date missing one input appears with nulls rather than being dropped, so a "
                "gap in the sweep stays visible.",
            ],
        },
        destination,
    )


def export_incidents(cfg: Config, destination: Path) -> Path:
    """Phase 5's curated incidents and how the detector fared on each.

    Reads what `hijax incidents` stored rather than re-fetching any archive window, so the
    site shows a recorded result instead of one recomputed on every build.
    """
    stored = cfg.paths.processed / "incidents" / "results.json"
    if not stored.exists():
        raise FileNotFoundError("no incident results stored; run 'hijax incidents' first")

    payload = json.loads(stored.read_text(encoding="utf-8"))
    return _write(
        {
            "collectors": payload.get("collectors", []),
            "summary": payload.get("summary", {}),
            "incidents": payload.get("incidents", []),
            "notes": [
                "Only route leaks can be judged this way. An origin hijack travels an "
                "ordinary-looking path and in an RPKI misuse incident the routing was "
                "correct, so neither is something a path-based detector could find; both are "
                "reported as not applicable, never as misses.",
                "'not visible' means the collectors used never saw the leak, which is a "
                "statement about where the vantage points are and not about the detector.",
                "Recall here rests on a denominator of two. It is a count, not an estimate.",
            ],
        },
        destination,
    )


def export_summary(cfg: Config, destination: Path, *, sources: dict[str, Path]) -> Path:
    """The headline numbers, each beside the caveat it must not be quoted without."""
    headline: dict[str, Any] = {"generated_from": sorted(p.name for p in sources.values())}

    regional = sources.get("regional")
    if regional is not None and regional.exists():
        payload = json.loads(regional.read_text(encoding="utf-8"))
        headline["adoption"] = {
            row["region"]: {
                "routed_networks": row["routed_networks"],
                "publishers": row["publishers_that_route"],
                "share_of_routed": row["share_of_routed"],
            }
            for row in payload["regions"]
        }
        ranked = payload.get("largest_transit", [])
        headline["largest_transit_publishing"] = {
            "country": payload.get("country"),
            "examined": len(ranked),
            "publishing": len([r for r in ranked if r.get("publishes_aspa")]),
        }

    coverage = sources.get("path_coverage")
    if coverage is not None and coverage.exists():
        headline["path_coverage"] = json.loads(coverage.read_text(encoding="utf-8"))["shares"]

    headline["caveats"] = [
        "Country means country of registration, not where a network operates.",
        "Relationships and customer cones are INFERRED from CAIDA data, not ground truth.",
        "Every number is limited by where the collectors are, and none of them is in India.",
        "Adoption share and path coverage must be read together: a large share of routes "
        "touching a publisher does not mean those routes can be validated.",
    ]
    return _write(headline, destination)


def build_all(cfg: Config, *, destination: Path | None = None) -> ExportResult:
    """Write every dashboard file the stored data supports, and measure the size budget."""
    out = destination or cfg.paths.web_data
    result = ExportResult()
    written: dict[str, Path] = {}

    jobs: list[tuple[str, str, Callable[[Config, Path], Path]]] = [
        ("networks", "networks.json", export_networks),
        ("regional", "regional.json", export_regional),
        ("path_coverage", "path_coverage.json", export_path_coverage),
        ("longitudinal", "longitudinal.json", export_longitudinal),
        ("incidents", "incidents.json", export_incidents),
    ]
    for name, filename, func in jobs:
        try:
            path = func(cfg, out / filename)
        except (FileNotFoundError, ValueError) as exc:
            result.skipped.append((name, str(exc)))
            continue
        written[name] = path
        result.written.append(path)

    # Only worth writing once something real went into it. A summary holding nothing but
    # caveats still looks like a result to anyone who opens it.
    if written:
        try:
            result.written.append(export_summary(cfg, out / "summary.json", sources=written))
        except (FileNotFoundError, ValueError) as exc:
            result.skipped.append(("summary", str(exc)))
    else:
        result.skipped.append(("summary", "nothing was exported to summarise"))

    # The adoption series is written by `hijax adoption --export` and counts against the same
    # budget, so include whatever is already published there.
    total = sum(p.stat().st_size for p in result.written)
    existing = out / "aspa_adoption.json"
    if existing.exists():
        total += existing.stat().st_size
    result.total_bytes = total
    return result
