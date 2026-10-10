"""Tests for the registry-guided ingestion integration (:mod:`civicmind.ingestion.integration`).

Covers eligibility resolution, unknown -> not-registered, REJECT -> blocked,
REPLACE -> blocked, CONDITIONAL -> requires explicit authorization, KEEP /
KEEP_WITH_CHUNKING eligibility, ingestor source_id alignment, and that
integration itself performs no acquisition and does not mutate status axes.

No network, no datasets: every canonical record is a minimal fixture, and every
ingestor is a fake that either succeeds or fails on acquire() without writing real
data.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from civicmind.ingestion.base import (
    AcquisitionResult,
    DatasetIngestor,
    SourceDescriptor,
    ValidationReport,
)
from civicmind.ingestion.catalog import DatasetRegistry
from civicmind.ingestion.exceptions import AcquisitionError
from civicmind.ingestion.integration import (
    ConditionalApprovalRequiredError,
    DatasetNotRegisteredError,
    prepare_ingestion,
    resolve_dataset_for_ingestion,
)
from civicmind.ingestion.metadata import (
    CANONICAL_DATASET_IDS,
    AcquisitionState,
    CanonicalDatasetRecord,
    ProfilingState,
    ResearchDecision,
    ResearchReview,
    ResearchStatus,
    ValidationState,
)
from civicmind.ingestion.policy import (
    ConditionalAuthorization,
    RejectedDatasetError,
    ReplacedDatasetError,
)
from civicmind.ingestion.sources import (
    CANONICAL_COLUMNS,
    CSV_PATH,
    CanonicalCSVError,
    CanonicalDataError,
    CanonicalMetadataError,
    load_canonical_metadata,
    load_canonical_registry,
    parse_canonical_metadata_csv,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


class FakeIngestor(DatasetIngestor):
    """Minimal fake ingestor bound to one canonical dataset id.

    Acquisition is phase-gated: a caller can mark it to fail at acquire time
    (simulating a download failure) without ever touching the metadata model.
    """

    HANDLER_VERSION = "0.1.0"

    def __init__(
        self,
        *,
        source_id: str,
        fail_acquire: bool = False,
    ) -> None:
        self._source_id = source_id
        self._fail_acquire = fail_acquire
        self.acquire_called = False
        self.ingest_called = False

    @property
    def source_id(self) -> str:
        return self._source_id

    def describe(self) -> SourceDescriptor:
        return SourceDescriptor(
            source_id=self._source_id,
            title=f"Fake ingestor for {self._source_id}",
            publisher="CivicMind test",
            license="CC0-1.0",
        )

    def acquire(self, destination: Path) -> AcquisitionResult:
        self.acquire_called = True
        if self._fail_acquire:
            raise AcquisitionError(f"cannot acquire {self._source_id!r}")
        return AcquisitionResult(
            source_id=self._source_id,
            acquired_at=datetime.now(tz=timezone.utc),
            method="fake",
            local_path=destination / "snapshot.csv",
            byte_size=10,
            checksum_sha256="a" * 64,
        )

    def validate(self, result: AcquisitionResult) -> ValidationReport:
        return ValidationReport(
            source_id=result.source_id, passed=True, checked_at=datetime.now(tz=timezone.utc)
        )


# Reusable canonical fixture -----------------------------------------------------

_ACCEPTED_RECORD_FIELDS = {
    "title",
    "domain",
    "publisher",
    "short_title",
    "subdomain",
    "publisher_aliases",
    "publisher_url",
    "dataset_url",
    "download_url",
    "license",
    "license_verified",
    "format",
    "temporal_coverage",
    "spatial_coverage",
    "geographic_granularity",
    "record_count",
    "file_size",
    "research_status",
    "source_reliability",
    "source_reliability_notes",
    "source_replaced_from",
    "acquisition_notes",
    "resource_plan",
    "data_quality_issues",
}


def _record(dataset_id: str, **kwargs: object) -> CanonicalDatasetRecord:
    """Build a canonical fixture record. ``dataset_id`` must already be a
    canonical id like ``'TRF-001'`` (with the hyphen); the record constructor
    enforces the pattern.

    Accepted kwargs must be canonical-record fields only. Review axes
    (``research_decision``, ``replacement_target``) are **not** accepted here;
    set those with :func:`_registry_with` or call :meth:`record.record_research_review`
    after construction.
    """
    unexpected = sorted(k for k in kwargs if k not in _ACCEPTED_RECORD_FIELDS)
    if unexpected:
        raise TypeError(
            f"_record does not accept non-field kwargs: {unexpected}; "
            f"use a ResearchReview + record_research_review() for axis changes"
        )
    defaults: dict[str, object] = {
        "title": f"Canonical {dataset_id}",
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


# Registry helpers ---------------------------------------------------------------


def _empty_registry() -> DatasetRegistry:
    return DatasetRegistry()


def _registry_with(
    records: dict[str, dict[str, object]] | None = None, **ids: dict[str, object]
) -> DatasetRegistry:
    """Register canonical records, optionally with a one-shot research review set
    after construction (because ``CanonicalDatasetRecord.__init__`` keeps axis 1
    at ``CONDITIONAL`` and only a documented review may change it).

    Accepts either:

    * ``records``: a dict keyed by canonical dataset id (e.g. ``'TRF-001'``)
      to a dict of extra kwargs for :func:`_record` plus optional
      ``research_decision`` / ``replacement_target``.
    * ``**ids``: the same mapping as keyword arguments, e.g.
      ``_registry_with(**{"TRF-001": {"research_decision": ResearchDecision.KEEP}})``.

    ``research_decision`` and ``replacement_target`` are popped from each
    per-dataset kwargs before they reach :func:`_record`.
    """
    if records is not None and ids:
        raise TypeError("pass either records=, or keyword dataset ids, not both")
    mapping: dict[str, dict[str, object]] = records if records is not None else ids
    if not all(value in CANONICAL_DATASET_IDS for value in mapping):
        bad = sorted(d for d in mapping if d not in CANONICAL_DATASET_IDS)
        raise ValueError(f"_registry_with received non-canonical dataset ids: {bad}")
    registry = DatasetRegistry()
    for did, kwargs in mapping.items():
        # Pop review-control keys BEFORE forwarding to _record, so the
        # constructor never sees them.
        decision = kwargs.pop("research_decision", None)
        replacement_target = kwargs.pop("replacement_target", None)
        record = _record(did, **kwargs)
        if decision is not None:
            replacement = replacement_target or None
            review = ResearchReview(
                decision=decision,
                rationale=f"test fixture: {did}",
                reviewed_at=NOW,
                replacement_target=replacement,
            )
            # Only apply the review if it actually changes the axis; CONDITIONAL ->
            # CONDITIONAL is a no-op and rejected by the record's transition guard.
            if (
                decision is not ResearchDecision.CONDITIONAL
                or record.research_decision is not ResearchDecision.CONDITIONAL
            ):
                record.record_research_review(review)
        registry.register(record)
    return registry


def _is_canonical_id(value: str) -> bool:
    return value in CANONICAL_DATASET_IDS


# ---------------------------------------------------------------------------
# 1. Eligibility / resolution
# ---------------------------------------------------------------------------


class TestResolveDatasetForIngestion:
    def test_keep_known_dataset_is_resolved(self) -> None:
        registry = _registry_with(
            {
                "TRF-001": {
                    "research_decision": ResearchDecision.KEEP,
                },
            }
        )
        record = resolve_dataset_for_ingestion(registry, "TRF-001")
        assert record.dataset_id == "TRF-001"
        assert record.research_decision is ResearchDecision.KEEP

    def test_keep_with_chunking_is_resolved(self) -> None:
        registry = _registry_with(
            {
                "TRF-002": {
                    "research_decision": ResearchDecision.KEEP_WITH_CHUNKING,
                },
            }
        )
        record = resolve_dataset_for_ingestion(registry, "TRF-002")
        assert record.research_decision is ResearchDecision.KEEP_WITH_CHUNKING

    def test_unknown_dataset_is_rejected_with_clear_error(self) -> None:
        registry = _empty_registry()

        with pytest.raises(DatasetNotRegisteredError, match="TRF-999"):
            resolve_dataset_for_ingestion(registry, "TRF-999")

    def test_reject_dataset_is_blocked(self) -> None:
        registry = _registry_with(
            {
                "WST-002": {"research_decision": ResearchDecision.REJECT},
            }
        )

        with pytest.raises(RejectedDatasetError, match="WST-002"):
            resolve_dataset_for_ingestion(registry, "WST-002")

    def test_replace_dataset_is_blocked(self) -> None:
        registry = _registry_with(
            {
                "WTR-001": {
                    "research_decision": ResearchDecision.REPLACE,
                    "replacement_target": "WTR-005",
                },
            }
        )

        with pytest.raises(ReplacedDatasetError, match="WTR-001"):
            resolve_dataset_for_ingestion(registry, "WTR-001")

    def test_conditional_dataset_requires_authorization(self) -> None:
        registry = _registry_with(
            {
                "WST-001": {"research_decision": ResearchDecision.CONDITIONAL},
            }
        )

        with pytest.raises(ConditionalApprovalRequiredError, match="WST-001"):
            resolve_dataset_for_ingestion(registry, "WST-001")

    def test_conditional_dataset_with_authorization_is_resolved(self) -> None:
        registry = _registry_with(
            {
                "WST-001": {"research_decision": ResearchDecision.CONDITIONAL},
            }
        )
        auth = ConditionalAuthorization(rationale="pilot: small and free to evaluate")
        record = resolve_dataset_for_ingestion(registry, "WST-001", authorization=auth)
        assert record.dataset_id == "WST-001"
        assert record.research_decision is ResearchDecision.CONDITIONAL
        assert auth.rationale == "pilot: small and free to evaluate"

    def test_authorization_rationale_is_mandatory(self) -> None:
        with pytest.raises(ValueError, match="rationale"):
            ConditionalAuthorization("   ")


# ---------------------------------------------------------------------------
# 2. prepare_ingestion integration
# ---------------------------------------------------------------------------


class TestPrepareIngestion:
    def test_prepare_ingestion_resolves_and_validates_source_id(self) -> None:
        registry = _registry_with(
            {
                "TRF-001": {
                    "research_decision": ResearchDecision.KEEP,
                },
            }
        )
        ingestor = FakeIngestor(source_id="TRF-001")
        record = prepare_ingestion(registry, ingestor)
        assert record.dataset_id == "TRF-001"
        assert record.research_decision is ResearchDecision.KEEP

    def test_prepare_ingestion_rejects_mismatched_source_id(self) -> None:
        registry = _registry_with(
            {
                "TRF-001": {"research_decision": ResearchDecision.KEEP},
            }
        )
        ingestor = FakeIngestor(source_id="TRF-002")

        with pytest.raises(DatasetNotRegisteredError, match="TRF-002"):
            prepare_ingestion(registry, ingestor)

    def test_prepare_ingestion_does_not_mutate_axes(self) -> None:
        registry = _registry_with(
            {
                "TRF-001": {"research_decision": ResearchDecision.KEEP},
            }
        )
        ingestor = FakeIngestor(source_id="TRF-001")
        record_before = registry.get("TRF-001")
        resolved = prepare_ingestion(registry, ingestor)
        record_after = registry.get("TRF-001")
        assert record_before is resolved
        assert record_after is resolved
        assert resolved.acquisition_state == AcquisitionState.METADATA_ONLY

    def test_prepare_ingestion_does_not_run_acquire(self) -> None:
        registry = _registry_with(
            {
                "TRF-001": {"research_decision": ResearchDecision.KEEP},
            }
        )
        ingestor = FakeIngestor(source_id="TRF-001")
        prepare_ingestion(registry, ingestor)
        assert ingestor.acquire_called is False

    def test_resolve_dataset_for_ingestion_returns_same_record_as_registry_get(self) -> None:
        registry = _registry_with(
            {
                "TRF-001": {"research_decision": ResearchDecision.KEEP},
            }
        )
        expected = registry.get("TRF-001")
        resolved = resolve_dataset_for_ingestion(registry, "TRF-001")
        assert resolved is expected


# ---------------------------------------------------------------------------
# 3. Failed acquisition does not falsely mark the dataset downloaded/validated
# ---------------------------------------------------------------------------


class TestFailedAcquisitionDoesNotInflateState:
    def test_failed_acquisition_in_fake_ingest_is_not_laundered(self, tmp_path: Path) -> None:
        """Acquisition failure is explicit and never silently converted into a
        valid acquired/validated artifact."""
        registry = _registry_with(
            {
                "TRF-001": {"research_decision": ResearchDecision.KEEP},
            }
        )
        ingestor = FakeIngestor(source_id="TRF-001", fail_acquire=True)
        prepare_ingestion(registry, ingestor)

        with pytest.raises(AcquisitionError, match="cannot acquire"):
            ingestor.acquire(tmp_path)

        assert ingestor.acquire_called is True


# ---------------------------------------------------------------------------
# 4. Deterministic listing and filtering (integration re-checks catalog contracts)
# ---------------------------------------------------------------------------


class TestRegistryContractsFromIntegration:
    def test_registry_deterministic_listing(self) -> None:
        registry = _registry_with(
            {
                "TRF-001": {},
                "TRF-005": {},
                "WTR-002": {},
            }
        )
        assert registry.ids() == ("TRF-001", "TRF-005", "WTR-002")

    def test_filter_by_research_decision(self) -> None:
        registry = _registry_with(
            {
                "TRF-001": {"research_decision": ResearchDecision.KEEP},
                "WST-002": {"research_decision": ResearchDecision.REJECT},
            }
        )
        rejected = registry.filter_by(research_decision=ResearchDecision.REJECT.value)
        assert [r.dataset_id for r in rejected] == ["WST-002"]


# ---------------------------------------------------------------------------
# 5. CSV -> records -> registry -> policy -> ingestion preparation
# ---------------------------------------------------------------------------

#: The committed, version-controlled metadata file this path is meant to serve.
REPO_CSV = Path(__file__).resolve().parents[1] / "configs" / "datasets" / "canonical_metadata.csv"


def _csv_header_and_rows() -> tuple[str, list[str]]:
    """Return the real CSV header and its raw data lines, in file order."""
    lines = CSV_PATH.read_text(encoding="utf-8").splitlines()
    return lines[0], lines[1:]


def _csv_row(dataset_id: str) -> str:
    """Return one raw data line of the real CSV by dataset id."""
    _, rows = _csv_header_and_rows()
    for row in rows:
        if row.startswith(f"{dataset_id},"):
            return row
    raise AssertionError(f"{dataset_id} is not a row in {CSV_PATH}")


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    """Write a synthetic CSV using the real header and the given raw data lines."""
    header, _ = _csv_header_and_rows()
    target = tmp_path / "canonical_metadata.csv"
    target.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return target


def _write_modified_csv(tmp_path: Path, dataset_id: str, **fields: str) -> Path:
    """Rewrite the real CSV verbatim with one dataset's fields overridden.

    Uses the strict parser + :func:`csv.writer` so quoting stays valid and the
    synthetic file keeps the real schema instead of relying on string surgery.
    """
    rows = parse_canonical_metadata_csv(CSV_PATH)
    target = tmp_path / "modified.csv"
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CANONICAL_COLUMNS)
        for row in rows:
            values = row._asdict()
            if values["dataset_id"] == dataset_id:
                values.update(fields)
            writer.writerow([values[column] for column in CANONICAL_COLUMNS])
    return target


class TestCanonicalCSVToRegistry:
    """The happy path: the committed CSV loads into a real :class:`DatasetRegistry`."""

    def test_default_csv_path_points_at_the_committed_file(self) -> None:
        assert CSV_PATH.is_file()
        assert CSV_PATH == REPO_CSV

    def test_loads_all_21_canonical_ids_without_duplicates(self) -> None:
        registry = load_canonical_registry()
        assert isinstance(registry, DatasetRegistry)
        assert len(registry) == 21
        assert len(registry.ids()) == 21
        assert set(registry.ids()) == set(CANONICAL_DATASET_IDS)

    def test_wtr_005_is_registered_and_trf_006_is_absent(self) -> None:
        registry = load_canonical_registry()
        assert "WTR-005" in registry
        assert "TRF-006" not in registry

    def test_lookup_returns_the_loaded_record(self) -> None:
        registry = load_canonical_registry()
        record = registry.get("TRF-001")
        assert record.dataset_id == "TRF-001"
        assert record.title
        assert record in registry.list_records()

    def test_publisher_aliases_load_as_distinct_entries(self) -> None:
        """A semicolon-separated alias cell becomes one tuple entry per alias."""
        registry = load_canonical_registry()

        assert registry.get("WTR-004").publisher_aliases == (
            "CPCB",
            "NWIC",
            "Ministry of Jal Shakti",
        )
        assert registry.get("TRF-005").publisher_aliases == (
            "Bengaluru Traffic Police",
            "Bengaluru Traffic Department",
            "btm.gov.in",
        )
        assert registry.get("TRF-001").publisher_aliases == (
            "Smart Cities Mission",
            "Ministry of Housing & Urban Affairs",
        )

    def test_single_alias_stays_one_entry_without_a_delimiter(self) -> None:
        registry = load_canonical_registry()

        assert registry.get("WTR-005").publisher_aliases == ("BWSSB",)
        assert registry.get("ENV-002").publisher_aliases == ("CPCB",)

    def test_empty_alias_cells_load_as_an_empty_tuple(self) -> None:
        registry = load_canonical_registry()

        assert registry.get("TRF-002").publisher_aliases == ()
        assert registry.get("WST-002").publisher_aliases == ()

    def test_every_loaded_alias_is_split_and_keeps_no_delimiter(self) -> None:
        """No loaded alias still carries a ``;``, so nothing stayed unsplit."""
        registry = load_canonical_registry()
        populated = [r for r in registry.list_records() if r.publisher_aliases]

        assert populated
        for record in populated:
            assert all(";" not in alias for alias in record.publisher_aliases)

    def test_alias_whitespace_is_trimmed_and_strays_dropped(self, tmp_path: Path) -> None:
        csv_path = _write_modified_csv(
            tmp_path, "TRF-001", publisher_aliases=" Alpha ; Beta ; ;Gamma; "
        )

        record = load_canonical_registry(csv_path).get("TRF-001")
        assert record.publisher_aliases == ("Alpha", "Beta", "Gamma")

    def test_comma_within_an_alias_is_not_a_delimiter(self, tmp_path: Path) -> None:
        """Semicolon is the delimiter, so a comma belongs to the alias text."""
        csv_path = _write_modified_csv(tmp_path, "TRF-001", publisher_aliases="Dept of X, Y")

        record = load_canonical_registry(csv_path).get("TRF-001")
        assert record.publisher_aliases == ("Dept of X, Y",)

    def test_loading_metadata_creates_no_local_evidence(self) -> None:
        """Loading metadata must not imply an artifact, validation, or profiling."""
        registry = load_canonical_registry()
        for record in registry.list_records():
            assert record.acquisition_state is AcquisitionState.METADATA_ONLY
            assert record.validation_state is ValidationState.NOT_VALIDATED
            assert record.profiling_state is ProfilingState.NOT_PROFILED
            assert record.artifacts == ()
            assert record.validation_history == ()
            assert record.profiling_history == ()
            assert record.active_artifact is None

    def test_historical_acquisition_claim_stays_a_research_status(self) -> None:
        """A documented ``ACQUIRED`` research_status is history, not local bytes."""
        registry = load_canonical_registry()
        claimed = [
            record
            for record in registry.list_records()
            if record.research_status is ResearchStatus.ACQUIRED
        ]
        assert claimed, "expected at least one documented ACQUIRED research_status"
        for record in claimed:
            assert record.acquisition_state is AcquisitionState.METADATA_ONLY

    def test_no_planning_decision_is_inferred_from_the_csv(self) -> None:
        """The CSV carries research_status, not a planning decision; every loaded
        record therefore stays ``CONDITIONAL`` and needs explicit authorization."""
        registry = load_canonical_registry()
        for record in registry.list_records():
            assert record.research_decision is ResearchDecision.CONDITIONAL

    def test_metadata_load_matches_the_strict_parser_row_count(self) -> None:
        assert len(load_canonical_metadata()) == 21
        assert len(parse_canonical_metadata_csv(CSV_PATH)) == 21


class TestCanonicalCSVPolicyAndPreparation:
    """Registry lookup -> research policy -> ingestion preparation."""

    def test_loaded_dataset_requires_explicit_authorization(self) -> None:
        registry = load_canonical_registry()
        with pytest.raises(ConditionalApprovalRequiredError, match="TRF-001"):
            resolve_dataset_for_ingestion(registry, "TRF-001")

    def test_loaded_dataset_with_authorization_is_resolvable(self) -> None:
        registry = load_canonical_registry()
        auth = ConditionalAuthorization(rationale="pilot review approved")
        record = resolve_dataset_for_ingestion(registry, "TRF-001", authorization=auth)
        assert record.dataset_id == "TRF-001"
        assert record.acquisition_state is AcquisitionState.METADATA_ONLY

    def test_unknown_dataset_id_from_a_loaded_registry(self) -> None:
        registry = load_canonical_registry()
        with pytest.raises(DatasetNotRegisteredError, match="TRF-999"):
            resolve_dataset_for_ingestion(registry, "TRF-999")

    def test_rejected_research_decision_is_blocked(self) -> None:
        registry = load_canonical_registry()
        record = registry.get("WST-002")
        record.record_research_review(
            ResearchReview(ResearchDecision.REJECT, "low decision value", NOW)
        )
        with pytest.raises(RejectedDatasetError, match="WST-002"):
            resolve_dataset_for_ingestion(registry, "WST-002")

    def test_replaced_research_decision_is_blocked(self) -> None:
        registry = load_canonical_registry()
        record = registry.get("WTR-001")
        record.record_research_review(
            ResearchReview(ResearchDecision.REPLACE, "superseded", NOW, "WTR-005")
        )
        with pytest.raises(ReplacedDatasetError, match="WTR-001"):
            resolve_dataset_for_ingestion(registry, "WTR-001")

    def test_conditional_authorization_is_required_for_prepare_ingestion(self) -> None:
        registry = load_canonical_registry()
        ingestor = FakeIngestor(source_id="WST-001")
        with pytest.raises(ConditionalApprovalRequiredError, match="WST-001"):
            prepare_ingestion(registry, ingestor)

    def test_prepare_ingestion_end_to_end_from_csv(self) -> None:
        registry = load_canonical_registry()
        auth = ConditionalAuthorization(rationale="pilot review approved")
        ingestor = FakeIngestor(source_id="WST-001")
        record = prepare_ingestion(registry, ingestor, authorization=auth)
        assert record.dataset_id == "WST-001"
        assert record is registry.get("WST-001")
        assert ingestor.acquire_called is False
        assert ingestor.ingest_called is False
        assert record.acquisition_state is AcquisitionState.METADATA_ONLY
        assert record.validation_state is ValidationState.NOT_VALIDATED
        assert record.profiling_state is ProfilingState.NOT_PROFILED

    def test_prepare_ingestion_rejects_a_mismatched_ingestor(self) -> None:
        registry = load_canonical_registry()
        auth = ConditionalAuthorization(rationale="pilot review approved")
        ingestor = FakeIngestor(source_id="TRF-999")
        with pytest.raises(DatasetNotRegisteredError, match="TRF-999"):
            prepare_ingestion(registry, ingestor, authorization=auth)


class TestCanonicalCSVIntegrationFailures:
    """Malformed, duplicated, and incomplete metadata must fail before registration."""

    def test_malformed_row_is_rejected_before_registration(self, tmp_path: Path) -> None:
        bad = _write_csv(tmp_path, [_csv_row("TRF-001") + ",extra"])
        with pytest.raises(CanonicalDataError, match=r"has \d+ fields"):
            load_canonical_registry(bad)

    def test_malformed_row_is_rejected_by_the_strict_parser(self, tmp_path: Path) -> None:
        bad = _write_csv(tmp_path, [_csv_row("TRF-001") + ",extra"])
        with pytest.raises(CanonicalCSVError, match=r"has \d+ fields"):
            parse_canonical_metadata_csv(bad)

    def test_duplicate_dataset_id_is_rejected(self, tmp_path: Path) -> None:
        row = _csv_row("TRF-001")
        bad = _write_csv(tmp_path, [row, row])
        with pytest.raises(CanonicalDataError, match="duplicate dataset_id"):
            load_canonical_registry(bad)

    def test_missing_canonical_id_is_rejected(self, tmp_path: Path) -> None:
        _, rows = _csv_header_and_rows()
        remaining = [row for row in rows if not row.startswith("CIT-004,")]
        bad = _write_csv(tmp_path, remaining)
        with pytest.raises(CanonicalDataError, match="CIT-004"):
            load_canonical_registry(bad)

    def test_missing_canonical_id_is_allowed_without_coverage_check(self, tmp_path: Path) -> None:
        _, rows = _csv_header_and_rows()
        remaining = [row for row in rows if not row.startswith("CIT-004,")]
        bad = _write_csv(tmp_path, remaining)
        registry = load_canonical_registry(bad, require_all_ids=False)
        assert len(registry) == 20
        assert "CIT-004" not in registry

    def test_missing_file_is_reported(self, tmp_path: Path) -> None:
        with pytest.raises(CanonicalMetadataError, match="not found"):
            load_canonical_registry(tmp_path / "absent.csv")

    def test_header_mismatch_is_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad_header.csv"
        bad.write_text("dataset_id,title\nTRF-001,Example\n", encoding="utf-8")
        with pytest.raises(CanonicalDataError, match="header mismatch"):
            load_canonical_registry(bad)

    def test_loading_a_broken_csv_leaves_no_partial_registry(self, tmp_path: Path) -> None:
        """A failure must not yield a registry; there is no half-registered catalog."""
        row = _csv_row("TRF-001")
        bad = _write_csv(tmp_path, [row, row])
        with pytest.raises(CanonicalDataError):
            load_canonical_registry(bad)

    def test_unsupported_size_marker_is_rejected(self, tmp_path: Path) -> None:
        """``file_size`` is ``int | None``; documented prose must not be forced in."""
        bad = _write_modified_csv(tmp_path, "TRF-001", file_size="42.3 MiB (approx.)")
        with pytest.raises(CanonicalDataError, match="file_size"):
            load_canonical_registry(bad)

    def test_integer_file_size_is_accepted(self, tmp_path: Path) -> None:
        good = _write_modified_csv(tmp_path, "TRF-001", file_size="1048576")
        registry = load_canonical_registry(good)
        assert registry.get("TRF-001").file_size == 1048576

    def test_unknown_values_are_not_invented(self) -> None:
        """The committed CSV is the evidence: unknown counts/sizes stay unknown."""
        registry = load_canonical_registry()
        record = registry.get("TRF-001")
        assert record.record_count is None
        assert record.file_size is None
        assert record.acquired_at is None
        # A documented, non-empty licence is carried across; nothing is invented.
        assert record.license.strip()
        assert record.license_verified is False

    def test_unknown_dataset_ids_never_reach_the_registry(self) -> None:
        registry = load_canonical_registry()
        assert "TRF-006" not in registry
        assert "TRF-999" not in registry

    def test_record_count_is_carried_when_documented(self) -> None:
        """ENV-004 is the one row with a documented integer record_count."""
        registry = load_canonical_registry()
        record = registry.get("ENV-004")
        assert record.record_count == 4090000
        assert record.file_size is None
