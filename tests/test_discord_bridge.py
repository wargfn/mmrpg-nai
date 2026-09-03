"""Tests for Discord MCP bridge helpers."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from mmrpg_nai.discord.bridge import MCPBridgeError, MCPSessionInactiveError, MCPWebClient, split_discord_message


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_split_discord_message_chunks_long_text():
    text = "A" * 4000
    chunks = split_discord_message(text, limit=1800)
    assert len(chunks) >= 3
    assert all(len(c) <= 1800 for c in chunks)
    assert "".join(chunks) == text


def test_mcp_client_chat_success():
    client = MCPWebClient("http://localhost:8000")
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse({"response": "ok", "mode": "narrate"})):
        response, mode = client.chat("sid", "hello")
    assert response == "ok"
    assert mode == "narrate"


def test_mcp_client_chat_inactive_session_error():
    client = MCPWebClient("http://localhost:8000")
    err = HTTPError(
        url="http://localhost:8000/web/session/sid/chat",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=io.BytesIO(json.dumps({"detail": "Session is not active; start or resume it first"}).encode("utf-8")),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(MCPSessionInactiveError):
            client.chat("sid", "hello")


def test_mcp_client_chat_other_http_error():
    client = MCPWebClient("http://localhost:8000")
    err = HTTPError(
        url="http://localhost:8000/web/session/sid/chat",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(json.dumps({"detail": "bad input"}).encode("utf-8")),
    )
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(MCPBridgeError, match="HTTP 400"):
            client.chat("sid", "hello")
