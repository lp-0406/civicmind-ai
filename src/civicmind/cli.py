"""Command-line interface for CivicMind AI.

Commands
--------
``civicmind --version``            Print the package version.
``civicmind health``               Inspect the local environment (exit 1 if unusable).
``civicmind config show``          Print resolved, secret-free settings.
``civicmind ingest list``          List available ingestion handlers (no downloads).
``civicmind ingest plan``          Show what an acquisition would do (no network).
``civicmind ingest acquire``       Acquire one explicitly authorized dataset.
``civicmind ingest validate``      Validate the locally acquired artifact.
``civicmind ingest profile``       Profile the locally acquired artifact.
``civicmind ingest status``        Show the recorded four-axis state.
``civicmind catalog list``         List canonical datasets from the metadata CSV.
``civicmind ask "question"``       Answer a municipal question from the supplied CSVs.
``civicmind ai datasets``          List the AI layer's datasets and availability.
``civicmind ai serve``             Serve the FastAPI interface with uvicorn.

The CLI is intentionally dependency-free (``argparse``) at import time so the
foundation runs on a bare Python install; the AI commands import pandas, the
decision engine and (for ``serve``) FastAPI lazily inside their handlers.
``catalog list`` reads the version-controlled metadata CSV and reports metadata
only, ``ingest plan`` is a dry run that neither uses the network nor writes, and
``ingest acquire`` is the only command that fetches anything - and only for a
dataset the eligibility policy has authorized.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from civicmind import __version__
from civicmind.config import ConfigurationError, Settings
from civicmind.environment import check_environment
from civicmind.ingestion import DEFAULT_REGISTRY, IngestionRegistry, pilot
from civicmind.ingestion.evidence import EvidenceError
from civicmind.ingestion.exceptions import IngestionError
from civicmind.ingestion.handlers import build_pilot_registry
from civicmind.ingestion.identifiers import canonical_dataset_id_or_none
from civicmind.ingestion.pilot import PILOT_DATASET_ID
from civicmind.ingestion.sources import CanonicalMetadataError, load_canonical_registry
from civicmind.logging_config import setup_logging

PROG = "civicmind"


def _load_settings() -> Settings:
    """Load settings, converting configuration problems into CLI errors."""
    try:
        return Settings.from_env()
    except ConfigurationError as exc:
        raise SystemExit(f"{PROG}: configuration error: {exc}") from exc


def _cmd_health(args: argparse.Namespace) -> int:
    """Run the environment check and report its result."""
    report = check_environment(args.settings)
    if args.as_json:
        payload = {
            "python_version": report.python_version,
            "platform": report.platform,
            "project_root": str(report.project_root),
            "ok": report.ok,
            "components": [asdict(component) for component in report.components],
        }
        print(json.dumps(payload, indent=2))
    else:
        print("\n".join(report.lines()))
    return 0 if report.ok else 1


def _cmd_config_show(args: argparse.Namespace) -> int:
    """Print the resolved settings (secrets are never included)."""
    summary = args.settings.summary()
    if args.as_json:
        print(json.dumps(summary, indent=2))
    else:
        width = max(len(key) for key in summary)
        for key, value in summary.items():
            print(f"{key:<{width}} : {value}")
    return 0


def _listed_handlers() -> IngestionRegistry:
    """Return every handler an operator could use, acquiring nothing.

    Combines the handlers this project ships (built explicitly by
    :func:`build_pilot_registry`, never auto-registered into the process-wide
    default registry) with any handler application code has registered into
    :data:`DEFAULT_REGISTRY`, so ``ingest list`` stays the single discovery
    point for both. Building a handler performs no I/O.
    """
    registry = build_pilot_registry()
    for ingestor in DEFAULT_REGISTRY:
        registry.register(ingestor, overwrite=True)
    return registry


def _cmd_ingest_list(args: argparse.Namespace) -> int:
    """List the ingestion handlers that are available.

    Listing is metadata only: it reads handlers' descriptors and downloads,
    validates or records nothing.
    """
    descriptors = _listed_handlers().describe_all()
    if args.as_json:
        payload = [
            {
                "source_id": item.source_id,
                "dataset_id": canonical_dataset_id_or_none(item.source_id),
                "title": item.title,
                "publisher": item.publisher,
                "license": item.license,
                "uri": item.uri,
            }
            for item in descriptors
        ]
        print(json.dumps(payload, indent=2))
        return 0
    if not descriptors:
        print("No ingestion handlers registered.")
        print("Handlers are registered explicitly; nothing is downloaded automatically.")
        return 0
    print(f"{'source_id':<24} {'dataset_id':<11} title (publisher, licence)")
    for item in descriptors:
        canonical = canonical_dataset_id_or_none(item.source_id) or "-"
        print(
            f"{item.source_id:<24} {canonical:<11} {item.title} ({item.publisher}, {item.license})"
        )
    return 0


def _cmd_catalog_list(args: argparse.Namespace) -> int:
    """List canonical datasets built from the version-controlled metadata CSV.

    This is the runtime entrypoint for the CSV -> registry path. It reads local
    metadata only: nothing is downloaded, and listing does not change any status
    axis (a record is reported exactly as loaded, still ``METADATA_ONLY``).
    """
    try:
        registry = load_canonical_registry()
    except CanonicalMetadataError as exc:
        raise SystemExit(f"{PROG}: canonical metadata error: {exc}") from exc

    records = registry.list_records()
    if args.as_json:
        payload = [
            {
                "dataset_id": record.dataset_id,
                "title": record.title,
                "research_status": (
                    record.research_status.value if record.research_status else None
                ),
                "research_decision": record.research_decision.value,
                "acquisition_state": record.acquisition_state.value,
                "validation_state": record.validation_state.value,
                "profiling_state": record.profiling_state.value,
            }
            for record in records
        ]
        print(json.dumps(payload, indent=2))
        return 0

    if not records:
        print("No canonical datasets loaded.")
        return 0

    for record in records:
        print(
            f"{record.dataset_id:<8} {record.research_decision.value:<12} "
            f"{record.acquisition_state.value:<14} {record.title}"
        )
    print(
        f"\n{len(records)} canonical datasets from metadata only; "
        "nothing downloaded, nothing validated."
    )
    return 0


def _cmd_ingest_plan(args: argparse.Namespace) -> int:
    """Describe a planned acquisition without touching the network or the disk."""
    report = pilot.build_plan(args.settings, dataset_id=args.dataset)
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    print(f"Dataset        : {report.dataset_id}  {report.title}")
    print(f"Publisher      : {report.publisher}")
    verified = str(report.license_verified).lower()
    print(f"Licence        : {report.license} (license_verified={verified})")
    print(
        f"Decision       : {report.research_decision}"
        + (" - explicit authorization required" if report.authorization_required else "")
    )
    print(
        f"Axes           : acquisition={report.acquisition_state} "
        f"validation={report.validation_state} profiling={report.profiling_state}"
    )
    print(f"Resource URL   : {report.resource_url}")
    print(f"  cited from   : {report.resource_url_citation}")
    print(f"Dataset page   : {report.dataset_page_url}")
    print(f"Format         : {report.expected_format}")
    print(f"Limits         : {_format_limits(report.limits)}")
    print(f"Artifact dir   : {report.artifact_dir}")
    print(f"Evidence file  : {report.evidence_path}")
    print(f"Profiles dir   : {report.profile_dir}")
    print(f"Local artifacts: {report.artifacts_present}")
    for note in report.notes:
        print(f"note           : {note}")
    return 0


def _cmd_ingest_acquire(args: argparse.Namespace) -> int:
    """Acquire the dataset once the eligibility policy authorizes it."""
    report = pilot.acquire(
        args.settings,
        dataset_id=args.dataset,
        rationale=args.authorize,
        max_bytes=args.max_bytes,
        local_artifact_path=getattr(args, "local_artifact", None),
    )
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    print(f"Acquired       : {report.dataset_id} artifact v{report.artifact_version}")
    print(f"Path           : {report.local_path}")
    print(f"Bytes          : {report.byte_size}")
    print(f"SHA-256        : {report.checksum_sha256}")
    print(f"Acquired at    : {report.acquired_at.isoformat()}")
    print(f"Method         : {report.method}")
    print(
        f"Axes           : acquisition={report.acquisition_state} "
        f"validation={report.validation_state} profiling={report.profiling_state}"
    )
    print(f"Evidence file  : {report.evidence_path}")
    print("nothing is validated or profiled by this step")
    return 0


def _cmd_ingest_validate(args: argparse.Namespace) -> int:
    """Validate the active artifact and report measured findings."""
    report = pilot.validate(args.settings, dataset_id=args.dataset)
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    print(f"Dataset        : {report.dataset_id} artifact v{report.artifact_version}")
    print(f"Scope          : {report.scope}")
    print(f"Passed         : {str(report.passed).lower()}")
    print(f"Validation     : {report.state} (state changed: {str(report.state_changed).lower()})")
    print(f"Errors         : {report.error_count} | warnings: {report.warning_count}")
    for issue in report.issues:
        print(f"  [{issue.get('severity')}] {issue.get('code')}: {issue.get('message')}")
    return 0


def _cmd_ingest_profile(args: argparse.Namespace) -> int:
    """Profile the active artifact and record the measured statistics."""
    report = pilot.profile(args.settings, dataset_id=args.dataset)
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    print(f"Dataset        : {report.dataset_id} artifact v{report.artifact_version}")
    print(f"Rows           : {report.data_rows} | columns: {report.column_count}")
    print(f"Duplicate rows : {report.duplicate_rows}")
    print(f"Sampled        : {str(report.sampled).lower()}")
    print(f"Profiling      : {report.state} (state changed: {str(report.state_changed).lower()})")
    print(f"Steps recorded : {', '.join(report.steps_recorded) or 'none'}")
    print(f"Profile file   : {report.profile_path}")
    for warning in report.warnings:
        print(f"  [warning] {warning}")
    return 0


def _cmd_ingest_status(args: argparse.Namespace) -> int:
    """Show the recorded four-axis state for the dataset."""
    report = pilot.status(args.settings, dataset_id=args.dataset)
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    print(f"Dataset        : {report.dataset_id}  {report.title}")
    print(f"Licence verified: {str(report.blockers['license_verified']).lower()}")
    for axis, value in report.axes.items():
        print(f"{axis:<15}: {value}")
    artifact = report.active_artifact
    if artifact is None:
        print("Active artifact: none (no local bytes)")
    else:
        print(f"Active artifact: v{artifact['version']} {artifact['path']}")
        print(f"  bytes        : {artifact['byte_size']}")
        print(f"  sha256       : {artifact['checksum_sha256']}")
        print(f"  acquired at  : {artifact['acquired_at']}")
    print(
        f"Recorded events: artifacts={report.artifact_count} "
        f"validation={report.validation_count} profiling={report.profiling_count}"
    )
    present = str(report.evidence_present).lower()
    print(f"Evidence file  : {report.evidence_path} (present: {present})")
    if report.replayed_skipped:
        print(f"Replay skipped : {', '.join(report.replayed_skipped)} (already reflected)")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    """Answer a municipal question through the evidence-grounded AI pipeline."""
    from civicmind.ai.engine import DecisionEngine

    engine = DecisionEngine.from_env(args.settings)
    answer = engine.ask(args.question)
    if args.as_json:
        print(json.dumps(answer.to_dict(), indent=2))
        return 0 if answer.supported else 2
    print(answer.explanation)
    print()
    mode = f"{answer.execution_mode} (provider: {answer.provider}"
    if answer.model:
        mode += f", model: {answer.model}"
    print(f"Execution mode : {mode})")
    if answer.dataset_id:
        print(f"Dataset        : {answer.dataset_id}")
    if answer.fallback_reason:
        print(f"Note           : {answer.fallback_reason}")
    return 0 if answer.supported else 2


def _cmd_ai_datasets(args: argparse.Namespace) -> int:
    """List the AI layer's declared datasets and whether each is present."""
    from civicmind.ai.datasets import available_datasets, list_dataset_specs

    available = {spec.dataset_id for spec in available_datasets(args.settings)}
    specs = list_dataset_specs()
    if args.as_json:
        print(
            json.dumps(
                [
                    {
                        "dataset_id": spec.dataset_id,
                        "filename": spec.filename,
                        "canonical_id": spec.canonical_id,
                        "mapping_status": spec.mapping_status,
                        "license_status": spec.license_status,
                        "available": spec.dataset_id in available,
                    }
                    for spec in specs
                ],
                indent=2,
            )
        )
        return 0
    print(f"{'dataset_id':<14} {'available':<10} {'canonical':<10} title")
    for spec in specs:
        present = "yes" if spec.dataset_id in available else "no"
        print(f"{spec.dataset_id:<14} {present:<10} {spec.canonical_id or '-':<10} {spec.title}")
    return 0


def _cmd_ai_evaluate(args: argparse.Namespace) -> int:
    """Run the fixed evaluation benchmark against the real CSVs."""
    from pathlib import Path

    from civicmind.ai.config import AISettings
    from civicmind.ai.evaluation import EvaluationHarness

    harness = EvaluationHarness(args.settings, ai_settings=AISettings(provider="deterministic"))
    report = harness.run()

    if args.out:
        payload = {"benchmark": harness.benchmark_payload(), "report": report.to_dict()}
        Path(args.out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if not args.as_json:
            print(f"wrote benchmark and report to {args.out}")

    if args.as_json:
        print(report.to_json())
    else:
        print("\n".join(report.summary_lines()))
        failing = [
            outcome.case_id
            for outcome in report.outcomes
            if not outcome.intent_ok
            or outcome.numerical_ok is False
            or outcome.attribution_ok is False
            or outcome.unsupported_ok is False
        ]
        if failing:
            print(f"failing cases: {', '.join(failing)}")

    core = (
        "numerical_accuracy",
        "attribution_accuracy",
        "unsupported_rejection_rate",
        "intent_accuracy",
    )
    return 0 if all(report.metrics.get(key, 0.0) == 1.0 for key in core) else 1


def _cmd_ai_serve(args: argparse.Namespace) -> int:
    """Serve the FastAPI application with uvicorn."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - uvicorn is an optional extra
        raise SystemExit(
            f"{PROG}: serving the API requires 'uvicorn' and 'fastapi'; install the 'api' extra"
        ) from exc
    uvicorn.run(
        "civicmind.ai.api:create_app",
        factory=True,
        host=args.host,
        port=args.port,
    )
    return 0


def _format_limits(limits: Mapping[str, Any]) -> str:
    """Render transfer limits for humans."""
    return (
        f"max {limits['max_bytes']} bytes, connect {limits['connect_timeout_seconds']}s, "
        f"read {limits['read_timeout_seconds']}s, attempts {limits['attempts']}"
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser (exposed for tests)."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="CivicMind AI - evidence-grounded municipal decision intelligence.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROG} {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser(
        "health",
        help="check the local environment; exits non-zero if it is unusable",
    )
    health.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the report as JSON",
    )
    health.set_defaults(handler=_cmd_health)

    config = subparsers.add_parser("config", help="inspect resolved configuration")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)
    config_show = config_subparsers.add_parser(
        "show",
        help="print resolved settings (secrets excluded)",
    )
    config_show.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit settings as JSON",
    )
    config_show.set_defaults(handler=_cmd_config_show)

    ingest = subparsers.add_parser(
        "ingest",
        help="dataset ingestion commands (registry metadata only; no downloads)",
    )
    ingest_subparsers = ingest.add_subparsers(dest="ingest_command", required=True)
    ingest_list = ingest_subparsers.add_parser(
        "list",
        help="list the ingestion handlers that are available",
    )
    ingest_list.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the list as JSON",
    )
    ingest_list.set_defaults(handler=_cmd_ingest_list)

    ingest_plan = ingest_subparsers.add_parser(
        "plan",
        help="show what an acquisition would do (dry run: no network, no writes)",
    )
    ingest_plan.set_defaults(handler=_cmd_ingest_plan)

    ingest_acquire = ingest_subparsers.add_parser(
        "acquire",
        help="acquire one explicitly authorized dataset (the only network command)",
    )
    ingest_acquire.add_argument(
        "--authorize",
        metavar="RATIONALE",
        default=None,
        help="documented rationale authorizing this acquisition (required)",
    )
    ingest_acquire.add_argument(
        "--max-bytes",
        type=int,
        default=None,
        dest="max_bytes",
        help="hard ceiling on the response size for this transfer",
    )
    ingest_acquire.add_argument(
        "--local-artifact",
        default=None,
        dest="local_artifact",
        help="path to an already-present local CSV to register (local-only handlers only)",
    )
    ingest_acquire.set_defaults(handler=_cmd_ingest_acquire)

    ingest_validate = ingest_subparsers.add_parser(
        "validate",
        help="validate the locally acquired artifact",
    )
    ingest_validate.set_defaults(handler=_cmd_ingest_validate)

    ingest_profile = ingest_subparsers.add_parser(
        "profile",
        help="profile the locally acquired artifact",
    )
    ingest_profile.set_defaults(handler=_cmd_ingest_profile)

    ingest_status = ingest_subparsers.add_parser(
        "status",
        help="show the recorded acquisition, validation and profiling state",
    )
    ingest_status.set_defaults(handler=_cmd_ingest_status)

    for subparser in (
        ingest_plan,
        ingest_acquire,
        ingest_validate,
        ingest_profile,
        ingest_status,
    ):
        _add_dataset_and_json_flags(subparser)

    catalog = subparsers.add_parser(
        "catalog",
        help="canonical dataset catalog commands (reads local metadata only)",
    )
    catalog_subparsers = catalog.add_subparsers(dest="catalog_command", required=True)
    catalog_list = catalog_subparsers.add_parser(
        "list",
        help="list canonical datasets built from the metadata CSV",
    )
    catalog_list.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the catalog as JSON",
    )
    catalog_list.set_defaults(handler=_cmd_catalog_list)

    ask = subparsers.add_parser(
        "ask",
        help="answer a municipal question from the supplied CSVs (deterministic by default)",
    )
    ask.add_argument("question", help="the municipal question to answer")
    ask.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the full grounded answer as JSON",
    )
    ask.set_defaults(handler=_cmd_ask)

    ai = subparsers.add_parser(
        "ai",
        help="AI decision-support layer commands",
    )
    ai_subparsers = ai.add_subparsers(dest="ai_command", required=True)
    ai_datasets = ai_subparsers.add_parser(
        "datasets",
        help="list the AI layer's datasets and whether each is present under data/raw",
    )
    ai_datasets.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the list as JSON",
    )
    ai_datasets.set_defaults(handler=_cmd_ai_datasets)

    ai_evaluate = ai_subparsers.add_parser(
        "evaluate",
        help="run the fixed benchmark and report numerical/attribution/rejection metrics",
    )
    ai_evaluate.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the full report as JSON",
    )
    ai_evaluate.add_argument(
        "--out",
        default=None,
        help="write the benchmark definition and report JSON to this path",
    )
    ai_evaluate.set_defaults(handler=_cmd_ai_evaluate)

    ai_serve = ai_subparsers.add_parser(
        "serve",
        help="serve the FastAPI interface (requires the 'api' extra)",
    )
    ai_serve.add_argument("--host", default="127.0.0.1", help="bind address")
    ai_serve.add_argument("--port", type=int, default=8000, help="bind port")
    ai_serve.set_defaults(handler=_cmd_ai_serve)
    return parser


def _add_dataset_and_json_flags(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--dataset`` and ``--json`` flags to an ingest subcommand."""
    parser.add_argument(
        "--dataset",
        default=PILOT_DATASET_ID,
        help=f"canonical dataset id (default: {PILOT_DATASET_ID})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the report as JSON",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``civicmind`` console script."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = _load_settings()
    setup_logging(settings.log_level, settings.log_format)
    args.settings = settings
    try:
        return int(args.handler(args))
    except (IngestionError, EvidenceError) as exc:
        raise SystemExit(f"{PROG}: {exc}") from exc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
