from __future__ import annotations

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
