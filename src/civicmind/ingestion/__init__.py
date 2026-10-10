"""Dataset ingestion foundation.

Exposes the ingestion contract (:class:`DatasetIngestor` and its value
objects), the exceptions raised by handlers, and the registry used to look
handlers up by ``source_id``.

No concrete handlers ship yet and nothing is downloaded automatically - see
``docs/datasets/ingestion_strategy.md`` for the planned workflow.
"""

from __future__ import annotations

from civicmind.ingestion.base import (
    AcquisitionResult,
    DatasetIngestor,
    IngestionOutcome,
    ProvenanceRecord,
    QualityIssue,
    SourceDescriptor,
    ValidationReport,
)
from civicmind.ingestion.exceptions import (
    AcquisitionError,
    DatasetValidationError,
    IngestionError,
    SourceRegistrationError,
    UnknownSourceError,
)
from civicmind.ingestion.registry import DEFAULT_REGISTRY, IngestionRegistry, register

__all__ = [
    "DEFAULT_REGISTRY",
    "AcquisitionError",
    "AcquisitionResult",
    "DatasetIngestor",
    "DatasetValidationError",
    "IngestionError",
    "IngestionOutcome",
    "IngestionRegistry",
    "ProvenanceRecord",
    "QualityIssue",
    "SourceDescriptor",
    "SourceRegistrationError",
    "UnknownSourceError",
    "ValidationReport",
    "register",
]
