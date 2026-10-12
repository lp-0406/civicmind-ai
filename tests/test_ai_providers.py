"""Tests for the answer-provider abstraction.

Nothing here needs a model, a GPU, a network connection or an API key.
"""

from __future__ import annotations

import importlib.util

import pytest

from civicmind.ai.config import AISettings, AISettingsError
from civicmind.ai.evidence import Evidence
from civicmind.ai.providers import (
    DeterministicProvider,
    GenerationRequest,
    LocalModelProvider,
    OpenAICompatibleProvider,
    ProviderError,
    build_provider,
    describe_runtime_failure,
    missing_grounding,
    provider_fallback_reason,
    render_deterministic_answer,
    required_figures,
    resolve_device,
)


def _evidence() -> Evidence:
    return Evidence(
        dataset_id="RA2019_A2",
        source_file="data/raw/RA2019_A2.csv",
        operation="state_accident_ranking",
        units="road accidents",
        time_period="2019",
        geographic_scope="India (states and union territories)",
        record_count=36,
        columns=("States/UTs",),
        limitations=("Counts are as reported by the source.",),
    )


def _request() -> GenerationRequest:
    return GenerationRequest(
        question="Which states had the most accidents?",
        summary="Tamil Nadu reported 57,228 accidents in 2019.",
        evidence=(_evidence(),),
        limitations=("Counts are as reported by the source.",),
        datasets=("RA2019_A2",),
    )


# -- deterministic provider ------------------------------------------------


def test_deterministic_provider_is_always_available() -> None:
    assert DeterministicProvider().available() is True


def test_deterministic_answer_includes_summary_sources_and_limitations() -> None:
    result = DeterministicProvider().generate(_request())
    assert result.mode == "deterministic"
    assert "57,228" in result.text
    assert "data/raw/RA2019_A2.csv" in result.text
    assert "Counts are as reported by the source." in result.text
    assert "deterministic" in result.text.lower()


def test_render_deterministic_answer_reports_no_specific_columns_gracefully() -> None:
    request = GenerationRequest(
        question="q",
        summary="s",
        evidence=(
            Evidence(
                dataset_id="d",
                source_file="data/raw/x.csv",
                operation="op",
                units="u",
                time_period="t",
                geographic_scope="g",
                record_count=0,
            ),
        ),
    )
    text = render_deterministic_answer(request)
    assert "(no specific columns recorded)" in text


# -- prompt grounding ------------------------------------------------------


def test_prompt_contains_the_evidence_and_forbids_invention() -> None:
    prompt = _request().render_prompt()
    assert "data/raw/RA2019_A2.csv" in prompt
    assert "57,228" in prompt
    assert "EVIDENCE" in prompt


# -- provider selection ----------------------------------------------------


def test_local_provider_unavailable_without_a_model_id() -> None:
    assert LocalModelProvider(AISettings(model_id="")).available() is False


def test_api_provider_unavailable_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVICMIND_AI_API_KEY", raising=False)
    assert OpenAICompatibleProvider(AISettings()).available() is False


def test_api_provider_available_with_url_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICMIND_AI_API_KEY", "test-key")
    provider = OpenAICompatibleProvider(AISettings(api_base_url="http://localhost:9/v1"))
    assert provider.available() is True


def test_auto_falls_back_to_deterministic_when_nothing_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CIVICMIND_AI_API_KEY", raising=False)
    provider = build_provider(AISettings(provider="auto"))
    assert isinstance(provider, DeterministicProvider)


def test_explicit_local_without_model_falls_back_to_deterministic() -> None:
    provider = build_provider(AISettings(provider="local", model_id=""))
    assert isinstance(provider, DeterministicProvider)


def test_explicit_api_without_configuration_falls_back_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CIVICMIND_AI_API_KEY", raising=False)
    provider = build_provider(AISettings(provider="api"))
    assert isinstance(provider, DeterministicProvider)


def test_fallback_reason_explains_the_downgrade() -> None:
    settings = AISettings(provider="local", model_id="")
    provider = build_provider(settings)
    reason = provider_fallback_reason(settings, provider)
    assert reason is not None
    assert "not available" in reason


def test_no_fallback_reason_when_deterministic_is_explicit() -> None:
    settings = AISettings(provider="deterministic")
    assert provider_fallback_reason(settings, build_provider(settings)) is None


# -- device resolution -----------------------------------------------------


def test_cpu_device_is_honoured() -> None:
    assert resolve_device("cpu") == ("cpu", None)


def test_cuda_request_falls_back_to_cpu_with_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("civicmind.ai.providers._torch_cuda_available", lambda: False)
    device, warning = resolve_device("cuda")
    assert device == "cpu"
    assert warning is not None and "CUDA" in warning


def test_auto_uses_cuda_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("civicmind.ai.providers._torch_cuda_available", lambda: True)
    assert resolve_device("auto") == ("cuda", None)


def test_auto_uses_cpu_when_cuda_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("civicmind.ai.providers._torch_cuda_available", lambda: False)
    assert resolve_device("auto") == ("cpu", None)


# -- settings --------------------------------------------------------------


def test_settings_defaults_are_safe() -> None:
    settings = AISettings.from_env({})
    assert settings.provider == "auto"
    assert settings.model_id == ""
    assert settings.device == "auto"
    assert settings.api_key is None


def test_settings_summary_never_contains_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICMIND_AI_API_KEY", "super-secret")
    summary = AISettings.from_env().summary()
    assert "super-secret" not in str(summary)
    assert summary["api_key_set"] == "true"


def test_settings_reject_an_invalid_provider() -> None:
    with pytest.raises(AISettingsError):
        AISettings(provider="quantum").validate()


def test_settings_reject_an_invalid_device() -> None:
    with pytest.raises(AISettingsError):
        AISettings(device="tpu").validate()


def test_settings_parse_invalid_integers() -> None:
    with pytest.raises(AISettingsError):
        AISettings.from_env({"CIVICMIND_AI_MAX_NEW_TOKENS": "many"})


# -- grounding guard -------------------------------------------------------


def test_required_figures_extracts_numeric_tokens() -> None:
    figures = required_figures("Tamil Nadu reported 57,228 accidents; share 4.80399%.")
    assert "57228" in figures
    assert "4.80399" in figures


def test_missing_grounding_is_empty_when_figures_and_limitations_are_preserved() -> None:
    summary = "Telangana had 21,570 accidents and a 4.80399% share."
    limitations = ("Counts are as reported by the source.",)
    answer = (
        "Telangana reported 21570 accidents, a 4.80399% share. "
        "Counts are as reported by the source."
    )
    assert missing_grounding(answer, summary, limitations) == ()


def test_missing_grounding_detects_a_dropped_figure() -> None:
    summary = "Telangana had 21,570 accidents and a 4.80399% share."
    answer = "Telangana had many accidents and a small share."
    missing = missing_grounding(answer, summary)
    assert any("21570" in item for item in missing)
    assert any("4.80399" in item for item in missing)


def test_missing_grounding_detects_an_undisclosed_limitation() -> None:
    summary = "Tamil Nadu reported 57,228 accidents."
    limitations = ("Counts are as reported by the source.",)
    answer = "Tamil Nadu reported 57228 accidents."
    missing = missing_grounding(answer, summary, limitations)
    assert any(item.startswith("limitation") for item in missing)


# -- runtime failure classification ---------------------------------------


def test_describe_runtime_failure_explains_oom_actionably() -> None:
    class OutOfMemoryError(RuntimeError):
        pass

    message = describe_runtime_failure(
        OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB"), "cuda"
    )
    assert "out of memory" in message.lower()
    assert "CIVICMIND_AI_MAX_NEW_TOKENS" in message


def test_describe_runtime_failure_mentions_cpu_fallback_for_cuda_errors() -> None:
    message = describe_runtime_failure(RuntimeError("CUDA driver version is insufficient"), "cuda")
    assert "CIVICMIND_AI_DEVICE=cpu" in message


def test_describe_runtime_failure_passes_through_other_errors() -> None:
    message = describe_runtime_failure(ValueError("bad revision"), "cpu")
    assert "bad revision" in message


# -- local provider failure handling --------------------------------------


def test_local_provider_load_without_a_model_id_raises_provider_error() -> None:
    provider = LocalModelProvider(AISettings(model_id=""))
    with pytest.raises(ProviderError, match="CIVICMIND_AI_MODEL_ID"):
        provider.load()


@pytest.mark.skipif(
    importlib.util.find_spec("transformers") is not None,
    reason="transformers is installed; the missing-dependency path cannot be exercised",
)
def test_local_provider_load_without_transformers_raises_actionable_error() -> None:
    provider = LocalModelProvider(AISettings(model_id="some/model"))
    with pytest.raises(ProviderError, match="ai"):
        provider.load()


def test_local_provider_reports_no_device_before_loading() -> None:
    assert LocalModelProvider(AISettings(model_id="some/model")).device is None
