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


def test_ingest_list_reports_the_shipped_handler_without_downloading(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The listing must be accurate and must never acquire anything.

    This test previously asserted an empty listing. That expectation became
    obsolete when the TRF-001 handler shipped: a listing that hides a handler
    which exists is a defect, not a contract. The invariant the old test
    actually protected - that listing downloads nothing - is preserved and
    strengthened here by failing the test if the transport is ever touched.
    """

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("ingest list must not perform a transfer")

    monkeypatch.setattr("civicmind.ingestion.handlers.trf_001.download_to_file", _forbidden)

    exit_code = main(["ingest", "list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "trf-001" in output
    assert "TRF-001" in output
    assert "No ingestion handlers registered." not in output


def test_ingest_list_json_describes_the_shipped_handler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["ingest", "list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert [item["source_id"] for item in payload] == ["trf-001"]
    handler = payload[0]
    assert handler["dataset_id"] == "TRF-001"
    assert handler["title"] == "Traffic Accidents in India (Smart Cities)"
    assert handler["license"] == "Other (Public Domain) / Open Data"
    assert handler["uri"].startswith("https://data.opencity.in/")


def test_nothing_is_auto_registered_into_the_default_registry() -> None:
    """Shipping a handler must not silently populate the process-wide registry."""
    from civicmind.ingestion import DEFAULT_REGISTRY

    assert len(DEFAULT_REGISTRY) == 0
    assert DEFAULT_REGISTRY.source_ids() == ()


def test_catalog_list_reports_metadata_without_downloading(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["catalog", "list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "21 canonical datasets" in output
    assert "METADATA_ONLY" in output
    assert "WTR-005" in output
    assert "TRF-006" not in output


def test_catalog_list_json_exposes_no_local_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["catalog", "list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(payload) == 21
    ids = {item["dataset_id"] for item in payload}
    assert "WTR-005" in ids
    assert "TRF-006" not in ids
    # Reading metadata must not imply an artefact, validation, or profiling.
    assert {item["acquisition_state"] for item in payload} == {"METADATA_ONLY"}
    assert {item["validation_state"] for item in payload} == {"NOT_VALIDATED"}
    assert {item["profiling_state"] for item in payload} == {"NOT_PROFILED"}


def test_parser_exposes_expected_commands() -> None:
    parser = build_parser()

    actions = [action for action in parser._actions if action.dest == "command"]
    assert actions, "expected a subparser action"
    choices = set(actions[0].choices)
    assert {"health", "config", "ingest"} <= choices
