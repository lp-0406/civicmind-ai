"""Answer-generation providers.

The pipeline separates *computing* an answer from *phrasing* it. This module
owns the phrasing side and offers three interchangeable backends behind one
:class:`AnswerProvider` contract:

``deterministic``
    Always available, no dependencies, no network. It renders the computed
    summary plus citations and limitations verbatim.
``local``
    A Hugging Face ``transformers`` text-generation pipeline, loaded lazily and
    run on CPU or CUDA. Nothing is imported or downloaded at module import time.
``api``
    An OpenAI-compatible chat-completions endpoint, used only when a base URL
    and an API key are configured.

Whatever the backend, the model receives the computed result and the evidence
and is instructed never to invent numbers, citations, dataset identities,
licence status or provenance. If a configured backend is unavailable the
pipeline falls back to ``deterministic`` and reports the reason; it never
fabricates an answer or silently drops the evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from civicmind.ai.config import AISettings
from civicmind.ai.evidence import Evidence

SYSTEM_PROMPT = (
    "You are CivicMind AI, a municipal decision-support assistant. You are given a "
    "question, a deterministic analytical result computed from real CSV data, and the "
    "supporting evidence. Rules you must follow without exception:\n"
    "1. Use ONLY the numbers, dates, places and figures present in the supplied result and "
    "evidence. Do not compute, estimate, round to new values, or invent any statistic.\n"
    "2. Cite the source file named in the evidence for every figure you state.\n"
    "3. Preserve the stated time period, geographic scope and units.\n"
    "4. Never claim a licence is verified, that a dataset was downloaded, or that a file is "
    "a verified canonical resource unless the evidence explicitly says so.\n"
    "5. Restate the listed limitations.\n"
    "6. If the evidence does not answer the question, say so plainly."
)


class ProviderError(RuntimeError):
    """Raised when a provider cannot generate an answer."""


@dataclass(frozen=True)
class GenerationRequest:
    """Everything a provider needs to phrase one grounded answer."""

    question: str
    summary: str
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...] = ()
    datasets: tuple[str, ...] = ()
    execution_mode_hint: str = "deterministic"

    def render_prompt(self) -> str:
        """Render the grounding prompt handed to a language model."""
        evidence_payload = json.dumps(
            [item.to_dict() for item in self.evidence], indent=2, ensure_ascii=False
        )
        limitations = "\n".join(f"- {item}" for item in self.limitations) or "- (none stated)"
        return (
            f"QUESTION:\n{self.question}\n\n"
            f"COMPUTED RESULT (deterministic, authoritative):\n{self.summary}\n\n"
            f"EVIDENCE (JSON; the only permitted source of facts):\n{evidence_payload}\n\n"
            f"LIMITATIONS TO RESTATE:\n{limitations}\n\n"
            "Write a concise, decision-useful answer grounded strictly in the material above."
        )


@dataclass(frozen=True)
class GenerationResult:
    """A phrased answer plus which backend produced it."""

    text: str
    mode: str
    provider: str
    model: str | None = None
    fallback_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable view."""
        return {
            "text": self.text,
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "fallback_reason": self.fallback_reason,
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class AnswerProvider(Protocol):
    """Contract every answer provider implements."""

    name: str
    mode: str

    def available(self) -> bool:
        """Return True when this provider can currently generate an answer."""

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Phrase ``request`` into a grounded answer."""


def render_deterministic_answer(request: GenerationRequest) -> str:
    """Render the deterministic, template-based answer text."""
    parts: list[str] = [request.summary]
    if request.evidence:
        parts.append("")
        parts.append("Sources and method:")
        for item in request.evidence:
            used = ", ".join(item.columns) if item.columns else "(no specific columns recorded)"
            parts.append(
                f"- {item.citation()} | operation: {item.operation} | units: {item.units} | "
                f"columns: {used}"
            )
    if request.limitations:
        parts.append("")
        parts.append("Limitations:")
        parts.extend(f"- {item}" for item in request.limitations)
    if request.evidence:
        quality: list[str] = []
        for item in request.evidence:
            quality.extend(item.quality_issues)
        if quality:
            parts.append("")
            parts.append("Data-quality notes:")
            parts.extend(f"- {note}" for note in dict.fromkeys(quality))
    parts.append("")
    parts.append(
        "Mode: deterministic analytics (no external model was used); every figure above was "
        "computed directly from the cited CSV."
    )
    return "\n".join(parts)


class DeterministicProvider:
    """Template-based provider: always available, never fabricates."""

    name = "deterministic"
    mode = "deterministic"

    def available(self) -> bool:
        """The deterministic provider is always available."""
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Render the deterministic answer."""
        return GenerationResult(
            text=render_deterministic_answer(request),
            mode="deterministic",
            provider=self.name,
            model=None,
        )


def resolve_device(requested: str) -> tuple[str, str | None]:
    """Resolve a configured device to a concrete torch device.

    Returns ``(device, warning)``. ``warning`` is set when a CUDA/MPS request
    cannot be honoured, so the caller can report the fallback rather than
    silently pretending the GPU was used.
    """
    normalized = (requested or "auto").strip().lower()
    if normalized == "cpu":
        return "cpu", None

    cuda_available = _torch_cuda_available()
    if normalized == "auto":
        return ("cuda" if cuda_available else "cpu"), None
    if normalized.startswith("cuda"):
        if cuda_available:
            return normalized, None
        return "cpu", (
            f"CUDA device {normalized!r} was requested but no CUDA device is available; "
            "falling back to CPU. Install a CUDA-enabled PyTorch build on the GPU machine."
        )
    if normalized.startswith("mps"):
        return "cpu", (
            "MPS device was requested; this build does not dispatch to MPS explicitly; using CPU."
        )
    return "cpu", f"unknown device {requested!r}; falling back to CPU."


def _torch_cuda_available() -> bool:
    """Return True when torch is importable and reports CUDA availability."""
    try:
        import torch  # noqa: PLC0415 - deliberately lazy: heavy optional dependency
    except ImportError:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:  # pragma: no cover - defensive against driver errors
        return False


def _device_index(device: str) -> int:
    """Map a resolved device string to the integer index transformers expects.

    ``-1`` means CPU; ``cuda:N`` maps to ``N``; a bare ``cuda`` maps to ``0``.
    """
    if device == "cpu":
        return -1
    if ":" in device:
        return int(device.split(":", 1)[1])
    return 0


def describe_runtime_failure(exc: BaseException, device: str) -> str:
    """Return an actionable message for a model load/inference failure.

    Recognises CUDA out-of-memory (by class name or message, so torch does not
    have to be imported to classify it) and other CUDA errors, and otherwise
    reports the underlying error verbatim.
    """
    message = str(exc)
    lowered = message.lower()
    is_oom = type(exc).__name__ == "OutOfMemoryError" or "out of memory" in lowered
    if is_oom:
        return (
            f"the model ran out of memory on {device!r}: {message}. Reduce "
            "CIVICMIND_AI_MAX_NEW_TOKENS, choose a smaller or quantized model, or free GPU memory."
        )
    if "cuda" in lowered:
        return (
            f"a CUDA error occurred on {device!r}: {message}. Verify the CUDA/torch build and "
            "driver, or set CIVICMIND_AI_DEVICE=cpu to run on CPU."
        )
    return f"inference on {device!r} failed: {message}"


class LocalModelProvider:
    """Local Hugging Face text-generation backend (CPU or CUDA), loaded lazily.

    The model is loaded on the first :meth:`generate` call, never at import time
    and never on construction, so importing this module downloads and allocates
    nothing. Load and inference failures (missing dependency, unavailable model,
    CUDA error, out-of-memory) are converted into an actionable
    :class:`ProviderError` so the decision engine can fall back to the
    deterministic answer instead of crashing or inventing one.
    """

    name = "local"

    def __init__(self, settings: AISettings) -> None:
        self.settings = settings
        self.mode = "local"
        self._pipeline: Any = None
        self._device: str | None = None

    def available(self) -> bool:
        """Return True when a model id is configured and transformers is importable."""
        if not self.settings.model_id:
            return False
        try:
            import transformers  # noqa: F401,PLC0415 - availability probe only
        except ImportError:
            return False
        return True

    @property
    def device(self) -> str | None:
        """The device the model actually runs on, once loaded."""
        return self._device

    def load(self) -> Any:
        """Load the text-generation pipeline lazily, converting failures to ProviderError."""
        if self._pipeline is not None:
            return self._pipeline
        if not self.settings.model_id:
            raise ProviderError(
                "no local model is configured; set CIVICMIND_AI_MODEL_ID to a model id or path"
            )
        try:
            from transformers import pipeline
        except ImportError as exc:
            raise ProviderError(
                "the local model backend requires 'transformers'; install the optional 'ai' extra"
            ) from exc

        device, _warning = resolve_device(self.settings.device)
        kwargs: dict[str, Any] = {}
        if device.startswith("cuda"):
            # 'auto' selects the model's own dtype; half precision halves VRAM on GPU.
            kwargs["torch_dtype"] = "auto"
        try:
            self._pipeline = pipeline(
                "text-generation",
                model=self.settings.model_id,
                device=_device_index(device),
                **kwargs,
            )
        except OSError as exc:
            raise ProviderError(
                f"could not load model {self.settings.model_id!r}: "
                f"{describe_runtime_failure(exc, device)}"
            ) from exc
        except (RuntimeError, ValueError, TypeError) as exc:
            raise ProviderError(
                f"failed to initialise model {self.settings.model_id!r}: "
                f"{describe_runtime_failure(exc, device)}"
            ) from exc
        self._device = device
        return self._pipeline

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate an answer with the local model."""
        generator = self.load()
        device, warning = resolve_device(self.settings.device)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request.render_prompt()},
        ]
        try:
            outputs = generator(
                messages,
                max_new_tokens=self.settings.max_new_tokens,
                do_sample=self.settings.temperature > 0,
                temperature=self.settings.temperature or 1.0,
            )
        except Exception as exc:  # noqa: BLE001 - classified, then re-raised as ProviderError
            raise ProviderError(describe_runtime_failure(exc, device)) from exc
        text = _extract_generated_text(outputs)
        if not text.strip():
            raise ProviderError("the local model returned an empty response")
        return GenerationResult(
            text=text,
            mode="local",
            provider=self.name,
            model=self.settings.model_id,
            fallback_reason=warning,
            metadata={"device": device, "cuda": device.startswith("cuda")},
        )


#: Matches a whole numeric token, including thousands separators, decimals and sign.
_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def required_figures(summary: str) -> tuple[str, ...]:
    """Return the whole numeric tokens (comma separators removed) a summary asserts."""
    return tuple(dict.fromkeys(token.replace(",", "") for token in _NUMBER_RE.findall(summary)))


def answer_figures(answer_text: str) -> set[str]:
    """Return the whole numeric tokens present in an answer (comma-normalised).

    Tokens are matched as complete numbers, so ``157228`` is *not* treated as
    containing ``57228``, ``4490020`` is not ``449002``, ``57228.9`` is not
    ``57228``, and ``-57228`` is not ``57228``. Matching is by exact token
    membership rather than substring containment, which is what stops an altered
    magnitude or sign from silently passing the grounding check.
    """
    normalized = answer_text.replace(",", "")
    return {match.group(0) for match in _NUMBER_RE.finditer(normalized)}


def _word_sequence(text: str) -> str:
    """Return a lower-cased, punctuation-free word sequence for comparison.

    Punctuation is dropped so that an answer writing ``the national Total row``
    matches a limitation written ``the national 'Total' row``; otherwise the
    guard rejects a faithful paraphrase purely because of quotation marks.
    """
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _limitation_signature(limitation: str, words: int = 4) -> str:
    """Return a short, comparable fragment of a limitation sentence."""
    return " ".join(_word_sequence(limitation).split()[:words])


def missing_grounding(
    answer_text: str,
    summary: str,
    limitations: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return the figures/limitations a generated answer failed to preserve.

    This is the guard that stops a language model from silently dropping or
    altering the computed numbers. Every numeric token in ``summary`` must appear
    (after removing thousands separators) in the generated text, and at least the
    opening fragment of each listed limitation must be disclosed. Anything
    missing is returned so the caller can fall back to the deterministic answer.

    The limitation check is a deliberately simple keyword-fragment heuristic: it
    is tuned to be permissive about paraphrase while still catching an answer
    that omits the caveats entirely.
    """
    present = answer_figures(answer_text)
    missing: list[str] = []
    for figure in required_figures(summary):
        if figure not in present:
            missing.append(f"figure {figure}")
    answer_words = f" {_word_sequence(answer_text)} "
    for limitation in limitations:
        signature = _limitation_signature(limitation)
        if signature and f" {signature} " not in answer_words:
            missing.append(f"limitation {signature!r}")
    return tuple(missing)


def _extract_generated_text(outputs: Any) -> str:
    """Pull the assistant's text out of a transformers pipeline result."""
    if isinstance(outputs, list) and outputs:
        first = outputs[0]
        if isinstance(first, dict):
            generated = first.get("generated_text")
            if isinstance(generated, list) and generated:
                last = generated[-1]
                if isinstance(last, dict) and "content" in last:
                    return str(last["content"]).strip()
            if isinstance(generated, str):
                return generated.strip()
    return str(outputs).strip()


class OpenAICompatibleProvider:
    """API backend for any OpenAI-compatible chat-completions endpoint."""

    name = "api"
    mode = "api"

    def __init__(self, settings: AISettings) -> None:
        self.settings = settings

    def available(self) -> bool:
        """Return True when a base URL and an API key are both configured."""
        return bool(self.settings.api_base_url) and self.settings.api_key is not None

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Call the configured endpoint and return its message content."""
        import httpx

        url = self.settings.api_base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.settings.model_id or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": request.render_prompt()},
            ],
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_new_tokens,
        }
        headers = {"Authorization": f"Bearer {self.settings.api_key}"}
        try:
            response = httpx.post(
                url, json=payload, headers=headers, timeout=self.settings.timeout_seconds
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(f"API provider request failed: {exc}") from exc
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"API provider returned an unexpected payload: {data!r}") from exc
        return GenerationResult(
            text=str(text).strip(),
            mode="api",
            provider=self.name,
            model=payload["model"],
        )


def build_provider(settings: AISettings) -> AnswerProvider:
    """Return the best available provider for ``settings``.

    ``auto`` prefers a configured local model, then a configured API model, then
    the deterministic fallback. An explicitly requested backend that is
    unavailable also falls back, with the reason recorded on the result.
    """
    deterministic = DeterministicProvider()
    requested = settings.provider

    if requested == "deterministic":
        return deterministic

    local = LocalModelProvider(settings)
    api = OpenAICompatibleProvider(settings)

    if requested == "local":
        return local if local.available() else deterministic
    if requested == "api":
        return api if api.available() else deterministic

    if local.available():
        return local
    if api.available():
        return api
    return deterministic


def provider_fallback_reason(settings: AISettings, provider: AnswerProvider) -> str | None:
    """Explain why the deterministic fallback is in use, when it is."""
    if provider.mode == "deterministic" and settings.provider != "deterministic":
        return (
            f"provider {settings.provider!r} was requested but is not available "
            "(check CIVICMIND_AI_MODEL_ID / transformers for local, or "
            "CIVICMIND_AI_API_BASE_URL and the configured API key for the API backend); "
            "using the deterministic fallback"
        )
    return None


__all__ = [
    "SYSTEM_PROMPT",
    "AnswerProvider",
    "DeterministicProvider",
    "GenerationRequest",
    "GenerationResult",
    "LocalModelProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "answer_figures",
    "build_provider",
    "describe_runtime_failure",
    "missing_grounding",
    "provider_fallback_reason",
    "render_deterministic_answer",
    "required_figures",
    "resolve_device",
]
