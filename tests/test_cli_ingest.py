"""Tests for the ``civicmind ingest`` pipeline commands.

The CLI is the interface a reviewer will use, so these tests drive it through
``main()`` exactly as a user would. Everything is offline: the handler's
resource URL is pointed at the loopback HTTP fixture for the end-to-end test,
and all paths live under ``tmp_path``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from civicmind.cli import main
from civicmind.config import Settings
from civicmind.ingestion import IngestionRegistry
from civicmind.ingestion.base import DatasetIngestor, SourceDescriptor
from civicmind.ingestion.exceptions import AcquisitionError


class _ExtraHandler(DatasetIngestor):
    """A handler an operator registered themselves, whose slug is not a canonical id."""

    def describe(self) -> SourceDescriptor:
        return SourceDescriptor(
            source_id="demo-extra",
            title="Extra handler",
            publisher="CivicMind test",
            license="CC0-1.0",
        )

    def acquire(self, destination: Path):
        raise AcquisitionError("listing must not acquire")

    def validate(self, result: object):
        raise AssertionError("listing must not validate")


def test_ingest_list_includes_handlers_registered_by_application_code(
    pilot_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Listing must keep serving the existing ``DEFAULT_REGISTRY`` contract."""
    registry = IngestionRegistry()
    registry.register(_ExtraHandler())
    monkeypatch.setattr("civicmind.cli.DEFAULT_REGISTRY", registry)

    exit_code = main(["ingest", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    shipped = {item["source_id"] for item in payload}
    assert "demo-extra" in shipped
    assert "trf-001" in shipped
    assert "trf-004" in shipped
    assert "wtr-005" in shipped
    extra = next(item for item in payload if item["source_id"] == "demo-extra")
    # A slug that is not a canonical id is listed, and simply has no dataset id.
    assert extra["dataset_id"] is None
    assert extra["title"] == "Extra handler"
    # The listing must contain exactly the application handler plus the three
    # shipped handlers, in the defined listing order.
    assert [item["source_id"] for item in payload] == [
        "demo-extra",
        "trf-001",
        "trf-004",
        "wtr-005",
    ]
