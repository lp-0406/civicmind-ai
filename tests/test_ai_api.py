"""Tests for the FastAPI interface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from civicmind.ai.api import create_app
from civicmind.ai.config import AISettings
from civicmind.ai.engine import DecisionEngine
from civicmind.config import Settings
from conftest import HAS_SUPPLIED_CSVS

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)


@pytest.fixture
def client(raw_settings: Settings) -> TestClient:
    ai_settings = AISettings(provider="deterministic")
    app = create_app(
        raw_settings,
        ai_settings=ai_settings,
        engine=DecisionEngine(raw_settings, ai_settings=ai_settings),
    )
    return TestClient(app)


def test_health_reports_readiness(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ready"] is True
    assert body["datasets_available"] == 5
    assert body["datasets_expected"] == 5
    assert body["provider"] == "deterministic"


def test_ask_endpoint_answers_a_supported_question(client: TestClient) -> None:
    response = client.post(
        "/ask",
        json={"question": "Which states had the highest reported road accidents in 2019?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is True
    assert body["intent"] == "state_accident_ranking"
    assert body["result"]["top_states"][0]["state"] == "Tamil Nadu"
    assert body["sources"]
    assert body["explanation"]


def test_ask_endpoint_reports_an_unsupported_question(client: TestClient) -> None:
    response = client.post("/ask", json={"question": "Who will win the next election?"})
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is False
    assert body["result"] is None
    assert body["explanation"]


def test_ask_endpoint_validates_the_request_body(client: TestClient) -> None:
    assert client.post("/ask", json={"question": ""}).status_code == 422
    assert client.post("/ask", json={}).status_code == 422


def test_datasets_endpoint_lists_all_five(client: TestClient) -> None:
    response = client.get("/datasets")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5
    assert {item["dataset_id"] for item in body} == {
        "RA2019_A2",
        "RA2019_A47",
        "RA2019_A49",
        "RA2019_A52",
        "BWSSB_WATER",
    }
    assert all(item["available"] is True for item in body)
    water = next(item for item in body if item["dataset_id"] == "BWSSB_WATER")
    assert water["canonical_id"] == "WTR-005"
    assert water["mapping_status"] == "plausible but unverified"


def test_dataset_detail_includes_a_quality_summary(client: TestClient) -> None:
    response = client.get("/datasets/RA2019_A47")
    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == 51
    assert body["encoding"] == "utf-8-sig"
    assert "missing_by_column" in body
    assert body["spec"]["dataset_id"] == "RA2019_A47"


def test_dataset_detail_returns_404_for_unknown_dataset(client: TestClient) -> None:
    assert client.get("/datasets/NOPE-999").status_code == 404


def test_app_factory_does_not_touch_the_filesystem_at_import() -> None:
    # Importing the module and calling nothing must not raise or read config.
    import civicmind.ai.api as api_module

    assert callable(api_module.create_app)
