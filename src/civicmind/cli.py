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

The CLI is intentionally dependency-free (``argparse``) so the foundation runs
on a bare Python install. ``catalog list`` reads the version-controlled metadata
CSV and reports metadata only, ``ingest plan`` is a dry run that neither uses the
network nor writes, and ``ingest acquire`` is the only command that fetches
anything - and only for a dataset the eligibility policy has authorized.
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
