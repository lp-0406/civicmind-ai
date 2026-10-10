"""Tests for the canonical dataset registry (:mod:`civicmind.ingestion.catalog`).

Covers registration, lookup, deterministic listing, filtering by research
decision and acquisition state, rejection of duplicate IDs and invalid records,
prevention of mutation through public accessors, and preservation of the 21-ID
canonical set (including WTR-005) with TRF-006 excluded.

No network, no datasets: every record used here is a minimal canonical fixture
built with :class:`CanonicalDatasetRecord`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from civicmind.ingestion.catalog import (
    DatasetRegistry,
    DuplicateDatasetError,
    InvalidDatasetRecordError,
    UnknownDatasetError,
)
from civicmind.ingestion.metadata import (
    CANONICAL_DATASET_IDS,
    AcquisitionState,
    CanonicalDatasetRecord,
    ResearchDecision,
    ResearchReview,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)

# Canonical ID helpers / fixtures -----------------------------------------------

_IDS = sorted(CANONICAL_DATASET_IDS)
assert len(_IDS) == 21
assert "WTR-005" in _IDS
assert "TRF-006" not in _IDS


def _record(dataset_id: str, **kwargs: object) -> CanonicalDatasetRecord:
    defaults: dict[str, object] = {
        "title": f"Canonical dataset {dataset_id}",
        "domain": "Traffic/Mobility",
        "publisher": "Test publisher",
        "license": "UNKNOWN",
        "temporal_coverage": "UNKNOWN",
        "license_verified": False,
        "format": "",
        "record_count": None,
        "file_size": None,
    }
    defaults.update(kwargs)
    return CanonicalDatasetRecord(dataset_id=dataset_id, **defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Registration, lookup, listing
# ---------------------------------------------------------------------------


class TestRegistrationAndLookup:
    def test_register_valid_record(self) -> None:
        registry = DatasetRegistry()
        record = _record("TRF-001")
        returned = registry.register(record)
        assert returned is record
        assert registry.get("TRF-001") is record
        assert "TRF-001" in registry
        assert len(registry) == 1

    def test_register_rejects_non_canonical_record(self) -> None:
        registry = DatasetRegistry()

        class NotCanonical:
            dataset_id = "TRF-001"  # type: ignore[assignment]

        with pytest.raises(InvalidDatasetRecordError, match="CanonicalDatasetRecord"):
            registry.register(NotCanonical())  # type: ignore[arg-type]

    def test_duplicate_registration_rejected(self) -> None:
        registry = DatasetRegistry()
        registry.register(_record("TRF-001"))

        with pytest.raises(DuplicateDatasetError, match="TRF-001"):
            registry.register(_record("TRF-001"))

    def test_duplicate_registration_allowed_with_allow_update(self) -> None:
        registry = DatasetRegistry()
        original = registry.register(_record("TRF-001"))
        original.title = "changed"  # type: ignore[misc]  # only attrs, not record logic

        replacement = registry.register(
            _record("TRF-001", title="Replacement title"), allow_update=True
        )
        assert replacement is not original
        assert registry.get("TRF-001").title == "Replacement title"
        assert len(registry) == 1

    def test_unregister_returns_record_and_clears_it(self) -> None:
        registry = DatasetRegistry()
        record = _record("TRF-002")
        registry.register(record)

        returned = registry.unregister("TRF-002")
        assert returned is record
        assert "TRF-002" not in registry
        assert len(registry) == 0

    def test_unregister_unknown_raises(self) -> None:
        registry = DatasetRegistry()

        with pytest.raises(UnknownDatasetError, match="TRF-003"):
            registry.unregister("TRF-003")

    def test_get_unknown_lists_known_ids(self) -> None:
        registry = DatasetRegistry()
        registry.register(_record("TRF-001"))
        registry.register(_record("TRF-004"))

        with pytest.raises(UnknownDatasetError) as excinfo:
            registry.get("TRF-999")

        message = str(excinfo.value)
        assert "TRF-999" in message
        assert "TRF-001" in message
        assert "TRF-004" in message


# ---------------------------------------------------------------------------
# 2. Deterministic listing and filtering
# ---------------------------------------------------------------------------


class TestListingAndFiltering:
    def test_ids_sorted(self) -> None:
        registry = DatasetRegistry()
        for did in ["TRF-005", "TRF-001", "WTR-002"]:
            registry.register(_record(did))

        assert registry.ids() == tuple(sorted(["TRF-001", "TRF-005", "WTR-002"]))
        assert len(registry.ids()) == 3

    def test_list_records_sorted_by_id(self) -> None:
        registry = DatasetRegistry()
        registry.register(_record("WTR-002", title="B"))
        registry.register(_record("TRF-001", title="A"))
        registry.register(_record("TRF-005", title="C"))

        records = registry.list_records()
        assert [r.dataset_id for r in records] == ["TRF-001", "TRF-005", "WTR-002"]
        assert len(records) == 3

    def test_list_records_returns_copy_not_internal(self) -> None:
        registry = DatasetRegistry()
        registry.register(_record("TRF-001"))

        records = registry.list_records()
        records += (object(),)  # mutate the returned tuple reference — must not affect registry
        assert len(registry.list_records()) == 1

    def test_filter_by_research_decision(self) -> None:
        registry = DatasetRegistry()

        trf001 = _record("TRF-001", acquisition_notes="")
        trf001.record_research_review(
            ResearchReview(decision=ResearchDecision.KEEP, rationale="fixture", reviewed_at=NOW)
        )
        registry.register(trf001)

        wst002 = _record("WST-002", acquisition_notes="")
        wst002.record_research_review(
            ResearchReview(decision=ResearchDecision.REJECT, rationale="fixture", reviewed_at=NOW)
        )
        registry.register(wst002)

        wtr001 = _record("WTR-001", acquisition_notes="")
        wtr001.record_research_review(
            ResearchReview(
                decision=ResearchDecision.REPLACE,
                rationale="fixture",
                reviewed_at=NOW,
                replacement_target="WTR-005",
            )
        )
        registry.register(wtr001)

        cit004 = _record("CIT-004", acquisition_notes="")
        # CIT-004 stays CONDITIONAL (no change from the default); do not call
        # record_research_review because CONDITIONAL -> CONDITIONAL is a no-op.
        registry.register(cit004)

        keep = registry.filter_by(research_decision=ResearchDecision.KEEP.value)
        assert [r.dataset_id for r in keep] == ["TRF-001"]

        rejected = registry.filter_by(research_decision=ResearchDecision.REJECT.value)
        assert [r.dataset_id for r in rejected] == ["WST-002"]

        replaced = registry.filter_by(research_decision=ResearchDecision.REPLACE.value)
        assert [r.dataset_id for r in replaced] == ["WTR-001"]

    def test_filter_by_acquisition_state(self) -> None:
        registry = DatasetRegistry()
        registry.register(_record("TRF-001", acquisition_notes=""))
        registry.register(_record("WST-002", acquisition_notes=""))
        registry.register(_record("WTR-005", acquisition_notes=""))

        # All start METADATA_ONLY by default
        mo = registry.filter_by(acquisition_state=AcquisitionState.METADATA_ONLY.value)
        assert len(mo) == 3

    def test_filter_by_both_axes(self) -> None:
        registry = DatasetRegistry()

        trf001 = _record("TRF-001", acquisition_notes="")
        trf001.record_research_review(
            ResearchReview(decision=ResearchDecision.KEEP, rationale="fixture", reviewed_at=NOW)
        )
        registry.register(trf001)

        env001 = _record("ENV-001", acquisition_notes="")
        env001.record_research_review(
            ResearchReview(decision=ResearchDecision.KEEP, rationale="fixture", reviewed_at=NOW)
        )
        registry.register(env001)

        filtered = registry.filter_by(
            research_decision=ResearchDecision.KEEP.value,
            acquisition_state=AcquisitionState.METADATA_ONLY.value,
        )
        # both are KEEP + METADATA_ONLY, so both match
        assert sorted(r.dataset_id for r in filtered) == ["ENV-001", "TRF-001"]

    def test_filter_with_no_matches_returns_empty_tuple(self) -> None:
        registry = DatasetRegistry()
        registry.register(_record("TRF-001"))

        assert registry.filter_by(research_decision=ResearchDecision.REJECT.value) == ()

    def test_filter_without_axis_values_is_the_same_as_listing(self) -> None:
        registry = DatasetRegistry()
        registry.register(_record("TRF-001"))
        registry.register(_record("TRF-002"))

        assert registry.filter_by() == registry.list_records()


# ---------------------------------------------------------------------------
# 3. Preservation of the canonical ID set and TRF-006 exclusion
# ---------------------------------------------------------------------------


class TestCanonicalSetPreservation:
    def test_registry_can_hold_all_21_canonical_ids(self) -> None:
        registry = DatasetRegistry()
        for did in _IDS:
            registry.register(_record(did))
        assert len(registry) == 21
        assert set(registry.ids()) == set(_IDS)
        assert "WTR-005" in registry.ids()
        assert "TRF-006" not in registry.ids()

    def test_trf_006_is_not_a_canonical_id_preserving_gap(self) -> None:
        # TRF-006 is an unresolved reference in the audit, not a canonical id.
        assert "TRF-006" not in CANONICAL_DATASET_IDS
        registry = DatasetRegistry()
        registry.register(_record("WTR-005"))
        assert "TRF-006" not in registry
        with pytest.raises(UnknownDatasetError, match="TRF-006"):
            registry.get("TRF-006")

    def test_unknown_id_error_message_is_clear(self) -> None:
        registry = DatasetRegistry()
        registry.register(_record("TRF-001"))

        with pytest.raises(UnknownDatasetError) as excinfo:
            registry.get("ZZZ-999")
        assert "ZZZ-999" in str(excinfo.value)
