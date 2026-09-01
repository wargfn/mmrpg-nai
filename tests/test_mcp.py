"""Tests for the MCP service."""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from mmrpg_nai.mcp import service
from mmrpg_nai.mcp.service import app, init_app
from mmrpg_nai.models.core import Campaign, Character, LogEntry


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    init_app(tmp_path)
    return TestClient(app)


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_campaign_crud(client: TestClient):
    payload = {"name": "Test Campaign", "description": "A test"}
    r = client.post("/campaigns", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test Campaign"
    cid = data["id"]

    r = client.get(f"/campaigns/{cid}")
    assert r.status_code == 200

    r = client.get("/campaigns")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.delete(f"/campaigns/{cid}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    r = client.get(f"/campaigns/{cid}")
    assert r.status_code == 404


def test_character_crud(client: TestClient):
    char = {"name": "Thor", "alias": "God of Thunder"}
    r = client.post("/characters", json=char)
    assert r.status_code == 201
    cid = r.json()["id"]

    r = client.get(f"/characters/{cid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Thor"


def test_equipment_crud(client: TestClient):
    eq = {"name": "Mjolnir", "equipment_type": "weapon", "damage_dice": "8d6"}
    r = client.post("/equipment", json=eq)
    assert r.status_code == 201

    r = client.get("/equipment")
    assert len(r.json()) == 1


def test_power_set_crud(client: TestClient):
    ps = {"name": "Asgardian Powers", "description": "Divine Asgardian abilities"}
    r = client.post("/power-sets", json=ps)
    assert r.status_code == 201

    r = client.get("/power-sets")
    assert len(r.json()) == 1


def test_config_get_put(client: TestClient):
    r = client.get("/config")
    assert r.status_code == 200
    cfg = r.json()
    cfg["system_prompt"] = "Custom test prompt"
    r = client.put("/config", json=cfg)
    assert r.status_code == 200
    assert r.json()["system_prompt"] == "Custom test prompt"


def test_web_index(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "MMRPG Narrator Web" in r.text


def test_web_bootstrap(client: TestClient):
    client.post("/campaigns", json={"name": "Web Campaign", "description": "Demo"})
    r = client.get("/web/bootstrap")
    assert r.status_code == 200
    data = r.json()
    assert len(data["campaigns"]) == 1
    assert "sessions" in data
    assert "characters" in data


def test_web_start_and_chat(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    class DummyNarrator:
        def __init__(self, cfg, store):
            self.store = store
            self.session = None

        def start_session(self, session, campaign, party, source_materials=None):
            self.session = session

        def recap_last_session(self, last_session):
            return "Last time on MMRPG..."

        def narrate(self, player_input: str, stream: bool = False):
            self.session.log.append(LogEntry(role="player", content=player_input))
            out = f"Narrated: {player_input}"
            self.session.log.append(LogEntry(role="narrator", content=out))
            self.store.sessions.save(self.session)
            return out

        def meta_direction(self, direction: str, stream: bool = False):
            self.session.log.append(LogEntry(role="meta", content=direction))
            out = f"Meta handled: {direction}"
            self.session.log.append(LogEntry(role="narrator", content=out))
            self.store.sessions.save(self.session)
            return out

    monkeypatch.setattr(service, "Narrator", DummyNarrator)

    campaign = client.post("/campaigns", json={"name": "Campaign 1", "description": "D"}).json()
    character = client.post("/characters", json={"name": "Hero", "alias": "H"}).json()

    r = client.post(
        "/web/session/start",
        json={"campaign_id": campaign["id"], "participant_ids": [character["id"]], "title": "Web Session"},
    )
    assert r.status_code == 200
    started = r.json()
    session_id = started["session"]["id"]
    assert started["campaign"]["id"] == campaign["id"]

    r = client.post(f"/web/session/{session_id}/chat", json={"message": "I investigate the room."})
    assert r.status_code == 200
    assert r.json()["response"] == "Narrated: I investigate the room."
    assert r.json()["mode"] == "narrate"

    r = client.post(f"/web/session/{session_id}/chat", json={"message": "[raise the tension]"})
    assert r.status_code == 200
    assert r.json()["response"] == "Meta handled: raise the tension"
    assert r.json()["mode"] == "meta"
