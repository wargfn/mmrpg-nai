"""Tests for `session attach` CLI command."""

from __future__ import annotations

import json
from unittest.mock import patch

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
        raise AssertionError(f"Unexpected URL: {req.full_url}")

    with patch("urllib.request.urlopen", side_effect=_urlopen):
        with patch("mmrpg_nai.cli.main.Prompt.ask", side_effect=["hello", "quit"]):
            result = runner.invoke(app, ["session", "attach", "--session-id", active_session_id])

    assert result.exit_code == 0, result.output
    assert "Narrated: hello" in result.output
    assert "Detached from active session." in result.output
