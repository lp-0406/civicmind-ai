"""Environment and GPU smoke test for the college deployment.

Run on the target machine (see ``scripts/gpu_smoke_test.py``) to answer, in one
command: is this machine ready, which model/device will be used, does a real
municipal question answer end to end, and does the answer carry its source
evidence?

Nothing here imports torch or transformers unless they are installed, and the
model is loaded only when ``--load-model`` is passed explicitly. Ordinary unit
tests exercise the reporting and readiness logic without a GPU.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from civicmind.ai.config import AISettings
from civicmind.ai.engine import DecisionEngine
from civicmind.ai.providers import ProviderError, build_provider, resolve_device
from civicmind.config import Settings

#: Exit codes: 0 ready, 2 environment not ready, 3 model load/inference failed.
EXIT_OK = 0
EXIT_NOT_READY = 2
EXIT_INFERENCE_FAILED = 3

DEFAULT_QUESTION = "Which states had the highest reported road accidents in 2019?"


@dataclass(frozen=True)
class Check:
    """A single readiness check."""

    name: str
    ok: bool
    detail: str
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "required": self.required,
        }


@dataclass(frozen=True)
class EnvironmentReport:
    """Detected runtime facts. Every field is best-effort and may be ``None``."""

    python_version: str
    platform: str
    torch_version: str | None
    transformers_version: str | None
    cuda_available: bool
    cuda_version: str | None
    gpu_name: str | None
    vram_total_mb: int | None
    vram_free_mb: int | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "python_version": self.python_version,
            "platform": self.platform,
            "torch_version": self.torch_version,
            "transformers_version": self.transformers_version,
            "cuda_available": self.cuda_available,
            "cuda_version": self.cuda_version,
            "gpu_name": self.gpu_name,
            "vram_total_mb": self.vram_total_mb,
            "vram_free_mb": self.vram_free_mb,
        }


def _module_version(name: str) -> str | None:
    """Return an installed module's version, or ``None`` when absent."""
    if importlib.util.find_spec(name) is None:
        return None
    try:
        module = importlib.import_module(name)
    except Exception:  # pragma: no cover - a broken install is reported as unknown
        return None
    return str(getattr(module, "__version__", "unknown"))


def environment_report() -> EnvironmentReport:
    """Detect Python, torch/CUDA and transformers facts without requiring them."""
    torch_version = _module_version("torch")
    cuda_available = False
    cuda_version: str | None = None
    gpu_name: str | None = None
    vram_total_mb: int | None = None
    vram_free_mb: int | None = None

    if torch_version is not None:
        try:
            import torch

            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                cuda_version = getattr(torch.version, "cuda", None)
                gpu_name = torch.cuda.get_device_name(0)
                properties = torch.cuda.get_device_properties(0)
                vram_total_mb = int(properties.total_memory // (1024 * 1024))
                free_bytes, _total = torch.cuda.mem_get_info(0)
                vram_free_mb = int(free_bytes // (1024 * 1024))
        except Exception:  # pragma: no cover - driver/alloc failures degrade gracefully
            cuda_available = False

    return EnvironmentReport(
        python_version=platform.python_version(),
        platform=platform.platform(),
        torch_version=torch_version,
        transformers_version=_module_version("transformers"),
        cuda_available=cuda_available,
        cuda_version=cuda_version,
        gpu_name=gpu_name,
        vram_total_mb=vram_total_mb,
        vram_free_mb=vram_free_mb,
    )


def readiness_checks(ai_settings: AISettings, report: EnvironmentReport) -> tuple[Check, ...]:
    """Return the readiness checks for the configured provider and device."""
    device, warning = resolve_device(ai_settings.device)
    checks: list[Check] = [
        Check(
            name="python",
            ok=sys.version_info[:2] >= (3, 10),
            detail=f"Python {report.python_version} (requires >= 3.10)",
            required=True,
        ),
        Check(
            name="data_dir",
            ok=True,
            detail="supplied CSVs are checked when the question is answered",
        ),
    ]

    if ai_settings.provider in {"auto", "local"} and ai_settings.model_id:
        checks.append(
            Check(
                name="transformers",
                ok=report.transformers_version is not None,
                detail=(
                    f"transformers {report.transformers_version}"
                    if report.transformers_version
                    else "transformers is not installed; run: pip install 'civicmind-ai[ai]'"
                ),
                required=ai_settings.provider == "local",
            )
        )
        checks.append(
            Check(
                name="torch",
                ok=report.torch_version is not None,
                detail=(
                    f"torch {report.torch_version}"
                    if report.torch_version
                    else "torch is not installed; install a CPU or CUDA build of PyTorch"
                ),
                required=ai_settings.provider == "local",
            )
        )

    if ai_settings.provider == "local" and not ai_settings.model_id:
        checks.append(
            Check(
                name="model_configured",
                ok=False,
                detail="CIVICMIND_AI_PROVIDER=local requires CIVICMIND_AI_MODEL_ID to be set",
                required=True,
            )
        )

    if ai_settings.device.startswith("cuda"):
        checks.append(
            Check(
                name="cuda",
                ok=report.cuda_available,
                detail=(
                    f"CUDA available ({report.gpu_name}, {report.vram_total_mb} MB)"
                    if report.cuda_available
                    else (
                        f"CIVICMIND_AI_DEVICE={ai_settings.device} but no CUDA device is "
                        "available; install the matching CUDA PyTorch build or set "
                        "CIVICMIND_AI_DEVICE=cpu"
                    )
                ),
                required=True,
            )
        )
    else:
        checks.append(
            Check(
                name="device",
                ok=True,
                detail=f"resolved device: {device}" + (f" ({warning})" if warning else ""),
            )
        )

    if ai_settings.provider in {"auto", "api"} and ai_settings.api_base_url:
        checks.append(
            Check(
                name="api_key",
                ok=ai_settings.api_key is not None,
                detail=(
                    "API key present via the configured environment variable"
                    if ai_settings.api_key is not None
                    else f"no API key found in {ai_settings.api_key_env}"
                ),
                required=ai_settings.provider == "api",
            )
        )

    return tuple(checks)


@dataclass(frozen=True)
class SmokeResult:
    """The measured outcome of one smoke-test question."""

    ready: bool
    configured_provider: str
    active_provider: str
    model_id: str | None
    device: str | None
    cuda_used: bool
    question: str
    answer_supported: bool
    execution_mode: str
    elapsed_seconds: float
    evidence_sources: tuple[str, ...]
    explanation_excerpt: str
    error: str | None
    checks: tuple[Check, ...]
    environment: EnvironmentReport

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "ready": self.ready,
            "configured_provider": self.configured_provider,
            "active_provider": self.active_provider,
            "model_id": self.model_id,
            "device": self.device,
            "cuda_used": self.cuda_used,
            "question": self.question,
            "answer_supported": self.answer_supported,
            "execution_mode": self.execution_mode,
            "elapsed_seconds": self.elapsed_seconds,
            "evidence_sources": list(self.evidence_sources),
            "explanation_excerpt": self.explanation_excerpt,
            "error": self.error,
            "checks": [check.to_dict() for check in self.checks],
            "environment": self.environment.to_dict(),
        }

    def exit_code(self, *, require_model: bool) -> int:
        """Return the process exit code for this result."""
        if not self.ready:
            return EXIT_NOT_READY
        if self.error is not None:
            return EXIT_INFERENCE_FAILED
        if self.execution_mode != "deterministic":
            return EXIT_OK
        if require_model:
            # A model was explicitly requested but the answer still fell back.
            return EXIT_INFERENCE_FAILED if self.model_id else EXIT_NOT_READY
        if self.active_provider != "deterministic":
            return EXIT_INFERENCE_FAILED
        return EXIT_OK


def run_smoke(
    settings: Settings,
    ai_settings: AISettings,
    *,
    question: str = DEFAULT_QUESTION,
    load_model: bool = False,
    provider: Any = None,
) -> SmokeResult:
    """Run one municipal question through the engine and record everything.

    ``provider`` is only supplied by tests; production callers omit it and the
    provider is resolved from ``ai_settings``.
    """
    environment = environment_report()
    checks = readiness_checks(ai_settings, environment)
    ready = all(check.ok for check in checks if check.required)

    if provider is None:
        provider = build_provider(ai_settings)
        if not load_model and provider.mode == "local":
            # Honour "load only when explicitly requested": force the
            # deterministic path while still reporting what *would* have run.
            provider = build_provider(replace(ai_settings, provider="deterministic"))

    engine = DecisionEngine(settings, ai_settings=ai_settings, provider=provider)

    device: str | None = None
    cuda_used = False
    resolved_device, _warning = resolve_device(ai_settings.device)
    started = time.perf_counter()
    error: str | None = None
    answer = None
    try:
        answer = engine.ask(question)
    except ProviderError as exc:  # pragma: no cover - engine already falls back
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - the smoke test must never crash opaquely
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started

    if answer is not None and answer.execution_mode != "deterministic":
        device = resolved_device
        cuda_used = resolved_device.startswith("cuda")
    elif load_model and ai_settings.provider == "local":
        device = resolved_device

    return SmokeResult(
        ready=ready,
        configured_provider=ai_settings.provider,
        active_provider=provider.name,
        model_id=ai_settings.model_id or None,
        device=device,
        cuda_used=cuda_used,
        question=question,
        answer_supported=bool(answer.supported) if answer else False,
        execution_mode=answer.execution_mode if answer else "error",
        elapsed_seconds=elapsed,
        evidence_sources=tuple(item.source_file for item in answer.evidence) if answer else (),
        explanation_excerpt=(answer.explanation[:400] if answer else ""),
        error=error,
        checks=checks,
        environment=environment,
    )


def build_parser() -> argparse.ArgumentParser:
    """Construct the smoke-test argument parser."""
    parser = argparse.ArgumentParser(
        prog="gpu_smoke_test",
        description=(
            "Verify the CivicMind AI environment on the college GPU machine and answer one "
            "municipal question end to end."
        ),
    )
    parser.add_argument(
        "--question",
        default=DEFAULT_QUESTION,
        help="the municipal question to answer",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="override CIVICMIND_AI_MODEL_ID for this run",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="override CIVICMIND_AI_DEVICE (auto|cpu|cuda|cuda:0)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="override CIVICMIND_AI_PROVIDER (auto|deterministic|local|api)",
    )
    parser.add_argument(
        "--load-model",
        action="store_true",
        dest="load_model",
        help="actually load and run the configured local model (default: report only)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit the full result as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the smoke test."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    ai_settings = AISettings.from_env()
    overrides: dict[str, Any] = {}
    if args.provider:
        overrides["provider"] = args.provider
    if args.model is not None:
        overrides["model_id"] = args.model
    if args.device:
        overrides["device"] = args.device
    if overrides:
        ai_settings = replace(ai_settings, **overrides)
        try:
            ai_settings.validate()
        except Exception as exc:  # noqa: BLE001 - report configuration errors plainly
            print(f"configuration error: {exc}", file=sys.stderr)
            return EXIT_NOT_READY

    settings = Settings.from_env()
    result = run_smoke(
        settings,
        ai_settings,
        question=args.question,
        load_model=args.load_model,
    )

    if args.as_json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_human(result, load_model=args.load_model)

    return result.exit_code(require_model=args.load_model)


def _print_human(result: SmokeResult, *, load_model: bool) -> None:
    environment = result.environment
    print("== environment ==")
    print(f"python        : {environment.python_version} ({environment.platform})")
    print(f"torch         : {environment.torch_version or 'not installed'}")
    print(f"transformers  : {environment.transformers_version or 'not installed'}")
    print(
        "cuda          : "
        + (
            f"available ({environment.gpu_name}, {environment.vram_total_mb} MB total, "
            f"{environment.vram_free_mb} MB free, cuda {environment.cuda_version})"
            if environment.cuda_available
            else "not available"
        )
    )
    print("== checks ==")
    for check in result.checks:
        flag = "ok  " if check.ok else "FAIL"
        marker = " (required)" if check.required else ""
        print(f"[{flag}] {check.name}{marker}: {check.detail}")
    print("== smoke question ==")
    print(f"question      : {result.question}")
    print(
        f"provider      : configured={result.configured_provider} active={result.active_provider}"
    )
    print(f"model         : {result.model_id or '(none)'}")
    print(f"device        : {result.device or '(not used)'}  cuda_used={result.cuda_used}")
    print(f"mode          : {result.execution_mode}")
    print(f"supported     : {result.answer_supported}")
    print(f"elapsed       : {result.elapsed_seconds:.3f}s")
    print(f"evidence      : {', '.join(result.evidence_sources) or '(none)'}")
    if result.error:
        print(f"error         : {result.error}")
    if not load_model and result.configured_provider == "local":
        print(
            "note          : the local model was not loaded; pass --load-model to run real "
            "inference"
        )
    print()
    if result.exit_code(require_model=load_model) == EXIT_OK:
        print("RESULT: ready")
    elif not result.ready:
        print("RESULT: environment not ready (see the failed required checks above)")
    else:
        print("RESULT: model inference did not produce a grounded local answer")


__all__ = [
    "DEFAULT_QUESTION",
    "EXIT_INFERENCE_FAILED",
    "EXIT_NOT_READY",
    "EXIT_OK",
    "Check",
    "EnvironmentReport",
    "SmokeResult",
    "build_parser",
    "environment_report",
    "main",
    "readiness_checks",
    "run_smoke",
]
