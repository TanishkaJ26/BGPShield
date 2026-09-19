"""Command-line entry point (plan Section 17).

Subcommands are added phase by phase, so every command that exists actually works.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

import polars as pl
import typer

from bgpshield import __version__
from bgpshield import reproduce as reproduce_mod
from bgpshield.analysis.adoption import build as build_adoption
from bgpshield.analysis.adoption import longest_daily_streak
from bgpshield.analysis.adoption import update_json as update_adoption_json
from bgpshield.analysis.correctness import (
    blame_by_as,
    compare_providers,
    completeness_summary,
    estimate_false_positives,
)
from bgpshield.analysis.longitudinal import build_series, publisher_series
from bgpshield.analysis.regional import compare_regions, largest_transit
from bgpshield.config import CONFIG_ENV_VAR, Config, ConfigError, load_config
from bgpshield.counterfactual import (
    Filtering,
    Publication,
    build_scenario,
    evaluate_route,
    summarise,
)
from bgpshield.detect.leaks import detect_in_path
from bgpshield.detect.run import detect_day
from bgpshield.export import BUDGET_BYTES as EXPORT_BUDGET_BYTES
from bgpshield.export import build_all as build_export
from bgpshield.incidents import Incident, IncidentResult, load_incidents, recall
from bgpshield.incidents import Outcome as IncidentOutcome
from bgpshield.ingest.bgp import ingest_many, ingest_updates
from bgpshield.ingest.meta import (
    RelationshipLookup,
    ingest_month,
    load_asn_registry,
    write_asn_registry,
)
from bgpshield.ingest.rpki import date_range, ingest_date
from bgpshield.net import DownloadError
from bgpshield.paths import PathFlag
from bgpshield.report import build_all as build_figures
from bgpshield.tables import date_partition, date_table, month_table, previous_month
from bgpshield.validate.aspa import AspaState
from bgpshield.validate.rov import RovState
from bgpshield.validate.run import load_aspa_registry, load_vrp_index, validate_collector

#: Plan Section 11 Phase 1: the daily job must have run this many days in a row.
DAILY_STREAK_REQUIRED = 7

app = typer.Typer(
    help="BGPShield: BGP route-security measurement pipeline.",
    no_args_is_help=True,
    # A traceback that dumps every local variable can print a whole DataFrame; the message
    # is what matters, and ``run`` below turns the expected failures into one line anyway.
    pretty_exceptions_show_locals=False,
)

_EVERY = re.compile(r"^(\d+)\s*d?$", re.IGNORECASE)

#: Shared by every command. ``None`` means "find it": ``$BGPSHIELD_CONFIG``, then
#: ``config/default.yaml`` in the working directory or any directory above it.
ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help=f"Config file. Default: ${CONFIG_ENV_VAR}, else config/default.yaml found upwards.",
        show_default=False,
    ),
]


def configure_logging(verbose: bool) -> None:
    """Send log lines to stderr, so stdout stays a clean report a script can parse.

    Normal runs show warnings only. ``--verbose`` shows every download attempt and retry,
    which is the first thing to look at when an archive is slow or refusing requests.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.INFO if verbose else logging.WARNING)


@app.callback()
def main(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Log every download attempt to stderr.")
    ] = False,
) -> None:
    """BGPShield command-line interface (plan Section 17).

    Registering a callback keeps Typer in multi-command mode even while only a few
    subcommands exist, so ``bgpshield version`` works from Phase 0 onward.
    """
    configure_logging(verbose)


def run() -> None:
    """Console-script entry point.

    Failures the operator can act on - a missing config file, an archive that would not
    serve a file - are printed as one line and exit non-zero, rather than as a traceback
    that buries the message. Anything unexpected still raises, because a stack trace is
    the right answer to a bug.
    """
    try:
        app()
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(2) from exc
    except DownloadError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from exc
    except FileNotFoundError as exc:
        # A missing input is something the operator fixes by running an earlier command, and
        # every one of these carries a message saying which. A stack trace buries that.
        typer.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from exc


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(f"bgpshield {__version__}")


def _parse_day(value: str, flag: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise typer.BadParameter(f"{flag} must look like YYYY-MM-DD, got {value!r}") from exc


def _split_csv(value: str | None) -> list[str]:
    """Split a comma-separated option, dropping blanks, so ``a, b,`` means ``[a, b]``."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


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
    config_path: ConfigOption = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-download and re-write existing days.")
    ] = False,
    jobs: Annotated[
        int, typer.Option("--jobs", min=1, max=8, help="Concurrent downloads per date (be polite).")
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
    config_path: ConfigOption = None,
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

    Reads only what ``bgpshield ingest-rpki`` has already stored. The country column comes
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
        typer.echo("no snapshots ingested yet; run 'bgpshield ingest-rpki' first")
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
        published = json.loads(written.read_text(encoding="utf-8"))
        days = [row["snapshot_date"] for row in published.get("by_day", [])]
    else:
        days = [str(d) for d in by_day["snapshot_date"].to_list()]

    # Plan Section 11 Phase 1 accepts only once the daily job has run seven days in a row.
    # That is a property of the published series, so report it rather than rely on memory.
    streak = longest_daily_streak(days)
    if streak.length >= DAILY_STREAK_REQUIRED:
        typer.echo(
            f"daily streak: {streak.length} consecutive days "
            f"({streak.first} .. {streak.last}) - meets the {DAILY_STREAK_REQUIRED}-day bar"
        )
    else:
        typer.echo(
            f"daily streak: {streak.length} consecutive day(s); "
            f"the {DAILY_STREAK_REQUIRED}-day acceptance bar is not met yet"
        )


@app.command("ingest-bgp")
def ingest_bgp(
    day: Annotated[str, typer.Option("--date", help="Snapshot date, YYYY-MM-DD.")],
    collectors: Annotated[
        str | None,
        typer.Option("--collectors", help="Comma-separated. Defaults to the configured set."),
    ] = None,
    config_path: ConfigOption = None,
    force: Annotated[bool, typer.Option("--force", help="Re-ingest days already stored.")] = False,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Stop after N routes per collector (smoke runs)."),
    ] = None,
    jobs: Annotated[
        int,
        typer.Option("--jobs", min=1, help="Collectors to ingest at once, in separate processes."),
    ] = 1,
) -> None:
    """Ingest one routing-table dump per collector into the routes table.

    Plain English: a route collector is a passive listener that records what its neighbours
    announce. This downloads one table dump per collector for the date, normalizes every
    AS_PATH to origin-first form, and stores the result column by column.
    """
    cfg = load_config(config_path)
    target = _parse_day(day, "--date")
    chosen = _split_csv(collectors) or list(cfg.bgp.collectors)

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
        totals["rows"] += result.rows
        if result.skipped:
            typer.echo(f"{collector:<20} rows={result.rows:>9}  cached")
            continue
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

    # Cached collectors count towards the row total - reporting 0 beside six "cached"
    # lines reads as a failure. The seconds are summed per collector, so under --jobs > 1
    # they are compute time rather than elapsed time, and are labelled as such.
    typer.echo(f"total rows: {totals['rows']}  ingest time: {totals['seconds']}s")
    if failures:
        typer.echo(f"{failures} of {len(chosen)} collectors failed")
        raise typer.Exit(code=1)


@app.command("ingest-meta")
def ingest_meta(
    month: Annotated[str, typer.Option("--month", help="Month to build, YYYY-MM.")],
    config_path: ConfigOption = None,
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
    if result.truncated_asrank:
        note = " (TRUNCATED by --asrank-pages, not cached)"
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
    config_path: ConfigOption = None,
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
    chosen = _split_csv(collectors) or list(cfg.bgp.collectors)
    rel_month = month or previous_month(target)

    rel_path = month_table(cfg, "as_rel", rel_month)
    if not rel_path.exists():
        typer.echo(
            f"no relationships for {rel_month}; run 'bgpshield ingest-meta --month {rel_month}'"
        )
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


@app.command("correctness")
def correctness(
    day: Annotated[str, typer.Option("--date", help="Snapshot date, YYYY-MM-DD.")],
    collectors: Annotated[
        str | None,
        typer.Option("--collectors", help="Comma-separated. Defaults to the configured set."),
    ] = None,
    month: Annotated[
        str | None,
        typer.Option("--month", help="Relationship month. Defaults to the month before."),
    ] = None,
    config_path: ConfigOption = None,
    top: Annotated[int, typer.Option("--top", help="How many networks to rank.")] = 20,
) -> None:
    """RQ2: how complete are published ASPA records, and what do the gaps cost?

    Plain English: an ASPA record has to list every one of a network's providers. If one is
    missing, legitimate routes arriving that way look like forgeries. This compares each
    published record with the providers inferred from public routing data, and counts the
    Invalid routes whose paths are actually well formed.

    The inferred topology has errors of its own, so a disagreement is evidence that one side
    is wrong, not proof that the record is.
    """
    cfg = load_config(config_path)
    target = _parse_day(day, "--date")
    chosen = _split_csv(collectors) or list(cfg.bgp.collectors)
    rel_month = month or previous_month(target)

    rel_path = month_table(cfg, "as_rel", rel_month)
    aspas_path = date_table(cfg, "aspas", target)
    for needed in (rel_path, aspas_path):
        if not needed.exists():
            typer.echo(f"missing {needed}")
            raise typer.Exit(code=1)

    relationships = RelationshipLookup.from_frame(pl.read_parquet(rel_path))
    aspa_records = pl.read_parquet(aspas_path)

    comparison = compare_providers(aspa_records, relationships)
    out = date_partition(cfg, "aspa_completeness", target)
    out.mkdir(parents=True, exist_ok=True)
    comparison.write_parquet(out / "aspa_completeness.parquet")

    summary = completeness_summary(comparison)
    typer.echo(f"ASPA publishers on {target}: {summary['publishers']:,}")
    typer.echo(f"  agree with the inferred topology exactly : {summary['agree_exactly']:>6,}")
    typer.echo(
        f"  missing at least one inferred provider   : {summary['missing_at_least_one']:>6,}"
        f"  ({summary['missing_share']:.1%})"
    )
    typer.echo(f"  list a provider the inference misses     : {summary['extra_at_least_one']:>6,}")
    typer.echo(f"  AS0 records ('I have no providers')      : {summary['as0_records']:>6,}")
    typer.echo(f"    of those, contradicted by inference    : {summary['as0_contradicted']:>6,}")
    typer.echo(f"    of those, corroborated by inference    : {summary['as0_corroborated']:>6,}")
    typer.echo(f"  no providers inferred, so unjudgeable    : {summary['cannot_judge']:>6,}")

    typer.echo("\nlikely incomplete records, by how many providers are missing:")
    for row in comparison.filter(pl.col("n_missing") > 0).head(top).iter_rows(named=True):
        kind = "AS0" if row["is_as0"] else f"{row['n_published']} listed"
        typer.echo(
            f"  AS{row['asn']:<9} {kind:<10} missing {row['n_missing']:>3}: {row['missing'][:8]}"
        )

    for collector in chosen:
        results = date_table(cfg, "aspa_results", target, collector=collector)
        routes = date_table(cfg, "routes", target, collector=collector)
        if not results.exists() or not routes.exists():
            continue
        invalid = (
            pl.read_parquet(results)
            .filter(pl.col("aspa_state") == "invalid")
            .join(
                pl.read_parquet(routes, columns=["peer_ip", "prefix", "as_path", "has_as_set"]),
                on=["peer_ip", "prefix"],
                how="inner",
            )
        )
        if invalid.height == 0:
            continue
        estimate = estimate_false_positives(invalid, relationships)
        typer.echo(f"\n{collector}: {estimate.invalid_routes:,} ASPA-Invalid routes")
        typer.echo(f"  mis-shaped path, ASPA corroborated : {estimate.valley:>8,}")
        typer.echo(f"  well-shaped path, likely false pos.: {estimate.valley_free:>8,}")
        typer.echo(f"  shape undetermined                 : {estimate.undetermined:>8,}")
        typer.echo(f"  Invalid only due to an AS_SET      : {estimate.as_set:>8,}")
        typer.echo(
            f"  likely false positive share (of judged routes): "
            f"{estimate.likely_false_positive_share:.1%}"
        )

        typer.echo(f"\n  networks whose records contradict the most routes, top {top}:")
        for row in blame_by_as(invalid, top=top).iter_rows(named=True):
            typer.echo(
                f"    AS{row['asn']:<9} {row['invalid_routes']:>7,} routes  "
                f"{row['distinct_prefixes']:>7,} prefixes  "
                f"claimed providers: {row['claimed_providers'][:6]}"
            )


@app.command("detect")
def detect(
    day: Annotated[str, typer.Option("--date", help="Snapshot date, YYYY-MM-DD.")],
    collectors: Annotated[
        str | None,
        typer.Option("--collectors", help="Comma-separated. Defaults to the configured set."),
    ] = None,
    month: Annotated[
        str | None, typer.Option("--month", help="Relationship month, default the previous.")
    ] = None,
    min_peers: Annotated[
        int, typer.Option("--min-peers", help="Vantage points needed to corroborate.")
    ] = 2,
    config_path: ConfigOption = None,
) -> None:
    """Find route leaks in the stored routes for a date.

    Plain English: a route leak is a network passing on a route it was not paid to carry,
    which shows up as a path that climbs the hierarchy again after coming down. Relationships
    come from the month before, so they were not inferred from the events being examined.

    A candidate seen from only one vantage point is reported but not counted as corroborated,
    because the relationships underneath are inferred and carry errors.
    """
    cfg = load_config(config_path)
    target = _parse_day(day, "--date")
    chosen = _split_csv(collectors) or list(cfg.bgp.collectors)
    rel_month = month or previous_month(target)

    rel_path = month_table(cfg, "as_rel", rel_month)
    if not rel_path.exists():
        typer.echo(f"no relationships for {rel_month}")
        raise typer.Exit(code=1)
    relationships = RelationshipLookup.from_frame(pl.read_parquet(rel_path))

    summary, findings = detect_day(cfg, chosen, target, relationships, min_peers=min_peers)
    typer.echo(f"routes examined     : {summary.routes_examined:>10,}")
    typer.echo(f"leak sightings      : {summary.observations:>10,}")
    typer.echo(f"distinct candidates : {summary.findings:>10,}")
    typer.echo(
        f"corroborated ({min_peers}+ peers): {summary.corroborated:>10,}"
        f"  ({summary.corroborated / summary.findings:.1%})"
        if summary.findings
        else "corroborated: 0"
    )
    typer.echo("\nby RFC 7908 type:")
    for kind, count in summary.by_type.most_common():
        typer.echo(f"  {kind:<20} {count:>8,}")

    top = [f for f in findings if f.corroborated][:10]
    if top:
        typer.echo("\nmost widely seen corroborated candidates:")
        for f in top:
            typer.echo(
                f"  {f.prefix:<20} leaker AS{f.leaker_asn:<8} {f.leak_type:<18} "
                f"{f.distinct_peers} peers"
            )


@app.command("counterfactual")
def counterfactual(
    day: Annotated[str, typer.Option("--date", help="Snapshot date, YYYY-MM-DD.")],
    scenarios: Annotated[
        str, typer.Option("--scenarios", help="Comma-separated: S0,S1,S2,S3.")
    ] = "S0,S1,S2,S3",
    filters: Annotated[
        str, typer.Option("--filters", help="Comma-separated: F-all,F-top20,F-top100.")
    ] = "F-all,F-top20,F-top100",
    month: Annotated[
        str | None, typer.Option("--month", help="Relationship month, default the previous.")
    ] = None,
    corroborated_only: Annotated[
        bool, typer.Option("--corroborated-only/--all", help="Use only multi-peer findings.")
    ] = True,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Evaluate at most this many leaks.")
    ] = None,
    config_path: ConfigOption = None,
) -> None:
    """RQ3: would ASPA have stopped these leaks, and where?

    Plain English: for each detected leak, replay it under different assumptions about who
    published ASPA records and who drops Invalid routes, and see whether it would have
    survived.

    S3 gives every network a synthetic record copied from the inferred topology, and the
    leaks were detected with that same topology, so S3 is an upper bound rather than a
    prediction. Every S3 row is flagged accordingly.
    """
    cfg = load_config(config_path)
    target = _parse_day(day, "--date")
    rel_month = month or previous_month(target)

    leaks_path = date_table(cfg, "leaks", target)
    rel_path = month_table(cfg, "as_rel", rel_month)
    meta_path = month_table(cfg, "as_meta", rel_month)
    aspas_path = date_table(cfg, "aspas", target)
    for needed in (leaks_path, rel_path, meta_path, aspas_path):
        if not needed.exists():
            typer.echo(f"missing {needed}")
            raise typer.Exit(code=1)

    relationships = RelationshipLookup.from_frame(pl.read_parquet(rel_path))
    as_meta = pl.read_parquet(meta_path)
    aspa_frame = pl.read_parquet(aspas_path)
    # One customer can hold a record under more than one trust anchor, and the effective
    # provider set is the union over all of them (draft-ietf-sidrops-aspa-verification-28
    # Section 5.3). A plain dict comprehension would keep only the last row and could turn a
    # legitimate provider into an apparent leak.
    real: dict[int, frozenset[int]] = {}
    for c, provs in zip(aspa_frame["customer_asn"], aspa_frame["provider_asns"], strict=True):
        customer = int(c)
        real[customer] = real.get(customer, frozenset()) | frozenset(int(p) for p in provs)

    leaks = pl.read_parquet(leaks_path)
    if corroborated_only:
        leaks = leaks.filter(pl.col("corroborated"))
    if limit is not None:
        leaks = leaks.head(limit)
    if leaks.height == 0:
        typer.echo("no leaks to evaluate")
        raise typer.Exit(code=1)

    try:
        chosen_pub = [Publication(s) for s in _split_csv(scenarios)]
        chosen_filters = [Filtering(f) for f in _split_csv(filters)]
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"building {len(chosen_pub)} publication scenarios")
    built = []
    for publication in chosen_pub:
        scenario = build_scenario(publication, real, relationships, as_meta)
        built.append(scenario)
        note = "  UPPER BOUND ONLY" if scenario.is_upper_bound else ""
        typer.echo(
            f"  {publication}: {scenario.real_records:,} real + "
            f"{scenario.synthetic_records:,} synthetic{note}"
        )

    typer.echo(f"\nevaluating {leaks.height:,} leaks")
    outcomes = []
    for path in leaks["example_path"]:
        outcomes.extend(evaluate_route(list(path), built, chosen_filters, relationships, as_meta))

    frame = summarise(outcomes)
    out = date_partition(cfg, "counterfactual", target)
    out.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(out / "counterfactual.parquet")

    typer.echo("\n  scenario  filters     blocked   share   median position")
    for row in frame.iter_rows(named=True):
        flag = "  <- upper bound only" if row["upper_bound_only"] else ""
        median = row["median_blocking_position"]
        median_text = f"{median:.2f}" if median is not None else "   -"
        typer.echo(
            f"  {row['publication']:<9} {row['filtering']:<11} "
            f"{row['blocked']:>7,} {row['blocked_share']:>7.1%}  {median_text:>8}{flag}"
        )
    typer.echo(f"\nwrote {out / 'counterfactual.parquet'}")


@app.command("incidents")
def incidents(
    incident_id: Annotated[
        str | None, typer.Option("--id", help="Run one incident instead of all of them.")
    ] = None,
    collectors: Annotated[
        str, typer.Option("--collectors", help="Collectors to pull update files from.")
    ] = "rrc00,route-views2",
    config_path: ConfigOption = None,
    incidents_path: Annotated[
        Path | None,
        typer.Option(
            "--incidents",
            help="Curated incident list. Default: config/incidents.yaml beside the config.",
            show_default=False,
        ),
    ] = None,
    list_only: Annotated[
        bool, typer.Option("--list", help="Show the curated list without fetching anything.")
    ] = False,
) -> None:
    """Replay curated incidents and measure what the leak detector finds (RQ3).

    Plain English: each incident is a real routing failure with a public post-mortem. This
    fetches the BGP messages collectors recorded during the incident and checks whether the
    detector flags the network that caused it.

    Only route leaks can be judged this way. An origin hijack travels an ordinary-looking
    path, and in an RPKI misuse incident the routing was correct, so neither is something a
    path-based detector could find. Both are reported as not applicable, never as misses.
    """
    cfg = load_config(config_path)
    curated = load_incidents(incidents_path or cfg.root / "config" / "incidents.yaml")
    chosen = _split_csv(collectors)

    if incident_id:
        curated = [i for i in curated if i.id == incident_id]
        if not curated:
            typer.echo(f"no incident with id {incident_id!r}")
            raise typer.Exit(code=1)

    typer.echo(f"curated incidents: {len(curated)}")
    for incident in curated:
        mark = "verified" if incident.verified else "UNVERIFIED"
        culprit = f"AS{incident.culprit_asn}" if incident.culprit_asn else "-"
        typer.echo(f"  {incident.id:<34} {incident.kind:<14} {culprit:<10} {mark}")
    if list_only:
        return

    unverified = [i for i in curated if not i.verified]
    if unverified:
        typer.echo(f"\nrefusing to analyse {len(unverified)} unverified entries")

    results: list[IncidentResult] = []
    for incident in curated:
        if not incident.verified:
            continue
        typer.echo(f"\n=== {incident.id} ({incident.kind}) ===")
        results.append(_run_incident(cfg, incident, chosen))

    summary = recall(results)
    typer.echo("\n" + "=" * 62)
    typer.echo("RECALL on curated route leaks")
    typer.echo(f"  curated incidents               : {summary['curated_incidents']}")
    typer.echo(f"  of which route leaks            : {summary['route_leaks']}")
    typer.echo(f"  not applicable to this detector : {summary['not_applicable']}")
    typer.echo(f"  no archive data for the window  : {summary['no_data']}")
    typer.echo(f"  culprit never seen by a collector: {summary['culprit_absent']}")
    typer.echo(f"  leak not visible to these collectors: {summary['not_visible']}")
    typer.echo(f"  judged                          : {summary['judged']}")
    typer.echo(f"  detected                        : {summary['detected']}")
    typer.echo(f"  missed                          : {summary['missed']}")
    if summary["recall"] is None:
        typer.echo("  recall                          : not measurable, nothing judged")
    else:
        typer.echo(f"  recall                          : {summary['recall']:.0%}")

    # Persist the outcomes so the dashboard can show them without re-fetching the windows.
    # Phase 7 publishes these numbers, and a web page should read a stored result rather
    # than have someone retype it from a terminal.
    #
    # A single-incident run is a debugging aid, not a result. Overwriting the shared file
    # with it would publish a recall computed over a denominator of one - the same shape of
    # mistake as caching a truncated AS Rank walk (D-050, D-067), and it happened during
    # testing. Such a run reports to the terminal and writes nothing.
    if incident_id:
        typer.echo(
            "ran one incident, so the shared results file was left alone; "
            "run without --id to refresh it"
        )
        return

    stored = cfg.paths.processed / "incidents" / "results.json"
    stored.parent.mkdir(parents=True, exist_ok=True)
    by_id = {incident.id: incident for incident in curated}
    stored.write_text(
        json.dumps(
            {
                "collectors": chosen,
                "summary": summary,
                "incidents": [
                    {
                        "id": result.incident_id,
                        "kind": str(result.kind),
                        "outcome": str(result.outcome),
                        "routes_examined": result.routes_examined,
                        "paths_with_culprit": result.paths_with_culprit,
                        "candidates_found": result.candidates_found,
                        "culprit_flagged": result.culprit_flagged,
                        "note": result.note,
                        # These come off the curated entry by their real field names. They
                        # used to be read as "title" and "source", neither of which exists
                        # on Incident, so `getattr`'s default quietly published an empty
                        # string: the site promised a primary post-mortem for every entry
                        # and linked to none.
                        "description": _incident_field(
                            by_id, result.incident_id, "description", ""
                        ),
                        "culprit_asn": _incident_field(
                            by_id, result.incident_id, "culprit_asn", None
                        ),
                        "sources": list(_incident_field(by_id, result.incident_id, "sources", ())),
                    }
                    for result in results
                ],
            },
            indent=1,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nwrote {stored}")


def _incident_field(by_id: dict[str, Incident], incident_id: str, field: str, default: Any) -> Any:
    """Read one field off a curated entry, refusing to invent a value for a typo.

    ``getattr(obj, name, default)`` cannot tell "this entry has no source" from "this field
    name does not exist", and the second is how the site came to show no citations at all.
    A name that is not part of ``Incident`` is a programming error and raises.
    """
    if not hasattr(Incident, "__dataclass_fields__") or field not in Incident.__dataclass_fields__:
        raise AttributeError(f"Incident has no field {field!r}")
    incident = by_id.get(incident_id)
    return default if incident is None else getattr(incident, field)


def _run_incident(cfg: Config, incident: Incident, collectors: list[str]) -> IncidentResult:
    """Fetch one incident's window and look for its culprit in the detector's output."""
    if not incident.detectable_by_leak_detector:
        typer.echo("  not a route leak; a path-based detector cannot see this one")
        return IncidentResult(
            incident_id=incident.id,
            kind=incident.kind,
            outcome=IncidentOutcome.NOT_APPLICABLE,
            note="kind is not route_leak",
        )
    if not incident.has_window or incident.culprit_asn is None:
        return IncidentResult(
            incident_id=incident.id,
            kind=incident.kind,
            outcome=IncidentOutcome.NO_DATA,
            note="no window or culprit recorded",
        )

    assert incident.window_start is not None and incident.window_end is not None
    month = previous_month(incident.window_start.date())
    rel_path = month_table(cfg, "as_rel", month)
    if not rel_path.exists():
        typer.echo(f"  no relationships for {month}; run 'bgpshield ingest-meta --month {month}'")
        return IncidentResult(
            incident_id=incident.id,
            kind=incident.kind,
            outcome=IncidentOutcome.NO_DATA,
            note=f"no relationships for {month}",
        )
    relationships = RelationshipLookup.from_frame(pl.read_parquet(rel_path))

    frames = []
    for collector in collectors:
        destination = (
            cfg.paths.processed
            / "incident_routes"
            / f"incident={incident.id}"
            / f"collector={collector}"
            / "routes.parquet"
        )
        try:
            outcome = ingest_updates(
                cfg, collector, incident.window_start, incident.window_end, destination
            )
        except Exception as exc:  # noqa: BLE001 - report and try the next collector
            typer.echo(f"  {collector}: {exc}")
            continue
        state = "cached" if outcome.skipped else "fetched"
        gap = (
            f", {len(outcome.missing_files)} of {outcome.files_read} update files unreachable"
            if outcome.missing_files
            else ""
        )
        typer.echo(f"  {collector}: {outcome.rows:,} announcements ({state}){gap}")
        frames.append(
            pl.read_parquet(destination, columns=["peer_ip", "prefix", "as_path", "timestamp"])
        )

    if not frames:
        return IncidentResult(
            incident_id=incident.id,
            kind=incident.kind,
            outcome=IncidentOutcome.NO_DATA,
            note="no update files could be fetched",
        )

    frame = pl.concat(frames)
    culprit = incident.culprit_asn
    core_start = _parse_iso(incident.raw.get("start_utc")) or incident.window_start
    core_end = _parse_iso(incident.raw.get("end_utc")) or incident.window_end

    observations = []
    with_culprit = 0
    relayed = 0
    relayed_in_window = 0
    seen: set[tuple[int, ...]] = set()
    for peer_ip, prefix, as_path, stamp in frame.iter_rows():
        path = tuple(as_path)
        if culprit not in path:
            continue
        with_culprit += 1
        # A route *relayed through* the culprit is what a leak looks like. A route the
        # culprit originated is its own announcement and says nothing either way.
        is_relayed = path[0] != culprit
        if is_relayed:
            relayed += 1
            if core_start and core_end and core_start <= stamp <= core_end:
                relayed_in_window += 1
        if path in seen:
            continue
        seen.add(path)
        observations.extend(detect_in_path("incident", peer_ip, prefix, path, relationships))

    expected = set(incident.expected_leaker_asns) or {culprit}
    flagged = sum(1 for o in observations if o.leaker_asn in expected)
    named = sorted({o.leaker_asn for o in observations if o.leaker_asn in expected})
    typer.echo(f"  routes examined                  : {frame.height:,}")
    typer.echo(f"  paths containing AS{culprit:<13}: {with_culprit:,}")
    typer.echo(f"  of those, relayed through it     : {relayed:,}")
    typer.echo(f"  relayed during the incident itself: {relayed_in_window:,}")
    typer.echo(f"  distinct paths examined          : {len(seen):,}")
    typer.echo(f"  leak sightings on those paths    : {len(observations):,}")
    typer.echo(f"  expected leaker(s)               : {sorted(expected)}")
    typer.echo(f"  sightings naming one of them     : {flagged:,} {named or ''}")

    if with_culprit == 0:
        outcome_kind = IncidentOutcome.CULPRIT_ABSENT
        note = "the culprit appears on no path these collectors recorded"
    elif flagged:
        outcome_kind = IncidentOutcome.DETECTED
        note = ""
    elif not _leak_looks_visible(
        relayed,
        relayed_in_window,
        core_start,
        core_end,
        incident.window_start,
        incident.window_end,
    ):
        outcome_kind = IncidentOutcome.NOT_VISIBLE
        note = "no elevation in routes relayed through the culprit during the incident"
    else:
        outcome_kind = IncidentOutcome.MISSED
        note = "leaked-looking routes were visible but the culprit was never flagged"
    typer.echo(f"  outcome                          : {outcome_kind.value}  {note}")

    return IncidentResult(
        incident_id=incident.id,
        kind=incident.kind,
        outcome=outcome_kind,
        routes_examined=frame.height,
        paths_with_culprit=with_culprit,
        candidates_found=len(observations),
        culprit_flagged=flagged,
        note=note,
    )


def _parse_iso(value: object) -> datetime | None:
    """Parse an ISO timestamp from the incident file, tolerating a trailing Z."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _leak_looks_visible(
    relayed_total: int,
    relayed_in_window: int,
    core_start: datetime | None,
    core_end: datetime | None,
    padded_start: datetime | None,
    padded_end: datetime | None,
) -> bool:
    """Did anything leak-shaped actually reach these collectors during the incident?

    A leak should show up as a burst: many more routes relayed through the culprit during the
    incident than in the quiet hours either side. Comparing rates rather than raw counts
    matters, because a network that legitimately carries a trickle of transit will always show
    a few relayed routes, and treating one of those as evidence that the leak was visible
    would turn an invisible leak into a false accusation against the detector.

    Visible means the in-window count is at least three times what the surrounding rate
    predicts, and at least ten routes. Below that, there is nothing here to detect.
    """
    if not all((core_start, core_end, padded_start, padded_end)):
        return relayed_in_window > 0
    assert core_start and core_end and padded_start and padded_end

    core_minutes = max((core_end - core_start).total_seconds() / 60, 1.0)
    padded_minutes = max((padded_end - padded_start).total_seconds() / 60, 1.0)
    outside_minutes = max(padded_minutes - core_minutes, 1.0)

    outside = max(relayed_total - relayed_in_window, 0)
    expected = (outside / outside_minutes) * core_minutes
    return relayed_in_window >= max(10, 3 * expected)


@app.command("report")
def report(
    config_path: ConfigOption = None,
    destination: Annotated[
        Path | None, typer.Option("--out", help="Where to write the figures.")
    ] = None,
) -> None:
    """Regenerate every paper figure the stored data supports.

    Plain English: this draws the charts for the write-up from the tables already on disk.
    It downloads nothing, so the same data always produces the same pictures. A figure whose
    inputs are missing is named and skipped rather than drawn from whatever is to hand.
    """
    cfg = load_config(config_path)
    result = build_figures(cfg, destination=destination)

    for path in result.written:
        typer.echo(f"wrote {path}")
    for name, reason in result.skipped:
        typer.echo(f"skipped {name}: {reason}")
    if not result.written:
        typer.echo("nothing could be drawn; ingest some data first")
        raise typer.Exit(code=1)
    typer.echo(f"\n{len(result.written)} figures written, {len(result.skipped)} skipped")


@app.command("regional")
def regional(
    day: Annotated[str, typer.Option("--date", help="Snapshot date, YYYY-MM-DD.")],
    country: Annotated[str, typer.Option("--country", help="Two-letter country code.")] = "IN",
    month: Annotated[
        str | None, typer.Option("--month", help="Metadata month, default the previous.")
    ] = None,
    collectors: Annotated[
        str | None, typer.Option("--collectors", help="Collectors whose routes to read.")
    ] = None,
    top: Annotated[int, typer.Option("--top", help="How many networks to list.")] = 15,
    config_path: ConfigOption = None,
) -> None:
    """RQ4: one country and its region against the world.

    Plain English: this compares how many networks registered in a country publish an ASPA
    record with how many do worldwide, and lists that country's largest transit networks with
    their current standing.

    Two limits travel with every number. The country is where the AS number was
    *registered*, not where the network operates. And none of this project's collectors sits
    in India, so the Indian view is assembled from how Indian networks appear elsewhere.
    """
    cfg = load_config(config_path)
    target = _parse_day(day, "--date")
    meta_month = month or previous_month(target)
    chosen = _split_csv(collectors) or list(cfg.bgp.collectors)

    meta_path = month_table(cfg, "as_meta", meta_month)
    aspas_path = date_table(cfg, "aspas", target)
    for needed in (meta_path, aspas_path):
        if not needed.exists():
            typer.echo(f"missing {needed}")
            raise typer.Exit(code=1)

    as_meta = pl.read_parquet(meta_path)
    publishers = {int(a) for a in pl.read_parquet(aspas_path)["customer_asn"]}

    routed: set[int] = set()
    for collector in chosen:
        routes = date_table(cfg, "routes", target, collector=collector)
        if not routes.exists():
            continue
        frame = pl.read_parquet(routes, columns=["origin_asn"]).drop_nulls()
        routed |= {int(a) for a in frame["origin_asn"].unique()}
    if not routed:
        typer.echo("no routes stored for that date; run 'bgpshield ingest-bgp' first")
        raise typer.Exit(code=1)

    typer.echo(f"snapshot {target}, metadata {meta_month}, {len(routed):,} routed networks seen")
    comparison = compare_regions(as_meta, publishers, routed, country=country)
    typer.echo("")
    typer.echo(f"  {'region':<18}{'routed':>10}{'publishers':>12}{'share':>9}")
    for row in comparison.iter_rows(named=True):
        typer.echo(
            f"  {row['region']:<18}{row['routed_networks']:>10,}"
            f"{row['publishers_that_route']:>12,}{row['share_of_routed']:>9.2%}"
        )

    typer.echo(f"\nlargest {country} networks by customer cone:")
    ranked = largest_transit(as_meta, publishers, country=country, top=top)
    typer.echo(f"  {'AS':<10}{'cone':>9}{'rank':>7}  publishes ASPA")
    for row in ranked.iter_rows(named=True):
        mark = "yes" if row["publishes_aspa"] else "no"
        rank = row["rank"] if row["rank"] is not None else "-"
        typer.echo(f"  AS{row['asn']:<8}{row['cone_size']:>9,}{rank:>7}  {mark}")

    published = ranked.filter(pl.col("publishes_aspa")).height
    typer.echo(
        f"\n{published} of the top {ranked.height} publish an ASPA record. "
        "Country here means country of registration, not where the network operates."
    )


@app.command("longitudinal")
def longitudinal(
    config_path: ConfigOption = None,
    csv_out: Annotated[
        Path | None, typer.Option("--csv", help="Also write the series as CSV.")
    ] = None,
) -> None:
    """Show ROV, ASPA and leak aggregates across every validated snapshot date.

    Plain English: this lines up each date the project has validated and shows what share of
    routes fell into each state, so a trend over time is visible rather than a single day.

    The RPKI half of the series is weekly and complete. The BGP half is sampled quarterly from
    one collector, because a weekly sweep across three years is about 150 table dumps.
    """
    cfg = load_config(config_path)
    series = build_series(cfg)
    if series.height == 0:
        typer.echo("no validated dates stored yet; run 'bgpshield validate' first")
        raise typer.Exit(code=1)

    publishers = publisher_series(cfg)
    typer.echo(
        f"{series.height} validated date(s); "
        f"{publishers.height} weekly RPKI snapshot(s) for context"
    )
    typer.echo("")
    header = f"  {'date':<12}{'routes':>12}{'ROV valid':>11}{'ROV inv':>9}{'leaks':>9}"
    typer.echo(header)
    for row in series.iter_rows(named=True):
        routes = row.get("routes")
        valid, invalid = row.get("rov_valid"), row.get("rov_invalid")
        leaks = row.get("leak_findings")
        typer.echo(
            f"  {str(row['snapshot_date']):<12}"
            f"{(f'{routes:,}' if routes else '-'):>12}"
            f"{(f'{valid:.2%}' if valid is not None else '-'):>11}"
            f"{(f'{invalid:.2%}' if invalid is not None else '-'):>9}"
            f"{(f'{leaks:,}' if leaks is not None else '-'):>9}"
        )

    if csv_out is not None:
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        series.write_csv(csv_out)
        typer.echo(f"\nwrote {csv_out}")


@app.command("export")
def export(
    config_path: ConfigOption = None,
    destination: Annotated[
        Path | None, typer.Option("--out", help="Where to write the JSON files.")
    ] = None,
) -> None:
    """Write the dashboard JSON files from the stored tables.

    Plain English: this turns the measurement tables into small JSON files the website reads.
    It downloads nothing, so the same data always produces the same files, and each file
    carries the caveats that belong with its numbers.

    The plan allows under 5 MB for the whole set, because these files are committed and every
    clone of the repository pays for them.
    """
    cfg = load_config(config_path)
    result = build_export(cfg, destination=destination)

    for path in result.written:
        typer.echo(f"wrote {path}  ({path.stat().st_size / 1024:.0f} KB)")
    for name, reason in result.skipped:
        typer.echo(f"skipped {name}: {reason}")
    for path in result.stale:
        typer.echo(f"STALE {path.name}: left from an earlier run and still published")

    if not result.written:
        typer.echo("nothing could be exported; ingest and validate some data first")
        raise typer.Exit(code=1)

    budget_mb = EXPORT_BUDGET_BYTES / 1_000_000
    typer.echo(
        f"\n{len(result.written)} files, {result.total_bytes / 1_000_000:.2f} MB total "
        f"(budget {budget_mb:.0f} MB)"
    )
    if not result.within_budget:
        typer.echo("OVER BUDGET: trim the per-network table before committing this")
        raise typer.Exit(code=1)


@app.command("reproduce")
def reproduce(
    update_fixture: Annotated[
        bool, typer.Option("--update-fixture", help="Record a fresh baseline instead of checking.")
    ] = False,
    skip_pipeline: Annotated[
        bool, typer.Option("--skip-pipeline", help="Compare what is already stored.")
    ] = False,
    config_path: ConfigOption = None,
) -> None:
    """Re-derive one date on one collector and check it against the committed fixtures.

    Plain English: this runs the whole pipeline for a single day and a single collector, then
    compares what came out against numbers recorded earlier. Archive files for a past date
    never change, so an honest rerun matches them exactly. It is how anyone else can check
    that the figures in the write-up are real.

    Recording a new baseline is a separate flag on purpose: a check that quietly rewrites what
    it compares against would pass forever and mean nothing.
    """
    cfg = load_config(config_path)
    repo = cfg.root
    started = time.monotonic()

    if not skip_pipeline:
        typer.echo(f"reproducing {reproduce_mod.DAY} on {reproduce_mod.COLLECTOR}\n")
        if not reproduce_mod.run_pipeline(
            repo, config_path or cfg.root / "config" / "default.yaml", typer.echo
        ):
            raise typer.Exit(code=1)

    elapsed = (time.monotonic() - started) / 60
    fresh = reproduce_mod.collect_numbers(cfg)

    if update_fixture:
        written = reproduce_mod.write_fixture(repo, fresh)
        typer.echo(f"\nrecorded baseline -> {written}")
        for key in reproduce_mod.EXACT_KEYS:
            if key in fresh:
                typer.echo(f"  {key:<16} {fresh[key]:>12,}")
        return

    fixture = reproduce_mod.load_fixture(repo)
    if fixture is None:
        typer.echo(f"no fixture at {reproduce_mod.fixture_path(repo)}; use --update-fixture first")
        raise typer.Exit(code=1)

    result = reproduce_mod.compare(fresh, fixture)

    typer.echo("\n=== REPRODUCE ===")
    typer.echo(f"date            : {reproduce_mod.DAY}, collector {reproduce_mod.COLLECTOR}")
    typer.echo(
        f"wall clock      : {elapsed:.1f} minutes (budget {reproduce_mod.TIME_BUDGET_MINUTES})"
    )
    for key in reproduce_mod.EXACT_KEYS:
        if key in fixture:
            got = fresh.get(key)
            shown = f"{got:,}" if isinstance(got, int) else str(got)
            typer.echo(f"  {key:<16} {shown:>14}  {'ok' if got == fixture[key] else 'DIFFERS'}")

    rates = fresh.get("flag_rates", {})
    if rates:
        typer.echo("  normalization drop rates:")
        for flag in sorted(rates):
            same = fixture.get("flag_rates", {}).get(flag) == rates[flag]
            typer.echo(f"    {flag:<14} {rates[flag]:>14.6f}  {'ok' if same else 'DIFFERS'}")

    within_budget = skip_pipeline or elapsed < reproduce_mod.TIME_BUDGET_MINUTES
    typer.echo(f"\nnumbers         : {'MATCH' if result.matches else 'DIFFER'}")
    typer.echo(f"time            : {'PASS' if within_budget else 'MISS'}")
    if not result.matches:
        typer.echo("\ndifferences:")
        for line in result.problems:
            typer.echo(f"  {line}")
        raise typer.Exit(code=1)
    if not within_budget:
        raise typer.Exit(code=1)
