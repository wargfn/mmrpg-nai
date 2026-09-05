"""Tests for `session query` command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from mmrpg_nai.cli.main import app
from mmrpg_nai.models.core import Campaign, Character, Session
from mmrpg_nai.storage.store import Store

runner = CliRunner()


class _FakeNarrator:
    def __init__(self, cfg, store) -> None:
        self.cfg = cfg
        self.store = store
        self.started = None

    def start_session(self, session, campaign, party, source_materials=None):
        self.started = (session, campaign, party, source_materials or [])

    def query_rules(self, question: str, stream: bool = False):
        return f"Answer: {question}"


def test_session_query_requires_campaign_or_session(tmp_path: Path):
    result = runner.invoke(
        app,
        ["session", "query", "How does melee work?", "--data-dir", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert "Provide exactly one of --campaign-id or --session-id" in result.output


def test_session_query_rejects_both_campaign_and_session(tmp_path: Path):
    store = Store(tmp_path)
    campaign = Campaign(name="Rules Campaign")
    store.campaigns.save(campaign)
    session = Session(campaign_id=campaign.id, title="Session 1")
    store.sessions.save(session)

    result = runner.invoke(
        app,
        [
            "session",
            "query",
            "How does melee work?",
            "--campaign-id",
            campaign.id,
            "--session-id",
            session.id,
            "--data-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "Provide exactly one of --campaign-id or --session-id" in result.output


def test_session_query_with_campaign_context(tmp_path: Path):
    store = Store(tmp_path)
    campaign = Campaign(name="Rules Campaign")
    store.campaigns.save(campaign)
    character = Character(name="Hero", alias="H")
    store.characters.save(character)
    campaign.character_ids.append(character.id)
    store.campaigns.save(campaign)

    with patch("mmrpg_nai.llm.narrator.Narrator", _FakeNarrator):
        result = runner.invoke(
            app,
            [
                "session",
                "query",
                "How does agility defense work?",
                "--campaign-id",
                campaign.id,
                "--data-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Rules Query" in result.output
    assert "agility defense" in result.output


def test_session_query_with_session_context(tmp_path: Path):
    store = Store(tmp_path)
    campaign = Campaign(name="Rules Campaign")
    store.campaigns.save(campaign)
    session = Session(campaign_id=campaign.id, title="Session 1")
    store.sessions.save(session)

    with patch("mmrpg_nai.llm.narrator.Narrator", _FakeNarrator):
        result = runner.invoke(
            app,
            [
                "session",
                "query",
                "How is focus checked?",
                "--session-id",
                session.id,
                "--data-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "focus checked" in result.output


def test_session_query_rejects_character_outside_context(tmp_path: Path):
    store = Store(tmp_path)
    campaign = Campaign(name="Rules Campaign")
    in_campaign = Character(name="Hero", alias="H")
    out_of_campaign = Character(name="Other", alias="O")
    store.characters.save(in_campaign)
    store.characters.save(out_of_campaign)
    campaign.character_ids.append(in_campaign.id)
    store.campaigns.save(campaign)

    result = runner.invoke(
        app,
        [
            "session",
            "query",
            "Who is in context?",
            "--campaign-id",
            campaign.id,
            "--character-ids",
            out_of_campaign.id,
            "--data-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "not in the selected session/campaign context" in result.output
