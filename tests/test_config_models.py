"""Tests for `mmrpg-nai config models` command."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from mmrpg_nai.cli.main import app
from mmrpg_nai.storage.store import Store

runner = CliRunner()


def _fake_model(id_: str, owned_by: str = "openai") -> SimpleNamespace:
    m = SimpleNamespace()
    m.id = id_
    m.owned_by = owned_by
    return m


def _make_models_response(*ids):
    resp = MagicMock()
    resp.data = [_fake_model(id_) for id_ in ids]
    return resp


@pytest.fixture
def data_dir(tmp_path: Path) -> str:
    store = Store(tmp_path)
    store.save_config(store.load_config())
    return str(tmp_path)


def test_config_models_lists_all(data_dir):
    with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
        with patch("openai.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.return_value = _make_models_response(
                "gpt-4o", "gpt-4o-mini", "gpt-5.4"
            )
            result = runner.invoke(app, ["config", "models", "--data-dir", data_dir])

    assert result.exit_code == 0
    assert "gpt-4o" in result.output
    assert "gpt-4o-mini" in result.output
    assert "gpt-5.4" in result.output


def test_config_models_highlights_active(data_dir):
    """The currently configured model should be marked active (✓)."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
        with patch("openai.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.return_value = _make_models_response("gpt-5.4", "gpt-4o")
            result = runner.invoke(app, ["config", "models", "--data-dir", data_dir])

    assert result.exit_code == 0
    assert "✓" in result.output


def test_config_models_filter(data_dir):
    """--filter narrows results to matching model IDs."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
        with patch("openai.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.return_value = _make_models_response(
                "gpt-4o", "gpt-4o-mini", "mistral-large"
            )
            result = runner.invoke(
                app, ["config", "models", "--data-dir", data_dir, "--filter", "gpt"]
            )

    assert result.exit_code == 0
    assert "gpt-4o" in result.output
    assert "mistral-large" not in result.output


def test_config_models_no_token(data_dir):
    """Missing token prints an actionable error and exits non-zero."""
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(app, ["config", "models", "--data-dir", data_dir])

    assert result.exit_code != 0
    assert "Token not set" in result.output or "GITHUB_TOKEN" in result.output


def test_config_models_api_failure(data_dir):
    """A generic exception is reported in a panel."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
        with patch("openai.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.side_effect = Exception("connection refused")
            result = runner.invoke(app, ["config", "models", "--data-dir", data_dir])

    assert result.exit_code != 0
    # Should show a panel with error info — old bare message replaced by panel title
    assert "Failed to fetch models" in result.output or "connection refused" in result.output


def test_config_models_connection_error_panel(data_dir):
    """An APIConnectionError shows a 'Connection error' panel with actionable guidance."""
    from openai import APIConnectionError
    from unittest.mock import MagicMock as _MagicMock

    def _mock_request():
        req = _MagicMock()
        req.method = "POST"
        req.url = "https://example.com"
        return req

    with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
        with patch("openai.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.side_effect = APIConnectionError(request=_mock_request())
            result = runner.invoke(app, ["config", "models", "--data-dir", data_dir])

    assert result.exit_code != 0
    assert "Connection error" in result.output
    # Should contain actionable guidance (internet / endpoint / proxy)
    assert any(word in result.output for word in ["internet", "endpoint", "proxy"])


def test_config_models_auth_error_panel(data_dir):
    """An AuthenticationError shows a permission-error panel."""
    from openai import AuthenticationError

    with patch.dict(os.environ, {"GITHUB_TOKEN": "bad-token"}):
        with patch("openai.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.side_effect = AuthenticationError(
                "bad token", response=MagicMock(status_code=401), body={}
            )
            result = runner.invoke(app, ["config", "models", "--data-dir", data_dir])

    assert result.exit_code != 0
    assert "Authentication" in result.output


def test_config_models_uses_detected_openai_provider(data_dir):
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
        with patch("openai.OpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.models.list.return_value = _make_models_response("gpt-4o", "gpt-4o-mini")
            result = runner.invoke(app, ["config", "models", "--data-dir", data_dir])

    assert result.exit_code == 0
    assert "openai" in result.output.lower()
    assert "gpt-4o" in result.output
