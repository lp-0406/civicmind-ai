"""Tests for environment-driven configuration.

These tests never read the developer's real secrets: they pass explicit
environment mappings or use ``monkeypatch``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civicmind.config import (
    ENV_PREFIX,
    ConfigurationError,
    Settings,
    find_project_root,
    get_secret,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_project_root_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise a developer's CIVICMIND_PROJECT_ROOT override."""
    monkeypatch.delenv(f"{ENV_PREFIX}PROJECT_ROOT", raising=False)


def test_defaults_are_sensible() -> None:
    settings = Settings.from_env(environ={})

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.log_format == "text"
    assert settings.project_root == find_project_root()
    assert settings.data_dir == settings.project_root / "data"
    assert settings.raw_data_dir == settings.data_dir / "raw"
    assert settings.interim_data_dir == settings.data_dir / "interim"
    assert settings.processed_data_dir == settings.data_dir / "processed"
    assert settings.external_data_dir == settings.data_dir / "external"
    assert settings.log_file == settings.logs_dir / "civicmind.log"


def test_environment_variables_override_defaults(tmp_path: Path) -> None:
    environ = {
        f"{ENV_PREFIX}ENV": "testing",
        f"{ENV_PREFIX}LOG_LEVEL": "debug",  # normalised to upper case
        f"{ENV_PREFIX}LOG_FORMAT": "JSON",  # normalised to lower case
        f"{ENV_PREFIX}DATA_DIR": str(tmp_path / "datasets"),
    }
    settings = Settings.from_env(environ=environ)

    assert settings.environment == "testing"
    assert settings.log_level == "DEBUG"
    assert settings.log_format == "json"
    assert settings.data_dir == (tmp_path / "datasets").resolve()
    assert settings.raw_data_dir == (tmp_path / "datasets" / "raw").resolve()


def test_relative_paths_resolve_against_project_root(tmp_path: Path) -> None:
    environ = {
        f"{ENV_PREFIX}PROJECT_ROOT": str(tmp_path),
        f"{ENV_PREFIX}LOGS_DIR": "var/logs",
    }
    settings = Settings.from_env(environ=environ)

    assert settings.project_root == tmp_path.resolve()
    assert settings.logs_dir == (tmp_path / "var" / "logs").resolve()


@pytest.mark.parametrize(
    ("environ", "match"),
    [
        ({f"{ENV_PREFIX}ENV": "qa"}, "CIVICMIND_ENV"),
        ({f"{ENV_PREFIX}LOG_LEVEL": "LOUD"}, "CIVICMIND_LOG_LEVEL"),
        ({f"{ENV_PREFIX}LOG_FORMAT": "xml"}, "CIVICMIND_LOG_FORMAT"),
    ],
)
def test_invalid_values_raise_configuration_error(environ: dict[str, str], match: str) -> None:
    with pytest.raises(ConfigurationError, match=match):
        Settings.from_env(environ=environ)


def test_missing_project_root_override_raises(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ConfigurationError, match="PROJECT_ROOT"):
        Settings.from_env(environ={f"{ENV_PREFIX}PROJECT_ROOT": str(missing)})


def test_summary_never_exposes_secrets() -> None:
    environ = {f"{ENV_PREFIX}EXAMPLE_API_KEY": "super-secret-value"}
    summary = Settings.from_env(environ=environ).summary()

    assert "super-secret-value" not in repr(summary)
    assert "environment" in summary and "raw_data_dir" in summary


def test_ensure_directories_creates_layout(tmp_path: Path) -> None:
    settings = Settings.from_env(
        environ={f"{ENV_PREFIX}PROJECT_ROOT": str(tmp_path), f"{ENV_PREFIX}DATA_DIR": "data"}
    )

    created = settings.ensure_directories()

    assert set(created) == set(settings.data_directories().values()) | {
        settings.logs_dir,
        settings.artifacts_dir,
        settings.configs_dir,
    }
    for directory in created:
        assert directory.is_dir()


def test_find_project_root_detects_repository() -> None:
    root = find_project_root()

    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "civicmind").is_dir()


def test_get_secret_reads_environment_with_prefix() -> None:
    environ = {f"{ENV_PREFIX}EXAMPLE_API_KEY": "abc123"}

    assert get_secret("EXAMPLE_API_KEY", environ=environ) == "abc123"
    assert get_secret(f"{ENV_PREFIX}EXAMPLE_API_KEY", environ=environ) == "abc123"


def test_get_secret_treats_blank_as_unset() -> None:
    environ = {f"{ENV_PREFIX}EXAMPLE_API_KEY": "   "}

    assert get_secret("EXAMPLE_API_KEY", default="fallback", environ=environ) == "fallback"
    assert get_secret("MISSING_KEY", default="fallback", environ=environ) == "fallback"
    assert get_secret("MISSING_KEY", environ=environ) is None
