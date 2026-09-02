"""Tests for `mmrpg-nai config provider` commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from mmrpg_nai.cli.main import app
from mmrpg_nai.storage.store import Store

runner = CliRunner()


@pytest.fixture
def data_dir(tmp_path: Path) -> str:
    store = Store(tmp_path)
    store.save_config(store.load_config())
    return str(tmp_path)


def test_provider_list_shows_known_providers(data_dir):
    result = runner.invoke(app, ["config", "provider", "list", "--data-dir", data_dir])
    assert result.exit_code == 0
    assert "google_ai_studio" in result.output
    assert "openai" in result.output
    assert "github_copilot" in result.output
    assert "ollama" in result.output


def test_provider_show_default_selected(data_dir):
    result = runner.invoke(app, ["config", "provider", "show", "--data-dir", data_dir])
    assert result.exit_code == 0
    assert '"provider": "github_copilot"' in result.output


def test_provider_show_specific(data_dir):
    result = runner.invoke(app, ["config", "provider", "show", "google_ai_studio", "--data-dir", data_dir])
    assert result.exit_code == 0
    assert '"provider": "google_ai_studio"' in result.output
    assert '"api_key_env": "GOOGLE_API_KEY"' in result.output


def test_provider_select_updates_config(data_dir):
    result = runner.invoke(app, ["config", "provider", "select", "openai", "--data-dir", data_dir])
    assert result.exit_code == 0
    assert "Selected provider: openai" in result.output

    cfg = Store(data_dir).load_config()
    assert cfg.llm.provider == "openai"
    assert cfg.llm.api_key_env == "OPENAI_API_KEY"


def test_provider_select_unknown(data_dir):
    result = runner.invoke(app, ["config", "provider", "select", "unknown", "--data-dir", data_dir])
    assert result.exit_code != 0
    assert "Unknown provider" in result.output
