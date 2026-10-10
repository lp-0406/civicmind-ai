"""Tests for the ingestion contract and registry.

The handlers below are *test fixtures*, deliberately kept inside the test
suite: production code ships no concrete handler and no dataset.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from civicmind import __version__
from civicmind.ingestion import (
    DEFAULT_REGISTRY,
    AcquisitionError,
    AcquisitionResult,
    DatasetIngestor,
    DatasetValidationError,
    IngestionRegistry,
    QualityIssue,
    SourceDescriptor,
    SourceRegistrationError,
    UnknownSourceError,
    ValidationReport,
    register,
)
from civicmind.ingestion.exceptions import IngestionError


def _descriptor(source_id: str = "test.dummy") -> SourceDescriptor:
    return SourceDescriptor(
        source_id=source_id,
        title="Test fixture source",
        publisher="CivicMind test suite",
        license="CC0-1.0",
        uri="https://example.invalid/data",
    )


class DummySource(DatasetIngestor):
    """Minimal in-memory handler used only by tests."""

    HANDLER_VERSION = "1.0"

    def __init__(
        self,
        source_id: str = "test.dummy",
        *,
        fail_validation: bool = False,
        error_on_acquire: bool = False,
    ) -> None:
        self._source_id = source_id
        self._fail_validation = fail_validation
        self._error_on_acquire = error_on_acquire
        self.describe_calls = 0
        self.acquire_calls = 0
        self.validate_calls = 0

    def describe(self) -> SourceDescriptor:
        self.describe_calls += 1
        return _descriptor(self._source_id)

    def acquire(self, destination: Path) -> AcquisitionResult:
        self.acquire_calls += 1
        if self._error_on_acquire:
            raise AcquisitionError(f"cannot reach {self._source_id!r}")
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "snapshot.csv"
        payload = b"id,value\n1,2\n"
        target.write_bytes(payload)
        return AcquisitionResult(
            source_id=self._source_id,
            acquired_at=datetime.now(tz=timezone.utc),
            method="test-fixture",
            local_path=target,
            byte_size=len(payload),
            checksum_sha256=hashlib.sha256(payload).hexdigest(),
        )

    def validate(self, result: AcquisitionResult) -> ValidationReport:
        self.validate_calls += 1
        issues = (
            (
                QualityIssue(
                    severity="error",
                    code="fixture-failure",
                    message="configured to fail",
                ),
            )
            if self._fail_validation
            else ()
        )
        return ValidationReport(
            source_id=result.source_id,
            passed=not self._fail_validation,
            issues=issues,
        )


# -- contract ----------------------------------------------------------------


def test_contract_is_abstract() -> None:
    with pytest.raises(TypeError):
        DatasetIngestor()  # type: ignore[abstract]


def test_descriptor_requires_valid_source_id() -> None:
    with pytest.raises(ValueError, match="source_id"):
        _descriptor("Not A Valid Id")


@pytest.mark.parametrize("field_name", ["title", "publisher", "license"])
def test_descriptor_rejects_blank_required_fields(field_name: str) -> None:
    values = {"title": "t", "publisher": "p", "license": "l"}
    values[field_name] = "   "
    with pytest.raises(ValueError, match=field_name):
        SourceDescriptor(source_id="test.dummy", **values)


def test_validation_report_raise_for_errors() -> None:
    report = ValidationReport(
        source_id="test.dummy",
        passed=False,
        issues=(QualityIssue(severity="warning", code="w", message="warn"),),
    )
    report.raise_for_errors()  # warnings alone must not raise
    assert report.errors == () and len(report.warnings) == 1

    failing = ValidationReport(
        source_id="test.dummy",
        passed=False,
        issues=(QualityIssue(severity="error", code="boom", message="broken"),),
    )
    with pytest.raises(DatasetValidationError, match="boom"):
        failing.raise_for_errors()


def test_ingest_runs_acquire_validate_and_provenance(tmp_path: Path) -> None:
    source = DummySource()

    outcome = source.ingest(tmp_path)

    assert source.acquire_calls == 1
    assert source.validate_calls == 1
    assert outcome.result.local_path is not None and outcome.result.local_path.is_file()
    assert outcome.report.passed is True
    provenance = outcome.provenance
    assert provenance.source_id == "test.dummy"
    assert provenance.acquisition_method == "test-fixture"
    assert provenance.checksum_sha256 == outcome.result.checksum_sha256
    assert provenance.handler.endswith("DummySource")
    assert provenance.handler_version == "1.0"
    assert provenance.civicmind_version == __version__


def test_ingest_enforces_validation_by_default(tmp_path: Path) -> None:
    source = DummySource(fail_validation=True)

    with pytest.raises(DatasetValidationError):
        source.ingest(tmp_path)

    outcome = source.ingest(tmp_path, enforce_validation=False)
    assert outcome.report.passed is False
    assert outcome.report.errors


def test_acquire_errors_propagate(tmp_path: Path) -> None:
    source = DummySource(error_on_acquire=True)

    with pytest.raises(AcquisitionError):
        source.ingest(tmp_path)
    assert source.validate_calls == 0


# -- registry ----------------------------------------------------------------


def test_register_and_lookup() -> None:
    registry = IngestionRegistry()
    source = DummySource("test.alpha")

    returned = registry.register(source)

    assert returned is source
    assert registry.get("test.alpha") is source
    assert "test.alpha" in registry
    assert len(registry) == 1
    assert registry.source_ids() == ("test.alpha",)


def test_registration_performs_no_acquisition() -> None:
    registry = IngestionRegistry()
    source = DummySource()

    registry.register(source)

    assert source.acquire_calls == 0
    assert source.validate_calls == 0


def test_duplicate_registration_requires_overwrite() -> None:
    registry = IngestionRegistry()
    registry.register(DummySource("test.dup"))

    with pytest.raises(SourceRegistrationError, match="test.dup"):
        registry.register(DummySource("test.dup"))

    replacement = DummySource("test.dup")
    registry.register(replacement, overwrite=True)
    assert registry.get("test.dup") is replacement
    assert len(registry) == 1


def test_unknown_source_lists_known_ids() -> None:
    registry = IngestionRegistry()
    registry.register(DummySource("test.known"))

    with pytest.raises(UnknownSourceError) as excinfo:
        registry.get("test.missing")

    message = str(excinfo.value)
    assert "test.missing" in message and "test.known" in message


def test_unregister() -> None:
    registry = IngestionRegistry()
    registry.register(DummySource("test.gone"))

    registry.unregister("test.gone")

    assert len(registry) == 0
    with pytest.raises(UnknownSourceError):
        registry.unregister("test.gone")


def test_register_rejects_non_contract_implementations() -> None:
    registry = IngestionRegistry()

    with pytest.raises(TypeError, match="DatasetIngestor"):
        registry.register(object())  # type: ignore[arg-type]


def test_describe_all_is_sorted_by_source_id() -> None:
    registry = IngestionRegistry()
    registry.register(DummySource("test.zulu"))
    registry.register(DummySource("test.alpha"))

    descriptors = registry.describe_all()

    assert [item.source_id for item in descriptors] == ["test.alpha", "test.zulu"]
    assert all(isinstance(item, SourceDescriptor) for item in descriptors)


def test_registries_are_isolated() -> None:
    local = IngestionRegistry()
    local.register(DummySource("test.local"))

    assert "test.local" not in DEFAULT_REGISTRY
    assert len(DEFAULT_REGISTRY) == 0


def test_module_level_register_uses_explicit_registry() -> None:
    local = IngestionRegistry()

    register(DummySource("test.helper"), registry=local)

    assert local.get("test.helper").source_id == "test.helper"
    assert "test.helper" not in DEFAULT_REGISTRY


def test_ingestion_errors_hierarchy() -> None:
    assert issubclass(SourceRegistrationError, IngestionError)
    assert issubclass(UnknownSourceError, IngestionError)
    assert issubclass(AcquisitionError, IngestionError)
    assert issubclass(DatasetValidationError, IngestionError)
