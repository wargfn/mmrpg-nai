"""FastAPI-based MCP (Model Context Protocol) service.

Exposes MMRPG data as REST endpoints that can be consumed by other tools
(e.g., VS Code extensions, custom front-ends, automation scripts).
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from mmrpg_nai.llm.narrator import Narrator
from mmrpg_nai.models.core import (
    Adventure,
    Campaign,
    Character,
    Equipment,
    LogEntry,
    NarratorConfig,
    PowerSet,
    Session,
    SourceMaterial,
    User,
)
from mmrpg_nai.storage.store import Store

app = FastAPI(
    title="MMRPG Narrator AI – MCP Service",
    description=(
        "Model Context Protocol service for Marvel Multiverse RPG Narrator AI. "
        "Provides REST access to campaigns, sessions, characters, equipment, "
        "power sets, adventures, and source materials."
    ),
    version="0.1.0",
)

_store: Store | None = None
_active_narrators: dict[str, Narrator] = {}
_active_narrators_lock = Lock()
_session_locks: dict[str, Lock] = {}
_session_create_lock = Lock()
_META_RE = re.compile(r"^\s*\[(.+)\]\s*$")
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


class WebParticipant(BaseModel):
    id: str
    name: str
    alias: str = ""


class WebSessionStartRequest(BaseModel):
    campaign_id: str | None = None
    session_id: str | None = None
    title: str | None = None
    participant_ids: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)


class WebSessionStartResponse(BaseModel):
    session: Session
    campaign: Campaign
    participants: list[WebParticipant]
    recap: str = ""


class WebChatRequest(BaseModel):
    message: str


class WebChatResponse(BaseModel):
    session_id: str
    response: str
    mode: str
    log: list[LogEntry]


class WebBootstrapResponse(BaseModel):
    campaigns: list[Campaign]
    sessions: list[Session]
    characters: list[Character]
    users: list[User]


class WebSessionStateResponse(BaseModel):
    session: Session
    campaign: Campaign
    participants: list[WebParticipant]
    users: list[User]
    is_active: bool


class UserWriteRequest(BaseModel):
    name: str
    email: str = ""
    notes: str = ""


def get_store() -> Store:
    if _store is None:
        raise RuntimeError("Store not initialised – call init_app() first.")
    return _store


def init_app(data_dir: str | Path) -> None:
    """Wire the FastAPI app to the data store at *data_dir*."""
    global _store
    _store = Store(data_dir)
    with _active_narrators_lock:
        _active_narrators.clear()
        _session_locks.clear()


def _get_session_lock(session_id: str) -> Lock:
    with _active_narrators_lock:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = Lock()
            _session_locks[session_id] = lock
        return lock


def _get_active_narrator(session_id: str) -> Narrator | None:
    with _active_narrators_lock:
        return _active_narrators.get(session_id)





def _load_participants(store: Store, campaign: Campaign, participant_ids: list[str]) -> list[Character]:
    ids = participant_ids or campaign.character_ids
    participants = [c for cid in ids if (c := store.characters.load(cid)) is not None]
    if participants:
        return participants
    return [c for c in store.characters.list_all() if not c.is_npc]


def _load_source_materials(store: Store, campaign: Campaign) -> list[SourceMaterial]:
    return [
        m
        for mid in campaign.source_material_ids
        if (m := store.source_materials.load(mid)) is not None
    ]


def _start_narrator(
    store: Store,
    cfg: NarratorConfig,
    session: Session,
    campaign: Campaign,
    participants: list[Character],
) -> tuple[Narrator, str]:
    narrator = Narrator(cfg, store)
    narrator.start_session(
        session,
        campaign,
        participants,
        source_materials=_load_source_materials(store, campaign),
    )
    with _active_narrators_lock:
        _active_narrators[session.id] = narrator
        _session_locks.setdefault(session.id, Lock())

    recap = ""
    previous_sessions = sorted(
        store.sessions.find(campaign_id=campaign.id),
        key=lambda s: (s.session_number, s.started_at),
    )
    previous = next((s for s in reversed(previous_sessions) if s.id != session.id), None)
    if previous:
        try:
            recap = narrator.recap_last_session(previous)
        except Exception:
            recap = ""
    return narrator, recap


def _as_web_participants(participants: list[Character]) -> list[WebParticipant]:
    return [WebParticipant(id=p.id, name=p.name, alias=p.alias) for p in participants]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse, tags=["web"])
def web_index(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(request=request, name="index.html")


@app.get("/web/bootstrap", response_model=WebBootstrapResponse, tags=["web"])
def web_bootstrap() -> WebBootstrapResponse:
    store = get_store()
    campaigns = store.campaigns.list_all()
    sessions = store.sessions.list_all()
    return WebBootstrapResponse(
        campaigns=campaigns,
        sessions=sessions,
        characters=[c for c in store.characters.list_all() if not c.is_npc],
        users=store.users.list_all(),
    )


@app.post("/web/session/start", response_model=WebSessionStartResponse, tags=["web"])
def web_session_start(req: WebSessionStartRequest) -> WebSessionStartResponse:
    store = get_store()
    cfg = store.load_config()

    if req.session_id:
        session = store.sessions.load(req.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        campaign = store.campaigns.load(session.campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")
        participants = _load_participants(store, campaign, session.participants)
        user_ids = session.user_ids or campaign.user_ids
        users = [u for uid in user_ids if (u := store.users.load(uid)) is not None]
        session.user_ids = [u.id for u in users]
        store.sessions.save(session)
        lock = _get_session_lock(session.id)
        with lock:
            narrator = _get_active_narrator(session.id)
            if narrator is None:
                _, recap = _start_narrator(store, cfg, session, campaign, participants)
            else:
                recap = ""
    else:
        if not req.campaign_id:
            raise HTTPException(status_code=400, detail="campaign_id is required when starting a new session")
        campaign = store.campaigns.load(req.campaign_id)
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaign not found")

        participants = _load_participants(store, campaign, req.participant_ids)
        chosen_user_ids = req.user_ids or campaign.user_ids
        users = [u for uid in chosen_user_ids if (u := store.users.load(uid)) is not None]
        user_ids = [u.id for u in users]
        with _session_create_lock:
            existing = store.sessions.find(campaign_id=campaign.id)
            next_session_number = len(existing) + 1
            session = Session(
                campaign_id=campaign.id,
                title=req.title or f"Session {next_session_number}",
                session_number=next_session_number,
                participants=[p.id for p in participants],
                user_ids=user_ids,
            )
            store.sessions.save(session)
            campaign.session_ids.append(session.id)
            for uid in user_ids:
                if uid not in campaign.user_ids:
                    campaign.user_ids.append(uid)
            store.campaigns.save(campaign)
        _, recap = _start_narrator(store, cfg, session, campaign, participants)
    store.touch_users_for_session(session.user_ids)
    return WebSessionStartResponse(
        session=session,
        campaign=campaign,
        participants=_as_web_participants(participants),
        recap=recap,
    )


@app.get("/web/session/{session_id}", response_model=WebSessionStateResponse, tags=["web"])
def web_session_state(session_id: str) -> WebSessionStateResponse:
    store = get_store()
    session = store.sessions.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    campaign = store.campaigns.load(session.campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    participants = _load_participants(store, campaign, session.participants)
    effective_user_ids = session.user_ids or campaign.user_ids
    users = [u for uid in effective_user_ids if (u := store.users.load(uid)) is not None]
    return WebSessionStateResponse(
        session=session,
        campaign=campaign,
        participants=_as_web_participants(participants),
        users=users,
        is_active=_get_active_narrator(session_id) is not None,
    )


@app.post("/web/session/{session_id}/chat", response_model=WebChatResponse, tags=["web"])
def web_session_chat(session_id: str, req: WebChatRequest) -> WebChatResponse:
    store = get_store()
    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    mode = "narrate"
    meta_match = _META_RE.match(text)
    lock = _get_session_lock(session_id)
    with lock:
        with _active_narrators_lock:
            narrator = _active_narrators.get(session_id)
        if narrator is None:
            raise HTTPException(status_code=404, detail="Session is not active; start or resume it first")

        try:
            if meta_match:
                mode = "meta"
                response = narrator.meta_direction(meta_match.group(1).strip(), stream=False)
            else:
                response = narrator.narrate(text, stream=False)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        session = store.sessions.load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
    return WebChatResponse(session_id=session_id, response=response, mode=mode, log=session.log)


@app.post("/web/session/{session_id}/end", tags=["web"])
def web_session_end(session_id: str) -> dict[str, bool]:
    lock = _get_session_lock(session_id)
    with lock:
        with _active_narrators_lock:
            ended = _active_narrators.pop(session_id, None) is not None
    return {"ended": ended}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@app.get("/users", response_model=list[User], tags=["users"])
def list_users() -> list[User]:
    return get_store().users.list_all()


@app.get("/users/{user_id}", response_model=User, tags=["users"])
def get_user(user_id: str) -> User:
    obj = get_store().users.load(user_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="User not found")
    return obj


@app.post("/users", response_model=User, status_code=201, tags=["users"])
def create_user(user: UserWriteRequest) -> User:
    new_user = User(name=user.name, email=user.email, notes=user.notes)
    return get_store().users.save(new_user)


@app.put("/users/{user_id}", response_model=User, tags=["users"])
def update_user(user_id: str, user: UserWriteRequest) -> User:
    store = get_store()
    existing = store.users.load(user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="User not found")
    existing.name = user.name
    existing.email = user.email
    existing.notes = user.notes
    existing.updated_at = datetime.now(timezone.utc)
    return store.users.save(existing)


@app.delete("/users/{user_id}", tags=["users"])
def delete_user(user_id: str) -> dict[str, bool]:
    return {"deleted": get_store().users.delete(user_id)}


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
