"""Tests for the MCP service."""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from mmrpg_nai.mcp.service import app, init_app
from mmrpg_nai.models.core import Campaign, Character


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
