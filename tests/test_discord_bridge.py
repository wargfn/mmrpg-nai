"""Tests for Discord MCP bridge helpers."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest

from mmrpg_nai.discord.bridge import (
    MCPBridgeError,
    MCPSessionInactiveError,
    MCPWebClient,
    _format_session_log_entry,
    process_bridge_command,
    split_discord_message,
)


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


def test_mcp_client_chat_timeout_error():
    client = MCPWebClient("http://localhost:8000", timeout_seconds=42)
    with patch("urllib.request.urlopen", side_effect=URLError("timed out")):
        with pytest.raises(MCPBridgeError, match="timed out after 42s"):
            client.chat("sid", "hello")


def test_mcp_client_ensure_active_session_already_active():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/sid"):
            return _FakeHTTPResponse({"is_active": True})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        sid, resumed = client.ensure_active_session("sid", resume_if_inactive=True)

    assert sid == "sid"
    assert resumed is False


def test_mcp_client_ensure_active_session_resumes_when_inactive():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/sid") and req.method == "GET":
            return _FakeHTTPResponse({"is_active": False})
        if req.full_url.endswith("/web/session/start"):
            return _FakeHTTPResponse({"session": {"id": "sid-2"}})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        sid, resumed = client.ensure_active_session("sid", resume_if_inactive=True)

    assert sid == "sid-2"
    assert resumed is True


def test_mcp_client_create_campaign_and_start_session():
    client = MCPWebClient("http://localhost:8000")
    calls = []

    def _urlopen(req, timeout=15):
        calls.append((req.full_url, req.method, json.loads(req.data.decode("utf-8")) if req.data else None))
        if req.full_url.endswith("/campaigns"):
            return _FakeHTTPResponse({"id": "camp-1", "name": "New Campaign"})
        if req.full_url.endswith("/web/session/start"):
            return _FakeHTTPResponse({"session": {"id": "sess-1", "title": "Session 1"}, "campaign": {"id": "camp-1"}})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        campaign = client.create_campaign("New Campaign")
        started = client.start_session("camp-1", title="Session 1")

    assert campaign["id"] == "camp-1"
    assert started["session"]["id"] == "sess-1"
    assert calls[0][0].endswith("/campaigns")
    assert calls[1][0].endswith("/web/session/start")


def test_process_bridge_command_campaign_then_start_session():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/campaigns") and req.method == "POST":
            return _FakeHTTPResponse({"id": "camp-1", "name": "Alpha"})
        if req.full_url.endswith("/web/session/start"):
            return _FakeHTTPResponse(
                {"session": {"id": "sess-1", "title": "Session 1"}, "campaign": {"id": "camp-1", "name": "Alpha"}}
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, last_campaign = process_bridge_command("/campaign new Alpha", client, None, None)
        assert handled is True
        assert "Created campaign" in (reply or "")
        assert active is None
        assert last_campaign == "camp-1"

        handled2, reply2, active2, last_campaign2 = process_bridge_command("/session start", client, active, last_campaign)
        assert handled2 is True
        assert "Started session" in (reply2 or "")
        assert active2 == "sess-1"
        assert last_campaign2 == "camp-1"


def test_process_bridge_command_malformed_quotes():
    client = MCPWebClient("http://localhost:8000")
    handled, reply, active, campaign = process_bridge_command('/campaign new "Alpha', client, None, None)
    assert handled is True
    assert "Malformed command syntax" in (reply or "")
    assert active is None
    assert campaign is None


def test_process_bridge_command_session_start_exact_id_without_campaign_lookup():
    client = MCPWebClient("http://localhost:8000")
    calls = []

    def _urlopen(req, timeout=15):
        calls.append(req.full_url)
        if req.full_url.endswith("/web/session/start"):
            return _FakeHTTPResponse(
                {"session": {"id": "sess-1", "title": "Session 1"}, "campaign": {"id": "camp-1", "name": "Alpha"}}
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session start camp-1", client, None, None)

    assert handled is True
    assert "Started session" in (reply or "")
    assert active == "sess-1"
    assert campaign == "camp-1"
    assert not any(url.endswith("/campaigns") for url in calls)


def test_process_bridge_command_session_start_updates_canonical_campaign_id():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/start"):
            return _FakeHTTPResponse(
                {"session": {"id": "sess-1", "title": "Session 1"}, "campaign": {"id": "camp-1-full", "name": "Alpha"}}
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session start camp-1", client, None, None)

    assert handled is True
    assert "Started session" in (reply or "")
    assert active == "sess-1"
    assert campaign == "camp-1-full"


def test_process_bridge_command_session_use_validates_session_state():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/sess-1"):
            return _FakeHTTPResponse({"is_active": True, "campaign": {"id": "camp-1"}})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session use sess-1", client, None, None)

    assert handled is True
    assert "Active session set to sess-1 (active)" in (reply or "")
    assert active == "sess-1"
    assert campaign == "camp-1"


def test_process_bridge_command_campaign_list():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/campaigns"):
            return _FakeHTTPResponse(
                [
                    {"id": "camp-11111111", "name": "Alpha"},
                    {"id": "camp-22222222", "name": "Beta"},
                ]
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/campaign list", client, None, None)

    assert handled is True
    assert "Campaigns:" in (reply or "")
    assert "Alpha" in (reply or "")
    assert "Beta" in (reply or "")
    assert active is None
    assert campaign is None


def test_process_bridge_command_prefixed_cli_style_campaign_list():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/campaigns"):
            return _FakeHTTPResponse([{"id": "camp-11111111", "name": "Alpha"}])
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, _, _ = process_bridge_command("/mmrpg-nai campaign list", client, None, None)

    assert handled is True
    assert "Campaigns:" in (reply or "")
    assert "Alpha" in (reply or "")


def test_process_bridge_command_session_start_title_uses_last_campaign_when_ref_not_found():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/start"):
            payload = json.loads(req.data.decode("utf-8"))
            if payload["campaign_id"] == "My":
                raise HTTPError(
                    url=req.full_url,
                    code=404,
                    msg="Not Found",
                    hdrs=None,
                    fp=io.BytesIO(json.dumps({"detail": "Campaign not found"}).encode("utf-8")),
                )
            if payload["campaign_id"] == "camp-1":
                return _FakeHTTPResponse(
                    {"session": {"id": "sess-1", "title": payload.get("title") or "Session 1"}, "campaign": {"id": "camp-1"}}
                )
        if req.full_url.endswith("/campaigns"):
            return _FakeHTTPResponse([])
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session start My Session Title", client, None, "camp-1")

    assert handled is True
    assert "Started session" in (reply or "")
    assert active == "sess-1"
    assert campaign == "camp-1"


def test_format_session_log_entry():
    assert _format_session_log_entry({"role": "player", "content": "hello"}) == "**Player:** hello"
    assert _format_session_log_entry({"role": "narrator", "content": "world"}) == "**Narrator:** world"
    assert _format_session_log_entry({"role": "system", "content": "ok"}) == "**System:** ok"
    assert _format_session_log_entry({"role": "custom", "content": "x"}) == "**Custom:** x"
    assert _format_session_log_entry({"role": "player", "content": "   "}) is None
