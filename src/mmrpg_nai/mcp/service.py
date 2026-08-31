"""FastAPI-based MCP (Model Context Protocol) service.

Exposes MMRPG data as REST endpoints that can be consumed by other tools
(e.g., VS Code extensions, custom front-ends, automation scripts).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mmrpg_nai.models.core import (
    Adventure,
    Campaign,
    Character,
    Equipment,
    NarratorConfig,
    PowerSet,
    Session,
    SourceMaterial,
)
from mmrpg_nai.storage.store import Store

app = FastAPI(
    title="MMRPG Narrator AI – MCP Service",
    description=(
        "Model Context Protocol service for Marvel Multiverse RPG Narrator AI. "
        "Provides CRUD access to campaigns, sessions, characters, equipment, "
        "power sets, adventures, and source materials."
    ),
    version="0.1.0",
)

_store: Store | None = None


def get_store() -> Store:
    if _store is None:
        raise RuntimeError("Store not initialised – call init_app() first.")
    return _store


def init_app(data_dir: str | Path) -> None:
    """Wire the FastAPI app to the data store at *data_dir*."""
    global _store
    _store = Store(data_dir)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@app.get("/campaigns", response_model=list[Campaign], tags=["campaigns"])
def list_campaigns() -> list[Campaign]:
    return get_store().campaigns.list_all()


@app.get("/campaigns/{id}", response_model=Campaign, tags=["campaigns"])
def get_campaign(id: str) -> Campaign:
    obj = get_store().campaigns.load(id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return obj


@app.post("/campaigns", response_model=Campaign, status_code=201, tags=["campaigns"])
def create_campaign(campaign: Campaign) -> Campaign:
    return get_store().campaigns.save(campaign)


@app.put("/campaigns/{id}", response_model=Campaign, tags=["campaigns"])
def update_campaign(id: str, campaign: Campaign) -> Campaign:
    campaign = campaign.model_copy(update={"id": id})
    return get_store().campaigns.save(campaign)


@app.delete("/campaigns/{id}", tags=["campaigns"])
def delete_campaign(id: str) -> dict[str, bool]:
    return {"deleted": get_store().campaigns.delete(id)}


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@app.get("/sessions", response_model=list[Session], tags=["sessions"])
def list_sessions(campaign_id: str | None = None) -> list[Session]:
    store = get_store()
    if campaign_id:
        return store.sessions.find(campaign_id=campaign_id)
    return store.sessions.list_all()


@app.get("/sessions/{id}", response_model=Session, tags=["sessions"])
def get_session(id: str) -> Session:
    obj = get_store().sessions.load(id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return obj


@app.post("/sessions", response_model=Session, status_code=201, tags=["sessions"])
def create_session(session: Session) -> Session:
    return get_store().sessions.save(session)


@app.put("/sessions/{id}", response_model=Session, tags=["sessions"])
def update_session(id: str, session: Session) -> Session:
    session = session.model_copy(update={"id": id})
    return get_store().sessions.save(session)


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


@app.get("/characters", response_model=list[Character], tags=["characters"])
def list_characters(is_npc: bool | None = None) -> list[Character]:
    store = get_store()
    if is_npc is not None:
        return store.characters.find(is_npc=is_npc)
    return store.characters.list_all()


@app.get("/characters/{id}", response_model=Character, tags=["characters"])
def get_character(id: str) -> Character:
    obj = get_store().characters.load(id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Character not found")
    return obj


@app.post("/characters", response_model=Character, status_code=201, tags=["characters"])
def create_character(character: Character) -> Character:
    return get_store().characters.save(character)


@app.put("/characters/{id}", response_model=Character, tags=["characters"])
def update_character(id: str, character: Character) -> Character:
    character = character.model_copy(update={"id": id})
    return get_store().characters.save(character)


@app.delete("/characters/{id}", tags=["characters"])
def delete_character(id: str) -> dict[str, bool]:
    return {"deleted": get_store().characters.delete(id)}


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------


@app.get("/equipment", response_model=list[Equipment], tags=["equipment"])
def list_equipment() -> list[Equipment]:
    return get_store().equipment.list_all()


@app.get("/equipment/{id}", response_model=Equipment, tags=["equipment"])
def get_equipment(id: str) -> Equipment:
    obj = get_store().equipment.load(id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return obj


@app.post("/equipment", response_model=Equipment, status_code=201, tags=["equipment"])
def create_equipment(equipment: Equipment) -> Equipment:
    return get_store().equipment.save(equipment)


@app.put("/equipment/{id}", response_model=Equipment, tags=["equipment"])
def update_equipment(id: str, equipment: Equipment) -> Equipment:
    equipment = equipment.model_copy(update={"id": id})
    return get_store().equipment.save(equipment)


@app.delete("/equipment/{id}", tags=["equipment"])
def delete_equipment(id: str) -> dict[str, bool]:
    return {"deleted": get_store().equipment.delete(id)}


# ---------------------------------------------------------------------------
# Power Sets
# ---------------------------------------------------------------------------


@app.get("/power-sets", response_model=list[PowerSet], tags=["power_sets"])
def list_power_sets() -> list[PowerSet]:
    return get_store().power_sets.list_all()


@app.get("/power-sets/{id}", response_model=PowerSet, tags=["power_sets"])
def get_power_set(id: str) -> PowerSet:
    obj = get_store().power_sets.load(id)
    if obj is None:
        raise HTTPException(status_code=404, detail="PowerSet not found")
    return obj


@app.post("/power-sets", response_model=PowerSet, status_code=201, tags=["power_sets"])
def create_power_set(power_set: PowerSet) -> PowerSet:
    return get_store().power_sets.save(power_set)


@app.put("/power-sets/{id}", response_model=PowerSet, tags=["power_sets"])
def update_power_set(id: str, power_set: PowerSet) -> PowerSet:
    power_set = power_set.model_copy(update={"id": id})
    return get_store().power_sets.save(power_set)


@app.delete("/power-sets/{id}", tags=["power_sets"])
def delete_power_set(id: str) -> dict[str, bool]:
    return {"deleted": get_store().power_sets.delete(id)}


# ---------------------------------------------------------------------------
# Adventures
# ---------------------------------------------------------------------------


@app.get("/adventures", response_model=list[Adventure], tags=["adventures"])
def list_adventures() -> list[Adventure]:
    return get_store().adventures.list_all()


@app.get("/adventures/{id}", response_model=Adventure, tags=["adventures"])
def get_adventure(id: str) -> Adventure:
    obj = get_store().adventures.load(id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Adventure not found")
    return obj


@app.post("/adventures", response_model=Adventure, status_code=201, tags=["adventures"])
def create_adventure(adventure: Adventure) -> Adventure:
    return get_store().adventures.save(adventure)


# ---------------------------------------------------------------------------
# Source Materials
# ---------------------------------------------------------------------------


@app.get("/source-materials", response_model=list[SourceMaterial], tags=["source_materials"])
def list_source_materials() -> list[SourceMaterial]:
    return get_store().source_materials.list_all()


@app.get("/source-materials/{id}", response_model=SourceMaterial, tags=["source_materials"])
def get_source_material(id: str) -> SourceMaterial:
    obj = get_store().source_materials.load(id)
    if obj is None:
        raise HTTPException(status_code=404, detail="SourceMaterial not found")
    return obj


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@app.get("/config", response_model=NarratorConfig, tags=["config"])
def get_config() -> NarratorConfig:
    return get_store().load_config()


@app.put("/config", response_model=NarratorConfig, tags=["config"])
def update_config(cfg: NarratorConfig) -> NarratorConfig:
    return get_store().save_config(cfg)
