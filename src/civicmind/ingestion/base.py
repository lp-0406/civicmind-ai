"""Contract definitions for municipal dataset ingestion.

Every ingestion handler implements the same explicit contract:

1. :meth:`DatasetIngestor.describe`  - identify the source with static,
   verifiable metadata (publisher, licence, scope).
2. :meth:`DatasetIngestor.acquire`   - read or retrieve the data into a
   controlled location, returning an :class:`AcquisitionResult`.
3. :meth:`DatasetIngestor.validate`  - check the acquisition result and report
   quality issues as a :class:`ValidationReport`.
4. Provenance                        - record where the data came from and how
   it was obtained (:meth:`DatasetIngestor.build_provenance`).

Design rules
------------
* No downloads happen implicitly. Registering a handler stores metadata only;
  :meth:`DatasetIngestor.acquire` runs only when a caller explicitly asks.
* No fabricated data. Fields that a handler cannot know (for example a record
  count) stay ``None`` rather than being invented.
* Failures are explicit: handlers raise :class:`~civicmind.ingestion.exceptions.AcquisitionError`
  (or a subclass) instead of returning partial, unlabelled results.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from civicmind import __version__ as CIVICMIND_VERSION
from civicmind.ingestion.exceptions import DatasetValidationError

_SOURCE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

Severity = Literal["info", "warning", "error"]


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class SourceDescriptor:
    """Static, human-verifiable metadata identifying a data source.

    Only facts that can be checked against the publisher's own documentation
    belong here. Nothing is inferred or invented.
    """

    source_id: str
    title: str
    publisher: str
    license: str
    description: str = ""
    uri: str | None = None
    update_frequency: str | None = None
    geographic_scope: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id or not _SOURCE_ID_PATTERN.match(self.source_id):
            raise ValueError(
                f"source_id must be a lowercase slug (letters, digits, '.', '_', '-'), "
                f"got {self.source_id!r}"
            )
        for field_name in ("title", "publisher", "license"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class AcquisitionResult:
    """Outcome of one explicit acquisition attempt.

    ``record_count`` is left ``None`` unless the handler genuinely knows it;
    CivicMind never fabricates dataset statistics.
    """

    source_id: str
    acquired_at: datetime
    method: str
    local_path: Path | None = None
    byte_size: int | None = None
    checksum_sha256: str | None = None
    record_count: int | None = None
    notes: str = ""


@dataclass(frozen=True)
class QualityIssue:
    """A single observation produced during validation."""

    severity: Severity
    code: str
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    """Structured result of validating an :class:`AcquisitionResult`."""

    source_id: str
    passed: bool
    issues: tuple[QualityIssue, ...] = ()
    checked_at: datetime = field(default_factory=_utc_now)

    @property
    def errors(self) -> tuple[QualityIssue, ...]:
        """Issues with ``error`` severity."""
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[QualityIssue, ...]:
        """Issues with ``warning`` severity."""
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def raise_for_errors(self) -> None:
        """Raise :class:`DatasetValidationError` when any error issue exists."""
        if self.errors:
            summary = "; ".join(f"{issue.code}: {issue.message}" for issue in self.errors)
            raise DatasetValidationError(
                f"Dataset {self.source_id!r} failed validation: {summary}"
            )


@dataclass(frozen=True)
class ProvenanceRecord:
    """Reproducibility trail describing exactly where a dataset came from."""

    source_id: str
    title: str
    publisher: str
    license: str
    source_uri: str | None
    acquired_at: datetime
    acquisition_method: str
    local_path: str | None
    checksum_sha256: str | None
    byte_size: int | None
    handler: str
    handler_version: str
    civicmind_version: str


@dataclass(frozen=True)
class IngestionOutcome:
    """Bundle returned by the default :meth:`DatasetIngestor.ingest` workflow."""

    result: AcquisitionResult
    report: ValidationReport
    provenance: ProvenanceRecord


class DatasetIngestor(ABC):
    """Abstract contract that every ingestion handler must implement.

    Implementations are registered with
    :class:`~civicmind.ingestion.registry.IngestionRegistry` and must not
    download anything at construction or registration time.
    """

    @abstractmethod
    def describe(self) -> SourceDescriptor:
        """Return static metadata identifying the source."""

    @abstractmethod
    def acquire(self, destination: Path) -> AcquisitionResult:
        """Read or retrieve the source data into ``destination``.

        Implementations must raise
        :class:`~civicmind.ingestion.exceptions.AcquisitionError` on failure
        rather than returning a partial result.
        """

    @abstractmethod
    def validate(self, result: AcquisitionResult) -> ValidationReport:
        """Check an acquisition result and report quality issues."""

    @property
    def source_id(self) -> str:
        """The registered identifier of this source."""
        return self.describe().source_id

    def build_provenance(self, result: AcquisitionResult) -> ProvenanceRecord:
        """Assemble a provenance record from the descriptor and the result."""
        descriptor = self.describe()
        return ProvenanceRecord(
            source_id=descriptor.source_id,
            title=descriptor.title,
            publisher=descriptor.publisher,
            license=descriptor.license,
            source_uri=descriptor.uri,
            acquired_at=result.acquired_at,
            acquisition_method=result.method,
            local_path=str(result.local_path) if result.local_path else None,
            checksum_sha256=result.checksum_sha256,
            byte_size=result.byte_size,
            handler=f"{type(self).__module__}.{type(self).__qualname__}",
            handler_version=getattr(self, "HANDLER_VERSION", "0"),
            civicmind_version=CIVICMIND_VERSION,
        )

    def ingest(self, destination: Path, *, enforce_validation: bool = True) -> IngestionOutcome:
        """Run the full acquire -> validate -> provenance workflow.

        Parameters
        ----------
        destination:
            Directory the handler may write to (created on demand by handlers).
        enforce_validation:
            When ``True`` (default), a failing report raises
            :class:`~civicmind.ingestion.exceptions.DatasetValidationError`.
            Set to ``False`` to inspect a failing report without raising.
        """
        acquisition = self.acquire(Path(destination))
        report = self.validate(acquisition)
        provenance = self.build_provenance(acquisition)
        if enforce_validation:
            report.raise_for_errors()
        return IngestionOutcome(result=acquisition, report=report, provenance=provenance)
