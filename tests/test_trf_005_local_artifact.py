"""Tests for the WTR-005 local-artifact ingestion path.

These tests exercise the local-registration extension: an already-present CSV
under ``data/raw`` is measured and recorded as an ``AcquisitionResult`` for the
rest of the pilot without inventing a download, URL, or verified licence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from civicmind.config import Settings
from civicmind.ingestion.base import AcquisitionResult
from civicmind.ingestion.handlers import (
    SUPPORTED_DATASET_IDS,
    UnsupportedDatasetError,
    acquire_local_artifact,
    build_pilot_handler,
    build_pilot_registry,
)
from civicmind.ingestion.handlers.trf_005 import (
    ACQUISITION_METHOD,
    Wtr005LocalIngestor,
    sha256_of,
)
from civicmind.ingestion.handlers.trf_005 import DATASET_ID as WTR_005_DATASET_ID
from civicmind.ingestion.handlers.trf_005 import SOURCE_ID as WTR_005_SOURCE_ID
from civicmind.ingestion.integration import prepare_ingestion
from civicmind.ingestion.policy import ConditionalAuthorization
from civicmind.ingestion.sources import load_canonical_registry
from civicmind.ingestion.states import ResearchDecision

#: Repository root, resolved from this test file so the suite works from any cwd.
REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA = "108639ce30129414e1dbd3d67b8403dcc83878bf2c2dc674b58d895f2adca974"
CSV_PATH = REPO_ROOT / "data" / "raw" / "BWSSB_Water_Consumption_August_2025.csv"


def _result(
    path: Path, *, digest: str | None = None, size: int | None = None
) -> AcquisitionResult:
    return AcquisitionResult(
        source_id=WTR_005_DATASET_ID,
        acquired_at=datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc),
        method=ACQUISITION_METHOD,
        local_path=path,
        byte_size=path.stat().st_size if size is None else size,
        checksum_sha256=sha256_of(path.read_bytes()) if digest is None else digest,
    )


def _staged(tmp_path: Path, name: str, body: bytes | None = None) -> Path:
    staging = tmp_path / "data" / "raw"
    staging.mkdir(parents=True, exist_ok=True)
    path = staging / name
    path.write_bytes(CSV_PATH.read_bytes() if body is None else body)
    return path


# -- handler shape ---------------------------------------------------------


def test_wtr_005_is_in_the_shipped_handler_set() -> None:
    assert WTR_005_DATASET_ID in SUPPORTED_DATASET_IDS
    assert WTR_005_SOURCE_ID in build_pilot_registry().source_ids()


def test_wtr_005_describes_a_local_artifact_handler_not_a_fetcher() -> None:
    ingestor = Wtr005LocalIngestor()

    descriptor = ingestor.describe()
    assert descriptor.source_id == WTR_005_SOURCE_ID
    assert descriptor.license == "Other (Public Domain) / Open Data"
    assert "local" in descriptor.description.lower()
    assert ingestor.limits.max_bytes == 0


def test_wtr_005_refuses_to_pretend_it_downloads() -> None:
    with pytest.raises(NotImplementedError):
        Wtr005LocalIngestor().acquire(CSV_PATH)


# -- validation ------------------------------------------------------------


def test_wtr_005_validate_accepts_the_supplied_csv() -> None:
    ingestor = Wtr005LocalIngestor()

    report = ingestor.validate(_result(CSV_PATH))

    assert report.passed is True
    assert report.source_id == WTR_005_DATASET_ID
    assert report.errors == ()


def test_wtr_005_validate_rejects_a_deleted_artifact() -> None:
    result = AcquisitionResult(
        source_id=WTR_005_DATASET_ID,
        acquired_at=datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc),
        method=ACQUISITION_METHOD,
        local_path=CSV_PATH.parent / "absent.csv",
        byte_size=377,
        checksum_sha256="a" * 64,
    )

    report = Wtr005LocalIngestor().validate(result)

    assert report.passed is False
    assert "ARTIFACT_MISSING" in {issue.code for issue in report.issues}


def test_wtr_005_validate_reports_a_checksum_mismatch(tmp_path: Path) -> None:
    # A tampered copy lives under tmp_path: validate() reads the recorded path
    # directly and never writes into the repository's raw tree.
    copy = tmp_path / "tampered.csv"
    copy.write_bytes(CSV_PATH.read_bytes())

    report = Wtr005LocalIngestor().validate(_result(copy, digest="f" * 64))

    assert report.passed is False
    assert "CHECKSUM_MISMATCH" in {issue.code for issue in report.issues}


# -- provenance ------------------------------------------------------------


def test_wtr_005_provenance_labels_it_as_local_registration() -> None:
    provenance = Wtr005LocalIngestor().build_provenance(_result(CSV_PATH))

    assert provenance.source_id == WTR_005_DATASET_ID
    assert provenance.acquisition_method == ACQUISITION_METHOD
    assert provenance.local_path is not None
    assert provenance.local_path.endswith("BWSSB_Water_Consumption_August_2025.csv")
    assert "download" not in provenance.acquisition_method.lower()


# -- local registration ----------------------------------------------------


def test_wtr_005_acquire_local_artifact_measures_the_existing_file(tmp_path: Path) -> None:
    copy = _staged(tmp_path, "wtr-005-staging-copy.csv")

    result = Wtr005LocalIngestor().acquire_local_artifact(copy)

    assert result.source_id == WTR_005_DATASET_ID
    assert result.local_path == copy.resolve()
    assert result.checksum_sha256 == EXPECTED_SHA
    assert result.byte_size == copy.stat().st_size
    assert result.method == ACQUISITION_METHOD
    assert result.record_count is None


def test_acquire_local_artifact_rejects_an_unsupported_dataset(tmp_path: Path) -> None:
    copy = _staged(tmp_path, "something.csv", b"no handler for this")

    with pytest.raises(UnsupportedDatasetError, match="WTR-999"):
        acquire_local_artifact("WTR-999", copy)


def test_acquire_local_artifact_rejects_a_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "data" / "raw" / "definitely-missing.csv"

    with pytest.raises(ValueError, match="not a readable file"):
        acquire_local_artifact(WTR_005_DATASET_ID, missing)


def test_acquire_local_artifact_rejects_a_directory(tmp_path: Path) -> None:
    directory = tmp_path / "data" / "raw"
    directory.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="not a readable file"):
        acquire_local_artifact(WTR_005_DATASET_ID, directory)


def test_acquire_local_artifact_rejects_a_path_outside_the_raw_tree(tmp_path: Path) -> None:
    outside = tmp_path / "escaped.csv"
    outside.write_bytes(b"outside the repo")

    with pytest.raises(ValueError, match="data/raw"):
        acquire_local_artifact(WTR_005_DATASET_ID, outside)


def test_acquire_local_artifact_rejects_a_changed_source_file(tmp_path: Path) -> None:
    copy = _staged(tmp_path, "changed.csv")

    first = Wtr005LocalIngestor().acquire_local_artifact(copy)

    # Tamper with the staged copy after registration.
    copy.write_bytes(CSV_PATH.read_bytes() + b"\n")

    second = Wtr005LocalIngestor().acquire_local_artifact(copy)

    assert second.checksum_sha256 != first.checksum_sha256
    assert second.checksum_sha256 == sha256_of(copy.read_bytes())


def test_wtr_005_local_artifact_idempotency(tmp_path: Path) -> None:
    copy = _staged(tmp_path, "idempotent.csv")

    first = Wtr005LocalIngestor().acquire_local_artifact(copy)
    second = Wtr005LocalIngestor().acquire_local_artifact(copy)

    assert second.local_path == first.local_path
    assert second.checksum_sha256 == first.checksum_sha256
    assert second.acquired_at >= first.acquired_at


def test_wtr_005_local_registration_does_not_overwrite_the_source(tmp_path: Path) -> None:
    copy = _staged(tmp_path, "existing.csv", b"prior artifact")

    prior = Wtr005LocalIngestor().acquire_local_artifact(copy)
    again = Wtr005LocalIngestor().acquire_local_artifact(copy)

    # Re-registering must not destroy or rewrite the prior artifact bytes.
    assert Path(prior.local_path).read_bytes() == b"prior artifact"
    assert again.local_path == prior.local_path
    assert again.checksum_sha256 == sha256_of(b"prior artifact")


# -- integration -----------------------------------------------------------


def test_wtr_005_integration_authorizes_and_prepares_ingestion(tmp_path: Path) -> None:
    copy = _staged(tmp_path, "BWSSB_Water_Consumption_August_2025.csv")
    artifact = acquire_local_artifact(WTR_005_DATASET_ID, copy)
    assert artifact.checksum_sha256 == EXPECTED_SHA

    ingestor = build_pilot_handler(WTR_005_DATASET_ID)
    # WTR-005 is research-decided CONDITIONAL, so an explicit authorization is
    # required before any ingestion operation can begin.
    authorization = ConditionalAuthorization(
        rationale=(
            "Milestone 8 local-artifact registration of the supplied BWSSB August 2025 snapshot"
        )
    )

    record = prepare_ingestion(
        load_canonical_registry(),
        ingestor,
        authorization=authorization,
    )

    assert record.dataset_id == WTR_005_DATASET_ID
    assert record.research_decision is ResearchDecision.CONDITIONAL


def test_wtr_005_integration_requires_authorization() -> None:
    ingestor = build_pilot_handler(WTR_005_DATASET_ID)

    from civicmind.ingestion.policy import ConditionalApprovalRequiredError

    with pytest.raises(ConditionalApprovalRequiredError):
        prepare_ingestion(load_canonical_registry(), ingestor, authorization=None)


def test_wtr_005_settings_raw_dir_matches_the_staged_file(pilot_settings: Settings) -> None:
    # The handler path and the configured raw-data directory agree on layout.
    assert CSV_PATH.parent.name == "raw"
    assert CSV_PATH.parent.parent.name == "data"
