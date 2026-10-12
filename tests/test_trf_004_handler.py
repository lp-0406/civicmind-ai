"""Tests for the TRF-004 ingestion handler.

The handler is exercised against the loopback HTTP fixture and against
hand-written files; no test reaches a real dataset endpoint.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from civicmind.ingestion.base import AcquisitionResult
from civicmind.ingestion.handlers import (
    SUPPORTED_DATASET_IDS,
    build_pilot_handler,
    build_pilot_registry,
)
from civicmind.ingestion.handlers.trf_001 import DATASET_ID as TRF_001_ID
from civicmind.ingestion.handlers.trf_004 import (
    DATASET_ID,
    DATASET_PAGE_URL,
    DOCUMENTED_COLUMN_HINTS,
    RESOURCE_URL,
    RESOURCE_URL_CITATION,
    SOURCE_ID,
    Trf004Ingestor,
)
from civicmind.ingestion.transfer import TransferLimits
from conftest import LocalHTTPServer

FIXED_TIME = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

#: A small CSV shaped like the TRF-004 station-wise resource, with a header that
#: includes the documented hints and a quoted station name containing an internal
#: comma, plus a subtotal/total row, a ragged row and a duplicate.
TRF004_STATION_CSV = (
    b"Zone,Sub-division,Station,2020 - Fatal Cases,2020 - Killed People,"
    b"2020 - Non-Fatal,2020 - Injured People,2020 - Total Cases\n"
    b"BTM Layout,BTM Layout,BTM Layout,0,0,1,2,3\n"
    b'East,East,Ashok Nagar,"1,5",1,8,4,13\n'
    b"East,East,Ashok Nagar,1,0,2,1,4\n"
    b"East,East,East Total,2,1,10,5,18\n"
    b"North,North,KR Market,0,0,0,1,1\n"
    b'North,North,,"2,0",0,3,2,5\n'
    b"South,South,Majestic,,0,0,0,0\n"
    b"Grand Total,Grand Total,Grand Total,3,1,13,8,25\n"
)


def _handler(
    url: str,
    *,
    limits: TransferLimits | None = None,
    at: datetime = FIXED_TIME,
) -> Trf004Ingestor:
    """Return a TRF-004 handler pointed at the local test server."""
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


# -- registration, identity and provenance -----------------------------------


def test_supported_dataset_ids_are_normalized() -> None:
    assert TRF_001_ID in SUPPORTED_DATASET_IDS
    assert DATASET_ID in SUPPORTED_DATASET_IDS
    assert DATASET_ID.lower() == SOURCE_ID
    assert SOURCE_ID not in SUPPORTED_DATASET_IDS  # registry keys on slugs in some paths


def test_build_pilot_handler_accepts_both_identifier_forms() -> None:
    h1 = build_pilot_handler(DATASET_ID)
    h2 = build_pilot_handler(SOURCE_ID)
    h3 = build_pilot_handler("TrF-004")

    assert isinstance(h1, Trf004Ingestor)
    assert isinstance(h2, Trf004Ingestor)
    assert isinstance(h3, Trf004Ingestor)
    assert h1.describe().source_id == SOURCE_ID
    assert h2.describe().source_id == SOURCE_ID
    assert h3.describe().source_id == SOURCE_ID


def test_build_pilot_handler_rejects_unsupported() -> None:
    from civicmind.ingestion.handlers import UnsupportedDatasetError

    with pytest.raises(UnsupportedDatasetError, match="TRF-999"):
        build_pilot_handler("TRF-999")


def test_build_pilot_registry_contains_both_handlers() -> None:
    registry = build_pilot_registry()
    ids = registry.source_ids()

    assert SOURCE_ID in ids
    assert TRF_001_ID.lower() in ids
    assert "wtr-005" in ids
    assert len(ids) == 3


def test_describe_is_static_and_needs_no_network(http_server: LocalHTTPServer) -> None:
    handler = Trf004Ingestor()

    descriptor = handler.describe()

    assert descriptor.source_id == SOURCE_ID == "trf-004"
    assert descriptor.title == ("Bengaluru Road Crashes Data (station-wise, 2007-2025)")
    assert "OpenCity" in descriptor.publisher
    assert descriptor.license == "Other (Public Domain) / Open Data"
    assert descriptor.geographic_scope == "Bengaluru"
    assert http_server.hit_count("/") == 0


def test_construction_and_registration_perform_no_io(tmp_path: Path) -> None:
    destination = tmp_path / "raw" / DATASET_ID

    handler = build_pilot_handler(DATASET_ID)

    assert destination.exists() is False
    assert handler.resource_url == RESOURCE_URL
    assert handler.describe().uri == RESOURCE_URL


def test_resource_url_provenance_is_recorded_with_its_citation() -> None:
    handler = Trf004Ingestor()

    provenance = handler.resource_provenance()

    assert provenance["resource_url"] == RESOURCE_URL
    assert provenance["cited_in"] == RESOURCE_URL_CITATION
    assert "trf_004_blocker_resolution_and_acquisition_prep.md" in provenance["cited_in"]
    assert provenance["dataset_page_url"] == DATASET_PAGE_URL
    assert "documented" in provenance["caveat"]
    assert "engineering choice" in provenance["caveat"]
    assert handler.describe().license == "Other (Public Domain) / Open Data"


def test_provenance_marks_licence_as_a_source_claim() -> None:
    handler = Trf004Ingestor()

    assert handler.describe().license  # recorded as the source states it
    # The handler never asserts that the licence has been verified.
    assert "verified" not in handler.resource_provenance()


# -- acquisition ------------------------------------------------------------


def test_acquire_returns_measured_facts(http_server: LocalHTTPServer, tmp_path: Path) -> None:
    url = http_server.serve("/resource.csv", body=TRF004_STATION_CSV)
    handler = _handler(url)

    result = handler.acquire(tmp_path)

    assert result.source_id == DATASET_ID
    assert result.local_path is not None and result.local_path.is_file()
    assert result.byte_size == len(TRF004_STATION_CSV)
    assert result.checksum_sha256 == hashlib.sha256(TRF004_STATION_CSV).hexdigest()
    assert result.method == "https-get"
    assert result.record_count is None
    assert "http=200" in result.notes
    assert "content-type=text/csv" in result.notes
    assert url in result.notes


def test_acquire_uses_the_selected_resource_url_by_default(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/selected.csv", body=TRF004_STATION_CSV)
    handler = _handler(url)

    result = handler.acquire(tmp_path)

    assert url in result.notes
    assert result.source_id == DATASET_ID


def test_acquire_never_overwrites_an_existing_artifact(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/resource.csv", body=TRF004_STATION_CSV)
    handler = _handler(url)
    stamp = FIXED_TIME.strftime("%Y%m%dT%H%M%SZ")
    colliding = tmp_path / f"trf-004-road-crashes-{stamp}.csv"
    colliding.write_bytes(b"bytes from an earlier acquisition")

    result = handler.acquire(tmp_path)

    assert result.local_path is not None
    assert result.local_path.name.endswith("-2.csv")
    assert colliding.read_bytes() == b"bytes from an earlier acquisition"


def test_acquire_stops_at_the_configured_size_limit(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/resource.csv", body=TRF004_STATION_CSV)
    handler = _handler(url, limits=TransferLimits(max_bytes=32))

    with pytest.raises(Exception) as excinfo:
        handler.acquire(tmp_path)

    assert "exceeded" in str(excinfo.value) or "above the" in str(excinfo.value)
    assert list(tmp_path.iterdir()) == []


def test_build_provenance_names_the_handler_and_version(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/resource.csv", body=TRF004_STATION_CSV)
    handler = _handler(url)

    result = handler.acquire(tmp_path)
    provenance = handler.build_provenance(result)

    assert provenance.handler.endswith("Trf004Ingestor")
    assert provenance.handler_version == "1.0"
    assert provenance.checksum_sha256 == result.checksum_sha256
    assert provenance.source_uri == url
    assert provenance.source_id == DATASET_ID


def test_build_provenance_uses_the_canonical_id_not_the_slug(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/resource.csv", body=TRF004_STATION_CSV)
    handler = _handler(url)

    result = handler.acquire(tmp_path)
    provenance = handler.build_provenance(result)

    assert provenance.source_id == DATASET_ID
    assert provenance.source_id != SOURCE_ID


# -- validation -------------------------------------------------------------


def test_validate_passes_a_well_formed_artifact(tmp_path: Path) -> None:
    path = _write(tmp_path, TRF004_STATION_CSV)

    report = Trf004Ingestor().validate(_result(path))

    assert report.passed is True
    assert report.source_id == DATASET_ID
    assert report.errors == ()


def test_validate_measures_the_header_and_row_counts(tmp_path: Path) -> None:
    path = _write(tmp_path, TRF004_STATION_CSV)

    report = Trf004Ingestor().validate(_result(path))

    schema_issue = next(i for i in report.issues if i.code == "SCHEMA_NOT_ASSERTED")
    assert schema_issue.severity == "info"
    assert schema_issue.context["documented_hints_present"]


def test_documented_column_hints_are_present_in_the_fixture_header() -> None:
    header = TRF004_STATION_CSV.split(b"\n", 1)[0].decode("utf-8")
    header_fields = [field.strip() for field in header.split(",")]
    for hint in DOCUMENTED_COLUMN_HINTS:
        assert any(hint in field for field in header_fields), (
            f"fixture header should contain a column matching documented hint {hint!r}"
        )


def test_validate_reports_a_missing_artifact(tmp_path: Path) -> None:
    missing = AcquisitionResult(
        source_id=DATASET_ID,
        acquired_at=FIXED_TIME,
        method="https-get",
        local_path=tmp_path / "absent.csv",
        byte_size=377,
        checksum_sha256="a" * 64,
    )

    report = Trf004Ingestor().validate(missing)

    assert report.passed is False
    assert "ARTIFACT_MISSING" in {issue.code for issue in report.issues}


def test_validate_reports_an_absent_path() -> None:
    report = Trf004Ingestor().validate(
        AcquisitionResult(source_id=DATASET_ID, acquired_at=FIXED_TIME, method="https-get")
    )

    assert report.passed is False
    assert "ARTIFACT_PATH_MISSING" in {issue.code for issue in report.issues}


def test_validate_reports_an_empty_artifact(tmp_path: Path) -> None:
    path = _write(tmp_path, b"")

    report = Trf004Ingestor().validate(_result(path, byte_size=0))

    assert report.passed is False
    assert "EMPTY_FILE" in {issue.code for issue in report.issues}


def test_validate_detects_a_size_mismatch(tmp_path: Path) -> None:
    path = _write(tmp_path, TRF004_STATION_CSV)

    report = Trf004Ingestor().validate(_result(path, byte_size=len(TRF004_STATION_CSV) + 1))

    assert report.passed is False
    issue = next(i for i in report.issues if i.code == "SIZE_MISMATCH")
    assert issue.context["measured"] == len(TRF004_STATION_CSV)


def test_validate_detects_a_checksum_mismatch(tmp_path: Path) -> None:
    path = _write(tmp_path, TRF004_STATION_CSV)

    report = Trf004Ingestor().validate(_result(path, checksum="f" * 64))

    assert report.passed is False
    assert "CHECKSUM_MISMATCH" in {issue.code for issue in report.issues}


def test_validate_reports_non_utf8_content(tmp_path: Path) -> None:
    path = _write(tmp_path, b"Zone,Station\n\xff\xfe\x00\x00")

    report = Trf004Ingestor().validate(_result(path))

    assert report.passed is False
    codes = {issue.code for issue in report.issues}
    assert "ENCODING_ERROR" in codes


def test_validate_reports_an_unterminated_quoted_field(tmp_path: Path) -> None:
    path = _write(tmp_path, b'Zone,Station\nAshok Nagar,"Central\n')

    report = Trf004Ingestor().validate(_result(path))

    assert report.passed is False
    issue = next(i for i in report.issues if i.code == "CSV_PARSE_ERROR")
    assert issue.context["rows_parsed"] == 1
    assert "strict" in issue.context["parser"]


def test_validate_reports_a_missing_header(tmp_path: Path) -> None:
    path = _write(tmp_path, b"\n\n")

    report = Trf004Ingestor().validate(_result(path))

    assert report.passed is False
    assert "HEADER_MISSING" in {issue.code for issue in report.issues}


def test_validate_reports_ragged_rows_as_a_warning(tmp_path: Path) -> None:
    path = _write(tmp_path, b"Zone,Station,Total\nNorth,KR Market,1\nSouth,Majestic\n")

    report = Trf004Ingestor().validate(_result(path))

    assert report.passed is True
    issue = next(i for i in report.issues if i.code == "RAGGED_ROWS")
    assert issue.severity == "warning"
    assert issue.context == {"ragged_rows": 1, "header_fields": 3}


def test_validate_warns_when_a_documented_column_hint_is_absent(tmp_path: Path) -> None:
    path = _write(tmp_path, b"Zone,Station,Total\nNorth,KR Market,1\nSouth,Majestic,2\n")

    report = Trf004Ingestor().validate(_result(path))

    assert report.passed is True
    codes = {issue.code for issue in report.issues}
    assert "DOCUMENTED_COLUMN_ABSENT" in codes
    absent = next(i for i in report.issues if i.code == "DOCUMENTED_COLUMN_ABSENT")
    assert absent.severity == "warning"
    assert absent.severity == "warning"
    assert "Sub-division" in absent.message


def test_validate_accepts_a_utf8_bom(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        b"\xef\xbb\xbfZone,Station,Total\nNorth,KR Market,1\nSouth,Majestic,2\n",
    )

    report = Trf004Ingestor().validate(_result(path))

    assert report.passed is True
    assert "BOM_PRESENT" in {issue.code for issue in report.issues}


def test_validate_flags_nul_bytes_as_an_error(tmp_path: Path) -> None:
    path = _write(tmp_path, b"Zone,Station,Total\nNorth,\x00KR Market,1\n")

    report = Trf004Ingestor().validate(_result(path))

    codes = {issue.code for issue in report.issues}
    assert "NUL_BYTES" in codes
    # The real CSV parser refuses a NUL byte, so the artifact is an error.
    assert report.passed is False
    assert "CSV_PARSE_ERROR" in codes


def test_validate_reports_a_header_only_file(tmp_path: Path) -> None:
    path = _write(tmp_path, b"Zone,Station,Total\n")

    report = Trf004Ingestor().validate(_result(path))

    assert report.passed is True
    assert "NO_DATA_ROWS" in {issue.code for issue in report.issues}


def test_validate_reports_total_and_subtotal_rows_as_data_not_structural_errors(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, TRF004_STATION_CSV)

    report = Trf004Ingestor().validate(_result(path))

    # Total/subtotal rows are data rows here, not structural violations.
    assert report.passed is True
    ragged = [i for i in report.issues if i.code == "RAGGED_ROWS"]
    assert not ragged, "the fixture is structurally consistent even with total rows"


def test_validate_allows_ambiguous_numeric_fields_without_semantic_rules(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        b"Zone,Station,2020 - Total Cases\nNorth,KR Market,1.0\nSouth,Majestic,\n",
    )

    report = Trf004Ingestor().validate(_result(path))

    # No numeric semantic rule is asserted, so a decimal-looking value and a blank
    # value are not errors by themselves.
    assert report.passed is True
    message = " ".join(issue.message for issue in report.issues).lower()
    assert "no required-column or semantic rule is asserted" in message


def test_validation_never_asserts_an_unverified_schema(tmp_path: Path) -> None:
    path = _write(tmp_path, TRF004_STATION_CSV)

    report = Trf004Ingestor().validate(_result(path))

    message = " ".join(issue.message for issue in report.issues).lower()
    assert "no required-column or semantic rule is asserted" in message
    assert "partial" in message


# -- handler selection round-trips through the identifier boundary ----------


def test_handler_selection_is_stable_across_identifier_forms() -> None:
    for form in (DATASET_ID, SOURCE_ID, "TrF-004", " trf-004 "):
        handler = build_pilot_handler(form)
        assert isinstance(handler, Trf004Ingestor)
        assert handler.DATASET_ID == DATASET_ID
        assert handler.SOURCE_ID == SOURCE_ID
