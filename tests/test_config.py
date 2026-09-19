"""Tests for finding and loading the config from any working directory (D-064).

The CLI used to work only from the repository root. These pin the three places the config
is looked for, the order they are tried in, and that relative data paths end up in the same
place whichever directory a command was started from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bgpshield import __version__
from bgpshield.config import CONFIG_ENV_VAR, ConfigError, find_config, load_config

REPO = Path(__file__).resolve().parent.parent
DEFAULT = REPO / "config" / "default.yaml"


def _copy_default(root: Path, **replacements: str) -> Path:
    """A private copy of the real config under ``root/config``, with optional edits."""
    (root / "config").mkdir(parents=True)
    text = DEFAULT.read_text(encoding="utf-8")
    for old, new in replacements.items():
        assert old in text, old
        text = text.replace(old, new)
    target = root / "config" / "default.yaml"
    target.write_text(text, encoding="utf-8")
    return target


def test_find_config_walks_up_from_a_subdirectory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    assert find_config(REPO / "src" / "bgpshield") == DEFAULT


def test_the_environment_variable_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.yaml"
    monkeypatch.setenv(CONFIG_ENV_VAR, str(elsewhere))
    assert find_config(REPO) == elsewhere


def test_falls_back_to_the_checkout_from_an_unrelated_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    assert find_config(tmp_path) == DEFAULT


def test_a_missing_file_is_a_config_error_that_names_the_fix(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found") as caught:
        load_config(tmp_path / "nope.yaml")
    assert CONFIG_ENV_VAR in str(caught.value)


def test_relative_paths_resolve_against_the_project_root(tmp_path: Path) -> None:
    target = _copy_default(tmp_path / "proj")
    cfg = load_config(target)
    root = (tmp_path / "proj").resolve()
    assert cfg.root == root
    assert cfg.paths.raw == root / "data" / "raw"
    assert cfg.paths.web_data == root / "web" / "public" / "data"
    assert all(
        p.is_absolute()
        for p in (
            cfg.paths.raw,
            cfg.paths.interim,
            cfg.paths.processed,
            cfg.paths.figures,
            cfg.paths.web_data,
        )
    )


def test_an_absolute_path_is_left_alone(tmp_path: Path) -> None:
    elsewhere = (tmp_path / "bulk").resolve()
    target = _copy_default(tmp_path / "proj", **{"raw: data/raw": f"raw: {elsewhere.as_posix()}"})
    cfg = load_config(target)
    assert cfg.paths.raw == elsewhere
    assert cfg.paths.processed == (tmp_path / "proj").resolve() / "data" / "processed"


def test_the_user_agent_carries_the_installed_version() -> None:
    cfg = load_config(DEFAULT)
    assert __version__ in cfg.project.user_agent
    assert "{version}" not in cfg.project.user_agent
    assert "@" in cfg.project.user_agent, "plan Section 16: a contact address on every download"


def test_a_misspelled_key_fails_loudly(tmp_path: Path) -> None:
    target = _copy_default(tmp_path / "proj", **{"rib_time_utc:": "rib_time_utcc:"})
    with pytest.raises(ConfigError, match="failed validation"):
        load_config(target)


def test_broken_yaml_is_reported_as_such(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    target = tmp_path / "config" / "default.yaml"
    target.write_text("project: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(target)


def test_a_yaml_list_at_the_top_level_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    target = tmp_path / "config" / "default.yaml"
    target.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(target)
