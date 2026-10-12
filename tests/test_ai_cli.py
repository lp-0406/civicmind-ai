"""CLI smoke tests for the AI commands (``ask`` and ``ai``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from civicmind.cli import build_parser, main
from conftest import HAS_SUPPLIED_CSVS

pytestmark = pytest.mark.skipif(
    not HAS_SUPPLIED_CSVS, reason="supplied CSVs not present under data/raw"
)


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point config at the repository root so the real data/raw tree is used."""
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("CIVICMIND_PROJECT_ROOT", str(repo_root))
    monkeypatch.setenv("CIVICMIND_DATA_DIR", str(repo_root / "data"))
    monkeypatch.setenv("CIVICMIND_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CIVICMIND_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CIVICMIND_ENV", "testing")
    monkeypatch.setenv("CIVICMIND_AI_PROVIDER", "deterministic")
    monkeypatch.delenv("CIVICMIND_AI_API_KEY", raising=False)


def test_ask_command_answers_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["ask", "Which states had the highest reported road accidents in 2019?"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "57,228" in output
    assert "deterministic" in output.lower()


def test_ask_command_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["ask", "--json", "What published share did Telangana have in 2019?"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["supported"] is True
    assert payload["intent"] == "state_share"
    assert payload["result"]["accidents"] == 21570


def test_ask_command_returns_two_for_an_unsupported_question(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["ask", "Who will win the next election?"])
    output = capsys.readouterr().out
    assert exit_code == 2
    assert "not supported" in output.lower()


def test_ai_datasets_command_lists_five(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["ai", "datasets"])
    output = capsys.readouterr().out
    assert exit_code == 0
    for dataset_id in ("RA2019_A2", "RA2019_A47", "RA2019_A49", "RA2019_A52", "BWSSB_WATER"):
        assert dataset_id in output


def test_parser_exposes_ask_and_ai_commands() -> None:
    parser = build_parser()
    args = parser.parse_args(["ask", "hello"])
    assert args.question == "hello"
    ai_args = parser.parse_args(["ai", "datasets", "--json"])
    assert ai_args.as_json is True
