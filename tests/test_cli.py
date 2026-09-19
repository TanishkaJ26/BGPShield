"""The command-line surface: what a user sees before any data is involved."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bgpshield import __version__
from bgpshield.cli import _split_csv, app, run


def test_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_verbose_flag_is_accepted_before_the_command() -> None:
    result = CliRunner().invoke(app, ["--verbose", "version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_works_from_an_unrelated_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-064: the working directory is not part of the interface."""
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ingest-rpki" in result.stdout


def test_split_csv_drops_blanks_and_whitespace() -> None:
    assert _split_csv("rrc00, route-views2,,") == ["rrc00", "route-views2"]
    assert _split_csv(None) == []
    assert _split_csv("") == []


def test_a_bad_date_is_a_usage_error_not_a_traceback() -> None:
    result = CliRunner().invoke(app, ["ingest-bgp", "--date", "yesterday"])
    assert result.exit_code == 2
    assert "YYYY-MM-DD" in result.output


def test_a_missing_config_is_one_line_and_a_non_zero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.yaml"
    monkeypatch.setattr(sys, "argv", ["bgpshield", "adoption", "--config", str(missing)])
    with pytest.raises(SystemExit) as caught:
        run()
    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "config file not found" in err
    assert "Traceback" not in err
