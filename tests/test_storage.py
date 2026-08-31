"""Tests for the storage layer."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def test_campaign_add_source(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app
    from mmrpg_nai.models.core import SourceMaterial

    campaign = Campaign(name="Source Test")
    store.campaigns.save(campaign)
    mat = SourceMaterial(title="Core Rulebook", file_path="/fake.pdf")
    store.source_materials.save(mat)

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "add-source", campaign.id, mat.id, "--data-dir", str(store.base_dir)])
    assert result.exit_code == 0, result.output

    reloaded = store.campaigns.load(campaign.id)
    assert mat.id in reloaded.source_material_ids


def test_campaign_add_source_duplicate(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app
    from mmrpg_nai.models.core import SourceMaterial

    campaign = Campaign(name="Dup Test")
    store.campaigns.save(campaign)
    mat = SourceMaterial(title="Rulebook", file_path="/fake.pdf")
    store.source_materials.save(mat)

    runner = CliRunner()
    runner.invoke(app, ["campaign", "add-source", campaign.id, mat.id, "--data-dir", str(store.base_dir)])
    result = runner.invoke(app, ["campaign", "add-source", campaign.id, mat.id, "--data-dir", str(store.base_dir)])
    assert "already linked" in result.output

    reloaded = store.campaigns.load(campaign.id)
    assert reloaded.source_material_ids.count(mat.id) == 1


def test_campaign_remove_source(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app
    from mmrpg_nai.models.core import SourceMaterial

    mat = SourceMaterial(title="Rulebook", file_path="/fake.pdf")
    store.source_materials.save(mat)
    campaign = Campaign(name="Remove Test", source_material_ids=[mat.id])
    store.campaigns.save(campaign)

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "remove-source", campaign.id, mat.id, "--data-dir", str(store.base_dir)])
    assert result.exit_code == 0, result.output

    reloaded = store.campaigns.load(campaign.id)
    assert mat.id not in reloaded.source_material_ids


def test_campaign_add_enemy(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app
    from mmrpg_nai.models.core import Character

    campaign = Campaign(name="Enemy Test")
    store.campaigns.save(campaign)
    villain = Character(name="Doctor Doom", alias="Victor von Doom", is_npc=True)
    store.characters.save(villain)

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "add-enemy", campaign.id, villain.id, "--data-dir", str(store.base_dir)])
    assert result.exit_code == 0, result.output
    assert "Doctor Doom" in result.output

    reloaded = store.campaigns.load(campaign.id)
    assert villain.id in reloaded.enemy_ids


def test_campaign_remove_enemy(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app
    from mmrpg_nai.models.core import Character

    villain = Character(name="Thanos", alias="Mad Titan", is_npc=True)
    store.characters.save(villain)
    campaign = Campaign(name="Thanos Campaign", enemy_ids=[villain.id])
    store.campaigns.save(campaign)

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "remove-enemy", campaign.id, villain.id, "--data-dir", str(store.base_dir)])
    assert result.exit_code == 0, result.output

    reloaded = store.campaigns.load(campaign.id)
    assert villain.id not in reloaded.enemy_ids


def test_campaign_enemies_list(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app
    from mmrpg_nai.models.core import Character

    villain = Character(name="Red Skull", alias="Johann Schmidt", is_npc=True)
    store.characters.save(villain)
    campaign = Campaign(name="Skull Campaign", enemy_ids=[villain.id])
    store.campaigns.save(campaign)

    runner = CliRunner()
    result = runner.invoke(app, ["campaign", "enemies", campaign.id, "--data-dir", str(store.base_dir)])
    assert result.exit_code == 0, result.output
    assert "Red Skull" in result.output


def test_load_by_prefix(store: Store):
    campaign = Campaign(name="Prefix Test")
    store.campaigns.save(campaign)
    prefix = campaign.id[:8]
    loaded = store.campaigns.load_by_prefix(prefix)
    assert loaded is not None
    assert loaded.id == campaign.id


def test_campaign_add_source_with_prefix(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app
    from mmrpg_nai.models.core import SourceMaterial

    campaign = Campaign(name="Prefix Source Test")
    store.campaigns.save(campaign)
    mat = SourceMaterial(title="Rulebook", file_path="/fake.pdf")
    store.source_materials.save(mat)

    runner = CliRunner()
    result = runner.invoke(app, [
        "campaign", "add-source",
        campaign.id[:8],   # prefix only
        mat.id[:8],        # prefix only
        "--data-dir", str(store.base_dir),
    ])
    assert result.exit_code == 0, result.output

    reloaded = store.campaigns.load(campaign.id)
    assert mat.id in reloaded.source_material_ids


def test_campaign_plan_saved_to_campaign(store: Store):
    from typer.testing import CliRunner
    from unittest.mock import patch
    from mmrpg_nai.cli.main import app

    campaign = Campaign(name="Plan Save Test")
    store.campaigns.save(campaign)

    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.complete.return_value = "# My Plan\nThis is the plan."
    with patch("mmrpg_nai.llm.client._build_client", return_value=MagicMock()), \
         patch("mmrpg_nai.llm.narrator.Narrator.plan_campaign", return_value="# My Plan\nThis is the plan."):
        result = runner.invoke(app, [
            "campaign", "plan",
            campaign.id[:8],
            "--brief", "A test brief",
            "--data-dir", str(store.base_dir),
        ])
    assert result.exit_code == 0, result.output

    reloaded = store.campaigns.load(campaign.id)
    assert reloaded is not None
    assert "My Plan" in reloaded.plan


def test_campaign_show_displays_plan(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app

    campaign = Campaign(name="Show Test", plan="# Campaign Plan\nThe heroes fight Doom.")
    store.campaigns.save(campaign)

    runner = CliRunner()
    result = runner.invoke(app, [
        "campaign", "show",
        campaign.id[:8],
        "--data-dir", str(store.base_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "Show Test" in result.output
    assert "Campaign Plan" in result.output


def test_campaign_show_no_plan(store: Store):
    from typer.testing import CliRunner
    from mmrpg_nai.cli.main import app

    campaign = Campaign(name="No Plan Yet")
    store.campaigns.save(campaign)

    runner = CliRunner()
    result = runner.invoke(app, [
        "campaign", "show",
        campaign.id,
        "--data-dir", str(store.base_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "No plan" in result.output
