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
    LLMConfig,
    NarratorConfig,
    Power,
    PowerSet,
    Rank,
    Scene,
    Session,
    SourceMaterial,
    User,
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


def test_llm_config_detects_openai_provider():
    cfg = LLMConfig()
    resolved = cfg.resolved({"OPENAI_API_KEY": "sk-test"})
    assert resolved.provider == "openai"
    assert resolved.api_key_env == "OPENAI_API_KEY"


def test_llm_config_detects_google_provider():
    cfg = LLMConfig()
    resolved = cfg.resolved({"GOOGLE_API_KEY": "AIza-test"})
    assert resolved.provider == "google_ai_studio"
    assert resolved.api_key_env == "GOOGLE_API_KEY"


def test_llm_config_detects_github_provider():
    cfg = LLMConfig()
    resolved = cfg.resolved({"GITHUB_TOKEN": "ghp_test"})
    assert resolved.provider == "github_copilot"
    assert resolved.api_key_env == "GITHUB_TOKEN"


def test_llm_config_detects_ollama_provider():
    cfg = LLMConfig()
    resolved = cfg.resolved({"OLLAMA_API_KEY": "ollama_test"})
    assert resolved.provider == "ollama"
    assert resolved.api_key_env == "OLLAMA_API_KEY"


def test_llm_config_detects_grok_provider():
    cfg = LLMConfig()
    resolved = cfg.resolved({"XAI_API_KEY": "xai-test"})
    assert resolved.provider == "grok"
    assert resolved.api_key_env == "XAI_API_KEY"


def test_llm_config_detects_openwebui_provider():
    cfg = LLMConfig()
    resolved = cfg.resolved({"OPENWEBUI_API_KEY": "owui-test"})
    assert resolved.provider == "openwebui"
    assert resolved.api_key_env == "OPENWEBUI_API_KEY"


def test_llm_config_uses_selected_provider_without_detected_env():
    cfg = LLMConfig(provider="openai")
    resolved = cfg.resolved({})
    assert resolved.provider == "openai"
    assert resolved.api_key_env == "OPENAI_API_KEY"


def test_llm_config_backfills_missing_provider_settings():
    cfg = LLMConfig.model_validate(
        {
            "provider": "github_copilot",
            "provider_settings": {
                "openai": {
                    "model": "custom-openai",
                    "api_base": "https://api.openai.com/v1",
                    "api_key_env": "OPENAI_API_KEY",
                    "max_tokens": 4096,
                    "temperature": 0.8,
                }
            },
        }
    )
    assert "openwebui" in cfg.provider_settings
    assert "grok" in cfg.provider_settings
    assert cfg.provider_settings["openai"].model == "custom-openai"


def test_llm_config_detects_provider_with_custom_api_key_env():
    cfg = LLMConfig()
    cfg.provider_settings["openai"].api_key_env = "MY_OPENAI_KEY"
    resolved = cfg.resolved({"MY_OPENAI_KEY": "sk-custom"})
    assert resolved.provider == "openai"
    assert resolved.api_key_env == "MY_OPENAI_KEY"


def test_source_material():
    sm = SourceMaterial(title="Core Rulebook", file_path="/tmp/core.pdf", page_count=300)
    assert sm.title == "Core Rulebook"
    assert sm.page_count == 300


def test_user_defaults():
    user = User(first_name="Natasha", last_name="Romanoff")
    assert user.id
    assert user.last_login_at is None
    assert user.session_timestamps == []
