"""Tests for the pilot orchestration (plan, acquire, validate, profile, status).

Every test is offline: acquisition is pointed at the loopback HTTP fixture, and
all paths live under ``tmp_path``. The real dataset is never fetched.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from civicmind.config import Settings
from civicmind.ingestion import pilot
from civicmind.ingestion.catalog import DatasetRegistry
from civicmind.ingestion.evidence import EvidenceCorruptError, EvidenceStore
from civicmind.ingestion.handlers import (
    UnsupportedDatasetError,
    build_pilot_handler,
    build_pilot_registry,
)
from civicmind.ingestion.handlers.trf_001 import DATASET_ID, RESOURCE_URL
from civicmind.ingestion.identifiers import IdentifierError
from civicmind.ingestion.metadata import CanonicalDatasetRecord, ResearchReview
from civicmind.ingestion.pilot import PilotError
from civicmind.ingestion.policy import RejectedDatasetError, ReplacedDatasetError
from civicmind.ingestion.states import ResearchDecision
from civicmind.ingestion.transfer import HttpStatusError, OversizedResponseError
from conftest import SAMPLE_CSV, LocalHTTPServer

#: A fixed instant in the past, so replay order is deterministic.
PAST = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

RATIONALE = "Gate B1 pilot acquisition of the single OpenCity CSV resource"


def _no_sleep(_seconds: float) -> None:
    """Replace real backoff so the tests never wait."""
    return


def _acquire(
    settings: Settings,
    url: str,
    *,
    max_bytes: int | None = None,
    rationale: str = RATIONALE,
    dataset_id: str = DATASET_ID,
):
    """Acquire the pilot dataset from the local test server."""
    return pilot.acquire(
        settings,
        dataset_id=dataset_id,
        rationale=rationale,
        resource_url=url,
        max_bytes=max_bytes,
        clock=lambda: PAST,
        sleep=_no_sleep,
    )


def _registry_with(
    decision: ResearchDecision,
    *,
    dataset_id: str = DATASET_ID,
    replacement_target: str | None = None,
) -> DatasetRegistry:
    """Build a one-record registry whose axis 1 has been reviewed to ``decision``."""
    record = CanonicalDatasetRecord(dataset_id=dataset_id, title="Traffic Accidents in India")
    if decision is not ResearchDecision.CONDITIONAL:
        record.record_research_review(
            ResearchReview(
                decision=decision,
                rationale="documented review in this test",
                reviewed_at=PAST,
                replacement_target=replacement_target,
            )
        )
    registry = DatasetRegistry()
    registry.register(record)
    return registry


# -- plan (dry run) ---------------------------------------------------------


def test_plan_performs_no_network_and_writes_nothing(pilot_settings: Settings) -> None:
    before = sorted(path.name for path in pilot_settings.project_root.iterdir())

    report = pilot.build_plan(pilot_settings)
    payload = report.as_dict()

    after = sorted(path.name for path in pilot_settings.project_root.iterdir())
    assert after == before
    assert payload["network_performed"] is False
    assert payload["writes_performed"] is False
    assert pilot_settings.raw_data_dir.exists() is False
    assert pilot_settings.artifacts_dir.exists() is False


def test_plan_reports_the_cited_resource_and_unverified_licence(pilot_settings: Settings) -> None:
    report = pilot.build_plan(pilot_settings)
    payload = report.as_dict()

    assert payload["dataset_id"] == DATASET_ID
    assert payload["resource_url"] == RESOURCE_URL
    assert payload["resource_url_citation"] == "docs/datasets/ingestion_plan.md#L251"
    assert payload["license_verified"] is False
    assert payload["authorization_required"] is True
    assert payload["acquisition_state"] == "METADATA_ONLY"
    assert payload["validation_state"] == "NOT_VALIDATED"
    assert payload["profiling_state"] == "NOT_PROFILED"
    assert payload["expected_format"] == "csv"
    assert payload["limits"]["max_bytes"] > 0


def test_plan_points_at_the_documented_evidence_location(pilot_settings: Settings) -> None:
    report = pilot.build_plan(pilot_settings)

    assert report.evidence_path.replace("\\", "/").endswith(
        "artifacts/ingestion/TRF-001/evidence.json"
    )


def test_plan_is_a_pure_function_of_recorded_state(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    first = pilot.build_plan(pilot_settings).as_dict()

    _acquire(pilot_settings, url)

    second = pilot.build_plan(pilot_settings).as_dict()
    assert first["artifacts_present"] == 0
    assert second["artifacts_present"] == 1
    assert second["acquisition_state"] == "DOWNLOADED"


# -- authorization ----------------------------------------------------------


def test_acquire_without_a_rationale_is_refused(pilot_settings: Settings) -> None:
    with pytest.raises(PilotError, match="--authorize"):
        pilot.acquire(pilot_settings, rationale=None)

    with pytest.raises(PilotError, match="--authorize"):
        pilot.acquire(pilot_settings, rationale="   ")

    assert pilot_settings.raw_data_dir.exists() is False
    assert pilot_settings.artifacts_dir.exists() is False


@pytest.mark.parametrize(
    ("decision", "replacement_target", "expected"),
    [
        (ResearchDecision.REJECT, None, RejectedDatasetError),
        (ResearchDecision.REPLACE, "TRF-002", ReplacedDatasetError),
    ],
)
def test_rejected_and_replaced_records_stay_blocked(
    pilot_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    decision: ResearchDecision,
    replacement_target: str | None,
    expected: type[Exception],
) -> None:
    registry = _registry_with(decision, replacement_target=replacement_target)
    monkeypatch.setattr(pilot, "load_canonical_registry", lambda: registry)

    with pytest.raises(expected):
        _acquire(pilot_settings, "http://127.0.0.1:9/never.csv")

    assert pilot_settings.raw_data_dir.exists() is False
    assert pilot_settings.artifacts_dir.exists() is False


def test_the_policy_gate_runs_before_the_network(
    pilot_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry_with(ResearchDecision.REJECT)
    monkeypatch.setattr(pilot, "load_canonical_registry", lambda: registry)
    touched: list[str] = []

    def _forbidden_handler(*args: object, **kwargs: object) -> None:
        touched.append("handler")
        raise AssertionError("the handler must not be built for a blocked dataset")

    monkeypatch.setattr(pilot, "build_pilot_handler", _forbidden_handler)

    with pytest.raises(RejectedDatasetError):
        _acquire(pilot_settings, "http://127.0.0.1:9/never.csv")

    assert touched == []


# -- acquisition -----------------------------------------------------------


def test_acquire_returns_measured_facts_and_writes_evidence(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")

    report = _acquire(pilot_settings, url)

    assert report.dataset_id == DATASET_ID
    assert report.artifact_version == 1
    assert report.byte_size == len(SAMPLE_CSV)
    assert report.method == "https-get"
    assert report.acquisition_state == "DOWNLOADED"
    assert report.validation_state == "NOT_VALIDATED"
    assert report.profiling_state == "NOT_PROFILED"
    assert Path(report.local_path).is_file()
    assert report.evidence_path == str(
        pilot_settings.artifacts_dir / "ingestion" / DATASET_ID / "evidence.json"
    )
    assert EvidenceStore(pilot_settings.artifacts_dir, DATASET_ID).exists() is True


def test_acquire_records_the_authorization_and_resource_provenance(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")

    _acquire(pilot_settings, url, rationale="reviewed at Gate B1")
    payload = json.loads(
        EvidenceStore(pilot_settings.artifacts_dir, DATASET_ID).path.read_text(encoding="utf-8")
    )

    assert payload["authorizations"] == [
        {"rationale": "reviewed at Gate B1", "recorded_at": PAST.isoformat()}
    ]
    assert payload["resource_provenance"]["resource_url"] == url
    assert payload["resource_provenance"]["cited_in"] == "docs/datasets/ingestion_plan.md#L251"
    assert "not proof" in payload["resource_provenance"]["caveat"]
    # Provenance is persisted, so it describes the transfer that actually ran.
    assert payload["artifacts"][0]["provenance"]["source_uri"] == url


def test_acquire_enforces_the_size_limit(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")

    with pytest.raises(OversizedResponseError):
        _acquire(pilot_settings, url, max_bytes=32)

    # The transfer is refused, so the artifact directory holds no file at all.
    assert list((pilot_settings.raw_data_dir / DATASET_ID).iterdir()) == []
    evidence = EvidenceStore(pilot_settings.artifacts_dir, DATASET_ID)
    assert evidence.exists() is False


def test_a_second_acquisition_keeps_every_artifact(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    first_url = http_server.serve("/v1.csv", body=SAMPLE_CSV)
    second_body = SAMPLE_CSV.replace(b"Ahmedabad", b"Gwalior")
    second_url = http_server.serve("/v2.csv", body=second_body)

    first = _acquire(pilot_settings, first_url)
    second = _acquire(pilot_settings, second_url)

    assert second.artifact_version == 2
    assert second.checksum_sha256 != first.checksum_sha256
    raw_dir = pilot_settings.raw_data_dir / DATASET_ID
    files = sorted(path.name for path in raw_dir.iterdir())
    assert len(files) == 2
    # Both versions stay on disk: the earlier artifact is preserved, not replaced.
    assert Path(first.local_path).is_file()
    assert Path(first.local_path).read_bytes() == SAMPLE_CSV


def test_a_failed_reacquisition_preserves_evidence_and_artifacts(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    _acquire(pilot_settings, url)
    evidence = EvidenceStore(pilot_settings.artifacts_dir, DATASET_ID)
    before = evidence.path.read_bytes()
    artifact_dir = pilot_settings.raw_data_dir / DATASET_ID
    files_before = sorted(path.name for path in artifact_dir.iterdir())

    gone = http_server.serve("/gone.csv", status=404, body=b"")
    with pytest.raises(HttpStatusError):
        _acquire(pilot_settings, gone)

    # The failed run touches neither the evidence document nor the artifact.
    assert evidence.path.read_bytes() == before
    assert sorted(path.name for path in artifact_dir.iterdir()) == files_before
    assert len(files_before) == 1


def test_acquire_refuses_to_run_against_corrupt_evidence(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    _acquire(pilot_settings, url)
    evidence = EvidenceStore(pilot_settings.artifacts_dir, DATASET_ID)
    evidence.path.write_text("{ corrupted", encoding="utf-8")

    with pytest.raises(EvidenceCorruptError):
        _acquire(pilot_settings, url)

    assert evidence.path.read_text(encoding="utf-8") == "{ corrupted"


# -- validation -------------------------------------------------------------


def test_validate_with_no_artifact_explains_what_to_run(pilot_settings: Settings) -> None:
    with pytest.raises(PilotError, match="ingest acquire"):
        pilot.validate(pilot_settings)


def test_validate_advances_only_the_validation_axis(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    _acquire(pilot_settings, url)

    report = pilot.validate(pilot_settings)

    assert report.passed is True
    assert report.state == "VALIDATED"
    assert report.state_changed is True
    assert report.error_count == 0
    assert report.artifact_version == 1
    assert report.scope == "single CSV: encoding, header presence, structural consistency"

    status = pilot.status(pilot_settings)
    assert status.axes["acquisition_state"] == "DOWNLOADED"
    assert status.axes["profiling_state"] == "NOT_PROFILED"


def test_a_second_validate_does_not_duplicate_the_event(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    _acquire(pilot_settings, url)
    pilot.validate(pilot_settings)

    second = pilot.validate(pilot_settings)

    assert second.state_changed is False
    assert pilot.status(pilot_settings).validation_count == 1


def test_a_failing_artifact_moves_axis_three_to_failed(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    malformed = b'City,Year\nAhmedabad,"2016\n'
    url = http_server.serve("/resource.csv", body=malformed)

    _acquire(pilot_settings, url)
    report = pilot.validate(pilot_settings)

    assert report.passed is False
    assert report.state == "VALIDATION_FAILED"
    assert report.error_count >= 1

    status = pilot.status(pilot_settings)
    assert status.axes["acquisition_state"] == "DOWNLOADED"
    assert status.axes["profiling_state"] == "NOT_PROFILED"


# -- profiling --------------------------------------------------------------


def test_profile_walks_the_ladder_and_keeps_profiles_separate(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    _acquire(pilot_settings, url)
    pilot.validate(pilot_settings)

    report = pilot.profile(pilot_settings)

    assert report.state == "PROFILED"
    assert report.state_changed is True
    assert report.steps_recorded == ("SCHEMA_ONLY", "PARTIALLY_PROFILED", "PROFILED")
    assert report.data_rows == 5
    assert report.column_count == 9
    assert report.duplicate_rows == 1
    assert report.sampled is False

    profile_path = Path(report.profile_path)
    assert profile_path.is_file()
    # Profiles live beside the evidence, never beside the raw artifact.
    assert str(profile_path).startswith(str(pilot_settings.artifacts_dir))
    assert str(profile_path) not in str(pilot_settings.raw_data_dir)
    assert str(profile_path).endswith("profile-v1.json")


def test_profile_output_contains_no_row_values(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    _acquire(pilot_settings, url)
    report = pilot.profile(pilot_settings)

    rendered = Path(report.profile_path).read_text(encoding="utf-8")
    assert "Ahmedabad" not in rendered
    assert "Bhopal" not in rendered


def test_a_second_profile_is_a_noop(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    _acquire(pilot_settings, url)
    pilot.validate(pilot_settings)
    pilot.profile(pilot_settings)

    second = pilot.profile(pilot_settings)

    assert second.state_changed is False
    assert second.state == "PROFILED"
    assert pilot.status(pilot_settings).profiling_count == 3


def test_profiling_does_not_imply_validation(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    malformed = b'City,Year\nAhmedabad,"2016\n'
    url = http_server.serve("/resource.csv", body=malformed)
    _acquire(pilot_settings, url)
    assert pilot.validate(pilot_settings).state == "VALIDATION_FAILED"

    report = pilot.profile(pilot_settings)

    assert report.state == "PROFILED"
    assert pilot.status(pilot_settings).axes["validation_state"] == "VALIDATION_FAILED"


# -- status -----------------------------------------------------------------


def test_status_without_evidence_reports_metadata_only(pilot_settings: Settings) -> None:
    report = pilot.status(pilot_settings)

    assert report.evidence_present is False
    assert report.axes == {
        "research_decision": "CONDITIONAL",
        "acquisition_state": "METADATA_ONLY",
        "validation_state": "NOT_VALIDATED",
        "profiling_state": "NOT_PROFILED",
    }
    assert report.active_artifact is None
    assert report.replayed_events == 0
    assert report.replayed_skipped == ()
    assert report.blockers["license_verified"] is False
    # Reading state must not create it.
    assert pilot_settings.artifacts_dir.exists() is False


def test_status_replays_persisted_events(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")
    _acquire(pilot_settings, url)
    pilot.validate(pilot_settings)

    report = pilot.status(pilot_settings)

    assert report.evidence_present is True
    assert report.replayed_events == 2
    assert report.replayed_skipped == ()
    assert report.artifact_count == 1
    assert report.validation_count == 1
    assert report.resource_provenance["resource_url"] == url


def test_status_reports_the_unverified_licence_as_a_blocker(
    pilot_settings: Settings,
) -> None:
    report = pilot.status(pilot_settings)

    assert report.blockers["license_verified"] is False
    assert report.title == "Traffic Accidents in India (Smart Cities)"


def test_every_axis_advances_independently(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")

    _acquire(pilot_settings, url)
    after_acquire = pilot.status(pilot_settings).axes
    pilot.validate(pilot_settings)
    after_validate = pilot.status(pilot_settings).axes
    pilot.profile(pilot_settings)
    after_profile = pilot.status(pilot_settings).axes

    assert after_acquire == {
        "research_decision": "CONDITIONAL",
        "acquisition_state": "DOWNLOADED",
        "validation_state": "NOT_VALIDATED",
        "profiling_state": "NOT_PROFILED",
    }
    assert after_validate["profiling_state"] == "NOT_PROFILED"
    assert after_profile["validation_state"] == "VALIDATED"
    assert after_profile["research_decision"] == "CONDITIONAL"


def test_pilot_does_not_change_the_canonical_csv() -> None:
    """The metadata CSV is read-only input for the pilot.

    TRF-001 keeps an empty ``download_url``: the verified resource URL lives in
    the handler, cited from the ingestion plan, until a separate metadata
    correction is reviewed and approved.
    """
    source = (
        Path(__file__).resolve().parents[1] / "configs" / "datasets" / "canonical_metadata.csv"
    )

    assert source.is_file()
    row = next(
        line
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.startswith("TRF-001,")
    )
    assert ",,Other (Public Domain) / Open Data,false,CSV" in row
    assert "data.opencity.in/dataset/ffd84c06" not in row


def test_plan_limits_are_the_handlers_documented_guard(pilot_settings: Settings) -> None:
    limits = pilot.build_plan(pilot_settings).limits

    assert limits["max_bytes"] == 1 * 1024 * 1024
    assert limits["attempts"] >= 1
    # The two timeouts are genuinely distinct bounds, not one reused value.
    assert limits["connect_timeout_seconds"] != limits["read_timeout_seconds"]


# -- identifier handling ---------------------------------------------------


def test_handler_lookup_accepts_both_id_forms() -> None:
    canonical = build_pilot_handler(DATASET_ID)
    slug = build_pilot_handler("trf-001")

    assert canonical.resource_url == slug.resource_url == RESOURCE_URL
    assert canonical.describe().source_id == "trf-001"
    assert canonical.describe().source_id == slug.describe().source_id


@pytest.mark.parametrize("dataset_id", ["TRF-999", "trf-999"])
def test_handler_lookup_rejects_unsupported_ids_in_either_form(dataset_id: str) -> None:
    with pytest.raises(UnsupportedDatasetError, match="TRF-001"):
        build_pilot_handler(dataset_id)


def test_handler_lookup_rejects_a_value_that_is_neither_form() -> None:
    with pytest.raises(IdentifierError):
        build_pilot_handler("traffic accidents")


def test_pilot_registry_is_the_shipped_discovery_path() -> None:
    registry = build_pilot_registry()

    assert registry.source_ids() == ("trf-001",)
    assert len(registry) == 1
    descriptor = registry.describe_all()[0]
    assert descriptor.uri == RESOURCE_URL
    assert descriptor.license == "Other (Public Domain) / Open Data"


def test_plan_accepts_the_slug_and_reports_the_canonical_id(pilot_settings: Settings) -> None:
    by_slug = pilot.build_plan(pilot_settings, dataset_id="trf-001")
    by_canonical = pilot.build_plan(pilot_settings, dataset_id="TRF-001")

    assert by_slug.dataset_id == "TRF-001"
    assert by_slug.as_dict() == by_canonical.as_dict()


def test_artifact_and_evidence_paths_are_canonical(pilot_settings: Settings) -> None:
    assert pilot.artifact_dir(pilot_settings, "trf-001") == pilot.artifact_dir(
        pilot_settings, "TRF-001"
    )
    assert pilot.profile_dir(pilot_settings, "trf-001") == pilot.profile_dir(
        pilot_settings, "TRF-001"
    )
    assert pilot.artifact_dir(pilot_settings).as_posix().endswith("data/raw/TRF-001")


def test_slug_and_canonical_share_one_recorded_state(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    """Acquiring under the slug must be visible under the canonical id."""
    url = http_server.serve("/resource.csv")

    acquired = _acquire(pilot_settings, url, dataset_id="trf-001")
    pilot.validate(pilot_settings, dataset_id="TRF-001")

    assert acquired.dataset_id == "TRF-001"
    canonical_status = pilot.status(pilot_settings, dataset_id="TRF-001")
    slug_status = pilot.status(pilot_settings, dataset_id="trf-001")
    assert canonical_status.axes == slug_status.axes
    assert canonical_status.evidence_path == slug_status.evidence_path
    assert canonical_status.artifact_count == 1
    assert canonical_status.validation_count == 1
    # Exactly one evidence file exists, whichever form wrote it.
    evidence_dir = pilot_settings.artifacts_dir / "ingestion"
    assert sorted(p.name for p in evidence_dir.iterdir()) == ["TRF-001"]


def test_provenance_retains_the_canonical_id_and_the_actual_url(
    pilot_settings: Settings, http_server: LocalHTTPServer
) -> None:
    url = http_server.serve("/resource.csv")

    _acquire(pilot_settings, url)
    payload = json.loads(
        EvidenceStore(pilot_settings.artifacts_dir, DATASET_ID).path.read_text(encoding="utf-8")
    )

    provenance = payload["artifacts"][0]["provenance"]
    assert provenance["source_id"] == "TRF-001"
    assert provenance["source_uri"] == url
    assert provenance["handler"].endswith("Trf001Ingestor")


def test_an_invalid_identifier_is_refused_before_any_io(pilot_settings: Settings) -> None:
    with pytest.raises(IdentifierError):
        pilot.build_plan(pilot_settings, dataset_id="nonsense")

    assert pilot_settings.artifacts_dir.exists() is False
    assert pilot_settings.raw_data_dir.exists() is False
