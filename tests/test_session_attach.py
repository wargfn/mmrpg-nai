"""Tests for `session attach` CLI command."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from typer.testing import CliRunner

from mmrpg_nai.cli.main import app

runner = CliRunner()


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_session_attach_no_active_sessions():
    def _urlopen(req, timeout=15):
        return _FakeHTTPResponse({"sessions": []})

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        result = runner.invoke(app, ["session", "attach"])

    assert result.exit_code != 0
    assert "No active sessions found" in result.output


def test_session_attach_chats_with_active_session():
    active_session_id = "session-1234abcd"

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse(
                {
                    "sessions": [
                        {
                            "id": active_session_id,
                            "campaign_id": "campaign-1",
                            "title": "Session 1",
                            "user_ids": [],
                        }
                    ]
                }
            )
        if req.full_url.endswith(f"/web/session/{active_session_id}/chat"):
            return _FakeHTTPResponse({"response": "Narrated: hello", "mode": "narrate", "log": []})
        if req.full_url.endswith(f"/web/session/{active_session_id}") and req.method == "GET":
            return _FakeHTTPResponse({"is_active": True})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        with patch("mmrpg_nai.cli.main.Prompt.ask", side_effect=["hello", "quit"]):
            result = runner.invoke(app, ["session", "attach", "--session-id", active_session_id])

    assert result.exit_code == 0, result.output
    assert "Narrated: hello" in result.output
    assert "Detached from active session." in result.output


def test_session_attach_can_resume_inactive_session_by_id():
    base_session_id = "session-old1234"
    resumed_session_id = "session-new5678"
    resumed = {"done": False}

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/active-sessions"):
            if resumed["done"]:
                return _FakeHTTPResponse({"sessions": [{"id": resumed_session_id}]})
            return _FakeHTTPResponse({"sessions": []})
        if req.full_url.endswith("/web/bootstrap"):
            return _FakeHTTPResponse(
                {
                    "sessions": [
                        {
                            "id": base_session_id,
                            "campaign_id": "campaign-1",
                            "title": "Session 1",
                            "user_ids": [],
                        }
                    ]
                }
            )
        if req.full_url.endswith(f"/web/session/{base_session_id}") and req.method == "GET":
            return _FakeHTTPResponse({"is_active": False})
        if req.full_url.endswith("/web/session/start") and req.method == "POST":
            resumed["done"] = True
            return _FakeHTTPResponse(
                {
                    "session": {
                        "id": resumed_session_id,
                        "campaign_id": "campaign-1",
                        "title": "Session 2",
                        "user_ids": [],
                    }
                }
            )
        if req.full_url.endswith(f"/web/session/{resumed_session_id}/chat"):
            return _FakeHTTPResponse({"response": "Narrated: hello", "mode": "narrate", "log": []})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        with patch("mmrpg_nai.cli.main.Prompt.ask", side_effect=["hello", "quit"]):
            result = runner.invoke(app, ["session", "attach", "--session-id", base_session_id])

    assert result.exit_code == 0, result.output
    assert "Narrated: hello" in result.output


def test_session_attach_errors_when_state_active_but_not_listed():
    active_session_id = "session-1234abcd"
    started_called = {"value": False}

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse({"sessions": []})
        if req.full_url.endswith("/web/bootstrap"):
            return _FakeHTTPResponse(
                {
                    "sessions": [
                        {
                            "id": active_session_id,
                            "campaign_id": "campaign-1",
                            "title": "Session 1",
                            "user_ids": [],
                        }
                    ]
                }
            )
        if req.full_url.endswith(f"/web/session/{active_session_id}") and req.method == "GET":
            return _FakeHTTPResponse({"is_active": True})
        if req.full_url.endswith("/web/session/start"):
            started_called["value"] = True
            return _FakeHTTPResponse({"session": {"id": active_session_id}})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        result = runner.invoke(app, ["session", "attach", "--session-id", active_session_id])

    assert result.exit_code != 0
    assert "Session reports active but is not listed in active sessions." in result.output
    assert started_called["value"] is False


def test_session_attach_uses_canonical_session_id_from_state():
    requested_session_id = "sess-prefix"
    canonical_session_id = "session-1234abcd"

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse({"sessions": [{"id": canonical_session_id}]})
        if req.full_url.endswith(f"/web/session/{requested_session_id}") and req.method == "GET":
            return _FakeHTTPResponse({"is_active": True, "session": {"id": canonical_session_id}})
        if req.full_url.endswith(f"/web/session/{canonical_session_id}") and req.method == "GET":
            return _FakeHTTPResponse({"is_active": True, "session": {"id": canonical_session_id}})
        if req.full_url.endswith(f"/web/session/{canonical_session_id}/chat"):
            return _FakeHTTPResponse({"response": "Narrated: hello", "mode": "narrate", "log": []})
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        with patch("mmrpg_nai.cli.main.Prompt.ask", side_effect=["hello", "quit"]):
            result = runner.invoke(app, ["session", "attach", "--session-id", requested_session_id])

    assert result.exit_code == 0, result.output
    assert "Narrated: hello" in result.output


def test_session_attach_surfaces_non_404_state_lookup_errors():
    session_id = "session-1234abcd"

    def _urlopen(req, timeout=15):
        if req.full_url.endswith("/web/active-sessions"):
            return _FakeHTTPResponse({"sessions": []})
        if req.full_url.endswith(f"/web/session/{session_id}") and req.method == "GET":
            raise HTTPError(
                req.full_url,
                code=500,
                msg="Internal Server Error",
                hdrs=None,
                fp=BytesIO(b'{"detail":"boom"}'),
            )
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        result = runner.invoke(app, ["session", "attach", "--session-id", session_id])

    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "HTTP 500" in str(result.exception)
