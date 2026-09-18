"""Command-line entry point (plan Section 17).

Subcommands are added phase by phase, so every command that exists actually works.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from hijax import __version__
from hijax.analysis.adoption import build as build_adoption
from hijax.analysis.adoption import update_json as update_adoption_json
from hijax.config import DEFAULT_CONFIG_PATH, load_config
from hijax.ingest.bgp import ingest_many
from hijax.ingest.meta import (
    RelationshipLookup,
    ingest_month,
    load_asn_registry,
    write_asn_registry,
)
from hijax.ingest.rpki import date_range, ingest_date
from hijax.paths import PathFlag
from hijax.validate.aspa import AspaState
from hijax.validate.rov import RovState
from hijax.validate.run import load_aspa_registry, load_vrp_index, validate_collector

app = typer.Typer(help="Hijax: BGP route-security measurement pipeline.", no_args_is_help=True)

_EVERY = re.compile(r"^(\d+)\s*d?$", re.IGNORECASE)


@app.callback()
def main() -> None:
    """Hijax command-line interface (plan Section 17).

    Registering a callback keeps Typer in multi-command mode even while only a few
    subcommands exist, so ``hijax version`` works from Phase 0 onward.
    """


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(f"hijax {__version__}")


def _parse_day(value: str, flag: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} must look like YYYY-MM-DD, got {value!r}") from exc


def _parse_every(value: str) -> int:
    match = _EVERY.match(value.strip())
    if not match:
        raise typer.BadParameter(f"--every must look like '7d' or '7', got {value!r}")
    return int(match.group(1))


@app.command("ingest-rpki")
def ingest_rpki(
    day: Annotated[
        str | None, typer.Option("--date", help="Single snapshot date, YYYY-MM-DD.")
    ] = None,
    date_from: Annotated[
        str | None, typer.Option("--from", help="First date of a backfill.")
    ] = None,
    date_to: Annotated[
        str | None, typer.Option("--to", help="Last date of a backfill, inclusive.")
    ] = None,
    every: Annotated[
        str, typer.Option("--every", help="Backfill step, e.g. 7d for weekly.")
    ] = "1d",
    config_path: Annotated[Path, typer.Option("--config", help="Config file.")] = (
        DEFAULT_CONFIG_PATH
    ),
    force: Annotated[
        bool, typer.Option("--force", help="Re-download and re-write existing days.")
    ] = False,
    jobs: Annotated[
        int, typer.Option("--jobs", help="Concurrent downloads per date (be polite).")
    ] = 4,
) -> None:
    """Download one or more days of RPKI validator output into the vrps and aspas tables.

    Plain English: this fetches the list of signed routing records that were valid on a
    given day, one file per regional registry, and stores them in a columnar file that
    later phases can query quickly. Source and format were verified in Phase 0; see
    ``docs/data-sources.md`` section 3.
    """
    cfg = load_config(config_path)

    if day and (date_from or date_to):
        raise typer.BadParameter("use --date on its own, or --from with --to")
    if day:
        days = [_parse_day(day, "--date")]
    elif date_from and date_to:
        days = date_range(
            _parse_day(date_from, "--from"), _parse_day(date_to, "--to"), _parse_every(every)
        )
    else:
        raise typer.BadParameter("give --date, or both --from and --to")

    earliest = cfg.rpki.earliest_aspa_date
    failures = 0
    for target in days:
        if target < earliest:
            typer.echo(f"{target}  skipped, before the first ASPA record on {earliest}")
            continue
        try:
            result = ingest_date(cfg, target, force=force, jobs=jobs)
        except Exception as exc:  # noqa: BLE001 - report and carry on with the backfill
            failures += 1
            typer.echo(f"{target}  FAILED: {exc}")
            continue
        if not result.trust_anchors and not result.skipped:
            failures += 1
            typer.echo(f"{target}  no data: archive returned nothing for any trust anchor")
            continue
        if result.skipped:
            # Counts come from the Parquet files; the per-parse statistics are not recomputed.
            typer.echo(f"{target}  vrps={result.vrps:>8}  aspas={result.aspas:>6}  cached")
        else:
            missing = ",".join(result.missing) or "none"
            typer.echo(
                f"{target}  vrps={result.vrps:>8}  aspas={result.aspas:>6}  "
                f"merged={result.aspas_merged}  as0only={result.providers_as0}  "
                f"as0dropped={result.as0_dropped}  missing={missing}"
            )

    if failures:
        typer.echo(f"{failures} of {len(days)} dates failed")
        raise typer.Exit(code=1)


@app.command("adoption")
def adoption(
    config_path: Annotated[Path, typer.Option("--config", help="Config file.")] = (
        DEFAULT_CONFIG_PATH
    ),
    export: Annotated[
        Path | None,
        typer.Option("--export", help="Write or update the dashboard JSON at this path."),
    ] = None,
    refresh_registry: Annotated[
        bool, typer.Option("--refresh-registry", help="Re-download the RIR delegated files.")
    ] = False,
    top_countries: Annotated[
        int, typer.Option("--top-countries", help="Countries kept in the exported JSON.")
    ] = 25,
) -> None:
    """Report ASPA adoption over time: per day, per trust anchor, per country (RQ1).

    Reads only what ``hijax ingest-rpki`` has already stored. The country column comes
    from the RIR delegated-stats files and is the country of *registration*, which is not
    necessarily where the network operates (plan Sections 8 and 15).
    """
    cfg = load_config(config_path)
    if refresh_registry:
        path, count = write_asn_registry(cfg, force=True)
        typer.echo(f"registry refreshed: {count} AS numbers -> {path}")
    registry = load_asn_registry(cfg)
    tables = build_adoption(cfg, registry)

    by_day = tables.by_day
    if by_day.height == 0:
        typer.echo("no snapshots ingested yet; run 'hijax ingest-rpki' first")
        raise typer.Exit(code=1)

    typer.echo(f"snapshots: {by_day.height}")
    first, last = by_day.row(0, named=True), by_day.row(-1, named=True)
    typer.echo(f"first: {first['snapshot_date']}  aspas={first['aspas']}")
    typer.echo(f"last:  {last['snapshot_date']}  aspas={last['aspas']}")

    latest_ta = tables.by_ta.filter(pl.col("snapshot_date") == last["snapshot_date"])
    typer.echo("latest per trust anchor:")
    for row in latest_ta.iter_rows(named=True):
        typer.echo(f"  {row['ta']:<8} {row['aspas']}")

    latest_country = tables.by_country.filter(
        pl.col("snapshot_date") == last["snapshot_date"]
    ).head(10)
    typer.echo("latest top countries (country of registration):")
    for row in latest_country.iter_rows(named=True):
        typer.echo(f"  {row['country']:<4} {row['aspas']}")

    if export is not None:
        written = update_adoption_json(tables, export, top_countries=top_countries)
        typer.echo(f"wrote {written}")


@app.command("ingest-bgp")
def ingest_bgp(
    day: Annotated[str, typer.Option("--date", help="Snapshot date, YYYY-MM-DD.")],
    collectors: Annotated[
        str | None,
        typer.Option("--collectors", help="Comma-separated. Defaults to the configured set."),
    ] = None,
    config_path: Annotated[Path, typer.Option("--config", help="Config file.")] = (
        DEFAULT_CONFIG_PATH
    ),
    force: Annotated[bool, typer.Option("--force", help="Re-ingest days already stored.")] = False,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Stop after N routes per collector (smoke runs).")
    ] = None,
    jobs: Annotated[
        int, typer.Option("--jobs", help="Collectors to ingest at once, in separate processes.")
    ] = 1,
) -> None:
    """Ingest one routing-table dump per collector into the routes table.

    Plain English: a route collector is a passive listener that records what its neighbours
    announce. This downloads one table dump per collector for the date, normalizes every
    AS_PATH to origin-first form, and stores the result column by column.
    """
    cfg = load_config(config_path)
    target = _parse_day(day, "--date")
    chosen = [c.strip() for c in collectors.split(",")] if collectors else list(cfg.bgp.collectors)

    failures = 0
    totals = Counter[str]()
    try:
        results = ingest_many(cfg, chosen, target, force=force, limit=limit, jobs=jobs)
    except Exception as exc:  # noqa: BLE001 - report rather than leaving a stack trace
        typer.echo(f"FAILED: {exc}")
        raise typer.Exit(code=1) from exc

    for result in results:
        collector = result.collector
        if result.error is not None:
            failures += 1
            typer.echo(f"{collector:<20} FAILED: {result.error}")
            continue
        if result.skipped:
            typer.echo(f"{collector:<20} rows={result.rows:>9}  cached")
            continue
        totals["rows"] += result.rows
        totals["seconds"] += int(result.seconds)
        rates = "  ".join(
            f"{flag}={result.flags.get(flag, 0) / result.rows:.2%}"
            for flag in PathFlag
            if result.flags.get(flag)
        )
        typer.echo(
            f"{collector:<20} rows={result.rows:>9}  peers={result.peers:>4}  "
            f"prefixes={result.prefixes:>8}  {result.seconds:>6.1f}s  {rates}"
        )

    typer.echo(f"total rows: {totals['rows']}  wall clock: {totals['seconds']}s")
    if failures:
        typer.echo(f"{failures} of {len(chosen)} collectors failed")
        raise typer.Exit(code=1)


@app.command("ingest-meta")
def ingest_meta(
    month: Annotated[str, typer.Option("--month", help="Month to build, YYYY-MM.")],
    config_path: Annotated[Path, typer.Option("--config", help="Config file.")] = (
        DEFAULT_CONFIG_PATH
    ),
    force: Annotated[bool, typer.Option("--force", help="Re-download and rebuild.")] = False,
    skip_asrank: Annotated[
        bool, typer.Option("--skip-asrank", help="Skip the slow AS Rank walk.")
    ] = False,
    asrank_pages: Annotated[
        int | None, typer.Option("--asrank-pages", help="Stop after N AS Rank pages.")
    ] = None,
) -> None:
    """Build the as_rel and as_meta tables for one month.

    Plain English: this fetches who-pays-whom relationships between networks, which
    organisation owns each AS number, and how large each network's customer cone is. Later
    phases use the first to spot route leaks, the second to avoid calling two arms of one
    company a leak, and the third to pick the largest networks.
    """
    cfg = load_config(config_path)
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise typer.BadParameter(f"--month must look like YYYY-MM, got {month!r}")
    result = ingest_month(
        cfg, month, force=force, skip_asrank=skip_asrank, asrank_pages=asrank_pages
    )
    typer.echo(f"month {result.month}")
    typer.echo(f"  relationships : {result.relationships:>9,}")
    typer.echo(f"  organisations : {result.organisations:>9,}")
    note = " (skipped)" if result.skipped_asrank else ""
    typer.echo(f"  ranked ASes   : {result.ranked:>9,}{note}")
    typer.echo(f"  as_meta rows  : {result.as_meta_rows:>9,}")


@app.command("validate")
def validate(
    day: Annotated[str, typer.Option("--date", help="Snapshot date, YYYY-MM-DD.")],
    collectors: Annotated[
        str | None,
        typer.Option("--collectors", help="Comma-separated. Defaults to the configured set."),
    ] = None,
    month: Annotated[
        str | None,
        typer.Option("--month", help="Relationship month. Defaults to the month before."),
    ] = None,
    config_path: Annotated[Path, typer.Option("--config", help="Config file.")] = (
        DEFAULT_CONFIG_PATH
    ),
) -> None:
    """Run origin and ASPA validation over the stored routes for a date.

    Plain English: for every route a collector recorded, this asks two questions. Is the
    network announcing these addresses allowed to? And does the path it travelled make sense
    given what networks have published about their providers?

    Relationships default to the month *before* the snapshot, because plan Section 10.4 wants
    a relationship graph that was not inferred from the events being studied.
    """
    cfg = load_config(config_path)
    target = _parse_day(day, "--date")
    chosen = [c.strip() for c in collectors.split(",")] if collectors else list(cfg.bgp.collectors)
    rel_month = month or _previous_month(target)

    rel_path = cfg.paths.processed / "as_rel" / f"month={rel_month}" / "as_rel.parquet"
    if not rel_path.exists():
        typer.echo(f"no relationships for {rel_month}; run 'hijax ingest-meta --month {rel_month}'")
        raise typer.Exit(code=1)

    typer.echo(f"loading VRPs and ASPAs for {target}, relationships for {rel_month}")
    vrps = load_vrp_index(cfg, target)
    registry = load_aspa_registry(cfg, target)
    relationships = RelationshipLookup.from_frame(pl.read_parquet(rel_path))
    typer.echo(f"  {len(vrps):,} VRPs, {len(registry):,} ASPA records")

    failures = 0
    for collector in chosen:
        try:
            summary = validate_collector(cfg, collector, target, vrps, registry, relationships)
        except FileNotFoundError as exc:
            failures += 1
            typer.echo(f"{collector:<20} SKIPPED: {exc}")
            continue
        typer.echo(
            f"{collector:<20} routes={summary.routes:>10,}  "
            f"distinct origins={summary.distinct_origins:>9,}  "
            f"distinct paths={summary.distinct_paths:>8,}  {summary.seconds:>6.1f}s"
        )
        typer.echo(
            "    ROV  "
            + "  ".join(
                f"{state}={summary.rov_share(state):.2%}"
                for state in (RovState.VALID, RovState.INVALID, RovState.NOT_FOUND)
            )
            + (
                "  reasons: " + ", ".join(f"{k}={v:,}" for k, v in summary.rov_reasons.items())
                if summary.rov_reasons
                else ""
            )
        )
        typer.echo(
            "    ASPA "
            + "  ".join(
                f"{state}={summary.aspa_share(state):.2%}"
                for state in (AspaState.VALID, AspaState.INVALID, AspaState.UNKNOWN)
            )
            + "  procedure: "
            + ", ".join(f"{k}={v / summary.routes:.1%}" for k, v in summary.aspa_procedures.items())
        )

    if failures:
        raise typer.Exit(code=1)


def _previous_month(day: date) -> str:
    year, month = day.year, day.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"
