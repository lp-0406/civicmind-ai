"""Tests for the ``civicmind`` CLI.

The CLI must be exercisable without datasets, network access or a GPU.
"""

from __future__ import annotations

import json

import pytest

from civicmind import __version__
from civicmind.cli import build_parser, main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_help_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    output = capsys.readouterr().out
    assert "usage:" in output
    assert "health" in output


def test_missing_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])

    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_unknown_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["frobnicate"])

    assert excinfo.value.code == 2


def test_health_reports_ok_environment(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["health", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["project_root"]
    names = {component["name"] for component in payload["components"]}
    assert {"python", "pytorch", "project-root-writable"} <= names


def test_health_text_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["health"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Python" in output
    assert "Status      : OK" in output


def test_config_show_excludes_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CIVICMIND_EXAMPLE_API_KEY", "super-secret-value")
    monkeypatch.setenv("CIVICMIND_ENV", "testing")

    exit_code = main(["config", "show", "--json"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "super-secret-value" not in output
    payload = json.loads(output)
    assert payload["environment"] == "testing"
    assert "raw_data_dir" in payload


def test_ingest_list_is_empty_and_downloads_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["ingest", "list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "No ingestion handlers registered." in output


def test_ingest_list_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["ingest", "list", "--json"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_parser_exposes_expected_commands() -> None:
    parser = build_parser()

    actions = [action for action in parser._actions if action.dest == "command"]
    assert actions, "expected a subparser action"
    choices = set(actions[0].choices)
    assert {"health", "config", "ingest"} <= choices
