"""Shared, offline test fixtures.

Everything here is local and deterministic: the HTTP server binds to an ephemeral
loopback port, and every path a test writes to lives under ``tmp_path``. No test
in this suite reaches the network or depends on a live dataset endpoint.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from civicmind.config import Settings

#: A small CSV shaped like the TRF-001 pilot artifact, including a quoted field
#: with an internal comma, a duplicate row and a sparse column.
SAMPLE_CSV = (
    b"City,Total Registered Motor Vehicles (as of 2016),Year,Accident type,Pedestrian,"
    b'Bicycles,Two-wheelers,"Other modes of road transport (auto, bus, lorry)",Total\n'
    b"Ahmedabad,3200000,2016,Fatal,120,45,300,80,545\n"
    b"Bhopal,1100000,2016,Serious,,30,210,40,280\n"
    b"Indore,1500000,2017,Fatal,90,38,260,55,443\n"
    b"Indore,1500000,2017,Fatal,90,38,260,55,443\n"
    b"Surat,2400000,2018,Minor,60,20,150,25,255\n"
)


@dataclass
class _ScriptedResponse:
    """One scripted HTTP response."""

    status: int = 200
    body: bytes = b""
    content_type: str = "text/csv"
    #: Declared ``Content-Length``; defaults to the real body length. Set larger
    #: than the body to simulate a truncated transfer.
    declared_length: int | None = None
    delay: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)
    #: Send the body with ``Transfer-Encoding: chunked`` and no
    #: ``Content-Length``, so a client cannot learn the size up front.
    chunked: bool = False


class LocalHTTPServer(ThreadingHTTPServer):
    """A loopback HTTP server whose responses are scripted per path."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes: dict[str, list[_ScriptedResponse]] = {}
        self.hits: dict[str, int] = {}

    # -- scripting ---------------------------------------------------------
    def serve(
        self,
        path: str,
        *,
        body: bytes = SAMPLE_CSV,
        status: int = 200,
        content_type: str = "text/csv",
        declared_length: int | None = None,
        delay: float = 0.0,
        headers: dict[str, str] | None = None,
        chunked: bool = False,
    ) -> str:
        """Script a single response for ``path`` and return the full URL."""
        self.routes[path] = [
            _ScriptedResponse(
                status=status,
                body=body,
                content_type=content_type,
                declared_length=declared_length,
                delay=delay,
                headers=headers or {},
                chunked=chunked,
            )
        ]
        return self.url(path)

    def serve_sequence(self, path: str, responses: list[_ScriptedResponse]) -> str:
        """Script a sequence of responses; the last one repeats."""
        self.routes[path] = list(responses)
        return self.url(path)

    def serve_status_script(self, path: str, script: list[tuple[int, bytes]]) -> str:
        """Script ``(status, body)`` pairs for successive requests to ``path``."""
        self.routes[path] = [
            _ScriptedResponse(status=status, body=body) for status, body in script
        ]
        return self.url(path)

    def serve_redirect(self, path: str, location: str) -> str:
        """Script a redirect response for ``path``."""
        return self.serve(
            path,
            body=b"",
            status=302,
            content_type="text/html",
            headers={"Location": location},
        )

    def hit_count(self, path: str) -> int:
        """Return how many requests ``path`` has received."""
        return self.hits.get(path, 0)

    def url(self, path: str) -> str:
        """Return the absolute URL for ``path`` on this server."""
        host, port = self.server_address[:2]
        return f"http://{host}:{port}{path}"

    # -- lifecycle ---------------------------------------------------------
    @property
    def base_url(self) -> str:
        """Return the server's origin."""
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def next_response(self, path: str) -> _ScriptedResponse | None:
        """Return the response for the current (already recorded) request.

        ``record_hit`` runs before this, so the hit count is the 1-based ordinal
        of the request being served; the last scripted response repeats.
        """
        script = self.routes.get(path)
        if not script:
            return None
        index = min(max(self.hit_count(path) - 1, 0), len(script) - 1)
        return script[index]

    def record_hit(self, path: str) -> int:
        """Record a request and return its 1-based ordinal."""
        self.hits[path] = self.hits.get(path, 0) + 1
        return self.hits[path]


#: Chunk size used when scripting a chunked (size-unannounced) response.
_CHUNK_BYTES = 512


class _Handler(BaseHTTPRequestHandler):
    """Request handler delegating to the server's scripted routes."""

    protocol_version = "HTTP/1.1"
    server: LocalHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self.server.record_hit(self.path)
        response = self.server.next_response(self.path)
        if response is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            self.close_connection = True
            return

        if response.delay:
            time.sleep(response.delay)
        body = response.body
        declared = len(body) if response.declared_length is None else response.declared_length
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        if response.chunked:
            self.send_header("Transfer-Encoding", "chunked")
        else:
            self.send_header("Content-Length", str(declared))
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        try:
            if response.chunked:
                # Frame the body in small chunks so the client sees a stream
                # it cannot size-check up front.
                for start in range(0, len(body), _CHUNK_BYTES):
                    piece = body[start : start + _CHUNK_BYTES]
                    self.wfile.write(f"{len(piece):X}\r\n".encode())
                    self.wfile.write(piece)
                    self.wfile.write(b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            else:
                self.wfile.write(body)
            self.wfile.flush()
        except OSError:  # pragma: no cover - client closed early (timeout tests)
            pass
        self.close_connection = True

    def do_HEAD(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        self.do_GET()

    def log_message(self, format: str, *args: object) -> None:
        """Silence request logging in tests."""
        return


@pytest.fixture
def http_server() -> Iterator[LocalHTTPServer]:
    """Run a local HTTP server for the duration of one test."""
    server = LocalHTTPServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def pilot_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings whose data, artifacts and logs live under ``tmp_path``."""
    monkeypatch.setenv("CIVICMIND_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("CIVICMIND_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CIVICMIND_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CIVICMIND_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CIVICMIND_ENV", "testing")
    return Settings.from_env()


# ---------------------------------------------------------------------------
# AI-layer fixtures: the real, supplied CSVs under the repository's data/raw.
# ---------------------------------------------------------------------------

#: Repository root, resolved from this file so the path is cwd-independent.
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

#: The five supplied datasets the AI layer expects.
SUPPLIED_CSVS: tuple[str, ...] = (
    "RA2019_A2.csv",
    "RA2019_A47.csv",
    "RA2019_A49.csv",
    "RA2019_A52.csv",
    "BWSSB_Water_Consumption_August_2025.csv",
)

#: True when every supplied CSV is present; AI integration tests skip otherwise.
HAS_SUPPLIED_CSVS = all((RAW_DIR / name).is_file() for name in SUPPLIED_CSVS)


@pytest.fixture
def raw_settings() -> Settings:
    """Settings pointing at the repository's real data/raw tree.

    Constructed with an explicit empty environment mapping so a developer's
    local ``.env`` cannot redirect the path or inject credentials into tests.
    """
    return Settings.from_env({})
