"""End-to-end local research run for the supplied CSV artifacts.

This module is intentionally an orchestration layer, not a new ingestion
architecture. It maps the five CSVs known to the AI layer, runs the existing
ingestion pilot only where a registered local-artifact handler exists
(``WTR-005``), and records every unsupported local file honestly.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import sys
import textwrap
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from civicmind.ai.datasets import (
    LocalDatasetSpec,
    dataset_path,
    list_dataset_specs,
    load_dataset,
)
from civicmind.config import Settings
from civicmind.ingestion import pilot
from civicmind.ingestion.handlers import (
    UnsupportedDatasetError,
    build_pilot_handler,
)
from civicmind.ingestion.identifiers import source_slug
from civicmind.ingestion.sources import load_canonical_registry
from civicmind.profiling.csv_profile import ProfileError

CLIENT_TIMEZONE = timezone(timedelta(hours=5, minutes=30), "Asia/Calcutta")
DEFAULT_OUTPUT_SUBDIR = Path("ingestion") / "research_run"
DEFAULT_RATIONALE = (
    "Research run local-artifact registration of the supplied BWSSB August 2025 snapshot"
)


@dataclass(frozen=True)
class ResearchRunReport:
    """Paths and payload from one generated research run."""

    output_dir: Path
    results: dict[str, Any]
    markdown_path: Path
    json_path: Path
    csv_path: Path
    pdf_path: Path
    manifest_path: Path

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe command result."""
        return {
            "output_dir": str(self.output_dir),
            "markdown_path": str(self.markdown_path),
            "json_path": str(self.json_path),
            "csv_path": str(self.csv_path),
            "pdf_path": str(self.pdf_path),
            "manifest_path": str(self.manifest_path),
            "dataset_count": len(self.results.get("datasets", [])),
        }


def build_local_dataset_mapping(settings: Settings) -> list[dict[str, Any]]:
    """Map every declared local CSV to its ingestion support status."""
    registry = load_canonical_registry()
    mappings: list[dict[str, Any]] = []
    for spec in list_dataset_specs():
        path = dataset_path(settings, spec.dataset_id)
        exists = path.is_file()
        digest = _sha256_file(path) if exists else None
        byte_size = path.stat().st_size if exists else None

        canonical_id = spec.canonical_id
        canonical_title = None
        catalog_dataset_url = None
        catalog_download_url = None
        ingestion_source_id = None
        handler_supported = False
        handler_support_detail = "no canonical ingestion mapping is recorded"
        provenance_confidence = spec.mapping_status

        if canonical_id is not None:
            record = registry.get(canonical_id)
            canonical_title = record.title
            catalog_dataset_url = record.dataset_url
            catalog_download_url = record.download_url
            ingestion_source_id = source_slug(canonical_id)
            try:
                handler = build_pilot_handler(canonical_id)
            except UnsupportedDatasetError:
                handler_support_detail = f"{canonical_id} has no registered handler"
            else:
                if hasattr(handler, "acquire_local_artifact"):
                    handler_supported = True
                    handler_support_detail = (
                        f"{canonical_id} supports local-artifact registration"
                    )
                else:
                    handler_support_detail = (
                        f"{canonical_id} handler exists but is not local-artifact capable"
                    )

        mappings.append(
            {
                "local_dataset_id": spec.dataset_id,
                "canonical_dataset_id": canonical_id,
                "canonical_title": canonical_title,
                "catalog_dataset_url_claim": catalog_dataset_url,
                "catalog_download_url_claim": catalog_download_url,
                "ingestion_source_id": ingestion_source_id,
                "original_filename": spec.filename,
                "local_path": str(path),
                "file_exists": exists,
                "byte_size": byte_size,
                "sha256": digest,
                "subject": spec.title,
                "description": spec.description,
                "geographic_scope": spec.geographic_scope,
                "geographic_granularity": spec.geographic_granularity,
                "temporal_coverage": spec.time_period,
                "handler_supported": handler_supported,
                "handler_support_detail": handler_support_detail,
                "provenance_confidence": provenance_confidence,
                "mapping_status": spec.mapping_status,
                "license_status": spec.license_status,
                "source_url": None,
                "retrieval_date": None,
                "unresolved_questions": _unresolved_questions(spec, handler_supported),
            }
        )
    return mappings


def run_research_ingestion(
    settings: Settings,
    *,
    output_dir: Path | None = None,
    rationale: str = DEFAULT_RATIONALE,
    clock: Callable[[], datetime] | None = None,
) -> ResearchRunReport:
    """Execute the local research run and write Markdown/JSON/CSV/PDF outputs."""
    if not rationale.strip():
        raise ValueError("rationale must be non-empty")

    timestamp = (clock or _now_client_tz)()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("run timestamp must be timezone-aware")

    out_dir = (
        Path(output_dir)
        if output_dir is not None
        else settings.artifacts_dir / DEFAULT_OUTPUT_SUBDIR
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_results = [
        _run_one_dataset(settings, item, rationale)
        for item in build_local_dataset_mapping(settings)
    ]
    results: dict[str, Any] = {
        "run": {
            "objective": (
                "Complete supported local dataset ingestion and generate research deliverables"
            ),
            "timestamp": timestamp.isoformat(),
            "timezone": timestamp.tzname() or "unknown",
            "project_root": str(settings.project_root),
            "raw_data_dir": str(settings.raw_data_dir),
            "artifacts_dir": str(settings.artifacts_dir),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "network_performed": False,
            "model_inference_performed": False,
        },
        "datasets": dataset_results,
        "limitations": [
            "Only WTR-005 currently supports local-artifact registration.",
            (
                "RA2019 files are available local AI datasets but are not registered "
                "canonical ingestion sources."
            ),
            (
                "Source URLs, retrieval dates, and licences for the local CSV files "
                "were not verified from repository evidence."
            ),
        ],
    }

    markdown_path = out_dir / "ingestion_report.md"
    json_path = out_dir / "ingestion_results.json"
    csv_path = out_dir / "ingestion_summary.csv"
    pdf_path = out_dir / "ingestion_summary.pdf"
    manifest_path = out_dir / "manifest.json"

    markdown = _render_markdown(results)
    markdown_path.write_text(markdown, encoding="utf-8", newline="\n")
    json_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_summary_csv(csv_path, dataset_results)
    _write_pdf_report(pdf_path, _pdf_lines(results))

    manifest = _build_manifest((markdown_path, json_path, csv_path, pdf_path))
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    return ResearchRunReport(
        output_dir=out_dir,
        results=results,
        markdown_path=markdown_path,
        json_path=json_path,
        csv_path=csv_path,
        pdf_path=pdf_path,
        manifest_path=manifest_path,
    )


def _run_one_dataset(
    settings: Settings, mapping: Mapping[str, Any], rationale: str
) -> dict[str, Any]:
    result = dict(mapping)
    result["local_inspection"] = _inspect_local_csv(settings, str(mapping["local_dataset_id"]))
    result["registration"] = {
        "status": "not_registered_unsupported",
        "detail": mapping["handler_support_detail"],
    }
    result["validation"] = {"status": "not_run", "passed": None, "issues": []}
    result["profiling"] = {"status": "not_run", "profile_path": None}
    result["evidence_path"] = None
    result["final_status"] = None

    if not mapping["file_exists"]:
        result["registration"] = {"status": "missing_local_file", "detail": "source CSV absent"}
        return result

    if not mapping["handler_supported"]:
        result["validation"] = {
            "status": "not_run_no_registered_handler",
            "passed": None,
            "issues": [],
        }
        result["profiling"] = {
            "status": "local_inspected_not_ingestion_profiled",
            "profile_path": None,
        }
        return result

    canonical_id = str(mapping["canonical_dataset_id"])
    path = Path(str(mapping["local_path"]))
    digest = str(mapping["sha256"])
    status_before = pilot.status(settings, dataset_id=canonical_id)
    active = status_before.active_artifact
    if active is not None and _same_active_artifact(active, path, digest):
        result["registration"] = {
            "status": "already_registered",
            "detail": "active artifact path and SHA-256 already match the local CSV",
            "artifact_version": active["version"],
        }
    else:
        acquired = pilot.acquire(
            settings,
            dataset_id=canonical_id,
            rationale=rationale,
            local_artifact_path=path,
        )
        result["registration"] = {
            "status": "registered",
            "detail": "local artifact measured and recorded through the existing pilot",
            "artifact_version": acquired.artifact_version,
            "byte_size": acquired.byte_size,
            "sha256": acquired.checksum_sha256,
            "acquired_at": acquired.acquired_at.isoformat(),
            "method": acquired.method,
        }

    validation = pilot.validate(settings, dataset_id=canonical_id)
    result["validation"] = validation.as_dict()

    if validation.passed:
        status_after_validation = pilot.status(settings, dataset_id=canonical_id)
        active_after_validation = status_after_validation.active_artifact
        profile_path = (
            _existing_profile_path(settings, canonical_id, int(active_after_validation["version"]))
            if active_after_validation is not None
            else None
        )
        if (
            status_after_validation.axes["profiling_state"] == "PROFILED"
            and profile_path is not None
        ):
            result["profiling"] = {
                "status": "already_profiled",
                "profile_path": str(profile_path),
                "state": "PROFILED",
                "state_changed": False,
            }
        else:
            try:
                profiled = pilot.profile(settings, dataset_id=canonical_id)
            except ProfileError as exc:
                result["profiling"] = {
                    "status": "profile_failed",
                    "profile_path": None,
                    "error": str(exc),
                }
            else:
                result["profiling"] = profiled.as_dict()
    else:
        result["profiling"] = {
            "status": "skipped_validation_failed",
            "profile_path": None,
        }

    final_status = pilot.status(settings, dataset_id=canonical_id)
    result["final_status"] = final_status.as_dict()
    result["evidence_path"] = final_status.evidence_path
    return result


def _inspect_local_csv(settings: Settings, dataset_id: str) -> dict[str, Any]:
    """Read a local CSV through the AI dataset loader for non-ingestion facts."""
    try:
        loaded = load_dataset(settings, dataset_id)
    except Exception as exc:  # noqa: BLE001 - report the failure in the deliverable.
        return {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "rows": None,
            "columns": None,
            "encoding": None,
        }
    return {
        "status": "loaded",
        "rows": int(len(loaded.dataframe)),
        "columns": int(len(loaded.columns)),
        "encoding": loaded.encoding,
        "column_names": list(loaded.columns),
    }


def _unresolved_questions(spec: LocalDatasetSpec, handler_supported: bool) -> list[str]:
    questions = [
        "Exact source URL is not verified from repository evidence.",
        "Retrieval date is not verified from repository evidence.",
        f"Licence status: {spec.license_status}.",
    ]
    if spec.canonical_id is None:
        questions.append("No canonical ingestion dataset ID is recorded for this local CSV.")
    elif not handler_supported:
        questions.append("Canonical dataset has no supported local-artifact registration path.")
    if spec.mapping_status != "verified":
        questions.append(f"Mapping status: {spec.mapping_status}.")
    return questions


def _same_active_artifact(active: Mapping[str, Any], path: Path, digest: str) -> bool:
    active_path = Path(str(active.get("path") or "")).resolve()
    return active_path == path.resolve() and active.get("checksum_sha256") == digest


def _existing_profile_path(settings: Settings, dataset_id: str, version: int) -> Path | None:
    directory = pilot.profile_dir(settings, dataset_id)
    preferred = directory / f"profile-v{version}.json"
    if preferred.is_file():
        return preferred
    matches = sorted(directory.glob(f"profile-v{version}-*.json"))
    return matches[-1] if matches else None


def _write_summary_csv(path: Path, datasets: list[Mapping[str, Any]]) -> None:
    fields = [
        "local_dataset_id",
        "canonical_dataset_id",
        "ingestion_source_id",
        "original_filename",
        "file_exists",
        "byte_size",
        "sha256",
        "handler_supported",
        "registration_status",
        "validation_status",
        "validation_passed",
        "profiling_status",
        "evidence_path",
        "provenance_confidence",
        "license_status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in datasets:
            validation = item.get("validation") or {}
            profiling = item.get("profiling") or {}
            registration = item.get("registration") or {}
            writer.writerow(
                {
                    "local_dataset_id": item.get("local_dataset_id"),
                    "canonical_dataset_id": item.get("canonical_dataset_id") or "",
                    "ingestion_source_id": item.get("ingestion_source_id") or "",
                    "original_filename": item.get("original_filename"),
                    "file_exists": item.get("file_exists"),
                    "byte_size": item.get("byte_size") or "",
                    "sha256": item.get("sha256") or "",
                    "handler_supported": item.get("handler_supported"),
                    "registration_status": registration.get("status", ""),
                    "validation_status": validation.get("state") or validation.get("status", ""),
                    "validation_passed": validation.get("passed"),
                    "profiling_status": profiling.get("state") or profiling.get("status", ""),
                    "evidence_path": item.get("evidence_path") or "",
                    "provenance_confidence": item.get("provenance_confidence"),
                    "license_status": item.get("license_status"),
                }
            )


def _render_markdown(results: Mapping[str, Any]) -> str:
    run = results["run"]
    datasets = results["datasets"]
    lines = [
        "# CivicMind AI Local Ingestion Research Run",
        "",
        "## Experiment Objective and Scope",
        "",
        (
            "Complete the supported local dataset ingestion path for the supplied CSVs, "
            "without network transfer or model inference, and record unsupported files honestly."
        ),
        "",
        "## Environment and Software Context",
        "",
        f"- Project root: `{run['project_root']}`",
        f"- Raw data directory: `{run['raw_data_dir']}`",
        f"- Artifacts directory: `{run['artifacts_dir']}`",
        f"- Python: `{run['python_version']}`",
        f"- Platform: `{run['platform']}`",
        f"- Run timestamp: `{run['timestamp']}` (`{run['timezone']}`)",
        f"- Network performed: `{str(run['network_performed']).lower()}`",
        f"- Model inference performed: `{str(run['model_inference_performed']).lower()}`",
        "",
        "## Pipeline",
        "",
        "```text",
        (
            "local CSVs -> mapping check -> supported handler? -> register WTR-005 "
            "-> validate -> profile -> deliverables"
        ),
        (
            "                         \\-> unsupported RA2019 files -> read-only "
            "inspection + explicit limitation"
        ),
        "```",
        "",
        "## Dataset Mapping and Outcomes",
        "",
        (
            "| Local dataset | Canonical ID | Handler support | Registration | "
            "Validation | Profiling | Provenance |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in datasets:
        validation = item.get("validation") or {}
        profiling = item.get("profiling") or {}
        registration = item.get("registration") or {}
        lines.append(
            "| {local} | {canonical} | {support} | {registration} | {validation} | "
            "{profiling} | {provenance} |".format(
                local=item["local_dataset_id"],
                canonical=item.get("canonical_dataset_id") or "unregistered",
                support="yes" if item.get("handler_supported") else "no",
                registration=registration.get("status", "unknown"),
                validation=validation.get("state") or validation.get("status", "unknown"),
                profiling=profiling.get("state") or profiling.get("status", "unknown"),
                provenance=item.get("provenance_confidence", "unknown"),
            )
        )
    lines.extend(
        [
            "",
            "## File Hashes and Sizes",
            "",
            "| File | Bytes | SHA-256 |",
            "| --- | ---: | --- |",
        ]
    )
    for item in datasets:
        lines.append(
            f"| `{item['original_filename']}` | {item.get('byte_size') or 'missing'} | "
            f"`{item.get('sha256') or 'missing'}` |"
        )
    lines.extend(
        [
            "",
            "## Validation and Profiling Details",
            "",
        ]
    )
    for item in datasets:
        inspection = item.get("local_inspection") or {}
        validation = item.get("validation") or {}
        profiling = item.get("profiling") or {}
        lines.extend(
            [
                f"### {item['local_dataset_id']}",
                "",
                f"- Subject: {item['subject']}",
                f"- Coverage: {item['geographic_scope']}; {item['temporal_coverage']}",
                f"- Catalog dataset URL claim: {item.get('catalog_dataset_url_claim') or 'none'}",
                (
                    "- Catalog download URL claim: "
                    f"{item.get('catalog_download_url_claim') or 'none'}"
                ),
                f"- Local inspection: {inspection.get('status')} "
                f"({inspection.get('rows')} rows, {inspection.get('columns')} columns, "
                f"encoding={inspection.get('encoding')})",
                f"- Registration: {(item.get('registration') or {}).get('status')}",
                f"- Validation: {validation.get('state') or validation.get('status')} "
                f"(passed={validation.get('passed')})",
                f"- Profiling: {profiling.get('state') or profiling.get('status')}",
                f"- Evidence path: {item.get('evidence_path') or 'none'}",
                "",
            ]
        )
        if validation.get("issues"):
            lines.append("Quality issues:")
            for issue in validation["issues"]:
                lines.append(
                    f"- `{issue.get('severity')}` `{issue.get('code')}`: {issue.get('message')}"
                )
            lines.append("")
        if item.get("unresolved_questions"):
            lines.append("Unresolved:")
            for question in item["unresolved_questions"]:
                lines.append(f"- {question}")
            lines.append("")
    lines.extend(
        [
            "## Reproduction Commands",
            "",
            "```powershell",
            (
                ".\\.venv\\Scripts\\python.exe -m civicmind.cli ingest research-run "
                "--authorize \"Research run local-artifact registration of the supplied "
                "BWSSB August 2025 snapshot\" --out artifacts\\ingestion\\research_run "
                "--json"
            ),
            "```",
            "",
            "## Limitations and Next Steps",
            "",
        ]
    )
    for limitation in results.get("limitations", []):
        lines.append(f"- {limitation}")
    lines.extend(
        [
            (
                "- Add dedicated canonical ingestion records/handlers before treating "
                "RA2019 CSVs as registered ingestion datasets."
            ),
            (
                "- Verify exact source URLs, retrieval dates, and licence terms from "
                "publisher evidence."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def _pdf_lines(results: Mapping[str, Any]) -> list[str]:
    run = results["run"]
    lines = [
        "CivicMind AI Local Ingestion Research Run",
        "",
        f"Run timestamp: {run['timestamp']} ({run['timezone']})",
        f"Project root: {run['project_root']}",
        "",
        "Pipeline:",
        "local CSVs -> mapping -> register WTR-005 -> validate -> profile -> reports",
        "RA2019 files -> read-only inspection -> unsupported-by-ingestion limitation",
        "",
        "Dataset outcomes:",
    ]
    for item in results["datasets"]:
        validation = item.get("validation") or {}
        profiling = item.get("profiling") or {}
        registration = item.get("registration") or {}
        lines.extend(
            textwrap.wrap(
                (
                    f"{item['local_dataset_id']}: "
                    f"canonical={item.get('canonical_dataset_id') or 'unregistered'}; "
                    f"handler={'yes' if item.get('handler_supported') else 'no'}; "
                    f"registration={registration.get('status')}; "
                    f"validation={validation.get('state') or validation.get('status')}; "
                    f"profiling={profiling.get('state') or profiling.get('status')}; "
                    f"sha256={item.get('sha256') or 'missing'}"
                ),
                width=100,
            )
        )
    lines.extend(["", "Limitations:"])
    for limitation in results.get("limitations", []):
        lines.extend(textwrap.wrap(f"- {limitation}", width=100))
    return lines


def _write_pdf_report(path: Path, lines: list[str]) -> None:
    """Write a small, dependency-free text PDF."""
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(textwrap.wrap(line, width=95) or [""])

    lines_per_page = 48
    pages = [
        wrapped[index : index + lines_per_page]
        for index in range(0, len(wrapped), lines_per_page)
    ]
    if not pages:
        pages = [["CivicMind AI local ingestion research run"]]

    objects: list[bytes] = []
    page_ids: list[int] = []
    content_ids: list[int] = []
    for page in pages:
        page_ids.append(3 + len(objects))
        content_ids.append(4 + len(objects))
        objects.extend([b"", _pdf_stream(page)])

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[0:0] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii"),
    ]
    for index, page_id in enumerate(page_ids):
        content_id = content_ids[index]
        objects[page_id - 1] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
            f"/BaseFont /Helvetica >> >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_at = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(output))


def _pdf_stream(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 10 Tf", "50 750 Td", "13 TL"]
    for line in lines:
        commands.append(f"({_pdf_escape(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    content = "\n".join(commands).encode("latin-1", "replace")
    return (
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream"
    )


def _pdf_escape(value: str) -> str:
    safe = value.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_manifest(paths: tuple[Path, ...]) -> dict[str, Any]:
    return {
        "generated_at": _now_client_tz().isoformat(),
        "timezone": CLIENT_TIMEZONE.tzname(None),
        "deliverables": [
            {
                "path": str(path),
                "byte_size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for path in paths
        ],
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_client_tz() -> datetime:
    return datetime.now(tz=CLIENT_TIMEZONE)


__all__ = [
    "ResearchRunReport",
    "build_local_dataset_mapping",
    "run_research_ingestion",
]
