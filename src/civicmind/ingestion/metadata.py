"""Canonical dataset metadata record.

Implements the four-axis status model documented in
``docs/datasets/ingestion_plan.md`` §2.1:

* axis 1 ``research_decision`` - planning intent, changed only by a review;
* axis 2 ``acquisition_state`` - what bytes this repository actually holds;
* axis 3 ``validation_state``  - whether the current artifact passed our checks;
* axis 4 ``profiling_state``   - how much of the content has been measured.

Design rules carried over from the audit and plan:

* **Evidence or it did not happen.** ``VALIDATED`` requires the complete
  five-part evidence set (artifact on disk, byte size, SHA-256, acquisition
  timestamp, provenance) plus a passing validation report. A file that merely
  exists is never enough.
* **Validation is not profiling.** The two axes advance independently and
  neither implies the other.
* **Historical claims are not local state.** Axis 2 reflects repository-local
  evidence only; anything carried over from the research passes belongs in
  :attr:`CanonicalDatasetRecord.acquisition_notes`.
* **Unknown stays unknown.** Optional measurements default to ``None`` and are
  never invented.

This module implements no download behaviour and touches no network.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from civicmind.ingestion.base import ProvenanceRecord, QualityIssue, ValidationReport
from civicmind.ingestion.exceptions import InvalidTransitionError, MissingEvidenceError
from civicmind.ingestion.states import (
    ACQUISITION_STATE_TRANSITIONS,
    PROFILING_STATE_TRANSITIONS,
    RESEARCH_DECISION_TRANSITIONS,
    VALIDATION_STATE_TRANSITIONS,
    AcquisitionState,
    ProfilingState,
    ResearchDecision,
    ValidationState,
)

DATASET_ID_PATTERN = re.compile(r"^[A-Z]{3}-\d{3}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: The 21 dataset IDs of the V1 inventory, including WTR-005 (which the earliest
#: Master workbook omitted). ``TRF-006`` is deliberately absent: it is an
#: unresolved reference, not a catalogued dataset (audit conflict C-13).
CANONICAL_DATASET_IDS: frozenset[str] = frozenset(
    {
        "TRF-001",
        "TRF-002",
        "TRF-003",
        "TRF-004",
        "TRF-005",
        "WST-001",
        "WST-002",
        "WST-003",
        "WTR-001",
        "WTR-002",
        "WTR-003",
        "WTR-004",
        "WTR-005",
        "ENV-001",
        "ENV-002",
        "ENV-003",
        "ENV-004",
        "CIT-001",
        "CIT-002",
        "CIT-003",
        "CIT-004",
    }
)


class ResearchStatus(str, Enum):
    """Evidence maturity of the *research* (not one of the four axes).

    Carried over from the Freeze workbook's ``research_status`` column so the
    historical vocabulary stays representable. It never drives transitions.
    """

    ACQUIRED = "ACQUIRED"
    VERIFIED = "VERIFIED"
    CANDIDATE = "CANDIDATE"
    REJECTED = "REJECTED"


class SourceReliability(str, Enum):
    """Publisher reliability, from the workbooks' ``source_reliability_v3``.

    Only the three values that actually appear in the sources are modelled.
    The richer prose lives in ``source_reliability_notes`` (audit conflict C-12).
    """

    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"


class EvidenceSource(str, Enum):
    """Whether a profiling figure was measured or taken from documentation."""

    MEASURED = "MEASURED"
    DOCUMENTATION = "DOCUMENTATION"


def _ensure_aware(value: datetime, name: str) -> None:
    """Reject naive datetimes; every timestamp in this model is UTC-aware."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware (UTC), got {value!r}")


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


@dataclass
class ResourcePlan:
    """Local resource estimates for one dataset.

    Mirrors ``resource_requirements.csv``. ``None`` means *unknown* - the
    source files are explicit that many sizes were never measured, and this
    model never substitutes an estimate for a measurement.
    """

    processing_strategy: str = ""
    size_class: str = ""
    local_processing: str = ""
    download_storage_mb: float | None = None
    extracted_storage_mb: float | None = None
    working_storage_mb: float | None = None
    estimated_pandas_ram_mb: float | None = None
    recommended_ram_mb: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        for name in (
            "download_storage_mb",
            "extracted_storage_mb",
            "working_storage_mb",
            "estimated_pandas_ram_mb",
            "recommended_ram_mb",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0 or None (unknown), got {value!r}")


@dataclass
class ArtifactVersion:
    """One acquired version of a dataset's bytes.

    Immutable in practice except for the supersession fields, which the record
    sets when a newer acquisition replaces this artifact.
    """

    version: int
    path: Path
    byte_size: int
    checksum_sha256: str
    acquired_at: datetime
    provenance: ProvenanceRecord
    method: str = ""
    superseded_at: datetime | None = None
    superseded_reason: str | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"version must be >= 1, got {self.version!r}")
        if self.byte_size <= 0:
            raise ValueError(f"byte_size must be > 0, got {self.byte_size!r}")
        if not _SHA256_PATTERN.match(self.checksum_sha256):
            raise ValueError(
                f"checksum_sha256 must be 64 lowercase hex characters, got {self.checksum_sha256!r}"
            )
        _ensure_aware(self.acquired_at, "acquired_at")

    @property
    def is_active(self) -> bool:
        """True while this artifact is the one in use."""
        return self.superseded_at is None


@dataclass(frozen=True)
class ValidationEvent:
    """One recorded validation run, retained forever."""

    artifact_version: int
    passed: bool
    scope: str
    report: ValidationReport
    state: ValidationState
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.scope.strip():
            raise ValueError("scope must be non-empty (e.g. 'all resources')")
        _ensure_aware(self.recorded_at, "recorded_at")


@dataclass(frozen=True)
class ProfilingEvent:
    """One recorded profiling step, retained forever.

    ``SCHEMA_ONLY`` must be documentation-derived; ``PARTIALLY_PROFILED`` and
    ``PROFILED`` must be measured against a specific artifact.
    """

    state: ProfilingState
    scope: str
    evidence: EvidenceSource
    artifact_version: int | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        if self.state is ProfilingState.NOT_PROFILED:
            raise ValueError("NOT_PROFILED is the absence of profiling; do not record it")
        if not self.scope.strip():
            raise ValueError("scope must be non-empty (e.g. '3 of 7 resources')")
        _ensure_aware(self.recorded_at, "recorded_at")
        if (
            self.state is ProfilingState.SCHEMA_ONLY
            and self.evidence is not EvidenceSource.DOCUMENTATION
        ):
            raise ValueError("SCHEMA_ONLY must be labelled DOCUMENTATION, never measured")
        if self.state in (ProfilingState.PARTIALLY_PROFILED, ProfilingState.PROFILED):
            if self.evidence is not EvidenceSource.MEASURED:
                raise ValueError(f"{self.state.name} must be MEASURED, not documentation")
            if self.artifact_version is None:
                raise ValueError(f"{self.state.name} requires a concrete artifact_version")


@dataclass(frozen=True)
class ResearchReview:
    """One documented review that may change axis 1."""

    decision: ResearchDecision
    rationale: str
    reviewed_at: datetime
    replacement_target: str | None = None

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise ValueError("rationale must be non-empty; every axis-1 change is documented")
        _ensure_aware(self.reviewed_at, "reviewed_at")
        if self.decision is ResearchDecision.REPLACE and not (
            self.replacement_target and self.replacement_target.strip()
        ):
            raise ValueError("REPLACE requires a replacement_target dataset id")
        if self.decision is not ResearchDecision.REPLACE and self.replacement_target:
            raise ValueError(
                "replacement_target is only valid with REPLACE; the two dimensions stay separate"
            )


@dataclass(frozen=True)
class ValidationEvidence:
    """The five-part evidence set required to reach ``VALIDATED``."""

    artifact_present: bool
    byte_size: int | None
    checksum_sha256: str | None
    acquired_at: datetime | None
    provenance: ProvenanceRecord | None

    @property
    def missing(self) -> tuple[str, ...]:
        """Names of the evidence pieces that are absent."""
        gaps: list[str] = []
        if not self.artifact_present:
            gaps.append("artifact")
        if self.byte_size is None:
            gaps.append("byte_size")
        if self.checksum_sha256 is None:
            gaps.append("checksum_sha256")
        if self.acquired_at is None:
            gaps.append("acquired_at")
        if self.provenance is None:
            gaps.append("provenance")
        return tuple(gaps)

    @property
    def complete(self) -> bool:
        """True when every required piece of evidence is present."""
        return not self.missing


@dataclass
class CanonicalDatasetRecord:
    """Canonical metadata record for one municipal dataset.

    The descriptive fields mirror the 20-field canonical mapping in
    ``docs/datasets/dataset_inventory_audit.md`` §3.1; the four status axes are
    private and may only be changed through the methods below, so every state
    change is validated and recorded.

    Default axis values are deliberately conservative: a new record assumes
    nothing was acquired, validated or profiled, and starts ``CONDITIONAL``
    until a review says otherwise.
    """

    dataset_id: str
    title: str
    domain: str = ""
    publisher: str = ""
    short_title: str = ""
    subdomain: str | None = None
    publisher_aliases: tuple[str, ...] = ()
    publisher_url: str | None = None
    dataset_url: str | None = None
    download_url: str | None = None
    license: str = "UNKNOWN"
    license_verified: bool = False
    format: str = ""
    temporal_coverage: str = "UNKNOWN"
    spatial_coverage: str | None = None
    geographic_granularity: str | None = None
    record_count: int | None = None
    file_size: int | None = None
    acquired_at: datetime | None = None
    research_status: ResearchStatus | None = None
    source_reliability: SourceReliability | None = None
    source_reliability_notes: str = ""
    source_replaced_from: str | None = None
    resource_plan: ResourcePlan | None = None
    data_quality_issues: tuple[QualityIssue, ...] = ()
    acquisition_notes: str = ""

    _research_decision: ResearchDecision = field(
        init=False, repr=False, default=ResearchDecision.CONDITIONAL
    )
    _acquisition_state: AcquisitionState = field(
        init=False, repr=False, default=AcquisitionState.METADATA_ONLY
    )
    _validation_state: ValidationState = field(
        init=False, repr=False, default=ValidationState.NOT_VALIDATED
    )
    _profiling_state: ProfilingState = field(
        init=False, repr=False, default=ProfilingState.NOT_PROFILED
    )
    _superseded_by: str | None = field(init=False, repr=False, default=None)
    _blocker_reason: str | None = field(init=False, repr=False, default=None)
    _artifacts: list[ArtifactVersion] = field(init=False, repr=False, default_factory=list)
    _validation_events: list[ValidationEvent] = field(init=False, repr=False, default_factory=list)
    _profiling_events: list[ProfilingEvent] = field(init=False, repr=False, default_factory=list)
    _reviews: list[ResearchReview] = field(init=False, repr=False, default_factory=list)

    def __post_init__(self) -> None:
        if not DATASET_ID_PATTERN.match(self.dataset_id):
            raise ValueError(
                f"dataset_id must look like 'TRF-001' (3 uppercase letters, '-', 3 digits), "
                f"got {self.dataset_id!r}"
            )
        if not self.title.strip():
            raise ValueError("title must be a non-empty string")
        if self.record_count is not None and self.record_count < 0:
            raise ValueError(f"record_count must be >= 0 or None, got {self.record_count!r}")
        if self.file_size is not None and self.file_size < 0:
            raise ValueError(f"file_size must be >= 0 or None, got {self.file_size!r}")

    # -- read-only axis accessors -----------------------------------------
    @property
    def research_decision(self) -> ResearchDecision:
        """Axis 1 - planning intent (never implies the other axes)."""
        return self._research_decision

    @property
    def acquisition_state(self) -> AcquisitionState:
        """Axis 2 - repository-local bytes only."""
        return self._acquisition_state

    @property
    def validation_state(self) -> ValidationState:
        """Axis 3 - outcome of recorded validation runs."""
        return self._validation_state

    @property
    def profiling_state(self) -> ProfilingState:
        """Axis 4 - how much has been measured. Never implies ``VALIDATED``."""
        return self._profiling_state

    @property
    def replacement_target(self) -> str | None:
        """Set only by a ``REPLACE`` review; never inferred from axis 2."""
        for review in reversed(self._reviews):
            if review.decision is ResearchDecision.REPLACE:
                return review.replacement_target
        return None

    @property
    def superseded_by(self) -> str | None:
        """Set only by :meth:`mark_superseded`; never implies axis 1."""
        return self._superseded_by

    @property
    def blocker_reason(self) -> str | None:
        """Why acquisition is blocked, or ``None`` when not blocked."""
        return self._blocker_reason

    # -- histories ---------------------------------------------------------
    @property
    def artifacts(self) -> tuple[ArtifactVersion, ...]:
        """Every acquired artifact version, oldest first."""
        return tuple(self._artifacts)

    @property
    def active_artifact(self) -> ArtifactVersion | None:
        """The newest artifact that has not been superseded."""
        for artifact in reversed(self._artifacts):
            if artifact.is_active:
                return artifact
        return None

    @property
    def validation_history(self) -> tuple[ValidationEvent, ...]:
        """Every validation run, including superseded ones."""
        return tuple(self._validation_events)

    @property
    def profiling_history(self) -> tuple[ProfilingEvent, ...]:
        """Every profiling step, including those invalidated by a new artifact."""
        return tuple(self._profiling_events)

    @property
    def review_history(self) -> tuple[ResearchReview, ...]:
        """Every documented axis-1 review."""
        return tuple(self._reviews)

    @property
    def validation_evidence(self) -> ValidationEvidence:
        """The five-part evidence set for the currently active artifact."""
        artifact = self.active_artifact
        if artifact is None:
            return ValidationEvidence(False, None, None, None, None)
        return ValidationEvidence(
            artifact_present=True,
            byte_size=artifact.byte_size,
            checksum_sha256=artifact.checksum_sha256,
            acquired_at=artifact.acquired_at,
            provenance=artifact.provenance,
        )

    # -- axis 1 ------------------------------------------------------------
    def record_research_review(self, review: ResearchReview) -> None:
        """Apply a documented review to axis 1.

        Raises
        ------
        InvalidTransitionError
            If the change is not permitted (e.g. ``REPLACE -> KEEP``).
        """
        self._ensure_allowed(
            "research_decision",
            RESEARCH_DECISION_TRANSITIONS,
            self._research_decision,
            review.decision,
        )
        self._research_decision = review.decision
        self._reviews.append(review)

    # -- axis 2 ------------------------------------------------------------
    def record_artifact(self, artifact: ArtifactVersion) -> None:
        """Record an acquired artifact and advance axis 2 to ``DOWNLOADED``.

        A checksum change invalidates validation and profiling: the previous
        artifact is marked superseded and axis 3/4 reset to their initial
        states, while the earlier events stay in history. Re-downloading
        identical bytes appends a version without regressing anything.
        """
        if self._acquisition_state is AcquisitionState.SUPERSEDED:
            raise InvalidTransitionError(
                "acquisition_state: SUPERSEDED is terminal; a superseded record cannot "
                "acquire new artifacts (catalogue a new dataset id instead)"
            )
        if self._artifacts and artifact.version <= self._artifacts[-1].version:
            raise ValueError(
                f"artifact versions must strictly increase; "
                f"latest is {self._artifacts[-1].version}, got {artifact.version}"
            )

        previous = self.active_artifact
        checksum_changed = (
            previous is not None and previous.checksum_sha256 != artifact.checksum_sha256
        )
        if previous is not None:
            previous.superseded_at = artifact.acquired_at
            previous.superseded_reason = (
                "replaced by a newer acquisition with a different checksum"
                if checksum_changed
                else "re-downloaded; identical checksum"
            )

        if checksum_changed:
            self._invalidate_for_new_artifact()

        self._artifacts.append(artifact)
        self._acquisition_state = AcquisitionState.DOWNLOADED
        self._blocker_reason = None
        if self.acquired_at is None:
            self.acquired_at = artifact.acquired_at

    def mark_blocked(self, reason: str) -> None:
        """Record that acquisition is blocked, with a mandatory reason."""
        if not reason.strip():
            raise ValueError("reason must be non-empty; blocked always carries a reason")
        self._ensure_allowed(
            "acquisition_state",
            ACQUISITION_STATE_TRANSITIONS,
            self._acquisition_state,
            AcquisitionState.BLOCKED,
        )
        self._acquisition_state = AcquisitionState.BLOCKED
        self._blocker_reason = reason

    def clear_blocker(self) -> None:
        """Return to ``METADATA_ONLY`` once the blocker is resolved."""
        self._ensure_allowed(
            "acquisition_state",
            ACQUISITION_STATE_TRANSITIONS,
            self._acquisition_state,
            AcquisitionState.METADATA_ONLY,
        )
        self._acquisition_state = AcquisitionState.METADATA_ONLY
        self._blocker_reason = None

    def mark_superseded(self, superseded_by: str, reason: str) -> None:
        """Mark the bytes as replaced by ``superseded_by`` (axis 2 fact only).

        Superseded bytes must not be used, so any current validation or
        measured profiling derived from them is invalidated the same way a
        changed checksum is (:meth:`_invalidate_for_new_artifact`): axis 3
        returns to ``NOT_VALIDATED`` and measured axis-4 states drop to
        ``NOT_PROFILED``. ``SCHEMA_ONLY`` (documentation-derived, independent
        of the bytes) is retained, and prior events stay in history.

        This deliberately does **not** touch ``research_decision``: the two
        concepts are related but never interchangeable.
        """
        if not superseded_by.strip() or not reason.strip():
            raise ValueError("superseded_by and reason must both be non-empty")
        self._ensure_allowed(
            "acquisition_state",
            ACQUISITION_STATE_TRANSITIONS,
            self._acquisition_state,
            AcquisitionState.SUPERSEDED,
        )
        self._acquisition_state = AcquisitionState.SUPERSEDED
        self._superseded_by = superseded_by
        # Superseded bytes must not be used: drop the current validation and
        # measured profiling derived from them (history is kept). Reuses the
        # artifact-change invalidation so the two paths cannot drift apart.
        self._invalidate_for_new_artifact()

    # -- axis 3 ------------------------------------------------------------
    def record_validation(
        self, report: ValidationReport, *, scope: str, checked_at: datetime | None = None
    ) -> ValidationEvent:
        """Record a validation run and advance axis 3.

        A failing report moves axis 3 to ``VALIDATION_FAILED`` immediately -
        failure is itself evidence. A passing report only reaches ``VALIDATED``
        when the five-part evidence set is complete; otherwise
        :class:`MissingEvidenceError` is raised and the state is left untouched.
        """
        if report.source_id != self.dataset_id:
            raise ValueError(
                f"validation report is for {report.source_id!r}, record is {self.dataset_id!r}"
            )
        when = checked_at if checked_at is not None else _utc_now()
        passed = report.passed and not report.errors

        if not passed:
            target = ValidationState.VALIDATION_FAILED
            self._ensure_allowed(
                "validation_state", VALIDATION_STATE_TRANSITIONS, self._validation_state, target
            )
        else:
            evidence = self.validation_evidence
            if not evidence.complete:
                raise MissingEvidenceError(
                    f"cannot mark {self.dataset_id} VALIDATED; missing evidence: "
                    f"{', '.join(evidence.missing)}. A file that merely exists is not "
                    f"enough - record size, SHA-256, timestamp and provenance first."
                )
            if self._acquisition_state is not AcquisitionState.DOWNLOADED:
                raise MissingEvidenceError(
                    f"cannot validate {self.dataset_id}: acquisition_state is "
                    f"{self._acquisition_state.name}, not DOWNLOADED"
                )
            target = ValidationState.VALIDATED
            self._ensure_allowed(
                "validation_state", VALIDATION_STATE_TRANSITIONS, self._validation_state, target
            )

        event = ValidationEvent(
            artifact_version=self.active_artifact.version if self.active_artifact else 0,
            passed=passed,
            scope=scope,
            report=report,
            state=target,
            recorded_at=when,
        )
        self._validation_events.append(event)
        self._validation_state = target
        return event

    # -- axis 4 ------------------------------------------------------------
    def record_profiling(self, event: ProfilingEvent) -> None:
        """Record a profiling step and advance axis 4 (forward ladder only).

        Measured profiling requires bytes: ``PARTIALLY_PROFILED`` and
        ``PROFILED`` are rejected unless axis 2 is ``DOWNLOADED``.
        """
        if (
            event.evidence is EvidenceSource.MEASURED
            and self._acquisition_state is not AcquisitionState.DOWNLOADED
        ):
            raise MissingEvidenceError(
                f"cannot profile {self.dataset_id} from measurements while "
                f"acquisition_state is {self._acquisition_state.name}; "
                f"use SCHEMA_ONLY (documentation) or acquire the artifact first"
            )
        self._ensure_allowed(
            "profiling_state", PROFILING_STATE_TRANSITIONS, self._profiling_state, event.state
        )
        self._profiling_events.append(event)
        self._profiling_state = event.state

    # -- internals ---------------------------------------------------------
    def _invalidate_for_new_artifact(self) -> None:
        """Reset axes 3 and 4 after the artifact's bytes changed."""
        if self._validation_state is not ValidationState.NOT_VALIDATED:
            self._validation_state = ValidationState.NOT_VALIDATED
        if self._profiling_state in (
            ProfilingState.PARTIALLY_PROFILED,
            ProfilingState.PROFILED,
        ):
            self._profiling_state = ProfilingState.NOT_PROFILED

    @staticmethod
    def _ensure_allowed(
        axis: str,
        table: Mapping[Enum, frozenset[Enum]],
        current: Enum,
        target: Enum,
    ) -> None:
        """Raise :class:`InvalidTransitionError` unless ``current -> target`` is allowed."""
        if current is target:
            raise InvalidTransitionError(f"{axis}: {current.name} -> {target.name} is a no-op")
        allowed = table[current]
        if target not in allowed:
            options = ", ".join(sorted(state.name for state in allowed)) or "<terminal>"
            raise InvalidTransitionError(
                f"{axis}: {current.name} -> {target.name} is not permitted; "
                f"allowed from {current.name}: {options}"
            )
