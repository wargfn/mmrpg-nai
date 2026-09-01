"""Tests for data models."""

import pytest
from mmrpg_nai.models.core import (
    Abilities,
    Adventure,
    Campaign,
    CampaignSettings,
    Character,
    Equipment,
    EquipmentType,
    LogEntry,
    NarratorConfig,
    Power,
    PowerSet,
    Rank,
    Scene,
    Session,
    SourceMaterial,
)


def test_character_defaults():
    c = Character(name="Spider-Man", alias="Peter Parker")
    assert c.rank == Rank.BASIC
    assert c.tier == 1
    assert c.is_npc is False
    assert c.id  # auto-generated UUID


def test_campaign_defaults():
    camp = Campaign(name="Secret Invasion")
    assert camp.settings.tone == "heroic"
    assert camp.session_ids == []


def test_equipment_enum():
    eq = Equipment(name="Web-Shooters", equipment_type=EquipmentType.GADGET)
    assert eq.equipment_type == EquipmentType.GADGET


def test_power_set():
    ps = PowerSet(
        name="Spider Powers",
        description="Radioactive spider abilities",
        powers=[Power(name="Wall Crawling", description="Climb walls", cost=1)],
    )
    assert len(ps.powers) == 1
    assert ps.powers[0].name == "Wall Crawling"


def test_adventure_scenes():
    scene = Scene(
        title="The Alert",
        description="JARVIS sounds the alarm",
        objectives=["Investigate the energy readings"],
    )
    adv = Adventure(title="Crisis at Avengers Tower", acts=[[scene]])
    assert len(adv.acts) == 1
    assert adv.acts[0][0].title == "The Alert"


def test_session_log_entry():
    session = Session(campaign_id="camp-1", title="Session 1")
    entry = LogEntry(role="player", content="I attack the Hydra agent!")
    session.log.append(entry)
    assert len(session.log) == 1


def test_narrator_config_defaults():
    cfg = NarratorConfig()
    assert cfg.llm.model == "gpt-5.4"
    assert "Narrator" in cfg.system_prompt


def test_source_material():
    sm = SourceMaterial(title="Core Rulebook", file_path="/tmp/core.pdf", page_count=300)
    assert sm.title == "Core Rulebook"
    assert sm.page_count == 300
