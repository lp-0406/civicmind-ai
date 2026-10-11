"""Tests for the bounded streaming downloader.

Every test runs against the loopback HTTP fixture in ``conftest.py``; nothing
here touches a real dataset endpoint.
"""

from __future__ import annotations

import hashlib
import http.client
from pathlib import Path

import pytest

from civicmind.ingestion.transfer import (
    ArtifactExistsError,
    HttpStatusError,
    InvalidUrlError,
    OversizedResponseError,
    RedirectRefusedError,
    TransferLimits,
    TransferOutcome,
    TransientHttpStatusError,
    TransientTransferError,
    TruncatedResponseError,
    download_to_file,
    sha256_file,
)
from conftest import SAMPLE_CSV, LocalHTTPServer


def _no_sleep(_seconds: float) -> None:
    """Replace real backoff so retry tests stay fast and deterministic."""
    return


def _download(
    server: LocalHTTPServer,
    url: str,
    destination: Path,
    *,
    filename: str = "artifact.csv",
    limits: TransferLimits | None = None,
) -> TransferOutcome:
    """Download ``url`` with test-friendly defaults (no real backoff)."""
    return download_to_file(
        url,
        destination,
        filename=filename,
        limits=limits or TransferLimits(),
        sleep=_no_sleep,
    )


def test_successful_download_records_measured_facts(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/data.csv")

    outcome = _download(http_server, url, tmp_path)

    assert outcome.status == 200
    assert outcome.content_type == "text/csv"
    assert outcome.byte_size == len(SAMPLE_CSV)
    assert outcome.checksum_sha256 == hashlib.sha256(SAMPLE_CSV).hexdigest()
    assert outcome.checksum_sha256 == sha256_file(tmp_path / "artifact.csv")
    assert outcome.local_path == tmp_path / "artifact.csv"
    assert outcome.attempts == 1
    assert (tmp_path / "artifact.csv").read_bytes() == SAMPLE_CSV


def test_no_temporary_file_survives_a_success(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/data.csv")

    _download(http_server, url, tmp_path)

    assert [p.name for p in tmp_path.iterdir()] == ["artifact.csv"]


def test_permanent_http_error_is_not_retried(http_server: LocalHTTPServer, tmp_path: Path) -> None:
    url = http_server.serve("/missing.csv", status=404, body=b"")

    with pytest.raises(HttpStatusError) as excinfo:
        _download(http_server, url, tmp_path)

    assert excinfo.value.status == 404
    assert http_server.hit_count("/missing.csv") == 1
    assert list(tmp_path.iterdir()) == []


def test_transient_http_error_is_retried_then_succeeds(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve_status_script("/flaky.csv", [(503, b""), (200, SAMPLE_CSV)])

    outcome = _download(http_server, url, tmp_path)

    assert outcome.attempts == 2
    assert http_server.hit_count("/flaky.csv") == 2
    assert (tmp_path / "artifact.csv").read_bytes() == SAMPLE_CSV


def test_persistent_transient_error_exhausts_the_attempt_budget(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/down.csv", status=500, body=b"")

    with pytest.raises(TransientHttpStatusError):
        _download(http_server, url, tmp_path, limits=TransferLimits(attempts=2))

    assert http_server.hit_count("/down.csv") == 2
    assert list(tmp_path.iterdir()) == []


def test_read_timeout_is_a_transient_failure(http_server: LocalHTTPServer, tmp_path: Path) -> None:
    url = http_server.serve("/slow.csv", delay=1.0)

    with pytest.raises(TransientTransferError):
        _download(
            http_server,
            url,
            tmp_path,
            limits=TransferLimits(read_timeout=0.2, attempts=1),
        )

    assert list(tmp_path.iterdir()) == []


def test_redirect_is_refused_not_followed(http_server: LocalHTTPServer, tmp_path: Path) -> None:
    other = http_server.url("/other.csv")
    url = http_server.serve_redirect("/moved.csv", other)

    with pytest.raises(RedirectRefusedError):
        _download(http_server, url, tmp_path)

    assert http_server.hit_count("/moved.csv") == 1
    assert http_server.hit_count("/other.csv") == 0
    assert list(tmp_path.iterdir()) == []


def test_advertised_size_above_the_limit_fails_before_streaming(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/big.csv", declared_length=10_000_000)

    with pytest.raises(OversizedResponseError):
        _download(http_server, url, tmp_path, limits=TransferLimits(max_bytes=1024))

    assert http_server.hit_count("/big.csv") == 1
    assert list(tmp_path.iterdir()) == []


def test_streamed_size_above_the_limit_is_caught_mid_stream(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/undeclared.csv")

    with pytest.raises(OversizedResponseError):
        _download(http_server, url, tmp_path, limits=TransferLimits(max_bytes=64))

    assert list(tmp_path.iterdir()) == []


def test_size_limit_is_enforced_while_streaming_a_chunked_body(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    """A body without a Content-Length can still be refused mid-stream."""
    url = http_server.serve("/stream.csv", body=b"A" * 4096, chunked=True)

    with pytest.raises(OversizedResponseError) as excinfo:
        _download(http_server, url, tmp_path, limits=TransferLimits(max_bytes=1024))

    assert "while streaming" in str(excinfo.value)
    assert list(tmp_path.iterdir()) == []


def test_connect_and_read_timeouts_are_distinct(
    http_server: LocalHTTPServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The connect bound governs the socket connect; the read bound, every read."""
    recorded: dict[str, float | None] = {}

    class _RecordingConnection(http.client.HTTPConnection):
        def connect(self) -> None:
            super().connect()
            recorded["connect"] = self.timeout

        def send(self, data: object) -> None:
            recorded["send"] = None if self.sock is None else self.sock.gettimeout()
            super().send(data)  # type: ignore[arg-type]

    monkeypatch.setattr(http.client, "HTTPConnection", _RecordingConnection)

    url = http_server.serve("/data.csv")
    limits = TransferLimits(connect_timeout=3.0, read_timeout=7.0, attempts=1)
    download_to_file(url, tmp_path, filename="a.csv", limits=limits, sleep=_no_sleep)

    assert recorded["connect"] == 3.0
    assert recorded["send"] == 7.0
    assert recorded["connect"] != recorded["send"]


def test_truncated_body_is_detected_and_retried(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    url = http_server.serve("/short.csv", body=SAMPLE_CSV[:20], declared_length=len(SAMPLE_CSV))

    with pytest.raises(TruncatedResponseError):
        _download(http_server, url, tmp_path, limits=TransferLimits(attempts=2))

    assert http_server.hit_count("/short.csv") == 2
    assert list(tmp_path.iterdir()) == []


def test_empty_body_is_rejected(http_server: LocalHTTPServer, tmp_path: Path) -> None:
    url = http_server.serve("/empty.csv", body=b"")

    with pytest.raises(TruncatedResponseError):
        _download(http_server, url, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_existing_artifact_is_never_overwritten(
    http_server: LocalHTTPServer, tmp_path: Path
) -> None:
    existing = tmp_path / "artifact.csv"
    existing.write_bytes(b"previously acquired bytes")
    url = http_server.serve("/data.csv")

    with pytest.raises(ArtifactExistsError):
        _download(http_server, url, tmp_path)

    assert existing.read_bytes() == b"previously acquired bytes"
    assert http_server.hit_count("/data.csv") == 0


def test_unsupported_url_scheme_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidUrlError):
        download_to_file("ftp://example.invalid/data.csv", tmp_path, filename="a.csv")


def test_connection_failure_is_retried_then_reported(tmp_path: Path) -> None:
    limits = TransferLimits(attempts=2, connect_timeout=0.5)

    with pytest.raises(TransientTransferError):
        download_to_file(
            "http://127.0.0.1:9/never.csv",
            tmp_path,
            filename="a.csv",
            limits=limits,
            sleep=_no_sleep,
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_bytes": 0},
        {"attempts": 0},
        {"connect_timeout": 0},
        {"read_timeout": 0},
        {"backoff_seconds": -1},
    ],
)
def test_limits_reject_invalid_values(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        TransferLimits(**kwargs)


def test_limits_are_reported_for_planning() -> None:
    limits = TransferLimits(max_bytes=2048, attempts=4)

    described = limits.as_dict()

    assert described["max_bytes"] == 2048
    assert described["attempts"] == 4
    assert described["read_timeout_seconds"] > 0
