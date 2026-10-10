"""Runtime environment inspection.

Keeps heavyweight AI dependencies optional: PyTorch/CUDA availability is
*detected*, never required, so ingestion and validation run fine on CPU-only
machines without PyTorch installed.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from civicmind.config import Settings

logger = logging.getLogger(__name__)

MINIMUM_PYTHON: tuple[int, int] = (3, 10)


@dataclass(frozen=True)
class ComponentStatus:
    """Availability of a single runtime component."""

    name: str
    available: bool
    required: bool
    detail: str


@dataclass(frozen=True)
class EnvironmentReport:
    """Aggregate result of an environment check."""

    python_version: str
    platform: str
    project_root: Path
    components: tuple[ComponentStatus, ...]

    @property
    def ok(self) -> bool:
        """True when every *required* component is available."""
        return all(component.available for component in self.components if component.required)

    @property
    def missing_optional(self) -> tuple[ComponentStatus, ...]:
        """Optional components that are unavailable."""
        return tuple(
            component
            for component in self.components
            if not component.required and not component.available
        )

    def lines(self) -> list[str]:
        """Render the report as human-readable lines."""
        status = "OK" if self.ok else "DEGRADED"
        rendered = [
            f"Python      : {self.python_version}",
            f"Platform    : {self.platform}",
            f"Project root: {self.project_root}",
            f"Status      : {status}",
            "",
        ]
        for component in self.components:
            mark = "ok" if component.available else ("MISSING" if component.required else "absent")
            rendered.append(f"[{mark:>7}] {component.name}: {component.detail}")
        return rendered


def detect_pytorch() -> ComponentStatus:
    """Detect PyTorch and CUDA without making PyTorch a hard dependency.

    The module is only imported when it is actually installed, so machines
    without the optional ``ai`` extra pay no import cost.
    """
    name = "pytorch"
    if importlib.util.find_spec("torch") is None:
        return ComponentStatus(
            name=name,
            available=False,
            required=False,
            detail="not installed (optional; ingestion/validation run on CPU without it)",
        )
    try:
        import torch
    except Exception as exc:  # pragma: no cover - broken native installs
        return ComponentStatus(
            name=name,
            available=False,
            required=False,
            detail=f"installed but failed to import: {exc}",
        )
    cuda_available = bool(torch.cuda.is_available())
    detail = f"torch {torch.__version__}; CUDA {'available' if cuda_available else 'unavailable'}"
    return ComponentStatus(name=name, available=True, required=False, detail=detail)


def check_environment(settings: Settings) -> EnvironmentReport:
    """Inspect the runtime and return a structured report.

    Required components gate the health check; optional components (PyTorch,
    python-dotenv) are reported informationally only.
    """
    python_ok = sys.version_info >= MINIMUM_PYTHON
    minimum = ".".join(str(part) for part in MINIMUM_PYTHON)
    root = settings.project_root
    root_writable = os.access(root, os.W_OK)
    dotenv_available = importlib.util.find_spec("dotenv") is not None
    components: list[ComponentStatus] = [
        ComponentStatus(
            name="python",
            available=python_ok,
            required=True,
            detail=f"{platform.python_version()} (minimum {minimum})",
        ),
        ComponentStatus(
            name="project-root-writable",
            available=root_writable,
            required=True,
            detail=f"{root} ({'writable' if root_writable else 'read-only'})",
        ),
        ComponentStatus(
            name="python-dotenv",
            available=dotenv_available,
            required=False,
            detail=".env loading available"
            if dotenv_available
            else "not installed; set variables in the process environment instead",
        ),
        detect_pytorch(),
    ]
    report = EnvironmentReport(
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        project_root=settings.project_root,
        components=tuple(components),
    )
    logger.debug("Environment check finished: ok=%s", report.ok)
    return report
