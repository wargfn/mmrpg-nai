from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from mmrpg_nai.cli.main import app

runner = CliRunner()


def test_roll_command_narrates_without_session(tmp_path: Path):
    with patch("mmrpg_nai.cli.main.narrate_d616_roll", return_value="Rolled 12. Fantastic result.") as roll:
        result = runner.invoke(app, ["roll", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    roll.assert_called_once()
    assert "Narrator (roll)" in result.output
    assert "Rolled 12. Fantastic result." in result.output
