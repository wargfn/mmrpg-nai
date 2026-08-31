"""Tests for meta-direction and last-session recap in the Narrator engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mmrpg_nai.llm.narrator import Narrator
from mmrpg_nai.models.core import (
    Campaign,
    Character,
    LogEntry,
    NarratorConfig,
    Session,
)
from mmrpg_nai.storage.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path)


@pytest.fixture
def cfg() -> NarratorConfig:
    return NarratorConfig()


@pytest.fixture
def campaign(store: Store) -> Campaign:
    c = Campaign(name="Test Campaign")
    store.campaigns.save(c)
    return c


@pytest.fixture
def character(store: Store) -> Character:
    ch = Character(name="Spider-Man", alias="Peter Parker")
    store.characters.save(ch)
    return ch


@pytest.fixture
def session(store: Store, campaign: Campaign, character: Character) -> Session:
    s = Session(campaign_id=campaign.id, title="Session 1", participants=[character.id])
    store.sessions.save(s)
    return s


def _make_narrator(cfg: NarratorConfig, store: Store, session: Session, campaign: Campaign, party: list[Character]) -> Narrator:
    narrator = Narrator.__new__(Narrator)
    narrator.cfg = cfg
    narrator.store = store
    narrator.llm = MagicMock()
    narrator.llm.complete.return_value = "LLM response"
    narrator._messages = []
    narrator.start_session(session, campaign, party)
    return narrator


def test_meta_direction_logs_as_meta(cfg, store, session, campaign, character):
    narrator = _make_narrator(cfg, store, session, campaign, [character])
    result = narrator.meta_direction("make the next fight easier", stream=False)
    assert result == "LLM response"

    # The meta entry should be logged with role "meta"
    meta_entries = [e for e in session.log if e.role == "meta"]
    assert len(meta_entries) == 1
    assert meta_entries[0].content == "make the next fight easier"


def test_meta_direction_injects_system_message(cfg, store, session, campaign, character):
    narrator = _make_narrator(cfg, store, session, campaign, [character])
    narrator.meta_direction("skip to the boss", stream=False)

    # The system message injected should contain the OUT-OF-GAME marker
    system_msgs = [m for m in narrator._messages if m["role"] == "system"]
    meta_system = [m for m in system_msgs if "OUT-OF-GAME" in m["content"]]
    assert len(meta_system) == 1
    assert "skip to the boss" in meta_system[0]["content"]


def test_meta_direction_does_not_log_as_player(cfg, store, session, campaign, character):
    narrator = _make_narrator(cfg, store, session, campaign, [character])
    narrator.meta_direction("change the tone", stream=False)
    player_entries = [e for e in session.log if e.role == "player"]
    assert len(player_entries) == 0


def test_recap_last_session_uses_synopsis(cfg, store, campaign, character):
    prev = Session(campaign_id=campaign.id, title="Session 0", synopsis="The heroes defeated Hydra.")
    store.sessions.save(prev)
    current = Session(campaign_id=campaign.id, title="Session 1")
    store.sessions.save(current)

    narrator = _make_narrator(cfg, store, current, campaign, [character])
    recap = narrator.recap_last_session(prev)
    assert recap == "LLM response"
    # Verify the LLM was called with content referencing the synopsis
    call_args = narrator.llm.complete.call_args
    messages = call_args[0][0]
    user_msg = next(m for m in messages if m["role"] == "user")
    assert "Hydra" in user_msg["content"]


def test_recap_last_session_uses_log(cfg, store, campaign, character):
    prev = Session(campaign_id=campaign.id, title="Session 0")
    prev.log.append(LogEntry(role="player", content="I punch the villain!"))
    prev.log.append(LogEntry(role="narrator", content="You knock him out!"))
    store.sessions.save(prev)
    current = Session(campaign_id=campaign.id, title="Session 1")
    store.sessions.save(current)

    narrator = _make_narrator(cfg, store, current, campaign, [character])
    recap = narrator.recap_last_session(prev)
    assert recap == "LLM response"
    call_args = narrator.llm.complete.call_args
    messages = call_args[0][0]
    user_msg = next(m for m in messages if m["role"] == "user")
    assert "punch" in user_msg["content"]


def test_recap_last_session_empty_returns_empty_string(cfg, store, campaign, character):
    prev = Session(campaign_id=campaign.id, title="Session 0")
    store.sessions.save(prev)
    current = Session(campaign_id=campaign.id, title="Session 1")
    store.sessions.save(current)

    narrator = _make_narrator(cfg, store, current, campaign, [character])
    recap = narrator.recap_last_session(prev)
    # Empty prev session – no LLM call, returns ""
    assert recap == ""
    narrator.llm.complete.assert_not_called()
