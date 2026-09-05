from __future__ import annotations

from types import SimpleNamespace
from typer.testing import CliRunner
from unittest.mock import patch

from mmrpg_nai.cli.main import app

runner = CliRunner()


def test_serve_background_spawns_service():
    with patch("mmrpg_nai.cli.main._spawn_background_mcp_service", return_value=4321) as spawn:
        result = runner.invoke(
            app,
            [
                "serve",
                "--host",
                "0.0.0.0",
                "--port",
                "9000",
                "--data-dir",
                "/tmp/mmrpg-data",
                "--background",
            ],
        )

    assert result.exit_code == 0, result.output
    spawn.assert_called_once_with("0.0.0.0", 9000, "/tmp/mmrpg-data")
    assert "MCP Service started in background (pid=4321)" in result.output


def test_serve_background_reports_startup_failure():
    with patch("mmrpg_nai.cli.main._spawn_background_mcp_service", side_effect=RuntimeError("failed to start")):
        result = runner.invoke(app, ["serve", "--background"])

    assert result.exit_code != 0
    assert "failed to start" in result.output


def test_serve_foreground_does_not_spawn_background():
    fake_llm = SimpleNamespace(provider="openai", api_key_env="OPENAI_API_KEY")
    fake_cfg = SimpleNamespace(llm=SimpleNamespace(resolved=lambda env: fake_llm))
    fake_store = SimpleNamespace(load_config=lambda: fake_cfg)

    with patch("mmrpg_nai.cli.main._get_store", return_value=fake_store):
        with patch("mmrpg_nai.cli.main._spawn_background_mcp_service") as spawn:
            with patch("mmrpg_nai.mcp.service.init_app"):
                with patch("uvicorn.run") as run:
                    result = runner.invoke(app, ["serve", "--foreground", "--data-dir", "/tmp/mmrpg-data"])

    assert result.exit_code == 0, result.output
    spawn.assert_not_called()
    run.assert_called_once()
