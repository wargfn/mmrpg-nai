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
| **Session Logs** | Persistent, append-only logs for every session — automatically linked to their campaign |
| **Character Stat-Blocks** | Store and manage custom player characters and NPCs |
| **Enemy Roster** | Save villain/antagonist stat-blocks to a campaign for quick reuse |
| **Equipment Store** | Catalogue weapons, armour, gadgets and vehicles |
| **Power Sets** | Manage Marvel Multiverse power sets with individual powers |
| **Adventure Templates** | Import/export adventures from a standard JSON template |
| **PDF Source Materials** | Ingest rulebooks, bestiaries, and supplements as AI context — injected automatically each session |
| **MCP REST Service** | FastAPI service exposing all data to other tools |
| **Web Front End** | Browser UI for browsing campaigns/sessions and running chat sessions |
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

# 2. (Optional) Ingest a rulebook PDF and link it to your campaign
mmrpg-nai pdf ingest "MMRPG_Core_Rulebook.pdf" --title "Core Rulebook" --categories "rules,combat"
mmrpg-nai pdf list                                    # copy the source material ID
mmrpg-nai campaign add-source <campaign-id> <source-id>

# 3. (Optional) Add enemy stat-blocks to the campaign roster
mmrpg-nai character import doctor_doom.json           # import or create villain
mmrpg-nai campaign add-enemy <campaign-id> <character-id>

# 4. Start a session (prompts for campaign + characters)
mmrpg-nai session run

# 5. View the log afterwards
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
# LLM settings
mmrpg-nai config set llm.model gpt-4o
mmrpg-nai config set llm.temperature 0.9
mmrpg-nai config set llm.max_tokens 8192
mmrpg-nai config set llm.api_base https://api.githubcopilot.com

# Narrator settings
mmrpg-nai config set max_source_chars 40000   # max PDF text injected per session (0 = disabled)
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
Query the GitHub Copilot API endpoint and print a table of all available model IDs.
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
The plan is **saved to the campaign record** and can be viewed any time with `campaign show`.
```bash
mmrpg-nai campaign plan <campaign-id>
# --brief "A Hydra sleeper agent has infiltrated the X-Men"
```

#### `campaign show <campaign-id>`
Display full campaign details and the saved AI plan.
```bash
mmrpg-nai campaign show <campaign-id>
```

#### `campaign add-source <campaign-id> <source-id>`
Link an ingested PDF source material to a campaign so its text is injected into every session.
```bash
# First, check the source material ID
mmrpg-nai pdf list

# Then link it
mmrpg-nai campaign add-source <campaign-id> <source-material-id>
```

#### `campaign remove-source <campaign-id> <source-id>`
Unlink a source material from a campaign.
```bash
mmrpg-nai campaign remove-source <campaign-id> <source-material-id>
```

#### `campaign add-enemy <campaign-id> <character-id>`
Add an enemy/antagonist stat-block to the campaign's enemy roster.
The character must already exist (import a JSON stat-block with `character import`).
```bash
# Import the villain character first
mmrpg-nai character import ./doctor_doom.json

# Then add to campaign roster
mmrpg-nai campaign add-enemy <campaign-id> <character-id>
```

#### `campaign remove-enemy <campaign-id> <character-id>`
Remove an enemy from the campaign's enemy roster.
```bash
mmrpg-nai campaign remove-enemy <campaign-id> <character-id>
```

#### `campaign enemies <campaign-id>`
List all enemies/antagonists saved to a campaign's roster.
```bash
mmrpg-nai campaign enemies <campaign-id>
```

#### `campaign add-character <campaign-id> <character-id>`
Add a player character to the campaign's default character list.
This list is used as a fallback when a session has no explicit participants selected.
```bash
mmrpg-nai campaign add-character <campaign-id> <character-id>
```

#### `campaign remove-character <campaign-id> <character-id>`
Remove a character from the campaign's default character list.
```bash
mmrpg-nai campaign remove-character <campaign-id> <character-id>
```

#### `campaign characters <campaign-id>`
List all player characters in a campaign's default character list.
```bash
mmrpg-nai campaign characters <campaign-id>
```

#### `campaign add-user <campaign-id> <user-id>`
Add a user/player to a campaign.
```bash
mmrpg-nai campaign add-user <campaign-id> <user-id>
```

#### `campaign remove-user <campaign-id> <user-id>`
Remove a user/player from a campaign.
```bash
mmrpg-nai campaign remove-user <campaign-id> <user-id>
```

#### `campaign users <campaign-id>`
List users/players tracked in a campaign.
```bash
mmrpg-nai campaign users <campaign-id>
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

#### `session add-character <session-id> <character-id>`
Add a character as a participant in a specific session.
```bash
mmrpg-nai session add-character <session-id> <character-id>
```

#### `session remove-character <session-id> <character-id>`
Remove a character participant from a session.
```bash
mmrpg-nai session remove-character <session-id> <character-id>
```

#### `session add-user <session-id> <user-id>`
Add a user/player participant to a session.
```bash
mmrpg-nai session add-user <session-id> <user-id>
```

#### `session remove-user <session-id> <user-id>`
Remove a user/player participant from a session.
```bash
mmrpg-nai session remove-user <session-id> <user-id>
```

#### `session run`
Start an interactive narration session. Prompts you to pick a campaign and characters,
then generates an AI recap of the previous session before play begins.

At **session startup**, if the campaign has a plan and/or progress summary, they are
automatically injected into the Narrator's system prompt so the AI knows exactly where
the story stands and what comes next.

At **session end** (when you type `quit`/`exit`), if the campaign has a plan, the AI
automatically generates an updated campaign progress summary — recording which milestones
have been reached, the current story state, and unresolved threads — and saves it back to
the campaign. View it any time with `campaign show <id>`.

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

### `mmrpg-nai user` — Users / Players

#### `user list`
List users and show their last login timestamp (updated when they join a session).
```bash
mmrpg-nai user list
```

#### `user create`
Create a user/player record (`first_name` required; `last_name` and `email` optional).
```bash
mmrpg-nai user create
```

#### `user show <user-id>`
Show details for a user/player.
```bash
mmrpg-nai user show <user-id>
```

#### `user update <user-id>`
Update first/last name, email, or notes for a user/player.
```bash
mmrpg-nai user update <user-id> --first-name "New First Name"
```

#### `user delete <user-id>`
Delete a user/player.
```bash
mmrpg-nai user delete <user-id>
```

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

All fields are optional except `name`. Use the simple form or the extended form for any field.

```json
{
  "name": "Matthias",
  "alias": "Matthias",
  "rank": "rookie",
  "tier": 1,
  "is_npc": false,
  "background": "A mutant-associate trying to find his place in New York.",
  "traits": ["Combat Reflexes", "Connections:Outsiders", "Fresh Eyes", "Stranger"],
  "abilities": {
    "melee":      { "score": 1, "edge": 1, "defense_score": 11, "non-combat_checks": 2 },
    "agility":    { "score": 1, "edge": 1, "defense_score": 11, "non-combat_checks": 1 },
    "resilience": { "score": 1, "edge": 1, "defense_score": 11, "non-combat_checks": 1 },
    "vigilance":  { "score": 1, "edge": 1, "defense_score": 11, "non-combat_checks": 1 },
    "ego":        { "score": 0, "edge": 0, "defense_score": 10, "non-combat_checks": 0 },
    "logic":      { "score": 1, "edge": 1, "defense_score": 11, "non-combat_checks": 1 }
  },
  "powers": [
    "Attack Stance Standard",
    "Healing Factor 1 Health",
    "Mighty 1",
    "Sturdy 1"
  ],
  "health": { "score": 30, "damage_reduction": -1 },
  "focus":  { "score": 30, "damage_reduction": -1 },
  "karma": 5,
  "speed": { "run": 5, "climb": 3, "swim": 3, "jump": 3 },
  "initiative_mod": 1,
  "tags": ["hounded", "mutant-associate"],
  "equipment": ["baton"]
}
```

**Field reference:**

| Field | Type | Description |
|---|---|---|
| `rank` | string | `basic` `rookie` `veteran` `champion` `master` `legendary` |
| `tier` | int | Character tier (1–5) |
| `abilities.*` | object | Each ability has `score`, `edge`, optional `defense_score` (10+score+edge), `non-combat_checks` |
| `powers` | string array | Inline power/ability names (e.g. `"Mighty 1"`) |
| `power_sets` | string array | IDs of full `PowerSet` records (from `powerset import`) |
| `health` | int or `{"score": N, "damage_reduction": N}` | DR negative = extra damage taken |
| `focus` | int or `{"score": N, "damage_reduction": N}` | Same as health |
| `speed` | object | `run`, `climb`, `swim`, `jump` (squares per turn) |
| `initiative_mod` | int | Added to initiative rolls |
| `equipment` | string array | Inline item names or Equipment IDs |
| `is_npc` | bool | `true` for enemies/NPCs; `false` for player characters |

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

**Web front end:** `http://127.0.0.1:8000/`

**Available endpoints:**

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/` | Web front end |
| GET | `/web/bootstrap` | Campaign/session/character data for web UI |
| GET | `/web/active-sessions` | List currently active web chat sessions for attach workflows |
| POST | `/web/session/start` | Start a new chat session or create a resumed follow-up session from an existing one |
| GET | `/web/session/{id}` | Fetch current session state/log for multi-client sync |
| POST | `/web/session/{id}/chat` | Send chat or meta-direction message |
| POST | `/web/session/{id}/end` | Mark in-memory web chat session ended |
| GET/POST | `/users` | List / create users |
| GET/PUT/DELETE | `/users/{user_id}` | Get / update / delete a user |
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

Default model: **GPT-5.4** via `https://api.githubcopilot.com` (GitHub Copilot API).

```bash
# See all available models (requires GITHUB_TOKEN)
mmrpg-nai config models

# Switch model
mmrpg-nai config set llm.model gpt-4o

# Tune generation
mmrpg-nai config set llm.temperature 0.7
mmrpg-nai config set llm.max_tokens 4096
```

### Configuration reference

| Key | Default | Description |
|-----|---------|-------------|
| `llm.model` | `gpt-5.4` | Model ID from [GitHub Marketplace](https://github.com/marketplace/models) |
| `llm.api_base` | `https://api.githubcopilot.com` | API endpoint |
| `llm.api_key_env` | `GITHUB_TOKEN` | Environment variable holding the API key |
| `llm.temperature` | `0.8` | Sampling temperature (0 = deterministic, 1 = creative) |
| `llm.max_tokens` | `4096` | Maximum tokens in each LLM response |
| `system_prompt` | *(built-in)* | Main narrator system prompt (replace with `config system-prompt`) |
| `max_source_chars` | `20000` | Max characters of PDF source material injected per session; set to `0` to disable |
| `extra_prompts` | `{}` | Named extra prompt sections appended to every system prompt |

### Source material injection

When you link PDFs to a campaign, their extracted text is automatically injected into the
Narrator's system prompt at the start of every session under a `## Rules & Source Materials`
section.  This gives the AI access to rulebook text, enemy stat-blocks, and lore without
manual copy-pasting.

```bash
# 1. Ingest a PDF (one-time)
mmrpg-nai pdf ingest "MMRPG Core Rulebook.pdf" \
  --title "Core Rulebook" \
  --categories "rules,combat,powers"

# 2. Link it to your campaign using the ID shown by 'pdf list'
mmrpg-nai pdf list
mmrpg-nai campaign add-source <campaign-id> <source-material-id>

# 3. Control how much text is injected (default 20 000 chars ≈ 10-15 rulebook pages)
mmrpg-nai config set max_source_chars 40000

# 4. Disable injection entirely
mmrpg-nai config set max_source_chars 0
```

The startup panel shows which source materials are loaded for each session:
```
╭─ 🦸 MMRPG Narrator AI ──────────────────────────────╮
│ Session: Session 3 (#3)                              │
│ Campaign: Dark Avengers Arc                          │
│ Party: Spider-Man, Iron Man                          │
│ Source Materials: Core Rulebook, Antagonists Book    │
╰──────────────────────────────────────────────────────╯
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
