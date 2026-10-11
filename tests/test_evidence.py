"""Tests for the versioned, persistent evidence store.

Everything here is local and deterministic: no network, no sleeps, and every
path lives under ``tmp_path``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from civicmind import __version__
from civicmind.ingestion.base import ProvenanceRecord, QualityIssue, ValidationReport
from civicmind.ingestion.evidence import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceBusyError,
    EvidenceCorruptError,
    EvidenceSchemaError,
    EvidenceStore,
    build_document,
    evidence_path,
)
from civicmind.ingestion.exceptions import InvalidTransitionError
from civicmind.ingestion.metadata import (
    ArtifactVersion,
    CanonicalDatasetRecord,
    EvidenceSource,
    ProfilingEvent,
    ResearchReview,
)
from civicmind.ingestion.states import ProfilingState, ResearchDecision

DATASET_ID = "TRF-001"
CHECKSUM_A = "a" * 64
CHECKSUM_B = "b" * 64
BASE_TIME = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def _provenance(checksum: str = CHECKSUM_A, acquired_at: datetime = BASE_TIME) -> ProvenanceRecord:
    """Return a provenance record shaped like the TRF-001 handler's output."""
    return ProvenanceRecord(
        source_id=DATASET_ID,
        title="Traffic Accidents in India (Smart Cities)",
        publisher=(
            "Smart Cities Mission, Ministry of Housing & Urban Affairs (via OpenCity mirror)"
        ),
        license="Other (Public Domain) / Open Data",
        source_uri="https://example.invalid/resource.csv",
        acquired_at=acquired_at,
        acquisition_method="https-get",
        local_path="data/raw/TRF-001/artifact.csv",
        checksum_sha256=checksum,
        byte_size=377,
        handler="civicmind.ingestion.handlers.trf_001.Trf001Ingestor",
        handler_version="1.0",
        civicmind_version=__version__,
    )


def _artifact(
    version: int = 1,
    *,
    checksum: str = CHECKSUM_A,
    acquired_at: datetime = BASE_TIME,
    path: str = "data/raw/TRF-001/artifact.csv",
) -> ArtifactVersion:
    """Return one artifact version."""
    return ArtifactVersion(
        version=version,
        path=Path(path),
        byte_size=377,
        checksum_sha256=checksum,
        acquired_at=acquired_at,
        provenance=_provenance(checksum, acquired_at),
        method="https-get",
    )


def _record() -> CanonicalDatasetRecord:
    """Return a fresh canonical record with conservative defaults."""
    return CanonicalDatasetRecord(dataset_id=DATASET_ID, title="Traffic Accidents in India")


def _store(tmp_path: Path) -> EvidenceStore:
    """Return a store rooted under ``tmp_path``."""
    return EvidenceStore(tmp_path / "artifacts", DATASET_ID)


def _passing_report() -> ValidationReport:
    """Return a passing validation report for the canonical dataset id."""
    return ValidationReport(
        source_id=DATASET_ID,
        passed=True,
        issues=(
            QualityIssue(
                severity="info",
                code="SCHEMA_NOT_ASSERTED",
                message="no required-column rule is asserted",
                context={"documented_hints_present": ["City"]},
            ),
        ),
        checked_at=BASE_TIME,
    )


def test_evidence_path_matches_the_documented_location(tmp_path: Path) -> None:
    path = evidence_path(tmp_path / "artifacts", DATASET_ID)

    assert path.as_posix().endswith("artifacts/ingestion/TRF-001/evidence.json")


def test_missing_evidence_is_a_fresh_start_not_an_error(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.exists() is False
    assert store.load_payload() is None
    assert store.load(_record()) is None


def test_round_trip_restores_axes_histories_and_claims(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _record()
    record.record_artifact(_artifact())
    record.record_validation(_passing_report(), scope="single CSV", checked_at=BASE_TIME)
    record.record_profiling(
        ProfilingEvent(
            state=ProfilingState.SCHEMA_ONLY,
            scope="documentation only",
            evidence=EvidenceSource.DOCUMENTATION,
            artifact_version=None,
            recorded_at=BASE_TIME,
        )
    )
    store.save(record)

    restored = _record()
    replay = store.load(restored)

    assert replay is not None
    assert restored.acquisition_state.value == "DOWNLOADED"
    assert restored.validation_state.value == "VALIDATED"
    assert restored.profiling_state.value == "SCHEMA_ONLY"
    assert len(restored.artifacts) == 1
    assert restored.artifacts[0].checksum_sha256 == CHECKSUM_A
    assert restored.artifacts[0].provenance.publisher == record.artifacts[0].provenance.publisher
    assert len(restored.validation_history) == 1
    assert len(restored.profiling_history) == 1
    # Axis 1 is untouched by the other axes.
    assert restored.research_decision is ResearchDecision.CONDITIONAL


def test_save_is_atomic_and_leaves_no_temporary_or_lock_files(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _record()
    record.record_artifact(_artifact())

    store.save(record)

    names = sorted(item.name for item in store.path.parent.iterdir())
    assert names == ["evidence.json"]
    assert store.lock_path.exists() is False


def test_document_records_measured_basis_and_unverified_claims(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _record()
    record.record_artifact(_artifact())

    store.save(record)
    payload = json.loads(store.path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert payload["dataset_id"] == DATASET_ID
    assert payload["artifacts"][0]["basis"] == "measured locally"
    assert payload["claims"]["basis"] == "source claim; not verified locally"
    assert payload["claims"]["license_verified"] is False


def test_load_rejects_malformed_json(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{ this is not json", encoding="utf-8")

    with pytest.raises(EvidenceCorruptError):
        store.load_payload()


def test_load_rejects_a_document_from_another_dataset(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"schema_version": EVIDENCE_SCHEMA_VERSION, "dataset_id": "TRF-002"}),
        encoding="utf-8",
    )

    with pytest.raises(EvidenceSchemaError):
        store.load_payload()


def test_load_rejects_an_unsupported_schema_version(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"schema_version": EVIDENCE_SCHEMA_VERSION + 99, "dataset_id": DATASET_ID}),
        encoding="utf-8",
    )

    with pytest.raises(EvidenceSchemaError):
        store.load_payload()


def test_load_rejects_a_structurally_incomplete_document(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps({"schema_version": EVIDENCE_SCHEMA_VERSION, "dataset_id": DATASET_ID}),
        encoding="utf-8",
    )

    with pytest.raises(EvidenceSchemaError):
        store.load_payload()


def test_save_never_silently_resets_an_incompatible_document(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"schema_version": 999, "dataset_id": DATASET_ID})
    store.path.write_text(original, encoding="utf-8")
    record = _record()
    record.record_artifact(_artifact())

    with pytest.raises(EvidenceSchemaError):
        store.save(record)

    assert store.path.read_text(encoding="utf-8") == original
    assert store.lock_path.exists() is False


def test_a_held_lock_blocks_a_second_writer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.lock_path.write_text("held by another writer", encoding="utf-8")
    record = _record()
    record.record_artifact(_artifact())

    with pytest.raises(EvidenceBusyError):
        store.save(record)

    assert store.path.exists() is False


def test_save_preserves_sections_the_record_cannot_supply(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _record()
    record.record_artifact(_artifact())
    store.save(
        record,
        extra={
            "authorizations": [{"rationale": "pilot acquisition", "recorded_at": "x"}],
            "resource_provenance": {"resource_url": "https://example.invalid/resource.csv"},
        },
    )

    record.record_artifact(_artifact(2, checksum=CHECKSUM_B, acquired_at=BASE_TIME + timedelta(1)))
    store.save(record)
    payload = json.loads(store.path.read_text(encoding="utf-8"))

    assert payload["authorizations"] == [{"rationale": "pilot acquisition", "recorded_at": "x"}]
    assert payload["resource_provenance"]["resource_url"].endswith("resource.csv")
    assert len(payload["artifacts"]) == 2


def test_replay_reports_a_noop_transition_instead_of_forcing_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _record()
    # Two acquisitions of byte-identical content: the second leaves every axis
    # exactly as it was, so it must be reported as skipped, never re-applied.
    record.record_artifact(_artifact(1))
    record.record_artifact(_artifact(2, acquired_at=BASE_TIME + timedelta(minutes=1)))
    store.save(record)

    restored = _record()
    replay = store.load(restored)

    assert replay is not None
    assert replay.applied == 1
    assert replay.skipped_noop == ("artifact[1]",)
    assert len(restored.artifacts) == 2
    assert restored.acquisition_state.value == "DOWNLOADED"


def test_replay_uses_the_records_own_transition_rules(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _record()
    record.record_artifact(_artifact())
    record.record_validation(_passing_report(), scope="single CSV", checked_at=BASE_TIME)
    store.save(record)

    payload = json.loads(store.path.read_text(encoding="utf-8"))
    duplicate = dict(payload["validation_events"][0])
    duplicate["recorded_at"] = (BASE_TIME + timedelta(minutes=5)).isoformat()
    payload["validation_events"].append(duplicate)
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    # Replaying an illegal sequence raises the record's own error rather than
    # forcing the state through.
    with pytest.raises(InvalidTransitionError):
        store.load(_record())


def test_build_document_carries_a_single_writer_note(tmp_path: Path) -> None:
    document = build_document(_record())

    assert document["single_writer"]
    assert document["producer"]["civicmind_version"] == __version__


def test_research_reviews_round_trip_through_the_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = _record()
    record.record_research_review(
        ResearchReview(
            decision=ResearchDecision.KEEP,
            rationale="reviewed after Gate B1",
            reviewed_at=BASE_TIME,
        )
    )
    store.save(record)

    restored = _record()
    store.load(restored)

    assert restored.research_decision is ResearchDecision.KEEP
    assert len(restored.review_history) == 1
    assert restored.review_history[0].rationale == "reviewed after Gate B1"
