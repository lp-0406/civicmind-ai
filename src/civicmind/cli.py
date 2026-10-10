"""Command-line interface for CivicMind AI.

Commands
--------
``civicmind --version``            Print the package version.
``civicmind health``               Inspect the local environment (exit 1 if unusable).
``civicmind config show``          Print resolved, secret-free settings.
``civicmind ingest list``          List registered ingestion handlers (no downloads).

The CLI is intentionally dependency-free (``argparse``) so the foundation runs
on a bare Python install.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from civicmind import __version__
from civicmind.config import ConfigurationError, Settings
from civicmind.environment import check_environment
from civicmind.ingestion import DEFAULT_REGISTRY
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


def _cmd_ingest_list(args: argparse.Namespace) -> int:
    """List the handlers currently registered in the default registry."""
    descriptors = DEFAULT_REGISTRY.describe_all()
    if args.as_json:
        payload = [
            {
                "source_id": item.source_id,
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
    for item in descriptors:
        print(f"{item.source_id:<24} {item.title} ({item.publisher}, {item.license})")
    return 0


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
        help="list registered ingestion handlers",
    )
    ingest_list.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the list as JSON",
    )
    ingest_list.set_defaults(handler=_cmd_ingest_list)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``civicmind`` console script."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = _load_settings()
    setup_logging(settings.log_level, settings.log_format)
    args.settings = settings
    return int(args.handler(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
