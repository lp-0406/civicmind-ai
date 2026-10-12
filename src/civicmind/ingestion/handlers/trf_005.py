"""Ingestion handler for the supplied local BWSSB water artifact (WTR-005 candidate).

This module is intentionally narrow. It exists to test and demonstrate the
local-artifact registration path for a dataset whose canonical mapping is
documented as *plausible but unverified*, and whose licence/attribution status
is explicitly unresolved in the project's own audit (C-07, C-10 family).

It is NOT:

* proof that this local CSV is the canonical WTR-005 resource;
* a network-acquisition handler — it never downloads anything;
* a licence verification — ``license_verified`` stays false and the canonical
  ``Other (Public Domain) / Open Data`` label stays a cited source claim, not a
  local legal conclusion;
* a normalization/crosswalk module — it preserves the supplied ward-number and
  ward-name values verbatim and does not invent a ward mapping.

Dataset identity
----------------
* Canonical dataset id referenced by this handler: ``WTR-005``.
* Ingestion-registry slug: ``wtr-005`` (derived through the canonical/slug
  boundary, same as the other handlers).
* The handler represents one *local artifact* already present under
  ``data/raw/WTR-005/``. It does not assert that this artifact is identical to
  the BWSSB Data Collection resource described in the canonical inventory, only
  that it is the artifact the operator chose to register under that canonical id
  for this milestone.

Evidence rules this handler follows
-----------------------------------
* ``build_provenance(...)`` records the *actual* local path, byte size, SHA-256,
  timestamp and a provenance record whose ``source_uri`` is the local artifact
  path, ``acquisition_method`` is ``local-registration``, and ``publisher`` /
  ``license`` are carried over from the canonical record (still unverified).
  A local registration is never represented as a network download.
* ``resource_provenance()`` makes the mapping caveat explicit and cites the
  report and audit that document the unresolved mapping/licence questions.
* Validation accepts only the bytes that were actually registered; it never
  re-fetch, re-normalize, or re-map data.

Validation scope
----------------
* Single CSV structural check, same discipline as the other handlers: encoding,
  header presence, structural consistency, BOM/NUL, size/digest agreement with
  the recorded result.
* No semantic claim about ward meaning, consumption/demand equivalence, or August
  2025 time limitation is made by the handler. Those are analysis-layer concerns
  and are documented in the milestone report instead.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from pathlib import Path

from civicmind.ingestion.base import (
    AcquisitionResult,
    DatasetIngestor,
    ProvenanceRecord,
    QualityIssue,
    SourceDescriptor,
    ValidationReport,
    _no_op_limits,
)
from civicmind.ingestion.identifiers import source_slug
from civicmind.ingestion.transfer import sha256_file

#: Canonical dataset id this handler is intended to represent.
DATASET_ID = "WTR-005"
#: Ingestion-registry slug, derived through the canonical/slug boundary.
SOURCE_ID = source_slug(DATASET_ID)
#: Handler version, recorded in provenance.
HANDLER_VERSION = "0.1.0"
#: How this particular artifact was obtained, recorded on every artifact version.
ACQUISITION_METHOD = "local-registration"

TITLE = "BWSSB Water Consumption Snapshot (August 2025) - local artifact, WTR-005 candidate"
PUBLISHER = "BWSSB (via OpenCity); publisher identity not locally verified"
LICENSE = "Other (Public Domain) / Open Data"
DESCRIPTION = (
    "A single CSV supplied in the repository's raw-data staging area, registered "
    "locally through the WTR-005 candidate path for Milestone 8. This handler does "
    "not assert that the file is the same resource described by the canonical "
    "BWSSB Data Collection dataset; the mapping is documented as plausible but "
    "unverified in the project's own reports and audit."
)
UPDATE_FREQUENCY = "static (point-in-time snapshot)"
GEOGRAPHIC_SCOPE = "Bengaluru wards (as supplied in the file)"

#: Scope line recorded with every validation run from this handler.
VALIDATION_SCOPE = (
    "single CSV: encoding, header presence, structural consistency; local artifact only"
)

#: No network transfer is possible for this handler; limits exist only to satisfy
#: the base contract and to be inspectable by plan/status code.
#: A concrete ``_limits`` is intentionally omitted; the base ``DatasetIngestor.limits``
#: property falls back to a shared no-op bounds object for this handler.
LIMITS = None

_UTF8_BOMS = (b"\xef\xbb\xbf",)

#: Expected column header, matched case-insensitively and trimmed. The handler does
#: not assert this is the only valid header shape; it reports what it sees.
_EXPECTED_HEADER = (
    "Ward number",
    "Ward Name",
    "Number of Connections",
    "Consumption in ML",
)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Wtr005LocalIngestor(DatasetIngestor):
    """A handler that validates a pre-existing local artifact, not a fetcher.

    Constructing or registering it performs no I/O. ``acquire_local_artifact`` is
    the small local-registration entry point: it measures the already-present file
    and returns an ``AcquisitionResult`` shaped for the rest of the pipeline.
    """

    HANDLER_VERSION = HANDLER_VERSION
    DATASET_ID = DATASET_ID
    SOURCE_ID = SOURCE_ID
    _limits = LIMITS

    def __init__(self, *, artifact_path: Path | None = None) -> None:
        self.artifact_path = artifact_path

    # -- contract -----------------------------------------------------------
    def describe(self) -> SourceDescriptor:
        return SourceDescriptor(
            source_id=SOURCE_ID,
            title=TITLE,
            publisher=PUBLISHER,
            license=LICENSE,
            description=DESCRIPTION,
            uri="file:" + str(self.artifact_path) if self.artifact_path is not None else "file:",
            update_frequency=UPDATE_FREQUENCY,
            geographic_scope=GEOGRAPHIC_SCOPE,
            tags=("water", "bengaluru", "bwssb", "local-artifact", "wtr-005-candidate"),
        )

    def acquire(self, destination: Path) -> AcquisitionResult:
        """This handler does not fetch anything from the network.

        The local-artifact registration path does not use ``acquire``. It exists
        only because the existing contract requires it; it refuses to pretend a
        local registration is a download.
        """
        raise NotImplementedError(
            "Wtr005LocalIngestor does not download data. Use acquire_local_artifact "
            "for the local registration path."
        )

    @property
    def limits(self) -> object:
        return getattr(self, "_limits", None) or _no_op_limits()

    # -- local registration -------------------------------------------------
    def acquire_local_artifact(self, artifact_path: Path) -> AcquisitionResult:
        """Measure an already-present local CSV and return an acquisition result.

        This is the local-artifact registration entry point. It does not move,
        copy, normalize, or rename the source file. It measures what is already
        there and returns the measured records so the pipeline can treat the file
        as the dataset's active artifact.

        Parameters
        ----------
        artifact_path:
            Path to the existing CSV. Must be a real file inside the designated
            raw-data tree; paths outside that tree are rejected so that arbitrary
            filesystem paths are not admitted under a dataset identity.
        """
        artifact_path = Path(artifact_path).resolve()
        _assert_within_raw_tree(artifact_path)
        if not artifact_path.is_file():
            raise ValueError(f"artifact_path is not a readable file: {artifact_path}")
        return _measure_local_csv(artifact_path)

    # -- validation --------------------------------------------------------
    def validate(self, result: AcquisitionResult) -> ValidationReport:
        """Validate the registered local artifact.

        Scope is deliberately narrow and identical in spirit to the other handlers:
        encoding, header presence, structural consistency, and agreement with the
        recorded byte size and SHA-256. No semantic ward/crosswalk/consumption claim
        is made here.
        """
        return _validate_local_csv(result)

    # -- provenance -------------------------------------------------------
    def build_provenance(self, result: AcquisitionResult) -> ProvenanceRecord:
        """Record provenance under the canonical id, with an honest local method.

        ``source_uri`` is the local artifact path, not a network URL. Publisher and
        license are carried from the canonical claim and stay unverified.
        """
        base = DatasetIngestor._build_provenance_for(self, result)
        return ProvenanceRecord(
            source_id=DATASET_ID,
            title=TITLE,
            publisher=PUBLISHER,
            license=LICENSE,
            source_uri=_local_uri(result.local_path),
            acquired_at=result.acquired_at,
            acquisition_method=result.method or ACQUISITION_METHOD,
            local_path=_local_str(result.local_path),
            checksum_sha256=result.checksum_sha256,
            byte_size=result.byte_size,
            handler=f"{__name__}.Wtr005LocalIngestor",
            handler_version=HANDLER_VERSION,
            civicmind_version=base.civicmind_version,
        )

    def resource_provenance(self) -> dict[str, str]:
        """Return the recorded provenance of this registration, with the caveat visible."""
        return {
            "registration_method": "local-registration",
            "source_uri_kind": "local filesystem artifact path",
            "artifact_placed_by": "operator (not fetched by this handler)",
            "canonical_mapping_status": "plausible but unverified",
            "license_status": "cited source claim only; not locally verified",
            "caveat": (
                "This handler does not establish that the registered CSV is the same "
                "resource described by the canonical BWSSB Data Collection dataset. "
                "The mapping, source identity, and licence are documented as unresolved "
                "in the project's own reports and audit; the evidence record must say so."
            ),
        }


def _local_uri(path: Path | None) -> str | None:
    return None if path is None else "file:" + str(path)


def _local_str(path: Path | None) -> str | None:
    return None if path is None else str(path)


def _measure_local_csv(artifact_path: Path) -> AcquisitionResult:
    """Measure an existing CSV and return a complete, honest acquisition result."""
    raw = artifact_path.read_bytes()
    byte_size = len(raw)
    checksum_sha256 = sha256_file(artifact_path)
    acquired_at = _utc_now()
    return AcquisitionResult(
        source_id=DATASET_ID,
        acquired_at=acquired_at,
        method=ACQUISITION_METHOD,
        local_path=artifact_path,
        byte_size=byte_size,
        checksum_sha256=checksum_sha256,
        record_count=None,
        notes=(f"local registration of existing file; bytes={byte_size} sha256={checksum_sha256}"),
    )


def _expected_header_match(actual_header: list[str]) -> tuple[bool, list[str]]:
    """Compare the actual header against the expected header case-insensitively.

    Returns ``(matched, missing)`` where ``missing`` lists the expected fields not
    found in the actual header. This is a report, not a schema enforcement.
    """
    lowered = [h.strip().lower() for h in actual_header]
    missing: list[str] = []
    for expected in _EXPECTED_HEADER:
        if expected.lower() not in lowered:
            missing.append(expected)
    return (len(missing) == 0, missing)


def _validate_local_csv(result: AcquisitionResult) -> ValidationReport:
    """Validate the registered local artifact."""
    issues: list[QualityIssue] = []
    path = result.local_path

    if path is None:
        issues.append(
            QualityIssue(
                severity="error",
                code="ARTIFACT_PATH_MISSING",
                message="acquisition result carries no local path to validate",
            )
        )
        return _report(issues)

    path = Path(path)
    if not path.exists():
        issues.append(
            QualityIssue(
                severity="error",
                code="ARTIFACT_MISSING",
                message=f"artifact does not exist: {path}",
                context={"path": str(path)},
            )
        )
        return _report(issues)

    if not path.is_file():
        issues.append(
            QualityIssue(
                severity="error",
                code="ARTIFACT_NOT_A_FILE",
                message=f"artifact is not a regular file: {path}",
                context={"path": str(path)},
            )
        )
        return _report(issues)

    measured_size = path.stat().st_size
    if measured_size == 0:
        issues.append(
            QualityIssue(
                severity="error",
                code="EMPTY_FILE",
                message=f"artifact is empty: {path}",
                context={"path": str(path)},
            )
        )
        return _report(issues)

    if result.byte_size is not None and measured_size != result.byte_size:
        issues.append(
            QualityIssue(
                severity="error",
                code="SIZE_MISMATCH",
                message=(
                    f"recorded byte size {result.byte_size} does not match the measured "
                    f"{measured_size} bytes"
                ),
                context={"recorded": result.byte_size, "measured": measured_size},
            )
        )

    measured_digest = sha256_file(path)
    if result.checksum_sha256 is not None and measured_digest != result.checksum_sha256:
        issues.append(
            QualityIssue(
                severity="error",
                code="CHECKSUM_MISMATCH",
                message="recomputed SHA-256 does not match the recorded digest",
                context={"recorded": result.checksum_sha256, "measured": measured_digest},
            )
        )

    raw = path.read_bytes()
    if raw.startswith(_UTF8_BOMS):
        issues.append(
            QualityIssue(
                severity="info",
                code="BOM_PRESENT",
                message="artifact begins with a UTF-8 BOM; it is decoded as utf-8-sig",
            )
        )
    if b"\x00" in raw:
        issues.append(
            QualityIssue(
                severity="warning",
                code="NUL_BYTES",
                message="artifact contains NUL bytes; the file may be binary or corrupted",
            )
        )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        issues.append(
            QualityIssue(
                severity="error",
                code="ENCODING_ERROR",
                message=f"artifact is not valid UTF-8: {exc}",
            )
        )
        return _report(issues)

    issues.extend(_structural_issues(text))
    return _report(issues)


def _report(issues: list[QualityIssue]) -> ValidationReport:
    return ValidationReport(
        source_id=DATASET_ID,
        passed=not any(issue.severity == "error" for issue in issues),
        issues=tuple(issues),
    )


def _structural_issues(text: str) -> list[QualityIssue]:
    """Return structural CSV findings for the decoded artifact text."""
    issues: list[QualityIssue] = []
    rows: list[list[str]] = []
    parse_failure: csv.Error | None = None
    reader = csv.reader(io.StringIO(text), strict=True)
    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            parse_failure = exc
            break
        rows.append(row)

    if parse_failure is not None:
        return [
            QualityIssue(
                severity="error",
                code="CSV_PARSE_ERROR",
                message=(
                    f"artifact is not structurally consistent CSV: {parse_failure} "
                    f"(the parser stopped after {len(rows)} row(s))"
                ),
                context={"rows_parsed": len(rows), "parser": "csv.reader(strict=True)"},
            )
        ]

    rows = [row for row in rows if row]
    if not rows:
        return [
            QualityIssue(
                severity="error",
                code="HEADER_MISSING",
                message="artifact has no header row",
            )
        ]

    header = rows[0]
    if all(not field.strip() for field in header):
        issues.append(
            QualityIssue(
                severity="error",
                code="HEADER_EMPTY",
                message="artifact header row is empty",
            )
        )

    matched, missing = _expected_header_match(header)
    if not matched:
        issues.append(
            QualityIssue(
                severity="info",
                code="HEADER_FIELD_MISMATCH",
                message=(
                    "supplied header does not match the documented BWSSB column hints; "
                    "the artifact is still structurally valid CSV, but the field mapping "
                    "is not asserted by this handler"
                ),
                context={
                    "expected_columns": list(_EXPECTED_HEADER),
                    "missing_expected_columns": missing,
                    "actual_header": list(header),
                },
            )
        )

    data_rows = rows[1:]
    if not data_rows:
        issues.append(
            QualityIssue(
                severity="warning",
                code="NO_DATA_ROWS",
                message="artifact contains a header but no data rows",
            )
        )

    width = len(header)
    ragged = sum(1 for row in data_rows if len(row) != width)
    if ragged:
        issues.append(
            QualityIssue(
                severity="warning",
                code="RAGGED_ROWS",
                message=(
                    f"{ragged} data row(s) do not match the header's {width} field(s); "
                    "the schema is unasserted, so this is reported rather than enforced"
                ),
                context={"ragged_rows": ragged, "header_fields": width},
            )
        )

    return issues


def _assert_within_raw_tree(path: Path) -> None:
    """Reject artifact paths that are not inside the designated raw-data tree.

    This is the narrow local-artifact safeguard: the handler does not admit an
    arbitrary filesystem path under a dataset identity. The caller is responsible
    for resolving the path, which is why this check uses the resolved absolute
    form.
    """
    resolved = path.resolve()
    raw_marker = resolved.parts
    if "data" not in raw_marker or "raw" not in raw_marker:
        raise ValueError(
            f"artifact_path must live under the repository's data/raw tree, not {resolved}"
        )
    data_index = raw_marker.index("data")
    if tuple(raw_marker[data_index : data_index + 2]) != ("data", "raw"):
        raise ValueError(f"artifact_path must live under data/raw/, not {resolved}")


def sha256_of(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


__all__ = [
    "ACQUISITION_METHOD",
    "DATASET_ID",
    "HANDLER_VERSION",
    "SOURCE_ID",
    "VALIDATION_SCOPE",
    "Wtr005LocalIngestor",
    "sha256_of",
]
