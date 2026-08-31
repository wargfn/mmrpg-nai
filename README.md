# mmrpg-nai
Marvel Multiverse Role-Playing Game Narrator AI Tools

## Overview

`mmrpg-nai` is an AI-powered Narrator assistant for the **Marvel Multiverse Role-Playing Game (MMRPG)**.  
It uses the **GitHub Copilot GPT-5.4** language model to help you plan campaigns, run interactive sessions, manage characters and equipment, import adventures, and more — all from your terminal.

## Features

| Feature | Description |
|---|---|
| **AI Campaign Planning** | Generate detailed campaign plans from a brief description |
| **Interactive Sessions** | Run fully narrated sessions from the command line |
| **Session Logs** | Persistent, append-only logs for every session |
| **Character Stat-Blocks** | Store and manage custom player characters and NPCs |
| **Equipment Store** | Catalogue weapons, armour, gadgets and vehicles |
| **Power Sets** | Manage Marvel Multiverse power sets with individual powers |
| **Adventure Templates** | Import adventures from a standard JSON template |
| **PDF Source Materials** | Ingest rulebooks, bestiaries, and supplements as AI context |
| **MCP REST Service** | FastAPI service exposing all data to other tools |
| **Settings & Prompts** | Configure LLM settings and custom system prompts |

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
mmrpg-nai campaign create
mmrpg-nai session create
mmrpg-nai session run <session-id>
mmrpg-nai session log <session-id>
```

## CLI Reference

```
Commands:
  campaign   Manage campaigns
  session    Manage and run sessions
  character  Manage characters and stat-blocks
  equipment  Manage equipment
  powerset   Manage power sets
  adventure  Manage adventure templates
  pdf        Manage PDF source materials
  config     Manage narrator configuration
  serve      Start the MCP REST service
```

## Adventure Template Format

Generate a schema example: `mmrpg-nai adventure template adventure_template.json`

## Data Storage

All data is stored as JSON files under `./data/` (configurable via `MMRPG_DATA_DIR`).

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## LLM Configuration

Default: GitHub Copilot GPT-5.4 via `https://models.inference.ai.azure.com`.  
Override any setting: `mmrpg-nai config set llm.model gpt-5.4`
