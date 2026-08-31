"""Tests for LLM client error handling."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError

from mmrpg_nai.llm.client import LLMClient, _build_client, _wrap_api_error
from mmrpg_nai.models.core import LLMConfig


@pytest.fixture
def cfg() -> LLMConfig:
    return LLMConfig(api_key_env="TEST_OPENAI_KEY")


# ---------------------------------------------------------------------------
# _build_client: missing token
# ---------------------------------------------------------------------------


def test_build_client_raises_when_token_missing(cfg):
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("TEST_OPENAI_KEY", None)
        with pytest.raises(EnvironmentError, match="TEST_OPENAI_KEY"):
            _build_client(cfg)


def test_build_client_raises_when_token_empty(cfg):
    with patch.dict(os.environ, {"TEST_OPENAI_KEY": "   "}):
        with pytest.raises(EnvironmentError, match="GitHub Copilot"):
            _build_client(cfg)


# ---------------------------------------------------------------------------
# _wrap_api_error: message quality
# ---------------------------------------------------------------------------


def _mock_request():
    req = MagicMock()
    req.method = "POST"
    req.url = "https://example.com"
    return req


def test_wrap_auth_error(cfg):
    exc = AuthenticationError("bad token", response=MagicMock(status_code=401), body={})
    wrapped = _wrap_api_error(exc, cfg)
    assert isinstance(wrapped, PermissionError)
    assert "Authentication failed" in str(wrapped)
    assert "copilot" in str(wrapped).lower()


def test_wrap_rate_limit_error(cfg):
    exc = RateLimitError("rate limit", response=MagicMock(status_code=429), body={})
    wrapped = _wrap_api_error(exc, cfg)
    assert isinstance(wrapped, RuntimeError)
    assert "Rate limit" in str(wrapped)


def test_wrap_connection_error(cfg):
    inner = Exception("connection refused")
    exc = APIConnectionError(request=_mock_request())
    exc.__cause__ = inner
    wrapped = _wrap_api_error(exc, cfg)
    assert isinstance(wrapped, ConnectionError)
    assert "internet" in str(wrapped).lower() or "endpoint" in str(wrapped).lower()
    assert cfg.api_base in str(wrapped)


def test_wrap_api_status_error(cfg):
    response = MagicMock()
    response.status_code = 404
    exc = APIStatusError("not found", response=response, body={"error": {"message": "model not found"}})
    wrapped = _wrap_api_error(exc, cfg)
    assert isinstance(wrapped, RuntimeError)
    assert "404" in str(wrapped)
    assert cfg.model in str(wrapped)


def test_wrap_unknown_error_passthrough(cfg):
    exc = ValueError("unexpected")
    wrapped = _wrap_api_error(exc, cfg)
    assert wrapped is exc


# ---------------------------------------------------------------------------
# LLMClient.complete: retry on connection error
# ---------------------------------------------------------------------------


def test_complete_retries_connection_error(cfg):
    """A transient APIConnectionError should be retried and succeed on second attempt."""
    with patch.dict(os.environ, {"TEST_OPENAI_KEY": "fake-key"}):
        client = LLMClient.__new__(LLMClient)
        client.cfg = cfg

        mock_openai = MagicMock()
        call_count = 0

        def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise APIConnectionError(request=_mock_request())
            resp = MagicMock()
            resp.choices[0].message.content = "Success"
            return resp

        mock_openai.chat.completions.create.side_effect = _side_effect
        client._client = mock_openai

        with patch("mmrpg_nai.llm.client.time.sleep"):  # skip actual delay
            result = client.complete([{"role": "user", "content": "hi"}], stream=False)

    assert result == "Success"
    assert call_count == 2


def test_complete_raises_after_max_retries(cfg):
    """Persistent APIConnectionError should bubble up as ConnectionError after retries exhausted."""
    with patch.dict(os.environ, {"TEST_OPENAI_KEY": "fake-key"}):
        client = LLMClient.__new__(LLMClient)
        client.cfg = cfg
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.side_effect = APIConnectionError(request=_mock_request())
        client._client = mock_openai

        with patch("mmrpg_nai.llm.client.time.sleep"):
            with pytest.raises(ConnectionError, match="endpoint"):
                client.complete([{"role": "user", "content": "hi"}], stream=False)


def test_complete_auth_error_not_retried(cfg):
    """AuthenticationError should surface immediately without retrying."""
    with patch.dict(os.environ, {"TEST_OPENAI_KEY": "fake-key"}):
        client = LLMClient.__new__(LLMClient)
        client.cfg = cfg
        mock_openai = MagicMock()
        mock_openai.chat.completions.create.side_effect = AuthenticationError(
            "bad", response=MagicMock(status_code=401), body={}
        )
        client._client = mock_openai

        with pytest.raises(PermissionError, match="Authentication"):
            client.complete([{"role": "user", "content": "hi"}], stream=False)

        assert mock_openai.chat.completions.create.call_count == 1
