"""Pilot orchestration for one canonical dataset.

This module is the only place where the moving parts meet. It composes, in
order: the canonical catalog (metadata from the CSV), the eligibility policy
(who may be acquired), the handler (how bytes are fetched and checked), the
profiler (what the bytes contain), the four-axis record (state transitions) and
the evidence store (persistence). Each part keeps its own responsibility.

Rules this module is careful about
---------------------------------
* **Eligibility first.** No acquisition happens until the policy resolves the
  dataset; ``REJECT`` and ``REPLACE`` records stay blocked, and a
  ``CONDITIONAL`` record needs an explicit, recorded authorization.
* **One axis at a time.** Acquisition, validation and profiling each advance
  only their own axis, and a step whose recorded state would not change is
  reported as unchanged instead of being forced through a no-op transition.
* **Nothing is claimed that was not measured.** Reports carry the measured
  numbers; the licence stays unverified and no research decision is inferred
  from a historical acquisition label.
* **One identity.** Every public entry point accepts either the canonical id
  (``TRF-001``) or the registry slug (``trf-001``) and normalises it once
  through :mod:`civicmind.ingestion.identifiers`. Record lookup, artifact
  paths, evidence paths and every report field then use the canonical id, so a
  single dataset can never be recorded under two identities.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from civicmind.config import Settings
from civicmind.ingestion.base import AcquisitionResult
from civicmind.ingestion.catalog import DatasetRegistry
from civicmind.ingestion.evidence import EvidenceStore, ReplayReport, append_section
from civicmind.ingestion.exceptions import IngestionError
from civicmind.ingestion.handlers import build_pilot_handler
from civicmind.ingestion.handlers.trf_001 import (
    ACQUISITION_METHOD,
    DATASET_PAGE_URL,
    DEFAULT_MAX_BYTES,
    RESOURCE_URL_CITATION,
    VALIDATION_SCOPE,
)
from civicmind.ingestion.handlers.trf_001 import (
    DATASET_ID as TRF_001_DATASET_ID,
)
from civicmind.ingestion.identifiers import canonical_dataset_id
from civicmind.ingestion.integration import resolve_dataset_for_ingestion
from civicmind.ingestion.metadata import (
    ArtifactVersion,
    CanonicalDatasetRecord,
    EvidenceSource,
    ProfilingEvent,
)
from civicmind.ingestion.policy import ConditionalAuthorization
from civicmind.ingestion.sources import load_canonical_registry
from civicmind.ingestion.states import ProfilingState, ValidationState
from civicmind.ingestion.transfer import TransferLimits
from civicmind.profiling.csv_profile import CsvProfile, profile_csv

#: The dataset this pilot implements.
PILOT_DATASET_ID = TRF_001_DATASET_ID

#: Data rows examined by the partial profiling step of the axis-4 ladder.
PARTIAL_PROFILE_ROWS = 10

#: Directory name under the artifacts directory for generated profile documents.
PROFILE_SUBDIRECTORY = "profiles"


class PilotError(IngestionError):
    """Raised when a pilot step cannot proceed."""


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class PlanReport:
    """What an acquisition would do, computed without any network or write."""

    dataset_id: str
    title: str
    publisher: str
    license: str
    license_verified: bool
    research_decision: str
    acquisition_state: str
    validation_state: str
    profiling_state: str
    authorization_required: bool
    resource_url: str
    resource_url_citation: str
    dataset_page_url: str
    artifact_dir: str
    evidence_path: str
    profile_dir: str
    expected_format: str
    limits: Mapping[str, Any]
    artifacts_present: int
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe plan."""
        return {
            "dataset_id": self.dataset_id,
            "title": self.title,
            "publisher": self.publisher,
            "license": self.license,
            "license_verified": self.license_verified,
            "research_decision": self.research_decision,
            "acquisition_state": self.acquisition_state,
            "validation_state": self.validation_state,
            "profiling_state": self.profiling_state,
            "authorization_required": self.authorization_required,
            "resource_url": self.resource_url,
            "resource_url_citation": self.resource_url_citation,
            "dataset_page_url": self.dataset_page_url,
            "artifact_dir": self.artifact_dir,
            "evidence_path": self.evidence_path,
            "profile_dir": self.profile_dir,
            "expected_format": self.expected_format,
            "limits": dict(self.limits),
            "artifacts_present": self.artifacts_present,
            "notes": list(self.notes),
            "network_performed": False,
            "writes_performed": False,
        }


@dataclass(frozen=True)
class AcquisitionReport:
    """Outcome of one authorized acquisition."""

    dataset_id: str
    artifact_version: int
    local_path: str
    byte_size: int
    checksum_sha256: str
    acquired_at: datetime
    method: str
    evidence_path: str
    acquisition_state: str
    validation_state: str
    profiling_state: str
    replayed_events: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe acquisition summary."""
        return {
            "dataset_id": self.dataset_id,
            "artifact_version": self.artifact_version,
            "local_path": self.local_path,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "acquired_at": self.acquired_at.isoformat(),
            "method": self.method,
            "evidence_path": self.evidence_path,
            "acquisition_state": self.acquisition_state,
            "validation_state": self.validation_state,
            "profiling_state": self.profiling_state,
            "replayed_events": self.replayed_events,
        }


@dataclass(frozen=True)
class ValidationReportSummary:
    """Outcome of one validation run."""

    dataset_id: str
    artifact_version: int
    passed: bool
    state: str
    state_changed: bool
    checksum_sha256: str
    byte_size: int
    scope: str
    issues: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    @property
    def error_count(self) -> int:
        """Number of error-severity issues."""
        return sum(1 for issue in self.issues if issue.get("severity") == "error")

    @property
    def warning_count(self) -> int:
        """Number of warning-severity issues."""
        return sum(1 for issue in self.issues if issue.get("severity") == "warning")

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe validation summary."""
        return {
            "dataset_id": self.dataset_id,
            "artifact_version": self.artifact_version,
            "passed": self.passed,
            "state": self.state,
            "state_changed": self.state_changed,
            "checksum_sha256": self.checksum_sha256,
            "byte_size": self.byte_size,
            "scope": self.scope,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [dict(issue) for issue in self.issues],
        }


@dataclass(frozen=True)
class ProfilingReport:
    """Outcome of one profiling step."""

    dataset_id: str
    artifact_version: int
    state: str
    state_changed: bool
    profile_path: str
    data_rows: int
    column_count: int
    duplicate_rows: int
    sampled: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)
    steps_recorded: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe profiling summary."""
        return {
            "dataset_id": self.dataset_id,
            "artifact_version": self.artifact_version,
            "state": self.state,
            "state_changed": self.state_changed,
            "profile_path": self.profile_path,
            "data_rows": self.data_rows,
            "column_count": self.column_count,
            "duplicate_rows": self.duplicate_rows,
            "sampled": self.sampled,
            "warnings": list(self.warnings),
            "steps_recorded": list(self.steps_recorded),
        }


@dataclass(frozen=True)
class StatusReport:
    """The recorded state of one dataset."""

    dataset_id: str
    title: str
    axes: Mapping[str, str]
    blockers: Mapping[str, Any]
    active_artifact: Mapping[str, Any] | None
    artifact_count: int
    validation_count: int
    profiling_count: int
    evidence_path: str
    evidence_present: bool
    replayed_events: int
    replayed_skipped: tuple[str, ...]
    resource_provenance: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe status summary."""
        return {
            "dataset_id": self.dataset_id,
            "title": self.title,
            "axes": dict(self.axes),
            "blockers": dict(self.blockers),
            "active_artifact": None
            if self.active_artifact is None
            else dict(self.active_artifact),
            "artifact_count": self.artifact_count,
            "validation_count": self.validation_count,
            "profiling_count": self.profiling_count,
            "evidence_path": self.evidence_path,
            "evidence_present": self.evidence_present,
            "replayed_events": self.replayed_events,
            "replayed_skipped": list(self.replayed_skipped),
            "resource_provenance": dict(self.resource_provenance),
        }


def _require_record(registry: DatasetRegistry, dataset_id: str) -> CanonicalDatasetRecord:
    """Return the canonical record for ``dataset_id``."""
    return registry.get(dataset_id)


def _rehydrate(
    settings: Settings, dataset_id: str
) -> tuple[
    DatasetRegistry,
    CanonicalDatasetRecord,
    EvidenceStore,
    dict[str, Any] | None,
    ReplayReport | None,
]:
    """Load the catalog and rehydrate the record from evidence exactly once.

    Replay happens here and nowhere else: applying the same events twice would
    duplicate artifact versions and violate the record's own contract.
    """
    canonical = canonical_dataset_id(dataset_id)
    registry = load_canonical_registry()
    record = _require_record(registry, canonical)
    store = EvidenceStore(settings.artifacts_dir, canonical)
    payload = store.load_payload()
    replay = store.load(record) if payload is not None else None
    return registry, record, store, payload, replay


def artifact_dir(settings: Settings, dataset_id: str = PILOT_DATASET_ID) -> Path:
    """Return the directory that holds this dataset's raw artifacts."""
    return settings.raw_data_dir / canonical_dataset_id(dataset_id)


def profile_dir(settings: Settings, dataset_id: str = PILOT_DATASET_ID) -> Path:
    """Return the directory that holds generated profile documents."""
    canonical = canonical_dataset_id(dataset_id)
    return settings.artifacts_dir / "ingestion" / canonical / PROFILE_SUBDIRECTORY


def build_plan(
    settings: Settings,
    *,
    dataset_id: str = PILOT_DATASET_ID,
    resource_url: str | None = None,
) -> PlanReport:
    """Describe what an acquisition would do, performing no network and no writes."""
    dataset_id = canonical_dataset_id(dataset_id)
    _, record, store, _, _ = _rehydrate(settings, dataset_id)
    handler = build_pilot_handler(dataset_id, resource_url=resource_url)
    bounds = handler.limits
    decision = record.research_decision.value
    notes = [
        "dry run: no network request, no file written, no state changed",
        f"resource URL is cited from {RESOURCE_URL_CITATION} and re-checked at acquisition time",
        "licence is recorded as a source claim only; license_verified stays false (C-07)",
    ]
    if record.license_verified:
        notes.append("license_verified is true in the canonical metadata")
    return PlanReport(
        dataset_id=dataset_id,
        title=record.title,
        publisher=record.publisher,
        license=record.license,
        license_verified=record.license_verified,
        research_decision=decision,
        acquisition_state=record.acquisition_state.value,
        validation_state=record.validation_state.value,
        profiling_state=record.profiling_state.value,
        authorization_required=decision == "CONDITIONAL",
        resource_url=handler.resource_url,
        resource_url_citation=RESOURCE_URL_CITATION,
        dataset_page_url=DATASET_PAGE_URL,
        artifact_dir=str(artifact_dir(settings, dataset_id)),
        evidence_path=str(store.path),
        profile_dir=str(profile_dir(settings, dataset_id)),
        expected_format="csv",
        limits=bounds.as_dict(),
        artifacts_present=len(record.artifacts),
        notes=tuple(notes),
    )


def acquire(
    settings: Settings,
    *,
    rationale: str | None,
    dataset_id: str = PILOT_DATASET_ID,
    resource_url: str | None = None,
    max_bytes: int | None = None,
    clock: Callable[[], datetime] = _utc_now,
    sleep: Callable[[float], None] | None = None,
) -> AcquisitionReport:
    """Acquire the dataset after the eligibility policy authorizes it.

    Raises
    ------
    PilotError
        When no authorization rationale is supplied.
    ConditionalApprovalRequiredError / RejectedDatasetError / ReplacedDatasetError
        From the eligibility policy, unchanged.
    """
    if rationale is None or not rationale.strip():
        raise PilotError(
            "acquisition requires an explicit --authorize rationale; conditional datasets "
            "are never approved silently"
        )

    dataset_id = canonical_dataset_id(dataset_id)
    registry, record, store, payload, replay = _rehydrate(settings, dataset_id)
    replayed = 0 if replay is None else replay.applied
    authorization = ConditionalAuthorization(rationale=rationale)
    resolve_dataset_for_ingestion(registry, dataset_id, authorization=authorization)

    limits = TransferLimits(max_bytes=max_bytes or DEFAULT_MAX_BYTES)
    handler = build_pilot_handler(
        dataset_id, resource_url=resource_url, limits=limits, clock=clock, sleep=sleep
    )
    destination = artifact_dir(settings, dataset_id)
    result = handler.acquire(destination)

    if result.local_path is None or result.byte_size is None or result.checksum_sha256 is None:
        raise PilotError("acquisition returned an incomplete result; nothing was recorded")

    artifact = ArtifactVersion(
        version=len(record.artifacts) + 1,
        path=Path(result.local_path),
        byte_size=result.byte_size,
        checksum_sha256=result.checksum_sha256,
        acquired_at=result.acquired_at,
        provenance=handler.build_provenance(result),
        method=result.method or ACQUISITION_METHOD,
    )
    record.record_artifact(artifact)

    authorizations = append_section(
        (payload or {}).get("authorizations"),
        {"rationale": rationale.strip(), "recorded_at": clock().isoformat()},
    )
    store.save(
        record,
        extra={
            "authorizations": authorizations,
            "resource_provenance": handler.resource_provenance(),
        },
    )

    return AcquisitionReport(
        dataset_id=dataset_id,
        artifact_version=artifact.version,
        local_path=str(artifact.path),
        byte_size=artifact.byte_size,
        checksum_sha256=artifact.checksum_sha256,
        acquired_at=artifact.acquired_at,
        method=artifact.method,
        evidence_path=str(store.path),
        acquisition_state=record.acquisition_state.value,
        validation_state=record.validation_state.value,
        profiling_state=record.profiling_state.value,
        replayed_events=replayed,
    )


def validate(settings: Settings, *, dataset_id: str = PILOT_DATASET_ID) -> ValidationReportSummary:
    """Validate the active artifact and advance axis 3 when the state changes."""
    dataset_id = canonical_dataset_id(dataset_id)
    _, record, store, _, _replay = _rehydrate(settings, dataset_id)
    artifact = record.active_artifact
    if artifact is None:
        raise PilotError(
            f"no local artifact for {dataset_id}; run 'civicmind ingest acquire --dataset "
            f"{dataset_id} --authorize <rationale>' first"
        )
    handler = build_pilot_handler(dataset_id)
    result = AcquisitionResult(
        source_id=dataset_id,
        acquired_at=artifact.acquired_at,
        method=artifact.method or ACQUISITION_METHOD,
        local_path=artifact.path,
        byte_size=artifact.byte_size,
        checksum_sha256=artifact.checksum_sha256,
    )
    report = handler.validate(result)
    target = ValidationState.VALIDATED if report.passed else ValidationState.VALIDATION_FAILED
    changed = target is not record.validation_state
    if changed:
        record.record_validation(report, scope=VALIDATION_SCOPE)
        store.save(record)

    return ValidationReportSummary(
        dataset_id=dataset_id,
        artifact_version=artifact.version,
        passed=report.passed,
        state=record.validation_state.value,
        state_changed=changed,
        checksum_sha256=artifact.checksum_sha256,
        byte_size=artifact.byte_size,
        scope=VALIDATION_SCOPE,
        issues=tuple(
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "context": dict(issue.context),
            }
            for issue in report.issues
        ),
    )


def profile(settings: Settings, *, dataset_id: str = PILOT_DATASET_ID) -> ProfilingReport:
    """Measure the active artifact and walk the axis-4 ladder honestly.

    ``PROFILED`` is only reached after the contract's own sequence: a
    documentation-derived ``SCHEMA_ONLY`` step, a partial measurement, then a
    full measurement. Each step is recorded, so the audit trail shows which
    numbers were measured over which share of the data.
    """
    dataset_id = canonical_dataset_id(dataset_id)
    _, record, store, _, _ = _rehydrate(settings, dataset_id)
    artifact = record.active_artifact
    if artifact is None:
        raise PilotError(
            f"no local artifact for {dataset_id}; acquire the dataset before profiling it"
        )

    steps: list[str] = []
    changed = False

    if record.profiling_state is ProfilingState.NOT_PROFILED:
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="documentation only: columns named in the ingestion plan §4",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=_utc_now(),
            )
        )
        steps.append("SCHEMA_ONLY")
        changed = True

    if record.profiling_state is ProfilingState.SCHEMA_ONLY:
        partial = profile_csv(artifact.path, max_rows=PARTIAL_PROFILE_ROWS)
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope=(
                    f"partial measurement: first {partial.data_rows} data row(s) of "
                    f"{artifact.path.name}"
                ),
                evidence=EvidenceSource.MEASURED,
                artifact_version=artifact.version,
                recorded_at=_utc_now(),
            )
        )
        steps.append("PARTIALLY_PROFILED")
        changed = True

    full = profile_csv(artifact.path)
    profile_file = _write_profile_document(
        profile_dir(settings, dataset_id), full, artifact.version
    )

    if record.profiling_state is ProfilingState.PARTIALLY_PROFILED:
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PROFILED,
                scope=f"full measurement: all {full.data_rows} data row(s)",
                evidence=EvidenceSource.MEASURED,
                artifact_version=artifact.version,
                recorded_at=_utc_now(),
            )
        )
        steps.append("PROFILED")
        changed = True

    if changed:
        store.save(record)

    return ProfilingReport(
        dataset_id=dataset_id,
        artifact_version=artifact.version,
        state=record.profiling_state.value,
        state_changed=changed,
        profile_path=str(profile_file),
        data_rows=full.data_rows,
        column_count=full.column_count,
        duplicate_rows=full.duplicate_rows,
        sampled=full.sampled,
        warnings=full.warnings,
        steps_recorded=tuple(steps),
    )


def status(settings: Settings, *, dataset_id: str = PILOT_DATASET_ID) -> StatusReport:
    """Return the recorded state of the dataset, rehydrated from evidence."""
    dataset_id = canonical_dataset_id(dataset_id)
    _, record, store, payload, replay = _rehydrate(settings, dataset_id)
    artifact = record.active_artifact
    handler = build_pilot_handler(dataset_id)
    active = None
    if artifact is not None:
        active = {
            "version": artifact.version,
            "path": str(artifact.path),
            "byte_size": artifact.byte_size,
            "checksum_sha256": artifact.checksum_sha256,
            "acquired_at": artifact.acquired_at.isoformat(),
            "method": artifact.method,
            "superseded_at": None
            if artifact.superseded_at is None
            else artifact.superseded_at.isoformat(),
            "superseded_reason": artifact.superseded_reason,
        }
    return StatusReport(
        dataset_id=dataset_id,
        title=record.title,
        axes={
            "research_decision": record.research_decision.value,
            "acquisition_state": record.acquisition_state.value,
            "validation_state": record.validation_state.value,
            "profiling_state": record.profiling_state.value,
        },
        blockers={
            "blocker_reason": record.blocker_reason,
            "superseded_by": record.superseded_by,
            "replacement_target": record.replacement_target,
            "license_verified": record.license_verified,
        },
        active_artifact=active,
        artifact_count=len(record.artifacts),
        validation_count=len(record.validation_history),
        profiling_count=len(record.profiling_history),
        evidence_path=str(store.path),
        evidence_present=store.exists(),
        replayed_events=0 if replay is None else replay.applied,
        replayed_skipped=() if replay is None else replay.skipped_noop,
        resource_provenance=(payload or {}).get("resource_provenance")
        or handler.resource_provenance(),
    )


def _write_profile_document(directory: Path, profile: CsvProfile, version: int) -> Path:
    """Write a profile document atomically and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    base = f"profile-v{version}.json"
    path = directory / base
    if path.exists():
        path = directory / f"profile-v{version}-{uuid.uuid4().hex[:6]}.json"
    tmp_path = directory / f".{path.name}.{os.getpid()}.tmp"
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(profile.as_dict(), handle, indent=2, sort_keys=False)
            handle.write("\n")
        os.replace(tmp_path, path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise PilotError(f"could not write profile document {path}: {exc}") from exc
    return path


__all__ = [
    "PARTIAL_PROFILE_ROWS",
    "PILOT_DATASET_ID",
    "AcquisitionReport",
    "PilotError",
    "PlanReport",
    "ProfilingReport",
    "StatusReport",
    "ValidationReportSummary",
    "acquire",
    "artifact_dir",
    "build_plan",
    "profile",
    "profile_dir",
    "status",
    "validate",
]
