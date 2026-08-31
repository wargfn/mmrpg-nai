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


# ---------------------------------------------------------------------------
# Source material injection tests
# ---------------------------------------------------------------------------

def test_source_material_injected_into_system_prompt(cfg, store, session, campaign, character, tmp_path):
    """Source material text should appear under ## Rules & Source Materials."""
    from mmrpg_nai.models.core import SourceMaterial

    # Write a fake extracted text file
    txt = tmp_path / "rulebook.txt"
    txt.write_text("Roll 2d6 for every action.", encoding="utf-8")

    mat = SourceMaterial(
        title="Core Rulebook",
        file_path="/fake/rulebook.pdf",
        extracted_text_path=str(txt),
    )
    store.source_materials.save(mat)
    campaign.source_material_ids = [mat.id]
    store.campaigns.save(campaign)

    narrator = Narrator.__new__(Narrator)
    narrator.cfg = cfg
    narrator.store = store
    narrator.llm = MagicMock()
    narrator.llm.complete.return_value = "LLM response"
    narrator._messages = []
    narrator.start_session(session, campaign, [character], source_materials=[mat])

    system_content = narrator._messages[0]["content"]
    assert "Rules & Source Materials" in system_content
    assert "Roll 2d6" in system_content


def test_no_source_materials_skips_section(cfg, store, session, campaign, character):
    """When no source materials are passed, the section must not appear."""
    narrator = _make_narrator(cfg, store, session, campaign, [character])
    system_content = narrator._messages[0]["content"]
    assert "Rules & Source Materials" not in system_content


def test_max_source_chars_zero_disables_injection(cfg, store, session, campaign, character, tmp_path):
    """Setting max_source_chars=0 should suppress injection even if materials exist."""
    from mmrpg_nai.models.core import NarratorConfig, SourceMaterial

    txt = tmp_path / "rules.txt"
    txt.write_text("Many rules here.", encoding="utf-8")
    mat = SourceMaterial(
        title="Rules",
        file_path="/fake/rules.pdf",
        extracted_text_path=str(txt),
    )
    store.source_materials.save(mat)

    cfg_no_inject = NarratorConfig(max_source_chars=0)
    narrator = Narrator.__new__(Narrator)
    narrator.cfg = cfg_no_inject
    narrator.store = store
    narrator.llm = MagicMock()
    narrator._messages = []
    narrator.start_session(session, campaign, [character], source_materials=[mat])

    system_content = narrator._messages[0]["content"]
    assert "Rules & Source Materials" not in system_content


def test_max_source_chars_truncates_text(cfg, store, session, campaign, character, tmp_path):
    """Text beyond max_source_chars should be truncated."""
    from mmrpg_nai.models.core import NarratorConfig, SourceMaterial

    long_text = "X" * 5000
    txt = tmp_path / "big.txt"
    txt.write_text(long_text, encoding="utf-8")
    mat = SourceMaterial(
        title="Big Book",
        file_path="/fake/big.pdf",
        extracted_text_path=str(txt),
    )
    store.source_materials.save(mat)

    cfg_small = NarratorConfig(max_source_chars=100)
    narrator = Narrator.__new__(Narrator)
    narrator.cfg = cfg_small
    narrator.store = store
    narrator.llm = MagicMock()
    narrator._messages = []
    narrator.start_session(session, campaign, [character], source_materials=[mat])

    system_content = narrator._messages[0]["content"]
    assert "Rules & Source Materials" in system_content
    # Only 100 chars of the 5000-char text should be injected
    injected = system_content.split("### Big Book\n", 1)[1]
    assert len(injected) <= 100
