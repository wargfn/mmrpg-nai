# mmrpg-nai
Marvel Multiverse Role-Playing Game Narrator AI Tools

## Overview

`mmrpg-nai` is an AI-powered Narrator assistant for the **Marvel Multiverse Role-Playing Game (MMRPG)**.  
It uses the **GitHub Copilot GPT-5.4** language model (configurable) to help you plan campaigns, run interactive sessions, manage characters and equipment, import adventures, and more — all from your terminal.

## Features

| Feature | Description |
|---|---|
| **AI Campaign Planning** | Generate detailed campaign plans from a brief description |
| **Interactive Sessions** | Run fully narrated sessions from the command line |
| **Out-of-Game Meta Directions** | Use `[square brackets]` during a session to send GM-level instructions to the AI |
| **Session Recap** | AI generates a "Previously on…" recap at the start of each session |
| **Session Logs** | Persistent, append-only logs for every session |
| **Character Stat-Blocks** | Store and manage custom player characters and NPCs |
| **Equipment Store** | Catalogue weapons, armour, gadgets and vehicles |
| **Power Sets** | Manage Marvel Multiverse power sets with individual powers |
| **Adventure Templates** | Import/export adventures from a standard JSON template |
| **PDF Source Materials** | Ingest rulebooks, bestiaries, and supplements as AI context |
| **MCP REST Service** | FastAPI service exposing all data to other tools |
| **Settings & Prompts** | Configure LLM settings, system prompts, and extra named prompts |

## Requirements

- Python 3.11+
- A **GitHub personal access token** with the `models` permission
- Optional: `pymupdf` for PDF ingestion (included in requirements)

## Installation

```bash
git clone https://github.com/wargfn/mmrpg-nai.git
cd mmrpg-nai
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Configuration

```bash
cp .env.example .env
# Edit .env and set GITHUB_TOKEN
export $(grep -v '^#' .env | xargs)
```

## Quick Start

```bash
# 1. Create a campaign
mmrpg-nai campaign create

# 2. Start a session (prompts for campaign + characters)
mmrpg-nai session run

# 3. View the log afterwards
mmrpg-nai session log <session-id>
```

---

## CLI Reference

```
mmrpg-nai [--help]

Commands:
  config     Manage narrator configuration
  campaign   Manage campaigns
  session    Manage and run sessions
  character  Manage characters and stat-blocks
  equipment  Manage equipment
  powerset   Manage power sets
  adventure  Manage adventure templates
  pdf        Manage PDF source materials
  serve      Start the MCP REST service
```

All commands accept `--data-dir <path>` (or env var `MMRPG_DATA_DIR`) to point at a
custom data directory (default: `./data`).

---

### `mmrpg-nai config` — Narrator configuration

#### `config show`
Print the full current configuration as JSON.
```bash
mmrpg-nai config show
```

#### `config set <key> <value>`
Set any configuration value using dot-notation.
```bash
mmrpg-nai config set llm.model gpt-4o
mmrpg-nai config set llm.temperature 0.9
mmrpg-nai config set llm.max_tokens 8192
mmrpg-nai config set llm.api_base https://models.inference.ai.azure.com
```

#### `config system-prompt`
View or replace the main narrator system prompt.
```bash
# View the current system prompt
mmrpg-nai config system-prompt

# Replace it with the contents of a text file
mmrpg-nai config system-prompt --prompt-file my_prompt.txt
```

#### `config models`
Query the GitHub Models endpoint and print a table of all available model IDs.
The currently active model is highlighted with ✓.
```bash
# List all models
mmrpg-nai config models

# Filter results (case-insensitive substring match)
mmrpg-nai config models --filter gpt
mmrpg-nai config models -f llama
```

---

### `mmrpg-nai campaign` — Campaigns

#### `campaign list`
List all saved campaigns.
```bash
mmrpg-nai campaign list
```

#### `campaign create`
Interactively create a new campaign (prompts for name, description, tone, location).
```bash
mmrpg-nai campaign create
```

#### `campaign plan <campaign-id>`
Use the AI to draft a full campaign plan (hooks, NPCs, locations, progression).
```bash
mmrpg-nai campaign plan <campaign-id>
# --brief "A Hydra sleeper agent has infiltrated the X-Men"
```

---

### `mmrpg-nai session` — Sessions

#### `session list`
List sessions, optionally filtered by campaign.
```bash
mmrpg-nai session list
mmrpg-nai session list --campaign-id <campaign-id>
```

#### `session create`
Create a new session record (without running it).
```bash
mmrpg-nai session create
# prompts for campaign ID and session title
```

#### `session run`
Start an interactive narration session. Prompts you to pick a campaign and characters,
then generates an AI recap of the previous session before play begins.

```bash
mmrpg-nai session run

# Resume a specific session by ID (skips startup prompts)
mmrpg-nai session run --session-id <session-id>

# Disable streaming (collect full response before printing)
mmrpg-nai session run --no-stream
```

**During a session:**

| Input | Effect |
|---|---|
| Any text | Sent to the Narrator as in-world player action/dialogue |
| `[square brackets]` | Out-of-game **meta direction** — adjusts the scene without being part of the story |
| `quit` / `exit` / `q` | End the session and save the log |

**Meta direction examples:**
```
[make the villain more menacing]
[skip ahead to the confrontation with Red Skull]
[add a surprise twist — one of the NPCs is a Skrull]
[tone down the violence — there are kids watching]
```

#### `session log <session-id>`
Print the full conversation log for a session.
```bash
mmrpg-nai session log <session-id>
```
Meta entries are shown in yellow, narrator in blue, player in green.

---

### `mmrpg-nai character` — Characters & stat-blocks

#### `character list`
List all characters.
```bash
mmrpg-nai character list

# Filter to player characters only
mmrpg-nai character list --no-npc

# Filter to NPCs only
mmrpg-nai character list --npc
```

#### `character import <file>`
Import a character from a JSON stat-block file.
```bash
mmrpg-nai character import spider_man.json
```

#### `character show <character-id>`
Print the full stat-block for a character as JSON.
```bash
mmrpg-nai character show <character-id>
```

**Character JSON format:**
```json
{
  "name": "Spider-Man",
  "alias": "Peter Parker",
  "rank": "veteran",
  "tier": 2,
  "is_npc": false,
  "background": "Bitten by a radioactive spider at Oscorp.",
  "traits": ["Friendly Neighborhood Hero"],
  "abilities": {
    "melee":      { "score": 4, "edge": 1 },
    "agility":    { "score": 6, "edge": 2 },
    "resilience": { "score": 4, "edge": 0 },
    "vigilance":  { "score": 4, "edge": 1 },
    "ego":        { "score": 3, "edge": 0 },
    "logic":      { "score": 4, "edge": 1 }
  },
  "health": 8,
  "focus": 6,
  "karma": 5
}
```

---

### `mmrpg-nai equipment` — Equipment

#### `equipment list`
List all equipment items.
```bash
mmrpg-nai equipment list
```

#### `equipment import <file>`
Import one or a list of equipment items from a JSON file.
```bash
mmrpg-nai equipment import web_shooters.json
mmrpg-nai equipment import avengers_arsenal.json  # array of items
```

**Equipment JSON format:**
```json
{
  "name": "Web-Shooters",
  "equipment_type": "gadget",
  "description": "Wrist-mounted devices that fire synthetic webbing.",
  "damage_dice": "3d6",
  "properties": { "range": "Close" },
  "source": "Core Rulebook",
  "tags": ["spider-man", "ranged"]
}
```
Valid `equipment_type` values: `weapon`, `armor`, `gadget`, `vehicle`, `consumable`, `other`.

---

### `mmrpg-nai powerset` — Power sets

#### `powerset list`
List all power sets.
```bash
mmrpg-nai powerset list
```

#### `powerset import <file>`
Import a power set from a JSON file.
```bash
mmrpg-nai powerset import spider_powers.json
```

**Power Set JSON format:**
```json
{
  "name": "Spider Powers",
  "description": "Abilities gained from a radioactive spider bite.",
  "origin": "Mutation",
  "powers": [
    { "name": "Wall Crawling",   "description": "Cling to any surface.", "cost": 1 },
    { "name": "Spider-Sense",    "description": "Danger precognition.",  "cost": 2 },
    { "name": "Web-Slinging",    "description": "Swing between buildings.", "cost": 2 }
  ],
  "tags": ["spider-man", "mutation"]
}
```

---

### `mmrpg-nai adventure` — Adventure templates

#### `adventure list`
List all imported adventures.
```bash
mmrpg-nai adventure list
```

#### `adventure import <file>`
Import an adventure from a JSON template file.
```bash
mmrpg-nai adventure import crisis_at_avengers_tower.json
```

#### `adventure template [output]`
Export the standard adventure template schema as an example JSON file.
```bash
mmrpg-nai adventure template                         # writes adventure_template.json
mmrpg-nai adventure template my_adventure.json       # custom output path
```

**Adventure template format:**
```json
{
  "title": "Crisis at Avengers Tower",
  "synopsis": "A mysterious energy pulse disables Avengers Tower…",
  "recommended_rank": "veteran",
  "recommended_tier": 2,
  "acts": [
    [
      {
        "title": "The Alert",
        "description": "JARVIS sounds the alarm…",
        "encounter_type": "investigation",
        "enemies": [],
        "objectives": ["Investigate the energy readings"],
        "rewards": [],
        "notes": ""
      }
    ]
  ],
  "locations": ["Avengers Tower", "New York City"],
  "npcs": ["Tony Stark", "Nick Fury"],
  "tags": ["avengers", "tech-villain"],
  "source": "Custom"
}
```
Valid `recommended_rank` values: `basic`, `rookie`, `veteran`, `champion`, `master`, `legendary`.

---

### `mmrpg-nai pdf` — PDF source materials

#### `pdf ingest <file>`
Extract text from a PDF and register it as a source material for AI context.
```bash
mmrpg-nai pdf ingest mmrpg_core_rulebook.pdf \
  --title "MMRPG Core Rulebook" \
  --categories "rules,combat" \
  --description "Official core rules"
```

Options:

| Option | Default | Description |
|---|---|---|
| `--title` | (prompted) | Display name for the material |
| `--categories` | `rules` | Comma-separated category tags |
| `--description` | `` | Short description |

#### `pdf list`
List all registered source materials.
```bash
mmrpg-nai pdf list
```

---

### `mmrpg-nai serve` — MCP REST service

Start the FastAPI-based Model Context Protocol service so other tools can read
and write all game data via HTTP.

```bash
mmrpg-nai serve

# Custom host/port
mmrpg-nai serve --host 0.0.0.0 --port 9000
```

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Bind host |
| `--port` | `8000` | Bind port |

**API docs:** `http://127.0.0.1:8000/docs` (Swagger UI)

**Available endpoints:**

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET/POST | `/campaigns` | List / create campaigns |
| GET/PUT/DELETE | `/campaigns/{id}` | Get / update / delete a campaign |
| GET/POST | `/sessions` | List / create sessions |
| GET/PUT | `/sessions/{id}` | Get / update a session |
| GET/POST | `/characters` | List / create characters |
| GET/PUT/DELETE | `/characters/{id}` | Get / update / delete a character |
| GET/POST | `/equipment` | List / create equipment |
| GET/PUT/DELETE | `/equipment/{id}` | Get / update / delete equipment |
| GET/POST | `/power-sets` | List / create power sets |
| GET/PUT/DELETE | `/power-sets/{id}` | Get / update / delete a power set |
| GET/POST | `/adventures` | List / create adventures |
| GET | `/adventures/{id}` | Get an adventure |
| GET | `/source-materials` | List source materials |
| GET | `/source-materials/{id}` | Get a source material |
| GET/PUT | `/config` | Get / update narrator config |

---

## Data Storage

All data is stored as JSON files under `./data/` (configurable via `MMRPG_DATA_DIR`):

```
data/
  config.json          ← narrator settings & system prompt
  campaigns/           ← one JSON file per campaign
  sessions/            ← one JSON file per session (includes full log)
  characters/          ← one JSON file per character
  equipment/           ← one JSON file per equipment item
  power_sets/          ← one JSON file per power set
  adventures/          ← one JSON file per adventure
  source_materials/    ← metadata JSON + extracted .txt per PDF
```

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## LLM Configuration

Default model: **GPT-5.4** via `https://models.inference.ai.azure.com` (GitHub Models).

```bash
# See all available models (requires GITHUB_TOKEN)
mmrpg-nai config models

# Switch model
mmrpg-nai config set llm.model gpt-4o

# Tune generation
mmrpg-nai config set llm.temperature 0.7
mmrpg-nai config set llm.max_tokens 4096
```

### Extra named prompts

Inject additional named sections into every system prompt without replacing the main one:

```bash
mmrpg-nai config show   # view current config
```

Edit `data/config.json` and add to `extra_prompts`:

```json
{
  "extra_prompts": {
    "House Rules": "We use the optional Karma bonus rules from page 42.",
    "Tone": "This campaign is grittier than standard Marvel comics — consequences are real."
  }
}
```
