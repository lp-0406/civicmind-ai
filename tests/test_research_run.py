"""Tests for the local ingestion research-run deliverable generator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from civicmind.config import Settings
from civicmind.ingestion import pilot
from civicmind.ingestion.research_run import (
    build_local_dataset_mapping,
    run_research_ingestion,
)

FIXED_TIME = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
RATIONALE = "test research run local-artifact authorization"


def _settings(tmp_path: Path) -> Settings:
    return Settings.from_env(
        {
            "CIVICMIND_PROJECT_ROOT": str(tmp_path),
            "CIVICMIND_DATA_DIR": str(tmp_path / "data"),
            "CIVICMIND_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
            "CIVICMIND_LOGS_DIR": str(tmp_path / "logs"),
            "CIVICMIND_ENV": "testing",
        }
    )


def _write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _write_supplied_csvs(settings: Settings) -> None:
    raw = settings.raw_data_dir
    _write(
        raw / "RA2019_A2.csv",
        b"States/UTs,Accidents - 2019\nTamil Nadu,57228\nTotal,449002\n",
    )
    _write(
        raw / "RA2019_A47.csv",
        b"States/UTs,Over Speeding - Accidents\nBengaluru,100\nTotal,100\n",
    )
    _write(
        raw / "RA2019_A49.csv",
        b"States/UTs,T Junction - Injured\nBengaluru,50\nTotal,50\n",
    )
    _write(
        raw / "RA2019_A52.csv",
        b"Name of Location Place,Police Station,Accidents - 2018\nSpot A,PS A,3\n",
    )
    _write(
        raw / "BWSSB_Water_Consumption_August_2025.csv",
        (
            b"Ward number,Ward Name,Number of Connections,Consumption in ML\n"
            b"1,Test Ward,10,20.5\n"
            b"2,Second Ward,5,8.0\n"
        ),
    )


def test_local_mapping_marks_only_wtr_005_as_local_ingestion_supported(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_supplied_csvs(settings)

    mapping = build_local_dataset_mapping(settings)

    by_id = {item["local_dataset_id"]: item for item in mapping}
    assert by_id["BWSSB_WATER"]["canonical_dataset_id"] == "WTR-005"
    assert by_id["BWSSB_WATER"]["ingestion_source_id"] == "wtr-005"
    assert by_id["BWSSB_WATER"]["handler_supported"] is True
    for dataset_id in ("RA2019_A2", "RA2019_A47", "RA2019_A49", "RA2019_A52"):
        assert by_id[dataset_id]["canonical_dataset_id"] is None
        assert by_id[dataset_id]["handler_supported"] is False
        assert by_id[dataset_id]["sha256"]


def test_research_run_writes_deliverables_and_registers_only_wtr_005(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_supplied_csvs(settings)
    out = settings.artifacts_dir / "ingestion" / "research_run"

    report = run_research_ingestion(
        settings,
        output_dir=out,
        rationale=RATIONALE,
        clock=lambda: FIXED_TIME,
    )

    for path in (
        report.markdown_path,
        report.json_path,
        report.csv_path,
        report.pdf_path,
        report.manifest_path,
    ):
        assert path.is_file()
        assert path.stat().st_size > 0

    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    by_id = {item["local_dataset_id"]: item for item in payload["datasets"]}
    assert by_id["BWSSB_WATER"]["registration"]["status"] == "registered"
    assert by_id["BWSSB_WATER"]["validation"]["passed"] is True
    assert by_id["BWSSB_WATER"]["profiling"]["state"] == "PROFILED"
    assert Path(by_id["BWSSB_WATER"]["evidence_path"]).is_file()
    for dataset_id in ("RA2019_A2", "RA2019_A47", "RA2019_A49", "RA2019_A52"):
        assert by_id[dataset_id]["registration"]["status"] == "not_registered_unsupported"
        assert by_id[dataset_id]["validation"]["status"] == "not_run_no_registered_handler"

    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert {Path(item["path"]).name for item in manifest["deliverables"]} == {
        "ingestion_report.md",
        "ingestion_results.json",
        "ingestion_summary.csv",
        "ingestion_summary.pdf",
    }


def test_research_run_is_idempotent_for_existing_wtr_artifact(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_supplied_csvs(settings)
    out = settings.artifacts_dir / "ingestion" / "research_run"

    run_research_ingestion(settings, output_dir=out, rationale=RATIONALE, clock=lambda: FIXED_TIME)
    second = run_research_ingestion(
        settings,
        output_dir=out,
        rationale=RATIONALE,
        clock=lambda: FIXED_TIME,
    )

    status = pilot.status(settings, dataset_id="WTR-005")
    assert status.artifact_count == 1
    assert status.validation_count == 1
    assert status.profiling_count == 3
    by_id = {item["local_dataset_id"]: item for item in second.results["datasets"]}
    assert by_id["BWSSB_WATER"]["registration"]["status"] == "already_registered"
    assert by_id["BWSSB_WATER"]["profiling"]["status"] == "already_profiled"


def test_research_run_skips_profile_when_supported_file_fails_validation(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _write(
        settings.raw_data_dir / "BWSSB_Water_Consumption_August_2025.csv",
        b'Ward number,Ward Name\n1,"unterminated\n',
    )

    report = run_research_ingestion(
        settings,
        output_dir=settings.artifacts_dir / "ingestion" / "research_run",
        rationale=RATIONALE,
        clock=lambda: FIXED_TIME,
    )

    by_id = {item["local_dataset_id"]: item for item in report.results["datasets"]}
    water = by_id["BWSSB_WATER"]
    assert water["validation"]["passed"] is False
    assert water["validation"]["state"] == "VALIDATION_FAILED"
    assert water["profiling"]["status"] == "skipped_validation_failed"
