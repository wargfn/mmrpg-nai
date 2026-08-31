"""Pydantic models for characters, equipment, power sets, campaigns and sessions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

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


class Abilities(BaseModel):
    melee: AbilityScore = Field(default_factory=AbilityScore)
    agility: AbilityScore = Field(default_factory=AbilityScore)
    resilience: AbilityScore = Field(default_factory=AbilityScore)
    vigilance: AbilityScore = Field(default_factory=AbilityScore)
    ego: AbilityScore = Field(default_factory=AbilityScore)
    logic: AbilityScore = Field(default_factory=AbilityScore)


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
    health: int = 10
    focus: int = 10
    karma: int = 0
    traits: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    power_sets: list[str] = Field(default_factory=list, description="Power set IDs")
    equipment: list[str] = Field(default_factory=list, description="Equipment IDs")
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
    settings: CampaignSettings = Field(default_factory=CampaignSettings)
    session_ids: list[str] = Field(default_factory=list)
    character_ids: list[str] = Field(default_factory=list)
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
