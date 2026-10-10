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
    InvalidTransitionError,
    MissingEvidenceError,
    SourceRegistrationError,
    UnknownSourceError,
)
from civicmind.ingestion.metadata import (
    CANONICAL_DATASET_IDS,
    ArtifactVersion,
    CanonicalDatasetRecord,
    EvidenceSource,
    ProfilingEvent,
    ResearchReview,
    ResearchStatus,
    ResourcePlan,
    SourceReliability,
    ValidationEvent,
    ValidationEvidence,
)
from civicmind.ingestion.registry import DEFAULT_REGISTRY, IngestionRegistry, register
from civicmind.ingestion.states import (
    ACQUISITION_STATE_TRANSITIONS,
    PROFILING_STATE_TRANSITIONS,
    RESEARCH_DECISION_TRANSITIONS,
    VALIDATION_STATE_TRANSITIONS,
    AcquisitionState,
    ProfilingState,
    ResearchDecision,
    ValidationState,
    ensure_transition,
)

__all__ = [
    "ACQUISITION_STATE_TRANSITIONS",
    "CANONICAL_DATASET_IDS",
    "DEFAULT_REGISTRY",
    "PROFILING_STATE_TRANSITIONS",
    "RESEARCH_DECISION_TRANSITIONS",
    "VALIDATION_STATE_TRANSITIONS",
    "AcquisitionError",
    "AcquisitionResult",
    "AcquisitionState",
    "ArtifactVersion",
    "CanonicalDatasetRecord",
    "DatasetIngestor",
    "DatasetValidationError",
    "EvidenceSource",
    "IngestionError",
    "IngestionOutcome",
    "IngestionRegistry",
    "InvalidTransitionError",
    "MissingEvidenceError",
    "ProfilingEvent",
    "ProfilingState",
    "ProvenanceRecord",
    "QualityIssue",
    "ResearchDecision",
    "ResearchReview",
    "ResearchStatus",
    "ResourcePlan",
    "SourceDescriptor",
    "SourceRegistrationError",
    "SourceReliability",
    "UnknownSourceError",
    "ValidationEvidence",
    "ValidationEvent",
    "ValidationReport",
    "ValidationState",
    "ensure_transition",
    "register",
]
