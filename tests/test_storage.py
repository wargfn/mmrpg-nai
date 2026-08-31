"""Tests for the storage layer."""

import pytest
from pathlib import Path

from mmrpg_nai.models.core import Campaign, Character, Equipment, EquipmentType, NarratorConfig, PowerSet, Session
from mmrpg_nai.storage.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path)


def test_campaign_roundtrip(store: Store):
    camp = Campaign(name="Test Campaign")
    store.campaigns.save(camp)
    loaded = store.campaigns.load(camp.id)
    assert loaded is not None
    assert loaded.name == "Test Campaign"


def test_campaign_list(store: Store):
    for i in range(3):
        store.campaigns.save(Campaign(name=f"Campaign {i}"))
    assert len(store.campaigns.list_all()) == 3


def test_campaign_delete(store: Store):
    camp = Campaign(name="Deletable")
    store.campaigns.save(camp)
    assert store.campaigns.delete(camp.id) is True
    assert store.campaigns.load(camp.id) is None


def test_session_roundtrip(store: Store):
    session = Session(campaign_id="cid", title="Session 1")
    store.sessions.save(session)
    loaded = store.sessions.load(session.id)
    assert loaded is not None
    assert loaded.title == "Session 1"


def test_character_roundtrip(store: Store):
    char = Character(name="Iron Man", alias="Tony Stark")
    store.characters.save(char)
    loaded = store.characters.load(char.id)
    assert loaded is not None
    assert loaded.alias == "Tony Stark"


def test_equipment_roundtrip(store: Store):
    eq = Equipment(name="Iron Man Suit", equipment_type=EquipmentType.ARMOR, defense_bonus=5)
    store.equipment.save(eq)
    loaded = store.equipment.load(eq.id)
    assert loaded is not None
    assert loaded.defense_bonus == 5


def test_power_set_roundtrip(store: Store):
    ps = PowerSet(name="Iron Man Tech", description="Advanced Stark tech")
    store.power_sets.save(ps)
    loaded = store.power_sets.load(ps.id)
    assert loaded is not None
    assert loaded.name == "Iron Man Tech"


def test_config_roundtrip(store: Store):
    cfg = NarratorConfig()
    cfg.system_prompt = "Custom prompt"
    store.save_config(cfg)
    loaded = store.load_config()
    assert loaded.system_prompt == "Custom prompt"


def test_store_find(store: Store):
    char1 = Character(name="Spider-Man", is_npc=False)
    char2 = Character(name="Hydra Agent", is_npc=True)
    store.characters.save(char1)
    store.characters.save(char2)
    npcs = store.characters.find(is_npc=True)
    assert len(npcs) == 1
    assert npcs[0].name == "Hydra Agent"


def test_session_create_links_to_campaign(store: Store):
    """Creating a session via session_create should register its ID on the campaign."""
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app
    import os

    campaign = Campaign(name="Link Test Campaign")
    store.campaigns.save(campaign)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "session", "create",
            "--campaign-id", campaign.id,
            "--title", "Test Session",
            "--data-dir", str(store.base_dir),
        ],
    )
    assert result.exit_code == 0, result.output

    reloaded = store.campaigns.load(campaign.id)
    assert reloaded is not None
    assert len(reloaded.session_ids) == 1
