"""Adventure template importer: load/export JSON adventure templates."""

from __future__ import annotations

import json
from pathlib import Path

from mmrpg_nai.models.core import Adventure
from mmrpg_nai.storage.store import Store

# ---------------------------------------------------------------------------
# Standard template schema (JSON)
# ---------------------------------------------------------------------------
# The standard adventure template is a plain JSON file whose top-level keys
# map directly onto the Adventure Pydantic model.  Any unknown keys are
# silently ignored so templates can include editor notes.

TEMPLATE_SCHEMA_EXAMPLE = {
    "title": "Crisis at Avengers Tower",
    "synopsis": "A mysterious energy pulse disables Avengers Tower...",
    "recommended_rank": "veteran",
    "recommended_tier": 2,
    "acts": [
        [
            {
                "title": "The Alert",
                "description": "JARVIS sounds the alarm...",
                "encounter_type": "investigation",
                "enemies": [],
                "objectives": ["Investigate the energy readings"],
                "rewards": [],
                "notes": "",
            }
        ]
    ],
    "locations": ["Avengers Tower", "New York City"],
    "npcs": ["Tony Stark", "Nick Fury"],
    "tags": ["avengers", "tech-villain"],
    "source": "Custom",
}


def import_adventure(
    file_path: str | Path,
    store: Store,
) -> Adventure:
    """Import an adventure from a JSON template file and persist it."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    adventure = Adventure.model_validate(raw)
    store.adventures.save(adventure)
    return adventure


def export_adventure(adventure: Adventure, output_path: str | Path) -> Path:
    """Export an adventure to a JSON template file."""
    path = Path(output_path).expanduser().resolve()
    path.write_text(adventure.model_dump_json(indent=2), encoding="utf-8")
    return path


def export_template_schema(output_path: str | Path) -> Path:
    """Write the template schema example to a file for reference."""
    path = Path(output_path).expanduser().resolve()
    path.write_text(json.dumps(TEMPLATE_SCHEMA_EXAMPLE, indent=2), encoding="utf-8")
    return path
