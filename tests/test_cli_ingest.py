"""Tests for the ``civicmind ingest`` pipeline commands.

The CLI is the interface a reviewer will use, so these tests drive it through
``main()`` exactly as a user would. Everything is offline: the handler's
resource URL is pointed at the loopback HTTP fixture for the end-to-end test,
and all paths live under ``tmp_path``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from civicmind.cli import build_parser, main
from civicmind.ingestion import IngestionRegistry
from civicmind.ingestion.base import DatasetIngestor, SourceDescriptor
from civicmind.ingestion.exceptions import AcquisitionError
from civicmind.ingestion.handlers import trf_001
from conftest import SAMPLE_CSV, LocalHTTPServer


class _ExtraHandler(DatasetIngestor):
    """A handler an operator registered themselves, whose slug is not a canonical id."""

    def describe(self) -> SourceDescriptor:
        return SourceDescriptor(
            source_id="demo-extra",
            title="Extra handler",
            publisher="CivicMind test",
            license="CC0-1.0",
        )

    def acquire(self, destination: Path):
        raise AcquisitionError("listing must not acquire")

    def validate(self, result: object):
        raise AssertionError("listing must not validate")


def test_ingest_list_includes_handlers_registered_by_application_code(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Listing must keep serving the existing ``DEFAULT_REGISTRY`` contract."""
    registry = IngestionRegistry()
    registry.register(_ExtraHandler())
    monkeypatch.setattr("civicmind.cli.DEFAULT_REGISTRY", registry)

    exit_code = main(["ingest", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [item["source_id"] for item in payload] == ["demo-extra", "trf-001"]
    extra = payload[0]
    # A slug that is not a canonical id is listed, and simply has no dataset id.
    assert extra["dataset_id"] is None
    assert extra["title"] == "Extra handler"
    assert payload[1]["dataset_id"] == "TRF-001"


def test_cli_accepts_the_slug_and_still_reports_the_canonical_id(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ingest", "plan", "--dataset", "trf-001", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)

    assert plan["dataset_id"] == "TRF-001"
    assert main(["ingest", "status", "--dataset", "trf-001", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)

    assert status["dataset_id"] == "TRF-001"
    # Neither command writes anything.
    assert _written(isolated_home / "artifacts") == []
    assert _written(isolated_home / "data") == []


def test_cli_rejects_an_identifier_that_is_neither_form(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["ingest", "status", "--dataset", "traffic accidents"])

    assert "neither a canonical dataset id" in str(excinfo.value)
    capsys.readouterr()
    assert _written(isolated_home / "artifacts") == []


#: A fixture that isolates every writable path under ``tmp_path``.
@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the CLI's settings at ``tmp_path`` for the duration of one test."""
    monkeypatch.setenv("CIVICMIND_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("CIVICMIND_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CIVICMIND_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CIVICMIND_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CIVICMIND_ENV", "testing")
    yield tmp_path


def _written(root: Path) -> list[str]:
    """Return every file under ``root``, relative to it."""
    if not root.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def test_parser_exposes_the_pipeline_subcommands() -> None:
    parser = build_parser()
    actions = [action for action in parser._actions if action.dest == "command"]
    assert actions
    ingest = actions[0].choices["ingest"]
    subcommands = [action for action in ingest._actions if action.dest == "ingest_command"]
    assert subcommands
    assert {"plan", "acquire", "validate", "profile", "status"} <= set(subcommands[0].choices)


def test_ingest_plan_is_a_dry_run(isolated_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["ingest", "plan", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["network_performed"] is False
    assert payload["writes_performed"] is False
    assert payload["dataset_id"] == "TRF-001"
    assert _written(isolated_home / "artifacts") == []
    assert _written(isolated_home / "data") == []


def test_ingest_plan_reports_the_cited_url_and_licence_caveat(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["ingest", "plan"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "docs/datasets/ingestion_plan.md#L251" in output
    assert "license_verified=false" in output
    assert "METADATA_ONLY" in output
    assert "dry run: no network request" in output


def test_ingest_acquire_without_a_rationale_is_refused(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["ingest", "acquire"])

    assert "--authorize" in str(excinfo.value)
    capsys.readouterr()
    assert _written(isolated_home / "data") == []
    assert _written(isolated_home / "artifacts") == []


def test_ingest_validate_without_an_artifact_explains_the_next_step(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["ingest", "validate"])

    assert "ingest acquire" in str(excinfo.value)
    capsys.readouterr()
    assert _written(isolated_home / "artifacts") == []


def test_ingest_profile_without_an_artifact_is_refused(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["ingest", "profile"])

    capsys.readouterr()
    assert _written(isolated_home / "artifacts") == []


def test_ingest_status_reports_metadata_only(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["ingest", "status"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "METADATA_ONLY" in output
    assert "NOT_VALIDATED" in output
    assert "NOT_PROFILED" in output
    assert "Active artifact: none (no local bytes)" in output
    assert "Licence verified: false" in output
    # Reading state must not create state.
    assert _written(isolated_home / "artifacts") == []


def test_ingest_status_json_keeps_the_licence_unverified(
    isolated_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["ingest", "status", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["blockers"]["license_verified"] is False
    assert payload["evidence_present"] is False
    assert payload["active_artifact"] is None


def test_end_to_end_pipeline_offline(
    isolated_home: Path,
    http_server: LocalHTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Drive plan -> acquire -> validate -> profile -> status through the CLI."""
    url = http_server.serve("/resource.csv")
    monkeypatch.setattr(trf_001, "RESOURCE_URL", url)

    assert main(["ingest", "plan", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["resource_url"] == url

    assert main(["ingest", "acquire", "--authorize", "Gate B1 pilot", "--json"]) == 0
    acquired = json.loads(capsys.readouterr().out)
    assert acquired["artifact_version"] == 1
    assert acquired["byte_size"] == len(SAMPLE_CSV)
    assert acquired["validation_state"] == "NOT_VALIDATED"

    assert main(["ingest", "validate", "--json"]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["passed"] is True
    assert validated["state"] == "VALIDATED"

    assert main(["ingest", "profile", "--json"]) == 0
    profiled = json.loads(capsys.readouterr().out)
    assert profiled["state"] == "PROFILED"
    assert profiled["data_rows"] == 5
    assert "Ahmedabad" not in Path(profiled["profile_path"]).read_text(encoding="utf-8")

    assert main(["ingest", "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["axes"]["acquisition_state"] == "DOWNLOADED"
    assert status["axes"]["validation_state"] == "VALIDATED"
    assert status["axes"]["profiling_state"] == "PROFILED"
    assert status["blockers"]["license_verified"] is False
    assert status["artifact_count"] == 1

    # The artifact is held in the raw-data tree; the evidence and profile live
    # under the artifacts tree, exactly where the plan said they would.
    raw = _written(isolated_home / "data")
    assert len(raw) == 1 and raw[0].endswith(".csv")
    artifacts = _written(isolated_home / "artifacts")
    assert any(item.endswith("evidence.json") for item in artifacts)
    assert any(item.endswith("profile-v1.json") for item in artifacts)


def test_end_to_end_pipeline_replays_persisted_evidence(
    isolated_home: Path,
    http_server: LocalHTTPServer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A later invocation must see recorded state, via evidence replay, not memory."""
    url = http_server.serve("/resource.csv")
    monkeypatch.setattr(trf_001, "RESOURCE_URL", url)

    assert main(["ingest", "acquire", "--authorize", "Gate B1 pilot"]) == 0
    capsys.readouterr()
    assert main(["ingest", "validate"]) == 0
    capsys.readouterr()

    # A second invocation replays the persisted evidence rather than losing it.
    assert main(["ingest", "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)

    assert status["evidence_present"] is True
    assert status["replayed_events"] == 2
    assert status["axes"]["validation_state"] == "VALIDATED"
    assert status["resource_provenance"]["resource_url"] == url
