"""Environment-driven configuration for CivicMind AI.

Resolution order (highest precedence first):

1. Real process environment variables.
2. Values loaded from a local ``.env`` file (git-ignored, never committed).
3. Sensible built-in defaults.

Secrets are read exclusively through :func:`get_secret`; they are never
hardcoded, never written to logs and never returned by :class:`Settings`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_PREFIX = "CIVICMIND_"

VALID_ENVIRONMENTS: frozenset[str] = frozenset(
    {"development", "testing", "staging", "production"},
)
VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
VALID_LOG_FORMATS: frozenset[str] = frozenset({"text", "json"})

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Raised when environment-derived configuration is missing or invalid."""


def _walk_up(start: Path) -> Path | None:
    """Return the nearest ancestor of ``start`` containing ``pyproject.toml``."""
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def find_project_root(start: Path | None = None) -> Path:
    """Locate the project root.

    Order of precedence:

    1. ``CIVICMIND_PROJECT_ROOT`` environment variable, if set and valid.
    2. The nearest ancestor of this module (works for editable installs).
    3. The nearest ancestor of the current working directory.
    4. The current working directory as a last resort.
    """
    override = os.environ.get(f"{ENV_PREFIX}PROJECT_ROOT")
    if override:
        root = Path(override).expanduser()
        if not root.is_dir():
            raise ConfigurationError(
                f"{ENV_PREFIX}PROJECT_ROOT points to a directory that does not exist: {root}"
            )
        return root.resolve()

    start_point = Path(start) if start is not None else Path(__file__)
    start_point = start_point.resolve()
    if start_point.is_file():
        start_point = start_point.parent

    for origin in (start_point, Path.cwd()):
        found = _walk_up(origin)
        if found is not None:
            return found
    return Path.cwd().resolve()


def load_dotenv_file(project_root: Path, dotenv_path: Path | None = None) -> Path | None:
    """Load a ``.env`` file into the process environment, if present.

    Existing process variables are never overridden, so real environment
    variables always win over ``.env`` values. Returns the loaded path, or
    ``None`` when no file was loaded (missing file or missing dependency).
    """
    path = (dotenv_path or project_root / ".env").expanduser()
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
        logger.debug("python-dotenv not installed; reading process environment only")
        return None
    if not path.is_file():
        return None
    load_dotenv(dotenv_path=path, override=False)
    logger.debug("Loaded environment overrides from %s", path)
    return path


def _resolve_path(value: str, project_root: Path) -> Path:
    """Resolve ``value`` into an absolute path (relative paths join the root)."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


@dataclass(frozen=True)
class Settings:
    """Immutable, environment-derived application settings.

    Instances are constructed with :meth:`from_env`; no setting is ever read
    from a hardcoded credential or a committed file.
    """

    environment: str = "development"
    log_level: str = "INFO"
    log_format: str = "text"
    project_root: Path = Path(".")
    data_dir: Path = Path("data")
    logs_dir: Path = Path("logs")
    artifacts_dir: Path = Path("artifacts")
    configs_dir: Path = Path("configs")

    # -- derived locations -------------------------------------------------
    @property
    def raw_data_dir(self) -> Path:
        """Directory for untouched, as-acquired datasets (never committed)."""
        return self.data_dir / "raw"

    @property
    def interim_data_dir(self) -> Path:
        """Directory for intermediate outputs of the validation/profiling stage."""
        return self.data_dir / "interim"

    @property
    def processed_data_dir(self) -> Path:
        """Directory for clean, analysis-ready datasets."""
        return self.data_dir / "processed"

    @property
    def external_data_dir(self) -> Path:
        """Directory for third-party reference data (e.g. gazetteers)."""
        return self.data_dir / "external"

    @property
    def log_file(self) -> Path:
        """Default application log file."""
        return self.logs_dir / "civicmind.log"

    def data_directories(self) -> dict[str, Path]:
        """Return the named data directories used by the pipeline stages."""
        return {
            "raw": self.raw_data_dir,
            "interim": self.interim_data_dir,
            "processed": self.processed_data_dir,
            "external": self.external_data_dir,
        }

    def ensure_directories(self) -> tuple[Path, ...]:
        """Create the managed directories (and return them) if missing."""
        directories = (
            *self.data_directories().values(),
            self.logs_dir,
            self.artifacts_dir,
            self.configs_dir,
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        return directories

    def summary(self) -> dict[str, str]:
        """Return a log/print-safe summary. Secrets are deliberately absent."""
        return {
            "environment": self.environment,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "project_root": str(self.project_root),
            "data_dir": str(self.data_dir),
            "raw_data_dir": str(self.raw_data_dir),
            "interim_data_dir": str(self.interim_data_dir),
            "processed_data_dir": str(self.processed_data_dir),
            "external_data_dir": str(self.external_data_dir),
            "logs_dir": str(self.logs_dir),
            "artifacts_dir": str(self.artifacts_dir),
            "configs_dir": str(self.configs_dir),
        }

    # -- construction ------------------------------------------------------
    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Build settings from the environment.

        Parameters
        ----------
        environ:
            Mapping to read from. When ``None`` (the default), a local
            ``.env`` file is loaded first and ``os.environ`` is used.
        """
        if environ is None:
            load_dotenv_file(find_project_root())
            environ = os.environ

        project_root = _resolve_root(environ)
        settings = cls(
            environment=environ.get(f"{ENV_PREFIX}ENV", "development").strip() or "development",
            log_level=(environ.get(f"{ENV_PREFIX}LOG_LEVEL", "INFO") or "INFO").strip().upper(),
            log_format=(environ.get(f"{ENV_PREFIX}LOG_FORMAT", "text") or "text").strip().lower(),
            project_root=project_root,
            data_dir=_resolve_path(environ.get(f"{ENV_PREFIX}DATA_DIR", "data"), project_root),
            logs_dir=_resolve_path(environ.get(f"{ENV_PREFIX}LOGS_DIR", "logs"), project_root),
            artifacts_dir=_resolve_path(
                environ.get(f"{ENV_PREFIX}ARTIFACTS_DIR", "artifacts"), project_root
            ),
            configs_dir=_resolve_path(
                environ.get(f"{ENV_PREFIX}CONFIGS_DIR", "configs"), project_root
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Raise :class:`ConfigurationError` when a setting is invalid."""
        if self.environment not in VALID_ENVIRONMENTS:
            raise ConfigurationError(
                f"Invalid {ENV_PREFIX}ENV={self.environment!r}; "
                f"expected one of {sorted(VALID_ENVIRONMENTS)}"
            )
        if self.log_level not in VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"Invalid {ENV_PREFIX}LOG_LEVEL={self.log_level!r}; "
                f"expected one of {sorted(VALID_LOG_LEVELS)}"
            )
        if self.log_format not in VALID_LOG_FORMATS:
            raise ConfigurationError(
                f"Invalid {ENV_PREFIX}LOG_FORMAT={self.log_format!r}; "
                f"expected one of {sorted(VALID_LOG_FORMATS)}"
            )


def _resolve_root(environ: Mapping[str, str]) -> Path:
    """Resolve the project root, honouring an explicit override if present."""
    override = environ.get(f"{ENV_PREFIX}PROJECT_ROOT")
    if override:
        root = Path(override).expanduser()
        if not root.is_dir():
            raise ConfigurationError(
                f"{ENV_PREFIX}PROJECT_ROOT points to a directory that does not exist: {root}"
            )
        return root.resolve()
    return find_project_root()


def get_secret(
    name: str,
    default: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Read a secret strictly from the environment.

    The ``CIVICMIND_`` prefix is added automatically when absent. An empty or
    whitespace-only value is treated as "not set" so placeholders in
    ``.env.example`` never masquerade as real credentials.

    Secrets must never be hardcoded, logged, cached in artifacts or committed.
    """
    key = name if name.startswith(ENV_PREFIX) else f"{ENV_PREFIX}{name.strip().upper()}"
    source = os.environ if environ is None else environ
    value = source.get(key, default)
    if value is None:
        return None
    return value if value.strip() else default
