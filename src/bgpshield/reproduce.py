"""The small reproduction that Phase 7 accepts on (plan Section 11).

Phase 7 accepts when somebody can clone the repository, run the reproduction for one date and
one collector in under thirty minutes, and get the same numbers as the committed fixtures.
That is the claim the whole project rests on: every figure and every percentage in the
write-up is worth exactly what an independent rerun says it is.

**Why this lives in the package rather than only in a script.** It was written as
`scripts/reproduce_small.py`, driven by `make reproduce-small`. Neither `make` nor `uv` turned
out to be on the owner's Windows machine, so the one command the acceptance criterion names
could not actually be run by the person the project belongs to. An acceptance check nobody can
run is not an acceptance check. The logic is importable here, `bgpshield reproduce` runs it with
no extra tools, and the Makefile target still works where `make` exists.

**Why rrc06 and 2026-09-01.** rrc06 is the smallest of the configured collectors at about
43 MB, so the download fits comfortably in the time budget, and archive files for a past date
never change, so the answer is stable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from bgpshield.config import Config
from bgpshield.tables import read_partition, table_root

DAY = date(2026, 9, 1)
COLLECTOR = "rrc06"
META_MONTH = "2026-08"
TIME_BUDGET_MINUTES = 30

#: Counts that must match exactly. These come from immutable archive files, so an honest
#: rerun reproduces them to the row; anything else means something changed and is worth
#: looking at rather than tolerating.
EXACT_KEYS = (
    "routes",
    "peers",
    "prefixes",
    "dump_bytes",
    "rov_valid",
    "rov_invalid",
    "rov_not_found",
    "aspa_valid",
    "aspa_invalid",
    "aspa_unknown",
    "vrps",
    "aspa_records",
)


def fixture_path(repo: Path) -> Path:
    return repo / "tests" / "fixtures" / "reproduce_small.json"


@dataclass(slots=True)
class Comparison:
    """What a rerun produced, and how it differs from the recorded baseline."""

    fresh: dict[str, Any]
    fixture: dict[str, Any]
    problems: list[str] = field(default_factory=list)

    @property
    def matches(self) -> bool:
        return not self.problems


def collect_numbers(cfg: Config) -> dict[str, Any]:
    """The numbers a rerun has to reproduce."""
    numbers: dict[str, Any] = {
        "date": str(DAY),
        "collector": COLLECTOR,
        "metadata_month": META_MONTH,
    }

    stats = (
        table_root(cfg, "routes")
        / f"snapshot_date={DAY:%Y-%m-%d}"
        / f"collector={COLLECTOR}"
        / "stats.json"
    )
    if stats.exists():
        recorded = json.loads(stats.read_text(encoding="utf-8"))
        numbers["routes"] = recorded["rows"]
        numbers["peers"] = recorded["peers"]
        numbers["prefixes"] = recorded["prefixes"]
        numbers["dump_bytes"] = recorded.get("dump_bytes", 0)
        numbers["flag_rates"] = recorded.get("flag_rates", {})

    def counts(table: str, leaf: str, column: str, states: tuple[str, ...], prefix: str) -> None:
        # A DataFrame has no truth value, so `a or b` raises rather than falling through.
        root = table_root(cfg, table)
        frame = read_partition(root, DAY, leaf, [column], collector=COLLECTOR)
        if frame is None:
            frame = read_partition(root, DAY, leaf, [column])
        if frame is None:
            return
        seen = {str(row[column]): row["len"] for row in frame.group_by(column).len().to_dicts()}
        for state in states:
            numbers[f"{prefix}_{state}"] = seen.get(state, 0)

    counts(
        "rov_results", "rov_results.parquet", "rov_state", ("valid", "invalid", "not_found"), "rov"
    )
    counts(
        "aspa_results",
        "aspa_results.parquet",
        "aspa_state",
        ("valid", "invalid", "unknown"),
        "aspa",
    )

    vrps = read_partition(table_root(cfg, "vrps"), DAY, "vrps.parquet", ["prefix"])
    if vrps is not None:
        numbers["vrps"] = vrps.height
    aspas = read_partition(table_root(cfg, "aspas"), DAY, "aspas.parquet", ["customer_asn"])
    if aspas is not None:
        numbers["aspa_records"] = aspas.height

    leaks = read_partition(table_root(cfg, "leaks"), DAY, "leaks.parquet", ["leaker_asn"])
    if leaks is not None:
        numbers["leak_findings"] = leaks.height
        numbers["leak_leakers"] = leaks["leaker_asn"].n_unique()

    return numbers


def compare(fresh: dict[str, Any], fixture: dict[str, Any]) -> Comparison:
    """Differences that matter, as readable lines."""
    problems: list[str] = []
    for key in EXACT_KEYS:
        if key not in fixture:
            continue
        if key not in fresh:
            problems.append(f"{key}: missing from this run, fixture says {fixture[key]:,}")
            continue
        if fresh[key] != fixture[key]:
            problems.append(
                f"{key}: got {fresh[key]:,}, fixture says {fixture[key]:,} "
                f"(difference {fresh[key] - fixture[key]:+,})"
            )

    # The share of rows flagged by each normalization rule is a Phase 2 deliverable in its own
    # right, and exactly the sort of thing that drifts quietly when the path parser changes.
    want_rates = fixture.get("flag_rates", {})
    got_rates = fresh.get("flag_rates", {})
    for flag in sorted(set(want_rates) | set(got_rates)):
        if want_rates.get(flag) != got_rates.get(flag):
            problems.append(
                f"flag_rate[{flag}]: got {got_rates.get(flag)}, fixture says {want_rates.get(flag)}"
            )

    return Comparison(fresh=fresh, fixture=fixture, problems=problems)


def bgpshield_command() -> list[str]:
    """How to invoke the CLI as a subprocess.

    Prefer the ``bgpshield`` console script installed beside the running interpreter, which is
    the one in the active virtual environment on Windows (``Scripts``) and elsewhere
    (``bin``) alike. Fall back to ``python -m bgpshield``, which ``bgpshield/__main__.py`` makes
    equivalent, so a checkout installed without scripts still reproduces.
    """
    script = shutil.which("bgpshield", path=str(Path(sys.executable).parent))
    return [script] if script else [sys.executable, "-m", "bgpshield"]


def run_pipeline(repo: Path, config_path: Path, echo: Any) -> bool:
    """Ingest, validate and detect for the one date, through the installed console script."""
    command = bgpshield_command()
    iso = str(DAY)
    steps = [
        (["ingest-rpki", "--date", iso], "RPKI snapshot"),
        (["ingest-meta", "--month", META_MONTH], f"topology {META_MONTH}"),
        (["ingest-bgp", "--date", iso, "--collectors", COLLECTOR], "routing table"),
        (["validate", "--date", iso, "--collectors", COLLECTOR], "validate"),
        (["detect", "--date", iso, "--collectors", COLLECTOR], "detect leaks"),
    ]
    for args, label in steps:
        started = time.time()
        finished = subprocess.run(
            [*command, *args, "--config", str(config_path)],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        ok = finished.returncode == 0
        echo(f"  {label}: {'ok' if ok else 'FAILED'} in {time.time() - started:.0f}s")
        if not ok:
            echo((finished.stdout or "")[-1500:])
            echo((finished.stderr or "")[-1500:])
            return False
    return True


def write_fixture(repo: Path, numbers: dict[str, Any]) -> Path:
    destination = fixture_path(repo)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(numbers, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def load_fixture(repo: Path) -> dict[str, Any] | None:
    path = fixture_path(repo)
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None
