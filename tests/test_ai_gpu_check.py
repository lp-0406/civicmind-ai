"""Tests for the GPU smoke-test module.

Everything here runs without a GPU, a model or the network: real inference is
covered only by the skipped integration test at the bottom, which requires an
explicit opt-in environment variable.
"""

from __future__ import annotations

import json
import os

import pytest

from civicmind.ai.config import AISettings
from civicmind.ai.gpu_check import (
    EXIT_INFERENCE_FAILED,
    EXIT_NOT_READY,
    EXIT_OK,
    EnvironmentReport,
    build_parser,
    environment_report,
    readiness_checks,
    run_smoke,
)
from civicmind.ai.providers import GenerationResult, ProviderError
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)


class _FailingProvider:
    """A provider that always fails, standing in for a broken local model."""

    name = "exploding"
    mode = "local"

    def available(self) -> bool:
        return True

    def generate(self, request: object) -> GenerationResult:
        raise ProviderError("CUDA out of memory")


def _fake_environment(
    *, cuda: bool = False, torch_version: str | None = "9.9.9"
) -> EnvironmentReport:
    return EnvironmentReport(
        python_version="3.10.0",
        platform="test-platform",
        torch_version=torch_version,
        transformers_version="4.99.0",
        cuda_available=cuda,
        cuda_version="12.1" if cuda else None,
        gpu_name="Fake GPU" if cuda else None,
        vram_total_mb=24576 if cuda else None,
        vram_free_mb=20000 if cuda else None,
    )


# -- environment reporting -------------------------------------------------


def test_environment_report_never_raises_without_a_gpu() -> None:
    report = environment_report()
    assert report.python_version
    assert isinstance(report.cuda_available, bool)
    assert set(report.to_dict()) == {
        "python_version",
        "platform",
        "torch_version",
        "transformers_version",
        "cuda_available",
        "cuda_version",
        "gpu_name",
        "vram_total_mb",
        "vram_free_mb",
    }


# -- readiness checks ------------------------------------------------------


def test_deterministic_provider_is_ready_without_any_ml_stack() -> None:
    checks = readiness_checks(
        AISettings(provider="deterministic"), _fake_environment(torch_version=None)
    )
    assert all(check.ok for check in checks if check.required)


def test_local_provider_without_a_model_id_fails_readiness() -> None:
    checks = readiness_checks(AISettings(provider="local", model_id=""), _fake_environment())
    failed = {check.name for check in checks if check.required and not check.ok}
    assert "model_configured" in failed


def test_local_provider_without_transformers_fails_readiness() -> None:
    report = EnvironmentReport(
        python_version="3.10.0",
        platform="test",
        torch_version="9.9.9",
        transformers_version=None,
        cuda_available=False,
        cuda_version=None,
        gpu_name=None,
        vram_total_mb=None,
        vram_free_mb=None,
    )
    checks = readiness_checks(AISettings(provider="local", model_id="x/y"), report)
    failed = {check.name for check in checks if check.required and not check.ok}
    assert "transformers" in failed


def test_cuda_request_without_a_gpu_fails_readiness_with_actionable_text() -> None:
    checks = readiness_checks(
        AISettings(provider="local", model_id="x/y", device="cuda:0"),
        _fake_environment(cuda=False),
    )
    cuda_check = next(check for check in checks if check.name == "cuda")
    assert cuda_check.ok is False
    assert cuda_check.required is True
    assert "CIVICMIND_AI_DEVICE=cpu" in cuda_check.detail


def test_cuda_request_with_a_gpu_passes_readiness() -> None:
    checks = readiness_checks(
        AISettings(provider="local", model_id="x/y", device="cuda:0"),
        _fake_environment(cuda=True),
    )
    cuda_check = next(check for check in checks if check.name == "cuda")
    assert cuda_check.ok is True
    assert "Fake GPU" in cuda_check.detail


# -- smoke run -------------------------------------------------------------


def test_run_smoke_deterministic_answers_with_evidence_and_exits_zero(
    raw_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("civicmind.ai.gpu_check.environment_report", lambda: _fake_environment())
    result = run_smoke(raw_settings, AISettings(provider="deterministic"))

    assert result.ready is True
    assert result.answer_supported is True
    assert result.execution_mode == "deterministic"
    assert result.cuda_used is False
    assert result.evidence_sources
    assert result.evidence_sources[0].endswith(".csv")
    assert result.elapsed_seconds >= 0
    assert result.error is None
    assert result.exit_code(require_model=False) == EXIT_OK


def test_run_smoke_does_not_load_a_local_model_without_opt_in(
    raw_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("civicmind.ai.gpu_check.environment_report", lambda: _fake_environment())
    ai_settings = AISettings(provider="local", model_id="fake/model", device="cpu")
    result = run_smoke(raw_settings, ai_settings, load_model=False)

    # The provider was never switched to local, so no weights were touched.
    assert result.active_provider == "deterministic"
    assert result.execution_mode == "deterministic"
    assert result.cuda_used is False
    assert result.exit_code(require_model=False) == EXIT_OK


def test_run_smoke_reports_failure_instead_of_claiming_gpu_success(
    raw_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "civicmind.ai.gpu_check.environment_report",
        lambda: _fake_environment(cuda=True),
    )
    ai_settings = AISettings(provider="local", model_id="fake/model", device="cuda:0")
    result = run_smoke(raw_settings, ai_settings, load_model=True, provider=_FailingProvider())

    assert result.active_provider == "exploding"
    assert result.execution_mode == "deterministic"  # fell back, did not claim local
    assert result.cuda_used is False
    assert result.model_id == "fake/model"
    assert result.exit_code(require_model=True) == EXIT_INFERENCE_FAILED


def test_exit_code_signals_not_ready_when_the_configured_device_is_missing(
    raw_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "civicmind.ai.gpu_check.environment_report", lambda: _fake_environment(cuda=False)
    )
    ai_settings = AISettings(provider="local", model_id="fake/model", device="cuda:0")
    result = run_smoke(raw_settings, ai_settings, load_model=False)

    assert result.ready is False
    assert result.exit_code(require_model=False) == EXIT_NOT_READY


def test_parser_exposes_the_documented_flags() -> None:
    args = build_parser().parse_args(["--load-model", "--json", "--device", "cuda:0"])
    assert args.load_model is True
    assert args.as_json is True
    assert args.device == "cuda:0"


def test_main_json_output_with_deterministic_provider(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pathlib import Path

    from civicmind.ai.gpu_check import main

    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("CIVICMIND_PROJECT_ROOT", str(repo_root))
    monkeypatch.setenv("CIVICMIND_DATA_DIR", str(repo_root / "data"))
    monkeypatch.setenv("CIVICMIND_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CIVICMIND_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CIVICMIND_AI_PROVIDER", "deterministic")

    exit_code = main(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_OK
    assert payload["execution_mode"] == "deterministic"
    assert payload["evidence_sources"]
    assert payload["environment"]["python_version"]


@pytest.mark.skipif(
    not os.environ.get("CIVICMIND_AI_RUN_INTEGRATION"),
    reason=(
        "real model inference is opt-in: set CIVICMIND_AI_RUN_INTEGRATION=1 and "
        "CIVICMIND_AI_MODEL_ID on the GPU machine to run it"
    ),
)
def test_real_local_model_inference_integration(raw_settings: Settings) -> None:
    """Marker test: proves nothing unless a real model is configured and loaded."""
    ai_settings = AISettings.from_env()
    assert ai_settings.model_id, "CIVICMIND_AI_MODEL_ID must be set for this test"
    result = run_smoke(raw_settings, ai_settings, load_model=True)
    assert result.execution_mode == "local", (
        f"expected local inference, got {result.execution_mode} ({result.error})"
    )
    assert result.evidence_sources
