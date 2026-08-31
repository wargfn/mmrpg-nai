"""Tests for adventure importer."""

import json
import pytest
from pathlib import Path

from mmrpg_nai.adventure.importer import export_adventure, export_template_schema, import_adventure
from mmrpg_nai.models.core import Adventure, Rank, Scene
from mmrpg_nai.storage.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path)


@pytest.fixture
def sample_template(tmp_path: Path) -> Path:
    template = {
        "title": "Test Adventure",
        "synopsis": "A test adventure",
        "recommended_rank": "veteran",
        "recommended_tier": 2,
        "acts": [
            [
                {
                    "title": "Scene 1",
                    "description": "Intro scene",
                    "encounter_type": "social",
                    "enemies": [],
                    "objectives": ["Talk to Nick Fury"],
                    "rewards": [],
                    "notes": "",
                }
            ]
        ],
        "locations": ["SHIELD HQ"],
        "npcs": ["Nick Fury"],
        "tags": ["shield"],
        "source": "Custom",
    }
    p = tmp_path / "adventure.json"
    p.write_text(json.dumps(template), encoding="utf-8")
    return p


def test_import_adventure(store: Store, sample_template: Path):
    adv = import_adventure(sample_template, store)
    assert adv.title == "Test Adventure"
    assert adv.recommended_rank == Rank.VETERAN
    loaded = store.adventures.load(adv.id)
    assert loaded is not None


def test_export_adventure(tmp_path: Path, store: Store):
    adv = Adventure(title="Export Test", acts=[[Scene(title="S1", description="d")]])
    store.adventures.save(adv)
    out = tmp_path / "out.json"
    export_adventure(adv, out)
    data = json.loads(out.read_text())
    assert data["title"] == "Export Test"


def test_export_template_schema(tmp_path: Path):
    out = tmp_path / "schema.json"
    export_template_schema(out)
    data = json.loads(out.read_text())
    assert "title" in data
    assert "acts" in data
