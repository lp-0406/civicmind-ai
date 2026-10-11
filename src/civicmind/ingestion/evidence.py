"""Persistent, versioned evidence for the local ingestion state of one dataset.

The four-axis model lives on :class:`~civicmind.ingestion.metadata.CanonicalDatasetRecord`,
which is an in-memory object. A CLI invocation is a short-lived process, so
without persistence every command would see a fresh ``METADATA_ONLY`` record and
the axes could never be observed across separate commands. This module is that
persistence layer, and nothing more.

Design rules
------------
* **The record is the only state machine.** Rehydration replays the recorded
  events through the record's own public methods
  (:meth:`record_artifact`, :meth:`record_validation`,
  :meth:`record_profiling`, :meth:`record_research_review`), so the permitted
  transition tables remain the single authority. Nothing here mutates a private
  attribute or re-implements a rule.
* **Events, not just states.** Artifact versions, validation runs and profiling
  steps are stored as ordered events with timestamps, so history survives a
  re-acquisition and a changed artifact version can be traced.
* **Measured versus claimed.** Locally measured facts
  (``basis: measured``) are stored apart from source claims
  (``claims``, which includes ``license_verified: false`` until a licence is
  read from the publisher). A claim never masquerades as a measurement.
* **Atomic and single-writer.** Writes go to a temporary file and are promoted
  with :func:`os.replace`. A lock file makes a concurrent writer fail loudly
  instead of silently discarding the other's evidence.
* **Fail safe.** A missing file is a fresh start; a malformed, incompatible or
  foreign file raises instead of being overwritten, so state is never silently
  reset.
* **Nothing sensitive, no payloads.** The JSON never contains dataset row
  values, credentials or secrets — only paths, digests, counts and prose.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from civicmind import __version__ as CIVICMIND_VERSION
from civicmind.ingestion.base import (
    ProvenanceRecord,
    QualityIssue,
    ValidationReport,
)
from civicmind.ingestion.metadata import (
    ArtifactVersion,
    CanonicalDatasetRecord,
    EvidenceSource,
    ProfilingEvent,
    ResearchReview,
)
from civicmind.ingestion.states import ProfilingState, ResearchDecision

#: Version of the evidence document schema. Bumped only for incompatible changes.
EVIDENCE_SCHEMA_VERSION = 1

#: Sub-directory of the artifacts directory that holds ingestion evidence.
EVIDENCE_SUBDIRECTORY = "ingestion"

_LOCK_SUFFIX = ".lock"
_TMP_SUFFIX = ".tmp"

#: Sections preserved from an existing document when the record cannot supply
#: them, with the shape each one must have. List sections are normalised to a
#: list and the mapping section is validated rather than coerced, so a
#: ``resource_provenance`` object can never silently degrade into its key names.
_LIST_SECTIONS: tuple[str, ...] = ("profiles", "authorizations", "notes")
_MAPPING_SECTIONS: tuple[str, ...] = ("resource_provenance",)
_PRESERVED_SECTIONS: tuple[str, ...] = (*_LIST_SECTIONS, *_MAPPING_SECTIONS)


class EvidenceError(RuntimeError):
    """Base class for evidence-store failures."""


class EvidenceSchemaError(EvidenceError):
    """Raised when evidence is incompatible, foreign, or structurally invalid."""


class EvidenceCorruptError(EvidenceError):
    """Raised when the evidence file cannot be decoded as JSON."""


class EvidenceBusyError(EvidenceError):
    """Raised when another writer holds the lock."""


@dataclass(frozen=True)
class ReplayReport:
    """What rehydration actually did, so a caller can report it honestly."""

    applied: int
    skipped_noop: tuple[str, ...]

    @property
    def skipped(self) -> int:
        """Number of recorded events that were already reflected in the state."""
        return len(self.skipped_noop)


def evidence_dir(artifacts_dir: Path, dataset_id: str) -> Path:
    """Return the evidence directory for ``dataset_id``."""
    return Path(artifacts_dir) / EVIDENCE_SUBDIRECTORY / dataset_id


def evidence_path(artifacts_dir: Path, dataset_id: str) -> Path:
    """Return the evidence document path for ``dataset_id``."""
    return evidence_dir(artifacts_dir, dataset_id) / "evidence.json"


def _iso(value: datetime | None) -> str | None:
    """Serialise an aware datetime in ISO-8601, or ``None``."""
    return None if value is None else value.isoformat()


def _parse_datetime(value: Any, field_name: str) -> datetime:
    """Parse a stored ISO-8601 datetime, raising :class:`EvidenceSchemaError`."""
    if not isinstance(value, str) or not value.strip():
        raise EvidenceSchemaError(f"{field_name} must be an ISO-8601 string, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceSchemaError(
            f"{field_name} is not a valid ISO-8601 value: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise EvidenceSchemaError(f"{field_name} must be timezone-aware: {value!r}")
    return parsed


def _provenance_to_dict(provenance: ProvenanceRecord) -> dict[str, Any]:
    """Serialise a :class:`ProvenanceRecord`."""
    return {
        "source_id": provenance.source_id,
        "title": provenance.title,
        "publisher": provenance.publisher,
        "license": provenance.license,
        "source_uri": provenance.source_uri,
        "acquired_at": _iso(provenance.acquired_at),
        "acquisition_method": provenance.acquisition_method,
        "local_path": provenance.local_path,
        "checksum_sha256": provenance.checksum_sha256,
        "byte_size": provenance.byte_size,
        "handler": provenance.handler,
        "handler_version": provenance.handler_version,
        "civicmind_version": provenance.civicmind_version,
    }


def _provenance_from_dict(payload: Mapping[str, Any]) -> ProvenanceRecord:
    """Rebuild a :class:`ProvenanceRecord` from stored JSON."""
    try:
        return ProvenanceRecord(
            source_id=str(payload["source_id"]),
            title=str(payload["title"]),
            publisher=str(payload["publisher"]),
            license=str(payload["license"]),
            source_uri=None if payload.get("source_uri") is None else str(payload["source_uri"]),
            acquired_at=_parse_datetime(
                payload.get("acquired_at"), "artifacts[].provenance.acquired_at"
            ),
            acquisition_method=str(payload["acquisition_method"]),
            local_path=None if payload.get("local_path") is None else str(payload["local_path"]),
            checksum_sha256=(
                None if payload.get("checksum_sha256") is None else str(payload["checksum_sha256"])
            ),
            byte_size=None if payload.get("byte_size") is None else int(payload["byte_size"]),
            handler=str(payload["handler"]),
            handler_version=str(payload["handler_version"]),
            civicmind_version=str(payload["civicmind_version"]),
        )
    except KeyError as exc:
        raise EvidenceSchemaError(f"provenance record is missing {exc.args[0]!r}") from exc


def _issue_to_dict(issue: QualityIssue) -> dict[str, Any]:
    """Serialise a :class:`QualityIssue`."""
    return {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "context": dict(issue.context),
    }


def _issue_from_dict(payload: Mapping[str, Any]) -> QualityIssue:
    """Rebuild a :class:`QualityIssue` from stored JSON."""
    try:
        severity = str(payload["severity"])
        if severity not in ("info", "warning", "error"):
            raise EvidenceSchemaError(f"unknown issue severity: {severity!r}")
        return QualityIssue(
            severity=severity,  # type: ignore[arg-type]
            code=str(payload["code"]),
            message=str(payload["message"]),
            context=dict(payload.get("context") or {}),
        )
    except KeyError as exc:
        raise EvidenceSchemaError(f"quality issue is missing {exc.args[0]!r}") from exc


def serialize_record(record: CanonicalDatasetRecord) -> dict[str, Any]:
    """Serialise the record's axes, histories and source claims."""
    return {
        "axes": {
            "research_decision": record.research_decision.value,
            "acquisition_state": record.acquisition_state.value,
            "validation_state": record.validation_state.value,
            "profiling_state": record.profiling_state.value,
        },
        "blocker_reason": record.blocker_reason,
        "superseded_by": record.superseded_by,
        "claims": {
            "basis": "source claim; not verified locally",
            "publisher": record.publisher,
            "publisher_aliases": list(record.publisher_aliases),
            "license": record.license,
            "license_verified": record.license_verified,
            "dataset_url": record.dataset_url,
            "download_url": record.download_url,
            "research_status": (
                None if record.research_status is None else record.research_status.value
            ),
            "source_reliability": (
                None if record.source_reliability is None else record.source_reliability.value
            ),
            "source_replaced_from": record.source_replaced_from,
        },
        "reviews": [
            {
                "decision": review.decision.value,
                "rationale": review.rationale,
                "reviewed_at": _iso(review.reviewed_at),
                "replacement_target": review.replacement_target,
            }
            for review in record.review_history
        ],
        "artifacts": [
            {
                "basis": "measured locally",
                "version": artifact.version,
                "path": str(artifact.path),
                "byte_size": artifact.byte_size,
                "checksum_sha256": artifact.checksum_sha256,
                "acquired_at": _iso(artifact.acquired_at),
                "method": artifact.method,
                "superseded_at": _iso(artifact.superseded_at),
                "superseded_reason": artifact.superseded_reason,
                "provenance": _provenance_to_dict(artifact.provenance),
            }
            for artifact in record.artifacts
        ],
        "validation_events": [
            {
                "basis": "measured locally",
                "artifact_version": event.artifact_version,
                "passed": event.passed,
                "scope": event.scope,
                "recorded_at": _iso(event.recorded_at),
                "state": event.state.value,
                "report": {
                    "source_id": event.report.source_id,
                    "passed": event.report.passed,
                    "checked_at": _iso(event.report.checked_at),
                    "issues": [_issue_to_dict(issue) for issue in event.report.issues],
                },
            }
            for event in record.validation_history
        ],
        "profiling_events": [
            {
                "basis": (
                    "documentation"
                    if event.evidence is EvidenceSource.DOCUMENTATION
                    else "measured locally"
                ),
                "state": event.state.value,
                "scope": event.scope,
                "evidence": event.evidence.value,
                "artifact_version": event.artifact_version,
                "recorded_at": _iso(event.recorded_at),
            }
            for event in record.profiling_history
        ],
    }


def build_document(
    record: CanonicalDatasetRecord,
    *,
    existing: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete evidence document for ``record``.

    Sections the record cannot supply (profile pointers, authorization trail,
    notes, resource provenance) are carried over from ``existing`` and then
    overridden by ``extra``, so unrelated history is never dropped by a write.
    """
    document: dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "dataset_id": record.dataset_id,
        "producer": {"civicmind_version": CIVICMIND_VERSION},
        "single_writer": (
            "one writer at a time; concurrent writers fail on the lock file rather than "
            "overwriting each other's evidence"
        ),
    }
    source = existing or {}
    for section in _LIST_SECTIONS:
        document[section] = list(source.get(section) or [])
    for section in _MAPPING_SECTIONS:
        stored = source.get(section)
        if stored is None:
            document[section] = None
            continue
        if not isinstance(stored, Mapping):
            raise EvidenceSchemaError(
                f"evidence section {section!r} must be a JSON object, got {type(stored).__name__}"
            )
        document[section] = dict(stored)
    document.update(serialize_record(record))
    if extra:
        document.update(dict(extra))
    return document


def _validate_document(payload: Any, dataset_id: str) -> dict[str, Any]:
    """Validate a decoded evidence document, raising on anything unexpected."""
    if not isinstance(payload, dict):
        raise EvidenceSchemaError("evidence document must be a JSON object")
    version = payload.get("schema_version")
    if version != EVIDENCE_SCHEMA_VERSION:
        raise EvidenceSchemaError(
            f"unsupported evidence schema_version {version!r}; "
            f"this build writes and reads version {EVIDENCE_SCHEMA_VERSION}"
        )
    stored_id = payload.get("dataset_id")
    if stored_id != dataset_id:
        raise EvidenceSchemaError(
            f"evidence document belongs to {stored_id!r}, not {dataset_id!r}"
        )
    for section in (
        "axes",
        "claims",
        "reviews",
        "artifacts",
        "validation_events",
        "profiling_events",
    ):
        if not isinstance(payload.get(section), (dict, list)):
            raise EvidenceSchemaError(f"evidence section {section!r} is missing or malformed")
    return payload


def _apply_artifact(record: CanonicalDatasetRecord, payload: Mapping[str, Any]) -> None:
    """Replay one recorded artifact through :meth:`record_artifact`."""
    try:
        artifact = ArtifactVersion(
            version=int(payload["version"]),
            path=Path(str(payload["path"])),
            byte_size=int(payload["byte_size"]),
            checksum_sha256=str(payload["checksum_sha256"]),
            acquired_at=_parse_datetime(payload.get("acquired_at"), "artifacts[].acquired_at"),
            provenance=_provenance_from_dict(payload["provenance"]),
            method=str(payload.get("method") or ""),
        )
    except KeyError as exc:
        raise EvidenceSchemaError(f"artifact is missing {exc.args[0]!r}") from exc
    record.record_artifact(artifact)


def _apply_validation(record: CanonicalDatasetRecord, payload: Mapping[str, Any]) -> None:
    """Replay one recorded validation run through :meth:`record_validation`."""
    reported = payload.get("report")
    if not isinstance(reported, Mapping):
        raise EvidenceSchemaError("validation event is missing its report")
    issues = reported.get("issues") or []
    if not isinstance(issues, list):
        raise EvidenceSchemaError("validation report issues must be a list")
    report = ValidationReport(
        source_id=str(reported.get("source_id")),
        passed=bool(reported.get("passed")),
        issues=tuple(_issue_from_dict(issue) for issue in issues),
        checked_at=_parse_datetime(reported.get("checked_at"), "validation.report.checked_at"),
    )
    record.record_validation(
        report,
        scope=str(payload.get("scope") or "recorded run"),
        checked_at=_parse_datetime(payload.get("recorded_at"), "validation_events[].recorded_at"),
    )


def _apply_profiling(record: CanonicalDatasetRecord, payload: Mapping[str, Any]) -> None:
    """Replay one recorded profiling step through :meth:`record_profiling`."""
    try:
        state = ProfilingState(str(payload["state"]))
        evidence = EvidenceSource(str(payload["evidence"]))
    except ValueError as exc:
        raise EvidenceSchemaError(
            f"profiling event has an unknown vocabulary value: {exc}"
        ) from exc
    target = payload.get("artifact_version")
    record.record_profiling(
        ProfilingEvent(
            state=state,
            scope=str(payload.get("scope") or "recorded scope"),
            evidence=evidence,
            artifact_version=None if target is None else int(target),
            recorded_at=_parse_datetime(
                payload.get("recorded_at"), "profiling_events[].recorded_at"
            ),
        )
    )


def _apply_review(record: CanonicalDatasetRecord, payload: Mapping[str, Any]) -> None:
    """Replay one recorded axis-1 review through :meth:`record_research_review`."""
    try:
        decision = ResearchDecision(str(payload["decision"]))
    except ValueError as exc:
        raise EvidenceSchemaError(f"review has an unknown decision: {exc}") from exc
    target = payload.get("replacement_target")
    record.record_research_review(
        ResearchReview(
            decision=decision,
            rationale=str(payload.get("rationale") or "recorded review"),
            reviewed_at=_parse_datetime(payload.get("reviewed_at"), "reviews[].reviewed_at"),
            replacement_target=None if target is None else str(target),
        )
    )


def rehydrate(record: CanonicalDatasetRecord, payload: Mapping[str, Any]) -> ReplayReport:
    """Replay stored events into ``record`` in chronological order.

    Events are applied through the record's public methods, so an illegal
    recorded sequence raises the record's own error rather than being forced.
    A recorded event whose target state is already the current state is skipped
    (the four-axis contract forbids a no-op transition) and reported in
    :attr:`ReplayReport.skipped_noop` instead of being silently dropped.
    """
    timeline: list[tuple[datetime, str, str, Mapping[str, Any]]] = []
    for key, kind in (
        ("reviews", "review"),
        ("artifacts", "artifact"),
        ("validation_events", "validation"),
        ("profiling_events", "profiling"),
    ):
        for index, item in enumerate(payload.get(key) or []):
            if not isinstance(item, Mapping):
                raise EvidenceSchemaError(f"{key}[{index}] must be a JSON object")
            stamp = _parse_datetime(
                item.get("reviewed_at") or item.get("acquired_at") or item.get("recorded_at"),
                f"{key}[{index}].timestamp",
            )
            timeline.append((stamp, kind, f"{kind}[{index}]", item))

    order = {"review": 0, "artifact": 1, "validation": 2, "profiling": 3}
    applied = 0
    skipped: list[str] = []
    for _, kind, label, item in sorted(timeline, key=lambda entry: (entry[0], order[entry[1]])):
        before = (
            record.research_decision,
            record.acquisition_state,
            record.validation_state,
            record.profiling_state,
        )
        if kind == "review":
            _apply_review(record, item)
        elif kind == "artifact":
            _apply_artifact(record, item)
        elif kind == "validation":
            _apply_validation(record, item)
        else:
            _apply_profiling(record, item)
        after = (
            record.research_decision,
            record.acquisition_state,
            record.validation_state,
            record.profiling_state,
        )
        if before == after:
            skipped.append(label)
        else:
            applied += 1
    return ReplayReport(applied=applied, skipped_noop=tuple(skipped))


class EvidenceStore:
    """Read and write the evidence document for one dataset.

    Single-writer assumption: at most one process writes a dataset's evidence
    at a time. A second writer fails with :class:`EvidenceBusyError` rather than
    overwriting the first writer's document.
    """

    def __init__(self, artifacts_dir: Path, dataset_id: str) -> None:
        self.artifacts_dir = Path(artifacts_dir)
        self.dataset_id = dataset_id
        self.path = evidence_path(self.artifacts_dir, dataset_id)
        self.lock_path = self.path.parent / (self.path.name + _LOCK_SUFFIX)

    def exists(self) -> bool:
        """Return whether evidence already exists for this dataset."""
        return self.path.is_file()

    def load_payload(self) -> dict[str, Any] | None:
        """Return the validated document, or ``None`` when none exists yet.

        Raises
        ------
        EvidenceCorruptError
            When the file is not valid JSON.
        EvidenceSchemaError
            When the document is incompatible or structurally invalid.
        """
        if not self.path.is_file():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise EvidenceCorruptError(f"could not read {self.path}: {exc}") from exc
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvidenceCorruptError(f"{self.path} is not valid JSON: {exc}") from exc
        return _validate_document(decoded, self.dataset_id)

    def load(self, record: CanonicalDatasetRecord) -> ReplayReport | None:
        """Rehydrate ``record`` from stored evidence; ``None`` when none exists."""
        payload = self.load_payload()
        if payload is None:
            return None
        if record.dataset_id != self.dataset_id:
            raise EvidenceSchemaError(
                f"record is {record.dataset_id!r} but the store holds {self.dataset_id!r}"
            )
        return rehydrate(record, payload)

    def save(
        self,
        record: CanonicalDatasetRecord,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> Path:
        """Write the record's state atomically, preserving unrelated sections.

        Parameters
        ----------
        record:
            The record whose axes and histories are written.
        extra:
            Sections to set, for example a resource-provenance block or an
            appended authorization trail.

        Returns
        -------
        Path
            The evidence document path.

        Raises
        ------
        EvidenceBusyError
            When another writer holds the lock.
        EvidenceError
            When the existing document is unreadable (never silently discarded).
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        try:
            existing = self.load_payload() if self.path.is_file() else None
            document = build_document(record, existing=existing, extra=extra)
            self._write_atomically(document)
        finally:
            self._release_lock()
        return self.path

    def _acquire_lock(self) -> None:
        """Create the lock file exclusively, or fail loudly."""
        try:
            handle = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise EvidenceBusyError(
                f"another writer holds {self.lock_path}; this pilot assumes a single writer "
                f"(remove the lock only if no writer is running)"
            ) from exc
        except OSError as exc:  # pragma: no cover - unexpected filesystem failure
            raise EvidenceError(f"could not create lock {self.lock_path}: {exc}") from exc
        os.close(handle)

    def _release_lock(self) -> None:
        """Remove the lock file, ignoring an already-vanished lock."""
        self.lock_path.unlink(missing_ok=True)

    def _write_atomically(self, document: Mapping[str, Any]) -> None:
        """Write ``document`` via a temporary file plus atomic replacement."""
        tmp_path = (
            self.path.parent
            / f"{self.path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}{_TMP_SUFFIX}"
        )
        try:
            with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, indent=2, sort_keys=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise EvidenceError(f"could not write evidence {self.path}: {exc}") from exc


def append_section(items: Iterable[Any] | None, *new_items: Any) -> list[Any]:
    """Return ``items`` plus ``new_items`` as a list, for use with ``extra``."""
    collected = list(items or [])
    collected.extend(new_items)
    return collected


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "EvidenceBusyError",
    "EvidenceCorruptError",
    "EvidenceError",
    "EvidenceSchemaError",
    "EvidenceStore",
    "ReplayReport",
    "append_section",
    "build_document",
    "evidence_dir",
    "evidence_path",
    "rehydrate",
    "serialize_record",
]
