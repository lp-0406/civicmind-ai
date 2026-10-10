#!/usr/bin/env python3
"""Validate the repository scaffold itself.

Intended use (from the repository root)::

    python scripts/validate_project.py

Checks performed
----------------
1. Required files and directories exist.
2. ``.gitkeep`` placeholders are present so Git preserves empty directories.
3. ``data/*`` and ``artifacts``/``logs`` contain no committed payloads.
4. ``.env`` is ignored by Git (secrets must never be committed).
5. The ``civicmind`` package is importable and exposes a version.

Exit codes: 0 = all checks passed, 1 = one or more checks failed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from civicmind import __version__  # noqa: E402

REQUIRED_PATHS: tuple[str, ...] = (
    "pyproject.toml",
    ".env.example",
    "README.md",
    "docs/architecture/system_overview.md",
    "docs/datasets/ingestion_strategy.md",
    "docs/PROJECT_STATUS.md",
    "configs/README.md",
    "scripts/check_environment.py",
    "scripts/validate_project.py",
    "src/civicmind/__init__.py",
    "src/civicmind/config.py",
    "src/civicmind/logging_config.py",
    "src/civicmind/cli.py",
    "src/civicmind/environment.py",
    "src/civicmind/ingestion/base.py",
    "src/civicmind/ingestion/registry.py",
    "src/civicmind/ingestion/exceptions.py",
    "src/civicmind/preprocessing/__init__.py",
    "src/civicmind/profiling/__init__.py",
    "src/civicmind/storage/__init__.py",
    "tests/test_config.py",
    "tests/test_cli.py",
    "tests/test_ingestion.py",
)

DIRECTORY_KEEP: tuple[str, ...] = (
    "data/raw/.gitkeep",
    "data/interim/.gitkeep",
    "data/processed/.gitkeep",
    "data/external/.gitkeep",
    "artifacts/.gitkeep",
    "logs/.gitkeep",
)

DATA_DIRS: tuple[str, ...] = ("data/raw", "data/interim", "data/processed", "data/external")

failures: list[str] = []
passes: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    """Record a single check result."""
    message = f"{label}: {detail}" if detail else label
    if ok:
        passes.append(message)
    else:
        failures.append(message)


def main() -> int:
    """Run every check and print a summary."""
    for relative in REQUIRED_PATHS:
        check((REPO_ROOT / relative).exists(), f"exists {relative}")

    for relative in DIRECTORY_KEEP:
        check((REPO_ROOT / relative).is_file(), f"gitkeep {relative}")

    for relative in DATA_DIRS:
        directory = REPO_ROOT / relative
        if not directory.is_dir():
            check(False, f"clean {relative}", "directory missing")
            continue
        unexpected = sorted(p.name for p in directory.iterdir() if p.name != ".gitkeep")
        check(
            not unexpected,
            f"clean {relative}",
            "no payloads committed" if not unexpected else f"unexpected entries: {unexpected}",
        )

    gitignore = REPO_ROOT / ".gitignore"
    ignored_env = False
    if gitignore.is_file():
        try:
            ignored_env = (
                subprocess.run(  # noqa: S603
                    ["git", "check-ignore", "-q", ".env"],
                    cwd=REPO_ROOT,
                    check=False,
                ).returncode
                == 0
            )
        except FileNotFoundError:  # pragma: no cover - git not installed
            ignored_env = ".env" in gitignore.read_text(encoding="utf-8").splitlines()
    check(ignored_env, "secret policy", ".env is ignored by Git")

    check(bool(__version__), "package importable", f"civicmind {__version__}")

    for message in passes:
        print(f"[ok]      {message}")
    for message in failures:
        print(f"[FAILED]  {message}")

    print(
        f"\n{len(passes)} passed, {len(failures)} failed"
        + ("" if not failures else " - repository scaffold is incomplete")
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
