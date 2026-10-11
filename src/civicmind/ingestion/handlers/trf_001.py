"""Ingestion handler for the TRF-001 pilot dataset (Traffic Accidents in India).

Dataset identity
----------------
* Canonical dataset id: ``TRF-001`` — "Traffic Accidents in India (Smart Cities)".
* Publisher: Smart Cities Mission / Ministry of Housing & Urban Affairs, reached
  through the **OpenCity mirror**. OpenCity is a re-publisher, not the primary
  portal, and the provenance record says so.
* Resource URL provenance: quoted verbatim from
  ``docs/datasets/ingestion_plan.md`` line 251 and verified by a bounded
  endpoint check on 2026-10-11 (HTTP 200, ``Content-Type: text/csv``,
  ``Content-Length: 2676``, no redirect). That check is a candidate endpoint
  test, never proof that the resource is the intended dataset: :meth:`validate`
  re-measures the artifact, and the licence stays unverified
  (``license_verified=false``, conflict C-07).

Two identifier namespaces
-------------------------
``SourceDescriptor.source_id`` must be a lowercase slug, while canonical dataset
ids are uppercase. The two values therefore cannot coincide, so they are mapped
through the single documented boundary in
:mod:`civicmind.ingestion.identifiers` rather than compared by hand:

* :data:`DATASET_ID` (``TRF-001``) is the canonical dataset id used by the
  catalog, the eligibility policy, the four-axis record, the evidence document
  and every CLI report.
* :data:`SOURCE_ID` (``trf-001``) is the ingestion-registry slug, derived from
  the canonical id by :func:`~civicmind.ingestion.identifiers.source_slug` so
  the two can never drift apart.

Every recorded value uses the canonical id: ``AcquisitionResult.source_id``,
:meth:`build_provenance`, the validation report, and therefore the four-axis
record and the evidence file. The slug appears only where a slug is required —
the handler registry and the descriptor. Acquisition still resolves eligibility
through
:func:`~civicmind.ingestion.integration.resolve_dataset_for_ingestion` with an
explicit :class:`~civicmind.ingestion.policy.ConditionalAuthorization`, the
same eligibility code path every other dataset uses.

Evidence limits
---------------
The documented data dictionary is **partial** (3 of the 9 columns now
measurable), so validation asserts only structure and explicitly states that no
required-column or semantic check is made. Anything else would invent a schema.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from civicmind.ingestion.base import (
    AcquisitionResult,
    DatasetIngestor,
    ProvenanceRecord,
    QualityIssue,
    SourceDescriptor,
    ValidationReport,
)
from civicmind.ingestion.identifiers import source_slug
from civicmind.ingestion.transfer import (
    TransferLimits,
    download_to_file,
    sha256_file,
)

#: Canonical dataset id (catalog, policy, evidence and four-axis record
#: namespace). This is the identity recorded everywhere; it is never rewritten.
DATASET_ID = "TRF-001"
#: Ingestion-registry slug, derived from the canonical id through the single
#: mapping boundary so the two namespaces cannot drift apart.
SOURCE_ID = source_slug(DATASET_ID)
#: Handler version, recorded in the provenance trail.
HANDLER_VERSION = "1.0"
#: How the bytes are obtained, recorded on every artifact version.
ACQUISITION_METHOD = "https-get"

TITLE = "Traffic Accidents in India (Smart Cities)"
PUBLISHER = "Smart Cities Mission, Ministry of Housing & Urban Affairs (via OpenCity mirror)"
#: Recorded exactly as the source states it; not a verified legal conclusion (C-07).
LICENSE = "Other (Public Domain) / Open Data"
DESCRIPTION = (
    "Traffic-related injuries and fatalities reported for eight Indian cities under the "
    "Smart Cities Mission, mirrored by the OpenCity re-publisher."
)
UPDATE_FREQUENCY = "static (not actively updated)"
GEOGRAPHIC_SCOPE = "8 Indian cities"

#: The dataset page this resource belongs to, as recorded in the canonical CSV.
DATASET_PAGE_URL = "https://data.opencity.in/dataset/traffic-accidents-in-india"

#: The exact resource URL, quoted from the ingestion plan rather than reconstructed.
RESOURCE_URL_CITATION = "docs/datasets/ingestion_plan.md#L251"
RESOURCE_URL_VERIFIED_AT = "2026-10-11"
RESOURCE_URL_VERIFICATION = (
    "bounded endpoint check: HTTP 200, Content-Type text/csv, Content-Length 2676, "
    "no redirect followed, dataset page lists this single resource"
)
RESOURCE_URL = (
    "https://data.opencity.in/dataset/ffd84c06-bc22-4716-9765-0a458d4f7571"
    "/resource/d43dcdc6-f35d-454d-8aaf-504a499f56a5"
    "/download/a224b81b-9d1c-46dc-9bbd-71adfedfddac.csv"
)

#: Pilot guard on a single transfer. The verified resource is 2676 bytes; this
#: ceiling leaves room for a revised revision without allowing a runaway fetch.
DEFAULT_MAX_BYTES = 1 * 1024 * 1024

#: Base name of an acquired artifact inside ``data/raw/TRF-001/``.
ARTIFACT_PREFIX = "trf-001-traffic-accidents"

#: Columns the source documentation names. They are *hints*, not an asserted
#: schema: the data dictionary is partial, so a missing hint is a warning.
DOCUMENTED_COLUMN_HINTS = (
    "City",
    "Total Registered Motor Vehicles (as of 2016)",
    "Year",
)

#: Scope line recorded with every validation run from this handler.
VALIDATION_SCOPE = "single CSV: encoding, header presence, structural consistency"

_UTF8_BOMS = (b"\xef\xbb\xbf",)


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


class Trf001Ingestor(DatasetIngestor):
    """Acquire and validate the TRF-001 CSV artifact.

    The handler never decides whether the dataset *may* be ingested — that is
    the eligibility policy's job. Constructing or registering it performs no
    I/O; only :meth:`acquire` touches the network.
    """

    HANDLER_VERSION = HANDLER_VERSION
    DATASET_ID = DATASET_ID
    SOURCE_ID = SOURCE_ID

    def __init__(
        self,
        *,
        resource_url: str | None = None,
        limits: TransferLimits | None = None,
        clock: object = _utc_now,
        sleep: object = None,
    ) -> None:
        self.resource_url = resource_url if resource_url is not None else RESOURCE_URL
        self.limits = limits if limits is not None else TransferLimits(max_bytes=DEFAULT_MAX_BYTES)
        self._clock = clock
        self._sleep = sleep

    # -- contract -----------------------------------------------------------
    def describe(self) -> SourceDescriptor:
        """Return static, verifiable metadata identifying this source."""
        return SourceDescriptor(
            source_id=SOURCE_ID,
            title=TITLE,
            publisher=PUBLISHER,
            license=LICENSE,
            description=DESCRIPTION,
            uri=self.resource_url,
            update_frequency=UPDATE_FREQUENCY,
            geographic_scope=GEOGRAPHIC_SCOPE,
            tags=("traffic", "mobility", "smart-cities", "open-city-mirror"),
        )

    def acquire(self, destination: Path) -> AcquisitionResult:
        """Stream the resource into ``destination`` and return measured facts."""
        destination = Path(destination)
        stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
        filename = self._unique_filename(destination, stamp)
        kwargs: dict[str, object] = {"limits": self.limits, "clock": self._now}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        outcome = download_to_file(self.resource_url, destination, filename=filename, **kwargs)
        return AcquisitionResult(
            source_id=DATASET_ID,
            acquired_at=outcome.retrieved_at,
            method=ACQUISITION_METHOD,
            local_path=outcome.local_path,
            byte_size=outcome.byte_size,
            checksum_sha256=outcome.checksum_sha256,
            record_count=None,
            notes=(
                f"http={outcome.status} content-type={outcome.content_type or 'unknown'} "
                f"attempts={outcome.attempts} max_bytes={self.limits.max_bytes} "
                f"url={self.resource_url}"
            ),
        )

    def validate(self, result: AcquisitionResult) -> ValidationReport:
        """Check the acquired artifact and report measured quality issues.

        Only structural facts are asserted. Because the documented data
        dictionary is partial, no required-column or semantic rule is invented;
        the report says so explicitly instead of implying a schema check
        happened.
        """
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
            return self._report(issues)

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
            return self._report(issues)
        if not path.is_file():
            issues.append(
                QualityIssue(
                    severity="error",
                    code="ARTIFACT_NOT_A_FILE",
                    message=f"artifact is not a regular file: {path}",
                    context={"path": str(path)},
                )
            )
            return self._report(issues)

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
            return self._report(issues)

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
            return self._report(issues)

        issues.extend(self._structural_issues(text))
        return self._report(issues)

    # -- helpers -----------------------------------------------------------
    def build_provenance(self, result: AcquisitionResult) -> ProvenanceRecord:
        """Record provenance under the canonical dataset id.

        The registry keys handlers by slug, but a provenance trail describes
        the *dataset*, and the record's validation gate compares the canonical
        id, so the canonical id is what is recorded. The source URI is the
        exact URL this handler fetched, not the dataset landing page.
        """
        provenance = super().build_provenance(result)
        return replace(provenance, source_id=DATASET_ID)

    def resource_provenance(self) -> dict[str, str]:
        """Return the recorded provenance of the resource URL, for the evidence file."""
        return {
            "resource_url": self.resource_url,
            "dataset_page_url": DATASET_PAGE_URL,
            "cited_in": RESOURCE_URL_CITATION,
            "verified_at": RESOURCE_URL_VERIFIED_AT,
            "verification": RESOURCE_URL_VERIFICATION,
            "caveat": (
                "endpoint reachability is not proof that the resource is the intended "
                "dataset; the artifact is re-measured on validation"
            ),
        }

    def _now(self) -> datetime:
        """Return the current UTC time using the injected clock."""
        clock = self._clock
        return clock() if callable(clock) else _utc_now()

    def _unique_filename(self, destination: Path, stamp: str) -> str:
        """Return a filename that does not collide with an existing artifact."""
        candidate = f"{ARTIFACT_PREFIX}-{stamp}.csv"
        suffix = 2
        while (destination / candidate).exists():
            candidate = f"{ARTIFACT_PREFIX}-{stamp}-{suffix}.csv"
            suffix += 1
        return candidate

    def _report(self, issues: list[QualityIssue]) -> ValidationReport:
        """Build the report, treating any error-severity issue as a failure."""
        return ValidationReport(
            source_id=DATASET_ID,
            passed=not any(issue.severity == "error" for issue in issues),
            issues=tuple(issues),
        )

    def _structural_issues(self, text: str) -> list[QualityIssue]:
        """Return structural CSV findings for the decoded artifact text.

        The text is parsed by the standard library's own CSV reader in strict
        mode, over the decoded bytes rather than over ``split(",")`` output. A
        strict parse failure (an unterminated quoted field, a stray quote inside
        an unquoted field, a field above the parser's limit) is reported as an
        ``error``: the artifact is not structurally consistent CSV, and saying so
        is a measurement, not an assumption. The rows are never split on commas
        by hand, because a quoted field may legally contain commas and newlines.
        """
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
        unnamed = [index for index, field in enumerate(header) if not field.strip()]
        if unnamed and len(unnamed) < len(header):
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="HEADER_UNNAMED_FIELD",
                    message=f"header has unnamed field position(s): {unnamed}",
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

        found = [hint for hint in DOCUMENTED_COLUMN_HINTS if hint in header]
        missing = [hint for hint in DOCUMENTED_COLUMN_HINTS if hint not in header]
        issues.append(
            QualityIssue(
                severity="info",
                code="SCHEMA_NOT_ASSERTED",
                message=(
                    "no required-column or semantic rule is asserted: the documented data "
                    f"dictionary is partial. Documented hints present: {found or 'none'}"
                ),
                context={"documented_hints_present": found, "documented_hints_missing": missing},
            )
        )
        for hint in missing:
            issues.append(
                QualityIssue(
                    severity="warning",
                    code="DOCUMENTED_COLUMN_ABSENT",
                    message=f"documented column hint {hint!r} is absent from the artifact header",
                )
            )
        return issues


def sha256_of(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data`` (small-payload helper for callers/tests)."""
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "ACQUISITION_METHOD",
    "ARTIFACT_PREFIX",
    "DATASET_ID",
    "DATASET_PAGE_URL",
    "DEFAULT_MAX_BYTES",
    "DOCUMENTED_COLUMN_HINTS",
    "HANDLER_VERSION",
    "RESOURCE_URL",
    "RESOURCE_URL_CITATION",
    "RESOURCE_URL_VERIFICATION",
    "RESOURCE_URL_VERIFIED_AT",
    "SOURCE_ID",
    "Trf001Ingestor",
    "VALIDATION_SCOPE",
    "sha256_of",
]
