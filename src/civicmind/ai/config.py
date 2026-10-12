"""Configuration for the AI/decision-support layer.

Kept separate from :class:`civicmind.config.Settings` so the ingestion and
vision-layer configuration stays untouched and backward compatible. All values
are read through the shared ``CIVICMIND_`` environment prefix and the same
``.env`` mechanism, so no new secret store or hardcoded credential is
introduced.

Model identifiers and device selection are configured here, never hardcoded to
a machine-specific absolute path, so the same code runs on a CPU laptop and on
the college GPU machine.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

ENV_PREFIX = "CIVICMIND_"

#: Provider selection modes.
PROVIDER_MODES: frozenset[str] = frozenset({"auto", "deterministic", "local", "api"})

#: Device selection modes accepted from configuration.
_DEVICE_PREFIXES: tuple[str, ...] = ("cpu", "cuda", "mps", "auto")

DEFAULT_MAX_NEW_TOKENS = 512
DEFAULT_TIMEOUT_SECONDS = 30.0


class AISettingsError(RuntimeError):
    """Raised when AI configuration is invalid."""


@dataclass(frozen=True)
class AISettings:
    """Immutable, environment-derived settings for the AI layer.

    Attributes
    ----------
    provider:
        ``auto`` (default), ``deterministic``, ``local`` or ``api``. ``auto``
        picks a local model when one is configured and importable, then an API
        model when one is configured, and otherwise the deterministic fallback.
    model_id:
        Hugging Face identifier (or local directory) for the local backend.
        Empty means "no local model configured".
    device:
        ``auto``, ``cpu``, ``cuda`` or ``cuda:N``/``mps``. ``auto`` resolves to
        CUDA when available, else CPU.
    max_new_tokens, temperature:
        Generation controls for the local/API backends.
    api_base_url:
        Base URL of an OpenAI-compatible chat-completions endpoint.
    api_key_env:
        Name of the environment variable holding the API key. The key itself is
        never stored on this object, never logged, and never written to disk.
    timeout_seconds:
        Request timeout for the API backend.
    """

    provider: str = "auto"
    model_id: str = ""
    device: str = "auto"
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
    temperature: float = 0.0
    api_base_url: str = ""
    api_key_env: str = f"{ENV_PREFIX}AI_API_KEY"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def api_key(self) -> str | None:
        """Return the API key from the environment, or ``None`` when unset.

        The value is read on demand and is never persisted on the settings
        object or emitted by :meth:`summary`.
        """
        value = os.environ.get(self.api_key_env)
        return value.strip() if value and value.strip() else None

    def summary(self) -> dict[str, str]:
        """Return a print/log-safe summary. The API key is deliberately absent."""
        return {
            "provider": self.provider,
            "model_id": self.model_id or "(none)",
            "device": self.device,
            "max_new_tokens": str(self.max_new_tokens),
            "temperature": str(self.temperature),
            "api_base_url": self.api_base_url or "(none)",
            "api_key_env": self.api_key_env,
            "api_key_set": str(self.api_key is not None).lower(),
            "timeout_seconds": str(self.timeout_seconds),
        }

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AISettings:
        """Build AI settings from the environment (or a supplied mapping)."""
        source = os.environ if environ is None else environ

        def _get(name: str, default: str) -> str:
            value = source.get(f"{ENV_PREFIX}{name}", default)
            return value if value is not None and value.strip() else default

        def _int(name: str, default: int) -> int:
            raw = _get(name, str(default)).strip()
            try:
                return int(raw)
            except ValueError as exc:
                raise AISettingsError(f"{ENV_PREFIX}{name}={raw!r} is not an integer") from exc

        def _float(name: str, default: float) -> float:
            raw = _get(name, str(default)).strip()
            try:
                return float(raw)
            except ValueError as exc:
                raise AISettingsError(f"{ENV_PREFIX}{name}={raw!r} is not a number") from exc

        settings = cls(
            provider=_get("AI_PROVIDER", "auto").strip().lower(),
            model_id=_get("AI_MODEL_ID", "").strip(),
            device=_get("AI_DEVICE", "auto").strip().lower(),
            max_new_tokens=_int("AI_MAX_NEW_TOKENS", DEFAULT_MAX_NEW_TOKENS),
            temperature=_float("AI_TEMPERATURE", 0.0),
            api_base_url=_get("AI_API_BASE_URL", "").strip(),
            api_key_env=_get("AI_API_KEY_ENV", f"{ENV_PREFIX}AI_API_KEY").strip(),
            timeout_seconds=_float("AI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Raise :class:`AISettingsError` when a value is invalid."""
        if self.provider not in PROVIDER_MODES:
            raise AISettingsError(
                f"{ENV_PREFIX}AI_PROVIDER={self.provider!r}; "
                f"expected one of {sorted(PROVIDER_MODES)}"
            )
        if self.max_new_tokens <= 0:
            raise AISettingsError("CIVICMIND_AI_MAX_NEW_TOKENS must be positive")
        if self.temperature < 0:
            raise AISettingsError("CIVICMIND_AI_TEMPERATURE must be non-negative")
        if self.timeout_seconds <= 0:
            raise AISettingsError("CIVICMIND_AI_TIMEOUT_SECONDS must be positive")
        if not any(self.device.startswith(prefix) for prefix in _DEVICE_PREFIXES):
            raise AISettingsError(
                f"{ENV_PREFIX}AI_DEVICE={self.device!r}; expected auto/cpu/cuda[:N]/mps"
            )
        if not self.api_key_env:
            raise AISettingsError("CIVICMIND_AI_API_KEY_ENV must name an environment variable")


__all__ = [
    "ENV_PREFIX",
    "PROVIDER_MODES",
    "AISettings",
    "AISettingsError",
]
