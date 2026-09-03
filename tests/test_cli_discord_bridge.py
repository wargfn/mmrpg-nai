from __future__ import annotations

import os

from typer.testing import CliRunner
from unittest.mock import patch

from mmrpg_nai.cli.main import app

runner = CliRunner()


def test_serve_discord_requires_token_env(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "DISCORD_BOT_TOKEN"}
    with patch.dict(os.environ, env, clear=True):
        result = runner.invoke(
            app,
            [
                "serve-discord",
                "--session-id",
                "session-1",
                "--channel-id",
                "12345",
            ],
        )
    assert result.exit_code != 0
    assert "DISCORD_BOT_TOKEN is not set" in result.output


def test_serve_discord_passes_settings_to_runner():
    captured = {}

    def _fake_run(settings):
        captured["settings"] = settings

    with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "token"}):
        with patch("mmrpg_nai.discord.bridge.run_discord_bridge", side_effect=_fake_run):
            result = runner.invoke(
                app,
                [
                    "serve-discord",
                    "--session-id",
                    "session-1",
                    "--channel-id",
                    "12345",
                    "--mcp-base-url",
                    "http://127.0.0.1:9000",
                    "--command-prefix",
                    "!nai",
                ],
            )

    assert result.exit_code == 0, result.output
    settings = captured["settings"]
    assert settings.session_id == "session-1"
    assert settings.channel_id == 12345
    assert settings.mcp_base_url == "http://127.0.0.1:9000"
    assert settings.command_prefix == "!nai"
