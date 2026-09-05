from __future__ import annotations

from typer.testing import CliRunner

from mmrpg_nai import __version__
from mmrpg_nai.cli.main import app

runner = CliRunner()


def test_cli_version_flag_prints_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert f"mmrpg-nai {__version__}" in result.output
