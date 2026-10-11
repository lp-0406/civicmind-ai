"""Tests for the TRF-001 ingestion handler.

The handler is exercised against the loopback HTTP fixture and against
hand-written files; no test reaches a real dataset endpoint.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from civicmind.ingestion.base import AcquisitionResult
from civicmind.ingestion.handlers import build_pilot_handler
from civicmind.ingestion.handlers.trf_001 import (
    DATASET_ID,
    DATASET_PAGE_URL,
    RESOURCE_URL,
    RESOURCE_URL_CITATION,
    SOURCE_ID,
    Trf001Ingestor,
)
from civicmind.ingestion.transfer import TransferLimits
from conftest import SAMPLE_CSV, LocalHTTPServer

FIXED_TIME = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def _handler(
    url: str,
    *,
    limits: TransferLimits | None = None,
    at: datetime = FIXED_TIME,
) -> Trf001Ingestor:
    """Return a TRF-001 handler pointed at the local test server."""
    return build_pilot_handler(
        DATASET_ID,
        resource_url=url,
        limits=limits or TransferLimits(max_bytes=1_000_000),
        clock=lambda: at,
        sleep=lambda _seconds: None,
    )


def _result(path: Path, *, byte_size: int | None = None, checksum: str | None = None):
    """Return an acquisition result describing ``path``."""
    return AcquisitionResult(
        source_id=DATASET_ID,
        acquired_at=FIXED_TIME,
        method="https-get",
        local_path=path,
        byte_size=byte_size if byte_size is not None else path.stat().st_size,
        checksum_sha256=(
            checksum if checksum is not None else hashlib.sha256(path.read_bytes()).hexdigest()
        ),
    )


def _write(tmp_path: Path, data: bytes, name: str = "artifact.csv") -> Path:
    """Write ``data`` under ``tmp_path`` and return the path."""
    path = tmp_path / name
    path.write_bytes(data)
    return path


# -- identity and provenance ------------------------------------------------


def test_describe_is_static_and_needs_no_network(http_server: LocalHTTPServer) -> None:
    handler = Trf001Ingestor()

    descriptor = handler.describe()

    assert descriptor.source_id == SOURCE_ID == "trf-001"
    assert descriptor.title == "Traffic Accidents in India (Smart Cities)"
    assert "OpenCity" in descriptor.publisher
    assert descriptor.license == "Other (Public Domain) / Open Data"
    assert descriptor.geographic_scope == "8 Indian cities"
    assert http_server.hit_count("/") == 0


def test_construction_and_registration_perform_no_io(tmp_path: Path) -> None:
    destination = tmp_path / "raw" / DATASET_ID

    handler = build_pilot_handler(DATASET_ID)

    assert destination.exists() is False
    assert handler.resource_url == RESOURCE_URL
    assert handler.describe().uri == RESOURCE_URL


def test_resource_url_provenance_is_recorded_with_its_citation() -> None:
    handler = Trf001Ingestor()

    provenance = handler.resource_provenance()

    assert provenance["resource_url"] == RESOURCE_URL
    assert (
        provenance["cited_in"] == RESOURCE_URL_CITATION == "docs/datasets/ingestion_plan.md#L251"
    )
    assert provenance["dataset_page_url"] == DATASET_PAGE_URL
    assert "not proof" in provenance["caveat"]
    assert handler.describe().license == "Other (Public Domain) / Open Data"


def test_provenance_marks_licence_as_a_source_claim() -> None:
    handler = Trf001Ingestor()

    assert handler.describe().license  # recorded as the source states it
    # The handler never asserts that the licence has been verified.
    assert "verified" not in handler.resource_provenance()


# -- acquisition ------------------------------------------------------------


def test_acquire_returns_measured_facts(http_server: LocalHTTPServer, tmp_path: Path) -> None:
    url = http_server.serve("/resource.csv")
    handler = _handler(url)

    result = handler.acquire(tmp_path)

    assert result.source_id == DATASET_ID
    assert result.local_path is not None and result.local_path.is_file()
    assert result.byte_size == len(SAMPLE_CSV)
    assert result.checksum_sha256 == hashlib.sha256(SAMPLE_CSV).hexdigest()
    assert result.method == "https-get"
    assert result.record_count is None
    assert "http=200" in result.notes
    assert "content-type=text/csv" in result.notes
    assert url in result.notes


def test_acquire_never_overwrites_an_existing_artifact(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/resource.csv")
    handler = _handler(url)
    stamp = FIXED_TIME.strftime("%Y%m%dT%H%M%SZ")
    colliding = tmp_path / f"trf-001-traffic-accidents-{stamp}.csv"
    colliding.write_bytes(b"bytes from an earlier acquisition")

    result = handler.acquire(tmp_path)

    assert result.local_path is not None
    assert result.local_path.name.endswith("-2.csv")
    assert colliding.read_bytes() == b"bytes from an earlier acquisition"


def test_acquire_stops_at_the_configured_size_limit(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/resource.csv")
    handler = _handler(url, limits=TransferLimits(max_bytes=32))

    with pytest.raises(Exception) as excinfo:
        handler.acquire(tmp_path)

    assert "exceeded" in str(excinfo.value) or "above the" in str(excinfo.value)
    assert list(tmp_path.iterdir()) == []


def test_build_provenance_names_the_handler_and_version(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/resource.csv")
    handler = _handler(url)

    result = handler.acquire(tmp_path)
    provenance = handler.build_provenance(result)

    assert provenance.handler.endswith("Trf001Ingestor")
    assert provenance.handler_version == "1.0"
    assert provenance.checksum_sha256 == result.checksum_sha256
    assert provenance.source_uri == url


# -- validation -------------------------------------------------------------


def test_validate_passes_a_well_formed_artifact(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE_CSV)

    report = Trf001Ingestor().validate(_result(path))

    assert report.passed is True
    assert report.source_id == DATASET_ID
    assert report.errors == ()
    codes = {issue.code for issue in report.issues}
    assert "SCHEMA_NOT_ASSERTED" in codes
    assert "RAGGED_ROWS" not in codes


def test_validate_measures_the_header_and_row_counts(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE_CSV)

    report = Trf001Ingestor().validate(_result(path))

    schema_issue = next(i for i in report.issues if i.code == "SCHEMA_NOT_ASSERTED")
    assert schema_issue.severity == "info"
    assert schema_issue.context["documented_hints_missing"] == []


def test_validate_reports_a_missing_artifact(tmp_path: Path) -> None:
    missing = AcquisitionResult(
        source_id=DATASET_ID,
        acquired_at=FIXED_TIME,
        method="https-get",
        local_path=tmp_path / "absent.csv",
        byte_size=377,
        checksum_sha256="a" * 64,
    )

    report = Trf001Ingestor().validate(missing)

    assert report.passed is False
    assert "ARTIFACT_MISSING" in {issue.code for issue in report.issues}


def test_validate_reports_an_absent_path() -> None:
    report = Trf001Ingestor().validate(
        AcquisitionResult(source_id=DATASET_ID, acquired_at=FIXED_TIME, method="https-get")
    )

    assert report.passed is False
    assert "ARTIFACT_PATH_MISSING" in {issue.code for issue in report.issues}


def test_validate_reports_an_empty_artifact(tmp_path: Path) -> None:
    path = _write(tmp_path, b"")

    report = Trf001Ingestor().validate(_result(path, byte_size=0))

    assert report.passed is False
    assert "EMPTY_FILE" in {issue.code for issue in report.issues}


def test_validate_detects_a_size_mismatch(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE_CSV)

    report = Trf001Ingestor().validate(_result(path, byte_size=len(SAMPLE_CSV) + 1))

    assert report.passed is False
    issue = next(i for i in report.issues if i.code == "SIZE_MISMATCH")
    assert issue.context["measured"] == len(SAMPLE_CSV)


def test_validate_detects_a_checksum_mismatch(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE_CSV)

    report = Trf001Ingestor().validate(_result(path, checksum="f" * 64))

    assert report.passed is False
    assert "CHECKSUM_MISMATCH" in {issue.code for issue in report.issues}


def test_validate_reports_non_utf8_content(tmp_path: Path) -> None:
    path = _write(tmp_path, b"City,Year\n\xff\xfe\x00\x00")

    report = Trf001Ingestor().validate(_result(path))

    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "ENCODING_ERROR" in codes


def test_validate_reports_an_unterminated_quoted_field(tmp_path: Path) -> None:
    path = _write(tmp_path, b'City,Year\nAhmedabad,"2016\n')

    report = Trf001Ingestor().validate(_result(path))

    assert report.passed is False
    issue = next(i for i in report.issues if i.code == "CSV_PARSE_ERROR")
    assert issue.context["rows_parsed"] == 1
    assert "strict" in issue.context["parser"]


def test_validate_reports_a_missing_header(tmp_path: Path) -> None:
    path = _write(tmp_path, b"\n\n")

    report = Trf001Ingestor().validate(_result(path))

    assert report.passed is False
    assert "HEADER_MISSING" in {issue.code for issue in report.issues}


def test_validate_reports_ragged_rows_as_a_warning(tmp_path: Path) -> None:
    path = _write(tmp_path, b"City,Year,Total\nAhmedabad,2016,12\nBhopal,2017\n")

    report = Trf001Ingestor().validate(_result(path))

    assert report.passed is True
    issue = next(i for i in report.issues if i.code == "RAGGED_ROWS")
    assert issue.severity == "warning"
    assert issue.context == {"ragged_rows": 1, "header_fields": 3}


def test_validate_warns_when_a_documented_column_hint_is_absent(tmp_path: Path) -> None:
    path = _write(tmp_path, b"City,Total\nAhmedabad,12\n")

    report = Trf001Ingestor().validate(_result(path))

    assert report.passed is True
    codes = {issue.code for issue in report.issues}
    assert "DOCUMENTED_COLUMN_ABSENT" in codes
    absent = next(i for i in report.issues if i.code == "DOCUMENTED_COLUMN_ABSENT")
    assert absent.severity == "warning"


def test_validate_accepts_a_utf8_bom(tmp_path: Path) -> None:
    path = _write(tmp_path, b"\xef\xbb\xbfCity,Year,Total\nAhmedabad,2016,12\n")

    report = Trf001Ingestor().validate(_result(path))

    assert report.passed is True
    assert "BOM_PRESENT" in {issue.code for issue in report.issues}


def test_validate_flags_nul_bytes_as_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, b"City,Year,Total\nAhmedabad,\x002016,12\n")

    report = Trf001Ingestor().validate(_result(path))

    codes = {issue.code for issue in report.issues}
    assert "NUL_BYTES" in codes
    # The real CSV parser refuses a NUL byte, so the artifact is an error.
    assert report.passed is False
    assert "CSV_PARSE_ERROR" in codes


def test_validate_reports_a_header_only_file(tmp_path: Path) -> None:
    path = _write(tmp_path, b"City,Year\n")

    report = Trf001Ingestor().validate(_result(path))

    assert report.passed is True
    assert "NO_DATA_ROWS" in {issue.code for issue in report.issues}


def test_validation_never_asserts_an_unverified_schema(tmp_path: Path) -> None:
    path = _write(tmp_path, SAMPLE_CSV)

    report = Trf001Ingestor().validate(_result(path))

    message = " ".join(issue.message for issue in report.issues).lower()
    assert "no required-column or semantic rule is asserted" in message
    assert "partial" in message
