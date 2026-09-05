"""Tests for first-run startup flows in `session run`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from mmrpg_nai.cli.main import app
from mmrpg_nai.models.core import Campaign, Character, User
from mmrpg_nai.storage.store import Store

runner = CliRunner()


class _FakeNarrator:
    def __init__(self, cfg, store) -> None:
        self.cfg = cfg
        self.store = store

    def start_session(self, session, campaign, party, source_materials=None) -> None:
        return None

    def recap_last_session(self, last_session) -> str:
        return ""

    def narrate(self, player_input: str, stream: bool = True):
        return ""

    def meta_direction(self, direction: str, stream: bool = True):
        return ""

    def summarise_campaign_progress(self, campaign, completed_sessions):
        return ""


def test_session_run_first_time_can_create_character_and_user(tmp_path: Path):
    store = Store(tmp_path)
    campaign = Campaign(name="First Run Campaign")
    store.campaigns.save(campaign)

    prompts = [
        "1",            # campaign selection
        "y",            # create character
        "Spider-Man",   # character name
        "Peter Parker", # alias
        "",             # background
        "y",            # create user
        "Peter",        # first_name
        "Parker",       # last_name
        "",             # email
        "",             # notes
        "",             # session title (accept default)
        "quit",         # immediate exit from play loop
    ]

    with patch("mmrpg_nai.llm.narrator.Narrator", _FakeNarrator):
        with patch("mmrpg_nai.cli.main.Prompt.ask", side_effect=prompts):
            result = runner.invoke(app, ["session", "run", "--no-stream", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output

    saved = Store(tmp_path)
    chars = saved.characters.list_all()
    users = saved.users.list_all()
    sessions = saved.sessions.list_all()
    updated_campaign = saved.campaigns.load(campaign.id)

    assert len(chars) == 1
    assert len(users) == 1
    assert len(sessions) == 1
    assert sessions[0].participants == [chars[0].id]
    assert sessions[0].user_ids == [users[0].id]
    assert updated_campaign is not None
    assert chars[0].id in updated_campaign.character_ids
    assert users[0].id in updated_campaign.user_ids


def test_session_run_can_create_unnamed_character_during_selection(tmp_path: Path):
    store = Store(tmp_path)
    campaign = Campaign(name="Selection Campaign")
    store.campaigns.save(campaign)
    existing_char = Character(name="Captain Marvel", alias="Carol Danvers", is_npc=False)
    store.characters.save(existing_char)
    existing_user = User(first_name="Carol", last_name="Danvers")
    store.users.save(existing_user)

    prompts = [
        "1",        # campaign selection
        "unnamed",  # character selection creates unnamed character
        "",         # users: accept default selection
        "",         # session title (accept default)
        "quit",     # immediate exit from play loop
    ]

    with patch("mmrpg_nai.llm.narrator.Narrator", _FakeNarrator):
        with patch("mmrpg_nai.cli.main.Prompt.ask", side_effect=prompts):
            result = runner.invoke(app, ["session", "run", "--no-stream", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output

    saved = Store(tmp_path)
    sessions = saved.sessions.list_all()
    assert len(sessions) == 1

    session = sessions[0]
    assert len(session.participants) == 1
    participant = saved.characters.load(session.participants[0])
    assert participant is not None
    assert participant.name.startswith("Unnamed Character")

    updated_campaign = saved.campaigns.load(campaign.id)
    assert updated_campaign is not None
    assert participant.id in updated_campaign.character_ids


def test_session_run_reprompts_on_invalid_character_selection(tmp_path: Path):
    store = Store(tmp_path)
    campaign = Campaign(name="Reprompt Campaign")
    store.campaigns.save(campaign)
    existing_char = Character(name="Wolverine", alias="Logan", is_npc=False)
    store.characters.save(existing_char)
    existing_user = User(first_name="Logan")
    store.users.save(existing_user)

    prompts = [
        "1",       # campaign selection
        "zzz",     # invalid character selector
        "1",       # valid character selector
        "",        # users: accept default
        "",        # session title (accept default)
        "quit",    # immediate exit from play loop
    ]

    with patch("mmrpg_nai.llm.narrator.Narrator", _FakeNarrator):
        with patch("mmrpg_nai.cli.main.Prompt.ask", side_effect=prompts):
            result = runner.invoke(app, ["session", "run", "--no-stream", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "No matching characters found. Try again." in result.output

    saved = Store(tmp_path)
    sessions = saved.sessions.list_all()
    assert len(sessions) == 1
    assert sessions[0].participants == [existing_char.id]
