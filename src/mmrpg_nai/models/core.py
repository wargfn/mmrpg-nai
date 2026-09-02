"""Pydantic models for characters, equipment, power sets, campaigns and sessions."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Rank(str, Enum):
    BASIC = "basic"
    ROOKIE = "rookie"
    VETERAN = "veteran"
    CHAMPION = "champion"
    MASTER = "master"
    LEGENDARY = "legendary"


class AbilityScore(BaseModel):
    score: int = 0
    edge: int = 0
    defense_score: int = Field(default=10, description="10 + score + edge")
    non_combat_checks: int = Field(default=0, alias="non-combat_checks", description="Score + edge for non-combat checks")

    model_config = {"populate_by_name": True}


class Abilities(BaseModel):
    melee: AbilityScore = Field(default_factory=AbilityScore)
    agility: AbilityScore = Field(default_factory=AbilityScore)
    resilience: AbilityScore = Field(default_factory=AbilityScore)
    vigilance: AbilityScore = Field(default_factory=AbilityScore)
    ego: AbilityScore = Field(default_factory=AbilityScore)
    logic: AbilityScore = Field(default_factory=AbilityScore)


class ResourcePool(BaseModel):
    """A scored resource (health, focus) with optional damage reduction."""
    score: int = 0
    damage_reduction: int = Field(default=0, description="Negative means extra damage taken; positive means DR")


class Speed(BaseModel):
    run: int = 4
    climb: int = 2
    swim: int = 2
    jump: int = 2


# ---------------------------------------------------------------------------
# Power Set
# ---------------------------------------------------------------------------

class Power(BaseModel):
    name: str
    description: str
    prerequisites: list[str] = Field(default_factory=list)
    cost: int = 0
    tags: list[str] = Field(default_factory=list)


class PowerSet(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    powers: list[Power] = Field(default_factory=list)
    origin: str = ""
    tags: list[str] = Field(default_factory=list)

    model_config = {"json_schema_extra": {"example": {
        "name": "Spider Powers",
        "description": "Abilities gained from a radioactive spider bite.",
        "powers": [],
    }}}


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

class EquipmentType(str, Enum):
    WEAPON = "weapon"
    ARMOR = "armor"
    GADGET = "gadget"
    VEHICLE = "vehicle"
    CONSUMABLE = "consumable"
    OTHER = "other"


class Equipment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    equipment_type: EquipmentType = EquipmentType.OTHER
    description: str = ""
    damage_dice: str = ""
    defense_bonus: int = 0
    properties: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------

class Character(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    alias: str = ""
    rank: Rank = Rank.BASIC
    tier: int = 1
    abilities: Abilities = Field(default_factory=Abilities)
    # Health and Focus accept either a plain int (legacy) or a ResourcePool object
    health: int | ResourcePool = Field(default=10)
    focus: int | ResourcePool = Field(default=10)
    karma: int = 0
    traits: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # Inline power names (e.g. "Healing Factor 1 Health").
    # Distinct from power_sets (which are IDs referencing full PowerSet records).
    powers: list[str] = Field(default_factory=list, description="Inline power/ability names")
    power_sets: list[str] = Field(default_factory=list, description="Power set IDs")
    equipment: list[str] = Field(default_factory=list, description="Equipment IDs or inline item names")
    speed: Speed = Field(default_factory=Speed)
    initiative_mod: int = Field(default=0, description="Modifier added to initiative rolls")
    background: str = ""
    notes: str = ""
    is_npc: bool = False
    source: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Session Log
# ---------------------------------------------------------------------------

class LogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    role: str  # "narrator" | "player" | "system" | "meta"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    campaign_id: str
    title: str
    session_number: int = 1
    synopsis: str = ""
    log: list[LogEntry] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list, description="Character IDs")
    user_ids: list[str] = Field(default_factory=list, description="User/player IDs")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Campaign
# ---------------------------------------------------------------------------

class CampaignSettings(BaseModel):
    starting_rank: Rank = Rank.BASIC
    starting_tier: int = 1
    tone: str = "heroic"
    era: str = "modern"
    location: str = "New York City"
    custom_rules: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Campaign(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    plan: str = Field(default="", description="AI-generated campaign plan (from 'campaign plan')")
    campaign_progress: str = Field(default="", description="Running narrative of story progress against the plan")
    settings: CampaignSettings = Field(default_factory=CampaignSettings)
    session_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list, description="User/player IDs in this campaign")
    enemy_ids: list[str] = Field(default_factory=list, description="Character IDs of enemies/antagonists for this campaign")
    adventure_ids: list[str] = Field(default_factory=list)
    source_material_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Adventure template
# ---------------------------------------------------------------------------

class Scene(BaseModel):
    title: str
    description: str
    encounter_type: str = ""
    enemies: list[str] = Field(default_factory=list, description="Character IDs or names")
    objectives: list[str] = Field(default_factory=list)
    rewards: list[str] = Field(default_factory=list)
    notes: str = ""


class Adventure(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    synopsis: str = ""
    recommended_rank: Rank = Rank.BASIC
    recommended_tier: int = 1
    acts: list[list[Scene]] = Field(default_factory=list, description="Ordered list of acts, each containing scenes")
    locations: list[str] = Field(default_factory=list)
    npcs: list[str] = Field(default_factory=list, description="Character IDs or names")
    tags: list[str] = Field(default_factory=list)
    source: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Source Material (PDF reference)
# ---------------------------------------------------------------------------

class SourceMaterial(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    file_path: str
    description: str = ""
    categories: list[str] = Field(default_factory=list)
    page_count: int = 0
    extracted_text_path: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    first_name: str
    last_name: str = ""
    email: str = ""
    notes: str = ""
    session_timestamps: list[datetime] = Field(default_factory=list)
    last_login_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def display_name(self) -> str:
        return " ".join(part for part in [self.first_name, self.last_name] if part).strip()


# ---------------------------------------------------------------------------
# App-level settings
# ---------------------------------------------------------------------------

class LLMConfig(BaseModel):
    provider: str = "github_copilot"
    # Model name as listed on https://github.com/marketplace/models
    # Change with: mmrpg-nai config set llm.model <name>
    model: str = "gpt-5.4"
    api_base: str = "https://api.githubcopilot.com"
    api_key_env: str = "GITHUB_TOKEN"
    max_tokens: int = 4096
    temperature: float = 0.8
    provider_settings: dict[str, "LLMProviderSettings"] = Field(default_factory=lambda: {
        "google_ai_studio": LLMProviderSettings(
            model="gemini-2.5-flash",
            api_base="https://generativelanguage.googleapis.com/v1beta/openai",
            api_key_env="GOOGLE_API_KEY",
            max_tokens=4096,
            temperature=0.8,
        ),
        "openai": LLMProviderSettings(
            model="gpt-4o",
            api_base="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            max_tokens=4096,
            temperature=0.8,
        ),
        "github_copilot": LLMProviderSettings(
            model="gpt-5.4",
            api_base="https://api.githubcopilot.com",
            api_key_env="GITHUB_TOKEN",
            max_tokens=4096,
            temperature=0.8,
        ),
        "ollama": LLMProviderSettings(
            model="llama3.1",
            api_base="http://localhost:11434/v1",
            api_key_env="OLLAMA_API_KEY",
            max_tokens=4096,
            temperature=0.8,
        ),
    })

    def detect_provider(self, env: Mapping[str, str] | None = None) -> str | None:
        env_map = env or os.environ
        if (env_map.get("GOOGLE_API_KEY") or "").strip():
            return "google_ai_studio"
        if (env_map.get("OPENAI_API_KEY") or "").strip():
            return "openai"
        if (env_map.get("GITHUB_TOKEN") or "").strip():
            return "github_copilot"
        if (env_map.get("OLLAMA_API_KEY") or "").strip():
            return "ollama"
        return None

    def resolved(self, env: Mapping[str, str] | None = None) -> "LLMConfig":
        detected = self.detect_provider(env)
        target_provider = detected or self.provider
        selected = self.provider_settings.get(target_provider)
        if not selected:
            return self
        return self.model_copy(update={
            "provider": target_provider,
            "model": selected.model,
            "api_base": selected.api_base,
            "api_key_env": selected.api_key_env,
            "max_tokens": selected.max_tokens,
            "temperature": selected.temperature,
        })


class LLMProviderSettings(BaseModel):
    model: str
    api_base: str
    api_key_env: str
    max_tokens: int = 4096
    temperature: float = 0.8


class NarratorConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    data_dir: str = "./data"
    system_prompt: str = (
        "You are the Narrator for a Marvel Multiverse Role-Playing Game campaign. "
        "You create immersive, story-driven experiences drawing on Marvel lore. "
        "You enforce the MMRPG rules, adjudicate dice rolls, voice NPCs with distinct "
        "personalities, and guide the heroes through thrilling adventures. "
        "Maintain continuity with the campaign log and character sheets provided to you."
    )
    extra_prompts: dict[str, str] = Field(default_factory=dict)
    # Max total characters of PDF source material text injected per session.
    # Set to 0 to disable injection.
    max_source_chars: int = 20_000
