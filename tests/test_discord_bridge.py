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
    clear_discord_channel_history,
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
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse({"sessions": [{"id": "sid"}]})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        sid, resumed = client.ensure_active_session("sid", resume_if_inactive=True)

    assert sid == "sid"
    assert resumed is False


def test_mcp_client_ensure_active_session_uses_canonical_id_when_active():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/sid"):
            return _FakeHTTPResponse({"is_active": True, "session": {"id": "sid-full"}})
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse({"sessions": [{"id": "sid-full"}]})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        sid, resumed = client.ensure_active_session("sid", resume_if_inactive=True)

    assert sid == "sid-full"
    assert resumed is False


def test_mcp_client_ensure_active_session_resumes_when_inactive():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/sid") and req.method == "GET":
            return _FakeHTTPResponse({"is_active": False})
        if req.full_url.endswith("/web/active-sessions"):
            if not seen_resume["done"]:
                return _FakeHTTPResponse({"sessions": []})
            return _FakeHTTPResponse({"sessions": [{"id": "sid-2"}]})
        if req.full_url.endswith("/web/session/start"):
            seen_resume["done"] = True
            return _FakeHTTPResponse({"session": {"id": "sid-2"}})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    seen_resume = {"done": False}
    with patch("urllib.request.urlopen", side_effect=_urlopen):
        sid, resumed = client.ensure_active_session("sid", resume_if_inactive=True)

    assert sid == "sid-2"
    assert resumed is True


def test_mcp_client_ensure_active_session_raises_when_not_listed_after_resume():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/sid") and req.method == "GET":
            return _FakeHTTPResponse({"is_active": True})
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse({"sessions": []})
        if req.full_url.endswith("/web/session/start"):
            return _FakeHTTPResponse({"session": {"id": "sid-2"}})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        with pytest.raises(MCPBridgeError, match="reports active but is not listed"):
            client.ensure_active_session("sid", resume_if_inactive=True)


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
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse({"sessions": [{"id": "sess-1"}]})
        if req.full_url.endswith("/web/session/sess-1"):
            return _FakeHTTPResponse(
                {
                    "is_active": True,
                    "session": {"id": "session-canonical-1"},
                    "campaign": {"id": "camp-1"},
                }
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session use sess-1", client, None, None)

    assert handled is True
    assert "Active session set to session-canonical-1 (active)" in (reply or "")
    assert active == "session-canonical-1"
    assert campaign == "camp-1"


def test_process_bridge_command_session_use_resolves_prefix():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse(
                {"sessions": [{"id": "session-canonical-1", "campaign_id": "camp-1", "title": "Alpha"}]}
            )
        if req.full_url.endswith("/web/session/session-canonical-1"):
            return _FakeHTTPResponse(
                {
                    "is_active": True,
                    "session": {"id": "session-canonical-1"},
                    "campaign": {"id": "camp-1"},
                }
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session use session-can", client, None, None)

    assert handled is True
    assert "Active session set to session-canonical-1 (active)" in (reply or "")
    assert active == "session-canonical-1"
    assert campaign == "camp-1"


def test_process_bridge_command_session_use_rejects_ambiguous_prefix():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse({"sessions": [{"id": "session-aaa"}, {"id": "session-aab"}]})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session use session-aa", client, None, None)

    assert handled is True
    assert "matches multiple active sessions" in (reply or "")
    assert active is None
    assert campaign is None


def test_process_bridge_command_session_list():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse(
                {
                    "sessions": [
                        {"id": "session-aaa", "campaign_id": "camp-1", "title": "Alpha"},
                        {"id": "session-bbb", "campaign_id": "camp-2", "title": "Beta"},
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session list", client, "session-bbb", "camp-2")

    assert handled is True
    assert "Active sessions:" in (reply or "")
    assert "session-aaa" in (reply or "")
    assert "session-bbb" in (reply or "")
    assert "(current)" in (reply or "")
    assert active == "session-bbb"
    assert campaign == "camp-2"


def test_process_bridge_command_session_end_detaches_active():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/session-bbb"):
            return _FakeHTTPResponse({"session": {"id": "session-bbb"}})
        if req.full_url.endswith("/web/session/session-bbb/end"):
            return _FakeHTTPResponse({"ended": True})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session end", client, "session-bbb", "camp-2")

    assert handled is True
    assert "Ended and detached from session session-bbb." in (reply or "")
    assert active is None
    assert campaign == "camp-2"


def test_process_bridge_command_session_end_without_active():
    client = MCPWebClient("http://localhost:8000")
    handled, reply, active, campaign = process_bridge_command("/session end", client, None, "camp-2")
    assert handled is True
    assert "No active session to end." in (reply or "")
    assert active is None
    assert campaign == "camp-2"


def test_process_bridge_command_session_detach_unsets_active():
    client = MCPWebClient("http://localhost:8000")
    handled, reply, active, campaign = process_bridge_command("/session detach", client, "session-bbb", "camp-2")
    assert handled is True
    assert "Detached from session session-bbb." in (reply or "")
    assert active is None
    assert campaign == "camp-2"


def test_process_bridge_command_session_detach_without_active():
    client = MCPWebClient("http://localhost:8000")
    handled, reply, active, campaign = process_bridge_command("/session detach", client, None, "camp-2")
    assert handled is True
    assert "No active session to detach." in (reply or "")
    assert active is None
    assert campaign == "camp-2"


def test_process_bridge_command_session_end_keeps_attachment_when_not_ended():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/session-bbb"):
            return _FakeHTTPResponse({"session": {"id": "session-bbb"}})
        if req.full_url.endswith("/web/session/session-bbb/end"):
            return _FakeHTTPResponse({"ended": False})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session end", client, "session-bbb", "camp-2")

    assert handled is True
    assert "Could not end session session-bbb; still attached." in (reply or "")
    assert active == "session-bbb"
    assert campaign == "camp-2"


def test_process_bridge_command_session_end_uses_canonical_session_id():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/sess-prefix"):
            return _FakeHTTPResponse({"session": {"id": "session-canonical-1"}})
        if req.full_url.endswith("/web/session/session-canonical-1/end"):
            return _FakeHTTPResponse({"ended": True})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session end", client, "sess-prefix", "camp-2")

    assert handled is True
    assert "Ended and detached from session session-canonical-1." in (reply or "")
    assert active is None
    assert campaign == "camp-2"


def test_process_bridge_command_session_end_falls_back_when_state_lookup_fails():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/session-bbb"):
            raise HTTPError(
                url=req.full_url,
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=io.BytesIO(json.dumps({"detail": "Session not found"}).encode("utf-8")),
            )
        if req.full_url.endswith("/web/session/session-bbb/end"):
            return _FakeHTTPResponse({"ended": True})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session end", client, "session-bbb", "camp-2")

    assert handled is True
    assert "Ended and detached from session session-bbb." in (reply or "")
    assert active is None
    assert campaign == "camp-2"


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


def test_process_bridge_command_session_run_starts_session():
    client = MCPWebClient("http://localhost:8000")

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/session/start"):
            payload = json.loads(req.data.decode("utf-8"))
            assert payload == {"campaign_id": "camp-1", "title": "Night Shift"}
            return _FakeHTTPResponse(
                {"session": {"id": "sess-9", "title": "Night Shift"}, "campaign": {"id": "camp-1", "name": "Alpha"}}
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        handled, reply, active, campaign = process_bridge_command("/session run camp-1 Night Shift", client, None, None)

    assert handled is True
    assert "Started session 'Night Shift' (sess-9) in campaign 'Alpha'." == reply
    assert active == "sess-9"
    assert campaign == "camp-1"


def test_process_bridge_command_clear_channel_command():
    client = MCPWebClient("http://localhost:8000")
    handled, reply, active, campaign = process_bridge_command("/clear", client, "session-bbb", "camp-2")
    assert handled is True
    assert reply is None
    assert active == "session-bbb"
    assert campaign == "camp-2"


def test_process_bridge_command_channel_clear_alias():
    client = MCPWebClient("http://localhost:8000")
    handled, reply, active, campaign = process_bridge_command("/channel clear", client, "session-bbb", "camp-2")
    assert handled is True
    assert reply is None
    assert active == "session-bbb"
    assert campaign == "camp-2"


@pytest.mark.asyncio
async def test_clear_discord_channel_history_uses_non_bulk_purge():
    calls = []
    before = object()

    class _FakeChannel:
        async def purge(self, **kwargs):
            calls.append(kwargs)
            return ("a", "b", "c")

    deleted_count = await clear_discord_channel_history(_FakeChannel(), before=before)

    assert deleted_count == 3
    assert calls == [{"limit": None, "before": before, "bulk": False}]


def test_format_session_log_entry():
    assert _format_session_log_entry({"role": "player", "content": "hello"}) == "**Player:** hello"
    assert _format_session_log_entry({"role": "narrator", "content": "world"}) == "**Narrator:** world"
    assert _format_session_log_entry({"role": "system", "content": "ok"}) == "**System:** ok"
    assert _format_session_log_entry({"role": "custom", "content": "x"}) == "**Custom:** x"
    assert _format_session_log_entry({"role": "player", "content": "   "}) is None
