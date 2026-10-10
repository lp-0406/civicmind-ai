#!/usr/bin/env python3
"""Check that this machine can run CivicMind AI.

Intended use (from the repository root)::

    python scripts/check_environment.py

Exit codes
----------
0  environment is usable (missing *optional* components are reported only)
1  a required component is missing
2  configuration could not be resolved

The script never downloads data and never requires PyTorch.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from civicmind.config import ConfigurationError, Settings  # noqa: E402
from civicmind.environment import check_environment  # noqa: E402


def main() -> int:
    """Run the environment check and print a report."""
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    report = check_environment(settings)
    print("\n".join(report.lines()))
    if not report.ok:
        missing = [c.name for c in report.components if c.required and not c.available]
        print(f"\nRequired components missing: {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
