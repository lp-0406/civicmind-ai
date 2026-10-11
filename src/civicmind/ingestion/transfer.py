"""Bounded streaming HTTP transfer for explicit dataset acquisition.

This module is the transport half of the ingestion contract: it knows how to
retrieve bytes safely, and nothing about which dataset is involved. Dataset
identity, schema and provenance live in the handler and the canonical record.

Safety rules enforced here
--------------------------
* **Explicit limits.** Connect timeout, read timeout and a maximum byte count
  are always supplied; a transfer cannot run unbounded.
* **No implicit redirects.** A 3xx response is refused, never followed, so a
  pinned resource URL cannot silently resolve to a different location.
* **Streaming, never buffered.** Bytes are read in chunks to a temporary file;
  the response is never held in memory as a whole.
* **Atomic promotion.** A temporary file is renamed into place only after the
  transfer's own checks pass. A failed or interrupted transfer leaves no
  artifact and never touches a previously acquired one.
* **No silent overwrite.** Promoting onto an existing path is an error.
* **Measured facts only.** Byte size and SHA-256 are computed from the bytes
  that were actually written.

Retries are deliberately narrow: only transport-level failures and the
explicitly transient HTTP statuses are retried, with bounded attempts and
exponential backoff. Client errors (4xx), redirects, an oversized response and
an existing destination are never retried.
"""

from __future__ import annotations

import hashlib
import http.client
import os
import ssl
import time
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from civicmind.ingestion.exceptions import AcquisitionError

#: Default socket timeout for establishing a connection, in seconds.
DEFAULT_CONNECT_TIMEOUT = 10.0
#: Default socket timeout for each read while streaming the body, in seconds.
DEFAULT_READ_TIMEOUT = 30.0
#: Default hard ceiling on a single transfer, in bytes (8 MiB).
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
#: Default number of total attempts (1 initial + retries) for transient failures.
DEFAULT_ATTEMPTS = 3
#: Base backoff between attempts, in seconds; doubled per attempt with jitter.
DEFAULT_BACKOFF_SECONDS = 0.5
#: Bytes read per chunk while streaming.
CHUNK_SIZE = 64 * 1024

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BACKOFF_JITTER = 0.25


class TransferError(AcquisitionError):
    """Base class for transfer failures. Non-retryable unless stated."""

    retryable = False


class TransientTransferError(TransferError):
    """A transport failure that may succeed if attempted again."""

    retryable = True


class InvalidUrlError(TransferError):
    """Raised when the URL is malformed or uses an unsupported scheme."""


class RedirectRefusedError(TransferError):
    """Raised when the server answers with a redirect instead of the resource."""


class OversizedResponseError(TransferError):
    """Raised when the response exceeds the configured maximum byte count."""


class ArtifactExistsError(TransferError):
    """Raised when promoting the artifact would overwrite an existing file."""


class HttpStatusError(TransferError):
    """Raised for a non-retryable HTTP status (typically a 4xx client error)."""

    def __init__(self, status: int, reason: str, url: str) -> None:
        super().__init__(f"HTTP {status} {reason} for {url}")
        self.status = status
        self.reason = reason
        self.url = url


class TransientHttpStatusError(HttpStatusError):
    """Raised for an HTTP status that is worth retrying (5xx, 408, 429)."""

    retryable = True


class TruncatedResponseError(TransientTransferError):
    """Raised when the body ends before the advertised content length."""


@dataclass(frozen=True)
class TransferLimits:
    """Explicit, caller-supplied bounds for one transfer."""

    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT
    max_bytes: int = DEFAULT_MAX_BYTES
    attempts: int = DEFAULT_ATTEMPTS
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS

    def __post_init__(self) -> None:
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise ValueError("timeouts must be positive")
        if self.max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {self.max_bytes!r}")
        if self.attempts < 1:
            raise ValueError(f"attempts must be >= 1, got {self.attempts!r}")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be >= 0")

    def as_dict(self) -> dict[str, float | int]:
        """Return a JSON-safe description of the limits."""
        return {
            "connect_timeout_seconds": self.connect_timeout,
            "read_timeout_seconds": self.read_timeout,
            "max_bytes": self.max_bytes,
            "attempts": self.attempts,
            "backoff_seconds": self.backoff_seconds,
        }


@dataclass(frozen=True)
class TransferOutcome:
    """Facts measured from one successful transfer."""

    url: str
    status: int
    content_type: str
    byte_size: int
    checksum_sha256: str
    local_path: Path
    attempts: int
    retrieved_at: datetime
    content_length_header: int | None = None
    etag: str | None = None
    last_modified: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe description of the transfer."""
        return {
            "url": self.url,
            "status": self.status,
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "local_path": str(self.local_path),
            "attempts": self.attempts,
            "retrieved_at": self.retrieved_at.isoformat(),
            "content_length_header": self.content_length_header,
            "etag": self.etag,
            "last_modified": self.last_modified,
        }


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=timezone.utc)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of ``path``, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_content_length(headers: object) -> int | None:
    """Return the ``Content-Length`` header as an int, or ``None`` when absent/invalid."""
    raw = None
    if hasattr(headers, "get"):
        raw = headers.get("Content-Length")  # type: ignore[union-attr]
    if raw is None:
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None
    return value if value >= 0 else None


def _header(headers: object, name: str) -> str | None:
    """Return a header value as a trimmed string, or ``None`` when absent."""
    if not hasattr(headers, "get"):
        return None
    value = headers.get(name)  # type: ignore[union-attr]
    return None if value is None else str(value).strip()


def _sleep_with_backoff(seconds: float) -> None:
    """Sleep for ``seconds`` plus a small deterministic-free jitter."""
    if seconds > 0:
        time.sleep(seconds)


def download_to_file(
    url: str,
    destination_dir: Path,
    *,
    filename: str,
    limits: TransferLimits | None = None,
    sleep: Callable[[float], None] = _sleep_with_backoff,
    clock: Callable[[], datetime] = _utc_now,
) -> TransferOutcome:
    """Stream ``url`` into ``destination_dir``/``filename`` with explicit limits.

    The body is written to a temporary file in ``destination_dir`` and only
    promoted to ``filename`` after the transfer's checks pass, so ``filename``
    never contains a partial download.

    Parameters
    ----------
    url:
        The exact resource URL to fetch. Redirects are refused, not followed.
    destination_dir:
        Directory for the temporary file and the promoted artifact.
    filename:
        Final file name inside ``destination_dir``. Must not already exist.
    limits:
        Explicit bounds; defaults to :class:`TransferLimits`.
    sleep:
        Injectable sleep, so tests do not have to wait for real backoff.
    clock:
        Injectable clock, so timestamps are deterministic in tests.

    Returns
    -------
    TransferOutcome
        Measured facts about the transfer.

    Raises
    ------
    InvalidUrlError
        When the URL is malformed or not http/https.
    ArtifactExistsError
        When ``filename`` already exists in ``destination_dir``.
    RedirectRefusedError
        When the server answers with a 3xx status.
    OversizedResponseError
        When the response exceeds ``limits.max_bytes``.
    HttpStatusError / TransientHttpStatusError
        When the server answers with an unexpected status.
    TransientTransferError / TruncatedResponseError
        On transport failures or a short body, after the attempt budget is spent.
    """
    bounds = limits if limits is not None else TransferLimits()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES or not parts.hostname:
        raise InvalidUrlError(f"unsupported or malformed URL: {url!r}")

    destination_dir = Path(destination_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    final_path = destination_dir / filename
    if final_path.exists():
        raise ArtifactExistsError(f"refusing to overwrite an existing artifact: {final_path}")

    tmp_path = destination_dir / f".{filename}.{os.getpid()}.{uuid.uuid4().hex[:8]}.part"
    target = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    headers = {
        "User-Agent": "CivicMind-AI/0.1 (explicit dataset acquisition)",
        "Accept": "text/csv,application/csv,text/plain,application/octet-stream,*/*;q=0.1",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }

    last_error: TransferError | None = None
    for attempt in range(1, bounds.attempts + 1):
        try:
            outcome = _stream_once(
                url=url,
                parts=parts,
                target=target,
                headers=headers,
                tmp_path=tmp_path,
                final_path=final_path,
                limits=bounds,
                attempt=attempt,
                clock=clock,
            )
        except TransferError as exc:
            last_error = exc
            tmp_path.unlink(missing_ok=True)
            if not exc.retryable or attempt >= bounds.attempts:
                raise
            sleep(bounds.backoff_seconds * (2 ** (attempt - 1)))
        else:
            tmp_path.unlink(missing_ok=True)
            return outcome
    raise last_error if last_error is not None else TransferError(f"transfer failed: {url}")


def _stream_once(
    *,
    url: str,
    parts: urllib.parse.SplitResult,
    target: str,
    headers: dict[str, str],
    tmp_path: Path,
    final_path: Path,
    limits: TransferLimits,
    attempt: int,
    clock: Callable[[], datetime],
) -> TransferOutcome:
    """Perform one bounded attempt, promoting the temporary file on success."""
    connection_cls = (
        http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    )
    kwargs: dict[str, object] = {"timeout": limits.connect_timeout}
    if parts.scheme == "https":
        kwargs["context"] = ssl.create_default_context()

    try:
        connection = connection_cls(parts.hostname, parts.port, **kwargs)
    except OSError as exc:  # pragma: no cover - construction rarely fails
        raise TransientTransferError(f"could not create connection for {url}: {exc}") from exc

    try:
        # Phase 1: establish the connection under the connect timeout.
        try:
            connection.connect()
        except (OSError, http.client.HTTPException) as exc:
            raise TransientTransferError(f"could not connect to {url}: {exc}") from exc

        # Phase 2: everything after the connection — sending the request,
        # waiting for the status line and headers, and reading the body — is
        # bounded by the read timeout, so a slow server cannot stall us.
        if connection.sock is not None:
            connection.sock.settimeout(limits.read_timeout)
        try:
            connection.request("GET", target, headers=headers)
            response = connection.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            raise TransientTransferError(f"transport error for {url}: {exc}") from exc

        status = response.status
        if status in _REDIRECT_STATUSES:
            location = _header(response.headers, "Location") or "<no Location header>"
            raise RedirectRefusedError(
                f"refusing to follow redirect {status} to {location!r} for {url}"
            )
        if status != 200:
            if status in _TRANSIENT_STATUSES:
                raise TransientHttpStatusError(status, response.reason, url)
            raise HttpStatusError(status, response.reason, url)

        advertised = _parse_content_length(response.headers)
        if advertised is not None and advertised > limits.max_bytes:
            raise OversizedResponseError(
                f"response advertises {advertised} bytes, above the {limits.max_bytes}-byte limit"
            )

        digest = hashlib.sha256()
        written = 0
        try:
            with tmp_path.open("wb") as handle:
                while True:
                    try:
                        chunk = response.read(CHUNK_SIZE)
                    except (OSError, http.client.HTTPException) as exc:
                        raise TransientTransferError(f"read failed for {url}: {exc}") from exc
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limits.max_bytes:
                        raise OversizedResponseError(
                            f"response exceeded the {limits.max_bytes}-byte limit while streaming"
                        )
                    digest.update(chunk)
                    handle.write(chunk)
        except OSError as exc:
            raise TransientTransferError(f"could not write to {tmp_path}: {exc}") from exc

        if advertised is not None and written < advertised:
            raise TruncatedResponseError(
                f"body ended after {written} of {advertised} advertised bytes for {url}"
            )
        if written == 0:
            raise TruncatedResponseError(f"empty response body for {url}")

        measured = tmp_path.stat().st_size
        if measured != written:
            raise TransientTransferError(
                f"wrote {measured} bytes but streamed {written}; temporary file is inconsistent"
            )

        if final_path.exists():
            raise ArtifactExistsError(f"refusing to overwrite an existing artifact: {final_path}")
        os.replace(tmp_path, final_path)

        return TransferOutcome(
            url=url,
            status=status,
            content_type=_header(response.headers, "Content-Type") or "",
            byte_size=measured,
            checksum_sha256=digest.hexdigest(),
            local_path=final_path,
            attempts=attempt,
            retrieved_at=clock(),
            content_length_header=advertised,
            etag=_header(response.headers, "ETag"),
            last_modified=_header(response.headers, "Last-Modified"),
        )
    finally:
        connection.close()
