"""Tests for the canonical dataset metadata model.

Covers the four-axis status model: permitted transitions, invalid transitions,
the validation evidence gate, failed validation, partial profiling, and
revalidation after an artifact changes.

No network, no datasets, no GPU: every artifact here is a synthetic byte
string created inside pytest's tmp_path.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from civicmind.ingestion import (
    ACQUISITION_STATE_TRANSITIONS,
    CANONICAL_DATASET_IDS,
    PROFILING_STATE_TRANSITIONS,
    RESEARCH_DECISION_TRANSITIONS,
    VALIDATION_STATE_TRANSITIONS,
    AcquisitionState,
    ArtifactVersion,
    CanonicalDatasetRecord,
    EvidenceSource,
    InvalidTransitionError,
    MissingEvidenceError,
    ProfilingEvent,
    ProfilingState,
    ProvenanceRecord,
    QualityIssue,
    ResearchDecision,
    ResearchReview,
    ResearchStatus,
    SourceReliability,
    ValidationEvidence,
    ValidationReport,
    ValidationState,
    ensure_transition,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


# -- helpers ---------------------------------------------------------------


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _provenance(source_id: str, checksum: str, size: int) -> ProvenanceRecord:
    return ProvenanceRecord(
        source_id=source_id,
        title="Test source",
        publisher="Test publisher",
        license="CC0-1.0",
        source_uri="https://example.invalid/data",
        acquired_at=NOW,
        acquisition_method="test-fixture",
        local_path=f"data/raw/{source_id.lower()}/snapshot.csv",
        checksum_sha256=checksum,
        byte_size=size,
        handler="tests.test_metadata.DummyHandler",
        handler_version="1.0",
        civicmind_version="0.1.0",
    )


def _artifact(
    tmp_path: Path,
    record: CanonicalDatasetRecord,
    *,
    version: int = 1,
    payload: bytes = b"id,value\n1,2\n",
) -> ArtifactVersion:
    checksum = _sha(payload)
    target = tmp_path / f"{record.dataset_id.lower()}-v{version}.csv"
    target.write_bytes(payload)
    return ArtifactVersion(
        version=version,
        path=target,
        byte_size=len(payload),
        checksum_sha256=checksum,
        acquired_at=NOW + timedelta(days=version),
        provenance=_provenance(record.dataset_id, checksum, len(payload)),
        method="test-fixture",
    )


def _record(dataset_id: str = "TRF-001", **kwargs: object) -> CanonicalDatasetRecord:
    return CanonicalDatasetRecord(
        dataset_id=dataset_id,
        title="Traffic Accidents in India (Smart Cities)",
        domain="Traffic/Mobility",
        publisher="Smart Cities Mission (via OpenCity)",
        **kwargs,  # type: ignore[arg-type]
    )


def _passing_report(record: CanonicalDatasetRecord) -> ValidationReport:
    return ValidationReport(source_id=record.dataset_id, passed=True, checked_at=NOW)


def _failing_report(record: CanonicalDatasetRecord) -> ValidationReport:
    return ValidationReport(
        source_id=record.dataset_id,
        passed=False,
        issues=(
            QualityIssue(severity="error", code="empty_file", message="no rows found"),
            QualityIssue(severity="warning", code="odd_header", message="unexpected column"),
        ),
        checked_at=NOW,
    )


def _downloaded(tmp_path: Path, **kwargs: object) -> CanonicalDatasetRecord:
    record = _record(**kwargs)  # type: ignore[arg-type]
    record.record_artifact(_artifact(tmp_path, record))
    return record


# -- vocabularies ----------------------------------------------------------


class TestVocabularies:
    """The implemented vocabularies must match the documented model exactly."""

    def test_axis_value_sets(self) -> None:
        assert {state.value for state in ResearchDecision} == {
            "KEEP",
            "KEEP_WITH_CHUNKING",
            "CONDITIONAL",
            "REPLACE",
            "REJECT",
        }
        assert {state.value for state in AcquisitionState} == {
            "METADATA_ONLY",
            "DOWNLOADED",
            "BLOCKED",
            "SUPERSEDED",
        }
        assert {state.value for state in ValidationState} == {
            "NOT_VALIDATED",
            "VALIDATION_FAILED",
            "VALIDATED",
        }
        assert {state.value for state in ProfilingState} == {
            "NOT_PROFILED",
            "SCHEMA_ONLY",
            "PARTIALLY_PROFILED",
            "PROFILED",
        }

    def test_research_vocabularies_match_sources(self) -> None:
        """Enum values are quoted from the workbooks, not invented."""
        assert {s.value for s in ResearchStatus} == {
            "ACQUIRED",
            "VERIFIED",
            "CANDIDATE",
            "REJECTED",
        }
        assert {s.value for s in SourceReliability} == {"VERY_HIGH", "HIGH", "MEDIUM"}

    def test_all_21_canonical_ids_present_including_wtr_005(self) -> None:
        assert len(CANONICAL_DATASET_IDS) == 21
        assert "WTR-005" in CANONICAL_DATASET_IDS

    def test_trf_006_is_not_catalogued(self) -> None:
        """C-13: a dangling reference never becomes a record."""
        assert "TRF-006" not in CANONICAL_DATASET_IDS

    def test_transition_tables_are_total(self) -> None:
        """Every state in every axis has an entry in its transition table."""
        for table, axis_type in (
            (RESEARCH_DECISION_TRANSITIONS, ResearchDecision),
            (ACQUISITION_STATE_TRANSITIONS, AcquisitionState),
            (VALIDATION_STATE_TRANSITIONS, ValidationState),
            (PROFILING_STATE_TRANSITIONS, ProfilingState),
        ):
            assert set(table) == set(axis_type)

    def test_ensure_transition_allows_and_rejects(self) -> None:
        ensure_transition("research_decision", ResearchDecision.CONDITIONAL, ResearchDecision.KEEP)
        with pytest.raises(InvalidTransitionError, match="not permitted"):
            ensure_transition("research_decision", ResearchDecision.KEEP, ResearchDecision.REJECT)
        with pytest.raises(InvalidTransitionError, match="no-op"):
            ensure_transition("research_decision", ResearchDecision.KEEP, ResearchDecision.KEEP)


# -- record construction ---------------------------------------------------


class TestRecordConstruction:
    def test_defaults_are_conservative(self) -> None:
        record = _record()
        assert record.research_decision is ResearchDecision.CONDITIONAL
        assert record.acquisition_state is AcquisitionState.METADATA_ONLY
        assert record.validation_state is ValidationState.NOT_VALIDATED
        assert record.profiling_state is ProfilingState.NOT_PROFILED

    def test_invalid_dataset_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="dataset_id"):
            _record(dataset_id="trf-001")
        with pytest.raises(ValueError, match="dataset_id"):
            _record(dataset_id="TRF-1")

    def test_blank_title_rejected(self) -> None:
        with pytest.raises(ValueError, match="title"):
            CanonicalDatasetRecord(dataset_id="TRF-001", title="   ")

    def test_negative_measurements_rejected(self) -> None:
        with pytest.raises(ValueError, match="record_count"):
            _record(record_count=-1)
        with pytest.raises(ValueError, match="file_size"):
            _record(file_size=-5)

    def test_unknown_values_stay_none(self) -> None:
        """The model never invents a measurement."""
        record = _record()
        assert record.record_count is None
        assert record.file_size is None
        assert record.acquired_at is None
        assert record.license == "UNKNOWN"
        assert record.temporal_coverage == "UNKNOWN"
        assert record.license_verified is False


# -- artifact version ------------------------------------------------------


class TestArtifactVersion:
    def test_valid_artifact_accepted(self, tmp_path: Path) -> None:
        record = _record()
        artifact = _artifact(tmp_path, record)
        assert artifact.version == 1
        assert artifact.is_active
        assert artifact.byte_size > 0

    @pytest.mark.parametrize(
        ("field_name", "value", "match"),
        [
            ("version", 0, "version"),
            ("byte_size", 0, "byte_size"),
            ("checksum_sha256", "not-a-hash", "checksum"),
            ("checksum_sha256", "A" * 64, "checksum"),  # uppercase rejected
        ],
    )
    def test_invalid_artifact_fields_rejected(
        self, tmp_path: Path, field_name: str, value: object, match: str
    ) -> None:
        record = _record()
        artifact = _artifact(tmp_path, record)
        with pytest.raises(ValueError, match=match):
            ArtifactVersion(
                version=artifact.version if field_name != "version" else int(value),  # type: ignore[arg-type]
                path=artifact.path,
                byte_size=artifact.byte_size if field_name != "byte_size" else int(value),  # type: ignore[arg-type]
                checksum_sha256=(
                    artifact.checksum_sha256 if field_name != "checksum_sha256" else str(value)
                ),
                acquired_at=artifact.acquired_at,
                provenance=artifact.provenance,
            )

    def test_naive_timestamp_rejected(self, tmp_path: Path) -> None:
        record = _record()
        artifact = _artifact(tmp_path, record)
        with pytest.raises(ValueError, match="timezone-aware"):
            ArtifactVersion(
                version=1,
                path=artifact.path,
                byte_size=artifact.byte_size,
                checksum_sha256=artifact.checksum_sha256,
                acquired_at=datetime(2026, 1, 1),  # naive
                provenance=artifact.provenance,
            )


# -- axis 1: research decision --------------------------------------------


class TestResearchDecisionAxis:
    def test_conditional_to_keep(self) -> None:
        record = _record()
        record.record_research_review(
            ResearchReview(ResearchDecision.KEEP, "schema confirmed", NOW)
        )
        assert record.research_decision is ResearchDecision.KEEP
        assert len(record.review_history) == 1

    @pytest.mark.parametrize(
        ("start", "target"),
        [
            (ResearchDecision.CONDITIONAL, ResearchDecision.KEEP),
            (ResearchDecision.CONDITIONAL, ResearchDecision.KEEP_WITH_CHUNKING),
            (ResearchDecision.CONDITIONAL, ResearchDecision.REJECT),
            (ResearchDecision.KEEP, ResearchDecision.KEEP_WITH_CHUNKING),
            (ResearchDecision.KEEP_WITH_CHUNKING, ResearchDecision.KEEP),
            (ResearchDecision.REJECT, ResearchDecision.CONDITIONAL),
        ],
    )
    def test_permitted_transitions(self, start: ResearchDecision, target: ResearchDecision) -> None:
        record = _record()
        record._research_decision = start  # set up the starting state directly
        record.record_research_review(ResearchReview(target, "reviewed", NOW))
        assert record.research_decision is target

    @pytest.mark.parametrize(
        ("start", "target"),
        [
            (ResearchDecision.KEEP, ResearchDecision.REJECT),
            (ResearchDecision.REPLACE, ResearchDecision.KEEP),
            # REJECT may only return to CONDITIONAL, never straight to KEEP:
            (ResearchDecision.REJECT, ResearchDecision.KEEP),
        ],
    )
    def test_invalid_transitions_rejected(
        self, start: ResearchDecision, target: ResearchDecision
    ) -> None:
        record = _record()
        record._research_decision = start
        with pytest.raises(InvalidTransitionError, match="research_decision"):
            record.record_research_review(ResearchReview(target, "reviewed", NOW))

    def test_replace_requires_replacement_target(self) -> None:
        with pytest.raises(ValueError, match="replacement_target"):
            ResearchReview(ResearchDecision.REPLACE, "superseded", NOW)

    def test_replacement_target_only_with_replace(self) -> None:
        with pytest.raises(ValueError, match="only valid with REPLACE"):
            ResearchReview(ResearchDecision.KEEP, "keep", NOW, replacement_target="WTR-005")

    def test_rationale_is_mandatory(self) -> None:
        with pytest.raises(ValueError, match="rationale"):
            ResearchReview(ResearchDecision.KEEP, "   ", NOW)

    def test_replace_does_not_touch_acquisition_axis(self) -> None:
        """WTR-001: REPLACE (axis 1) never implies SUPERSEDED (axis 2)."""
        record = _record(dataset_id="WTR-001")
        record.record_research_review(
            ResearchReview(ResearchDecision.REPLACE, "superseded by BWSSB", NOW, "WTR-005")
        )
        assert record.replacement_target == "WTR-005"
        assert record.acquisition_state is AcquisitionState.METADATA_ONLY
        assert record.superseded_by is None


# -- axis 2: acquisition ---------------------------------------------------


class TestAcquisitionAxis:
    def test_record_artifact_advances_to_downloaded(self, tmp_path: Path) -> None:
        record = _record()
        record.record_artifact(_artifact(tmp_path, record))
        assert record.acquisition_state is AcquisitionState.DOWNLOADED
        assert record.active_artifact is not None
        assert record.acquired_at is not None

    def test_blocked_requires_reason(self) -> None:
        record = _record()
        with pytest.raises(ValueError, match="reason"):
            record.mark_blocked("   ")
        record.mark_blocked("bot-detection blocks automated access")
        assert record.acquisition_state is AcquisitionState.BLOCKED
        assert record.blocker_reason == "bot-detection blocks automated access"

    def test_blocked_round_trip(self) -> None:
        record = _record()
        record.mark_blocked("no bulk API")
        record.clear_blocker()
        assert record.acquisition_state is AcquisitionState.METADATA_ONLY
        assert record.blocker_reason is None

    def test_clearing_blocker_returns_to_metadata_only(self) -> None:
        """Clearing a blocker does not fabricate bytes: no download is implied."""
        record = _record()
        record.mark_blocked("no bulk API")
        record.clear_blocker()
        assert record.acquisition_state is AcquisitionState.METADATA_ONLY
        assert record.blocker_reason is None

    def test_blocked_record_can_then_download(self, tmp_path: Path) -> None:
        record = _record()
        record.mark_blocked("no bulk API")
        record.clear_blocker()
        record.record_artifact(_artifact(tmp_path, record))
        assert record.acquisition_state is AcquisitionState.DOWNLOADED

    def test_superseded_records_provenance_and_is_terminal(self, tmp_path: Path) -> None:
        record = _record(dataset_id="ENV-003")
        record.record_artifact(_artifact(tmp_path, record))
        record.mark_superseded("ENV-003-2026", "newer citywide snapshot")
        assert record.acquisition_state is AcquisitionState.SUPERSEDED
        assert record.superseded_by == "ENV-003-2026"
        with pytest.raises(InvalidTransitionError, match="terminal"):
            record.record_artifact(_artifact(tmp_path, record, version=2))

    def test_superseded_requires_reason(self) -> None:
        record = _record()
        with pytest.raises(ValueError, match="non-empty"):
            record.mark_superseded("", "")

    def test_superseded_does_not_touch_research_decision(self) -> None:
        """Newer snapshot (axis 2 SUPERSEDED) leaves axis 1 at KEEP."""
        record = _record(dataset_id="ENV-003")
        record.record_research_review(
            ResearchReview(ResearchDecision.KEEP, "useful green-cover data", NOW)
        )
        record.mark_superseded("ENV-003-2026", "newer snapshot")
        assert record.research_decision is ResearchDecision.KEEP
        assert record.replacement_target is None

    def test_axes_are_not_writable_from_outside(self) -> None:
        record = _record()
        with pytest.raises(AttributeError):
            record.acquisition_state = AcquisitionState.DOWNLOADED  # type: ignore[misc]


# -- supersession invalidates current validation/profiling -----------------


class TestSupersessionInvalidation:
    """Superseding bytes must not keep claiming VALIDATED/PROFILED.

    Regression test for the Milestone 3 review: a SUPERSEDED record previously
    retained ``VALIDATED``/``PROFILED`` for bytes that must not be used,
    contradicting the standing cross-axis rule that ``VALIDATED`` requires
    axis 2 = ``DOWNLOADED``.
    """

    def test_supersede_after_validation_resets_validation_state(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_validation(_passing_report(record), scope="all resources")
        assert record.validation_state is ValidationState.VALIDATED

        record.mark_superseded("ENV-003-2026", "newer citywide snapshot")

        assert record.acquisition_state is AcquisitionState.SUPERSEDED
        assert record.validation_state is ValidationState.NOT_VALIDATED

    def test_supersede_after_profiling_resets_profiling_state(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="3 of 7 resources",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )
        assert record.profiling_state is ProfilingState.PARTIALLY_PROFILED

        record.mark_superseded("ENV-003-2026", "newer citywide snapshot")

        assert record.profiling_state is ProfilingState.NOT_PROFILED

    def test_supersede_preserves_history(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_validation(_passing_report(record), scope="all resources")
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="3 of 7 resources",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )

        record.mark_superseded("ENV-003-2026", "newer citywide snapshot")

        # states reset, but history is retained, not deleted
        assert len(record.validation_history) == 1
        assert record.validation_history[0].passed is True
        assert len(record.profiling_history) == 2
        assert record.profiling_history[-1].state is ProfilingState.PARTIALLY_PROFILED
        # artifact-version and supersession history stay consistent
        assert len(record.artifacts) == 1
        assert record.superseded_by == "ENV-003-2026"

    def test_supersede_does_not_touch_research_decision(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_research_review(
            ResearchReview(ResearchDecision.KEEP, "useful green-cover data", NOW)
        )
        record.record_validation(_passing_report(record), scope="all resources")

        record.mark_superseded("ENV-003-2026", "newer snapshot")

        assert record.research_decision is ResearchDecision.KEEP
        assert record.acquisition_state is AcquisitionState.SUPERSEDED

    def test_supersede_retains_schema_only_profiling(self, tmp_path: Path) -> None:
        """SCHEMA_ONLY is documentation-derived, so it survives supersession."""
        record = _downloaded(tmp_path)
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema from docs",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )

        record.mark_superseded("ENV-003-2026", "newer snapshot")

        assert record.profiling_state is ProfilingState.SCHEMA_ONLY

    def test_repeated_supersession_is_rejected(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.mark_superseded("ENV-003-2026", "newer citywide snapshot")
        # SUPERSEDED is terminal; re-superseding is a no-op and is rejected.
        with pytest.raises(InvalidTransitionError, match="no-op"):
            record.mark_superseded("ENV-003-2027", "an even newer snapshot")

    def test_supersede_requires_non_empty_reason_and_target(self) -> None:
        record = _record()
        with pytest.raises(ValueError, match="non-empty"):
            record.mark_superseded("   ", "reason")
        with pytest.raises(ValueError, match="non-empty"):
            record.mark_superseded("ENV-003-2026", "   ")


# -- axis 3: validation and the evidence gate ------------------------------


class TestValidationEvidenceGate:
    def test_full_evidence_reaches_validated(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        assert record.validation_evidence.complete
        event = record.record_validation(_passing_report(record), scope="all resources")
        assert record.validation_state is ValidationState.VALIDATED
        assert event.passed is True
        assert event.scope == "all resources"

    def test_file_alone_is_not_enough(self) -> None:
        """No artifact at all: the gate names every missing piece."""
        record = _record()
        evidence = record.validation_evidence
        assert evidence.complete is False
        assert set(evidence.missing) == {
            "artifact",
            "byte_size",
            "checksum_sha256",
            "acquired_at",
            "provenance",
        }

    @pytest.mark.parametrize(
        ("evidence", "missing"),
        [
            (ValidationEvidence(False, 10, "a" * 64, NOW, None), "provenance"),
            (ValidationEvidence(True, None, "a" * 64, NOW, None), "byte_size"),
            (ValidationEvidence(True, 10, None, NOW, None), "checksum_sha256"),
            (ValidationEvidence(True, 10, "a" * 64, None, None), "acquired_at"),
            (ValidationEvidence(False, None, None, None, None), "artifact"),
        ],
    )
    def test_each_missing_piece_is_named(self, evidence: ValidationEvidence, missing: str) -> None:
        """The gate names exactly what is absent, so the gap is actionable."""
        assert missing in evidence.missing
        assert evidence.complete is False

    def test_complete_evidence_is_accepted(self) -> None:
        provenance = _provenance("TRF-001", "a" * 64, 10)
        evidence = ValidationEvidence(True, 10, "a" * 64, NOW, provenance)
        assert evidence.missing == ()
        assert evidence.complete is True

    def test_passing_report_without_artifact_raises(self) -> None:
        record = _record()
        with pytest.raises(MissingEvidenceError, match="artifact"):
            record.record_validation(_passing_report(record), scope="all resources")
        assert record.validation_state is ValidationState.NOT_VALIDATED

    def test_incomplete_evidence_blocks_validation(self, tmp_path: Path) -> None:
        """An artifact whose provenance link is gone cannot reach VALIDATED."""
        record = _record()
        artifact = _artifact(tmp_path, record)
        # simulate an artifact recorded before provenance capture existed
        object.__setattr__(artifact, "provenance", None)  # type: ignore[arg-type]
        record.record_artifact(artifact)

        assert "provenance" in record.validation_evidence.missing
        with pytest.raises(MissingEvidenceError, match="provenance"):
            record.record_validation(_passing_report(record), scope="all resources")
        assert record.validation_state is ValidationState.NOT_VALIDATED

    def test_error_issue_forces_failure_even_if_passed_flag_true(self, tmp_path: Path) -> None:
        """A report claiming 'passed' but carrying an error issue is a failure."""
        record = _downloaded(tmp_path)
        contradictory = ValidationReport(
            source_id=record.dataset_id,
            passed=True,
            issues=(QualityIssue(severity="error", code="dup_keys", message="duplicate ids"),),
            checked_at=NOW,
        )
        record.record_validation(contradictory, scope="all resources")
        assert record.validation_state is ValidationState.VALIDATION_FAILED

    def test_report_for_other_dataset_rejected(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        other = ValidationReport(source_id="CIT-003", passed=True, checked_at=NOW)
        with pytest.raises(ValueError, match="record is"):
            record.record_validation(other, scope="all resources")


class TestFailedValidation:
    def test_failed_validation_keeps_bytes_and_issues(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        event = record.record_validation(_failing_report(record), scope="all resources")

        assert record.validation_state is ValidationState.VALIDATION_FAILED
        assert record.acquisition_state is AcquisitionState.DOWNLOADED  # bytes kept
        assert event.passed is False
        assert [issue.code for issue in event.report.issues] == ["empty_file", "odd_header"]

    def test_failed_then_passing_reaches_validated(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_validation(_failing_report(record), scope="all resources")
        record.record_validation(_passing_report(record), scope="all resources")

        assert record.validation_state is ValidationState.VALIDATED
        assert len(record.validation_history) == 2
        assert record.validation_history[0].passed is False

    def test_failed_rerun_after_validated_is_recorded(self, tmp_path: Path) -> None:
        """A re-run that fails must be recorded honestly, not hidden."""
        record = _downloaded(tmp_path)
        record.record_validation(_passing_report(record), scope="all resources")
        record.record_validation(_failing_report(record), scope="all resources")

        assert record.validation_state is ValidationState.VALIDATION_FAILED
        assert len(record.validation_history) == 2

    def test_scope_is_mandatory(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        with pytest.raises(ValueError, match="scope"):
            record.record_validation(_passing_report(record), scope="  ")


# -- axis 4: profiling -----------------------------------------------------


class TestProfilingAxis:
    def test_schema_only_from_documentation(self) -> None:
        record = _record(dataset_id="ENV-001")
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="9 fields cross-confirmed by secondary sources",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        assert record.profiling_state is ProfilingState.SCHEMA_ONLY
        assert record.acquisition_state is AcquisitionState.METADATA_ONLY

    def test_schema_only_cannot_claim_measurement(self) -> None:
        with pytest.raises(ValueError, match="DOCUMENTATION"):
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )

    def test_measured_profiling_requires_artifact_version(self) -> None:
        with pytest.raises(ValueError, match="artifact_version"):
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="3 of 7 resources",
                evidence=EvidenceSource.MEASURED,
                artifact_version=None,
                recorded_at=NOW,
            )

    def test_measured_profiling_requires_downloaded(self) -> None:
        record = _record()
        with pytest.raises(MissingEvidenceError, match="acquisition_state"):
            record.record_profiling(
                ProfilingEvent(
                    state=ProfilingState.PARTIALLY_PROFILED,
                    scope="1 of 6 yearly files",
                    evidence=EvidenceSource.MEASURED,
                    artifact_version=1,
                    recorded_at=NOW,
                )
            )

    def test_partial_profiling_carries_scope(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="header confirmed from documentation",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="3 of 7 resources",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )
        assert record.profiling_state is ProfilingState.PARTIALLY_PROFILED
        assert record.profiling_history[-1].scope == "3 of 7 resources"

    def test_ladder_is_forward_only(self, tmp_path: Path) -> None:
        """The ladder only climbs: a backward step is rejected at the gate.

        We advance to PARTIALLY_PROFILED, then attempt a *constructible*
        step back to SCHEMA_ONLY. (NOT_PROFILED cannot even be built as an
        event - see test_not_profiled_is_not_a_recordable_event - so it is
        not usable to probe the transition gate.)
        """
        record = _downloaded(tmp_path)
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="1 of 6 yearly files",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )
        assert record.profiling_state is ProfilingState.PARTIALLY_PROFILED

        with pytest.raises(InvalidTransitionError, match="profiling_state"):
            record.record_profiling(
                ProfilingEvent(
                    state=ProfilingState.SCHEMA_ONLY,
                    scope="rewind",
                    evidence=EvidenceSource.DOCUMENTATION,
                    artifact_version=None,
                    recorded_at=NOW,
                )
            )
        # the rejected step did not move the axis
        assert record.profiling_state is ProfilingState.PARTIALLY_PROFILED

    def test_partial_to_full_profiled(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="3 of 7 resources",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PROFILED,
                scope="all 7 resources",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )
        assert record.profiling_state is ProfilingState.PROFILED

    def test_profiled_does_not_imply_validated(self, tmp_path: Path) -> None:
        """The two axes are independent: fully profiled, never validated."""
        record = _downloaded(tmp_path)
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="3 of 7 resources",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PROFILED,
                scope="all resources",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )
        assert record.profiling_state is ProfilingState.PROFILED
        assert record.validation_state is ValidationState.NOT_VALIDATED

    def test_validated_does_not_imply_profiled(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_validation(_passing_report(record), scope="all resources")
        assert record.validation_state is ValidationState.VALIDATED
        assert record.profiling_state is ProfilingState.NOT_PROFILED

    def test_not_profiled_is_not_a_recordable_event(self) -> None:
        with pytest.raises(ValueError, match="NOT_PROFILED"):
            ProfilingEvent(
                state=ProfilingState.NOT_PROFILED,
                scope="n/a",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )


# -- artifact version history and revalidation -----------------------------


class TestArtifactVersionHistory:
    def test_revalidation_after_artifact_changes(self, tmp_path: Path) -> None:
        """A new checksum invalidates validation and profiling; history stays."""
        record = _downloaded(tmp_path)
        record.record_validation(_passing_report(record), scope="all resources")
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="1 of 6 files",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )
        assert record.validation_state is ValidationState.VALIDATED

        record.record_artifact(_artifact(tmp_path, record, version=2, payload=b"id,value\n2,3\n"))

        assert record.validation_state is ValidationState.NOT_VALIDATED
        assert record.profiling_state is ProfilingState.NOT_PROFILED
        # history retained, not deleted
        assert len(record.validation_history) == 1
        assert record.validation_history[0].passed is True
        assert len(record.profiling_history) == 2
        # artifact history: v1 superseded, v2 active
        assert len(record.artifacts) == 2
        assert record.artifacts[0].is_active is False
        assert record.artifacts[0].superseded_reason is not None
        assert record.active_artifact is not None and record.active_artifact.version == 2

    def test_revalidation_after_change_reaches_validated_again(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_validation(_passing_report(record), scope="all resources")
        record.record_artifact(_artifact(tmp_path, record, version=2, payload=b"x,y\n9,9\n"))

        assert record.validation_state is ValidationState.NOT_VALIDATED
        record.record_validation(_passing_report(record), scope="all resources")
        assert record.validation_state is ValidationState.VALIDATED

    def test_identical_redownload_does_not_regress(self, tmp_path: Path) -> None:
        """Re-downloading identical bytes keeps validation intact."""
        record = _downloaded(tmp_path)
        record.record_validation(_passing_report(record), scope="all resources")
        record.record_artifact(_artifact(tmp_path, record, version=2))  # same payload

        assert record.validation_state is ValidationState.VALIDATED
        assert record.acquisition_state is AcquisitionState.DOWNLOADED
        assert len(record.artifacts) == 2
        assert record.artifacts[0].superseded_reason == "re-downloaded; identical checksum"

    def test_versions_must_strictly_increase(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        with pytest.raises(ValueError, match="strictly increase"):
            record.record_artifact(_artifact(tmp_path, record, version=1, payload=b"other\n"))

    def test_failed_validation_survives_until_new_artifact(self, tmp_path: Path) -> None:
        record = _downloaded(tmp_path)
        record.record_validation(_failing_report(record), scope="all resources")
        assert record.validation_state is ValidationState.VALIDATION_FAILED

        record.record_artifact(_artifact(tmp_path, record, version=2, payload=b"a,b\n3,4\n"))
        assert record.validation_state is ValidationState.NOT_VALIDATED
        assert record.validation_history[0].passed is False


# -- end-to-end workflow ---------------------------------------------------


class TestWorkflow:
    def test_full_lifecycle(self, tmp_path: Path) -> None:
        """KEEP -> download -> validate -> partial profile, as the plan describes."""
        record = _record(dataset_id="TRF-001")
        record.record_research_review(ResearchReview(ResearchDecision.KEEP, "small, official", NOW))
        record.record_artifact(_artifact(tmp_path, record))
        record.record_validation(_passing_report(record), scope="single CSV")
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="3 columns from data dictionary",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.PARTIALLY_PROFILED,
                scope="row count measured; missingness pending",
                evidence=EvidenceSource.MEASURED,
                artifact_version=1,
                recorded_at=NOW,
            )
        )

        assert record.research_decision is ResearchDecision.KEEP
        assert record.acquisition_state is AcquisitionState.DOWNLOADED
        assert record.validation_state is ValidationState.VALIDATED
        assert record.profiling_state is ProfilingState.PARTIALLY_PROFILED

    def test_env_001_shape(self) -> None:
        """KEEP + BLOCKED + NOT_VALIDATED + SCHEMA_ONLY (audit worked example)."""
        record = _record(dataset_id="ENV-001")
        record.record_research_review(ResearchReview(ResearchDecision.KEEP, "highest value", NOW))
        record.mark_blocked("requires a registered data.gov.in API key")
        record.record_profiling(
            ProfilingEvent(
                state=ProfilingState.SCHEMA_ONLY,
                scope="schema cross-confirmed by secondary sources",
                evidence=EvidenceSource.DOCUMENTATION,
                artifact_version=None,
                recorded_at=NOW,
            )
        )

        assert record.research_decision is ResearchDecision.KEEP
        assert record.acquisition_state is AcquisitionState.BLOCKED
        assert record.validation_state is ValidationState.NOT_VALIDATED
        assert record.profiling_state is ProfilingState.SCHEMA_ONLY

    def test_wtr_001_shape(self) -> None:
        """REPLACE + METADATA_ONLY (never acquired, so never SUPERSEDED)."""
        record = _record(dataset_id="WTR-001")
        record.record_research_review(
            ResearchReview(ResearchDecision.REPLACE, "no API exists", NOW, "WTR-005")
        )
        record.mark_blocked("data.gov.in states no API exists for this resource")

        assert record.research_decision is ResearchDecision.REPLACE
        assert record.replacement_target == "WTR-005"
        assert record.acquisition_state is AcquisitionState.BLOCKED
        assert record.superseded_by is None
