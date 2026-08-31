"""Main CLI entry point for the MMRPG Narrator AI."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from mmrpg_nai.adventure.importer import (
    export_template_schema,
    import_adventure,
)
from mmrpg_nai.models.core import (
    Campaign,
    CampaignSettings,
    Character,
    Equipment,
    EquipmentType,
    NarratorConfig,
    PowerSet,
    Rank,
    Session,
)
from mmrpg_nai.pdf.ingestion import ingest_pdf
from mmrpg_nai.storage.store import Store

app = typer.Typer(
    name="mmrpg-nai",
    help="Marvel Multiverse RPG AI Narrator Tools",
    no_args_is_help=True,
)
console = Console()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_store(data_dir: str) -> Store:
    return Store(data_dir)


def _default_data_dir() -> str:
    cfg_path = Path("./data/config.json")
    if cfg_path.exists():
        try:
            cfg = NarratorConfig.model_validate_json(cfg_path.read_text(encoding="utf-8"))
            return cfg.data_dir
        except Exception:
            pass
    return "./data"


# ---------------------------------------------------------------------------
# Config commands
# ---------------------------------------------------------------------------

config_app = typer.Typer(help="Manage narrator configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show(data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR")) -> None:
    """Show current configuration."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    console.print_json(cfg.model_dump_json(indent=2))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Dot-notation key, e.g. llm.model"),
    value: str = typer.Argument(..., help="New value"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Set a configuration value."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    data = cfg.model_dump()
    keys = key.split(".")
    target = data
    for k in keys[:-1]:
        if k not in target:
            console.print(f"[red]Unknown key: {key}[/red]")
            raise typer.Exit(1)
        target = target[k]
    target[keys[-1]] = value
    updated = NarratorConfig.model_validate(data)
    store.save_config(updated)
    console.print(f"[green]Set {key} = {value}[/green]")


@config_app.command("system-prompt")
def config_system_prompt(
    prompt_file: Optional[Path] = typer.Option(None, help="Path to a .txt file with the system prompt"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """View or update the system prompt."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    if prompt_file:
        cfg.system_prompt = prompt_file.read_text(encoding="utf-8")
        store.save_config(cfg)
        console.print("[green]System prompt updated.[/green]")
    else:
        console.print(Panel(cfg.system_prompt, title="System Prompt"))


# ---------------------------------------------------------------------------
# Campaign commands
# ---------------------------------------------------------------------------

campaign_app = typer.Typer(help="Manage campaigns.")
app.add_typer(campaign_app, name="campaign")


@campaign_app.command("list")
def campaign_list(data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR")) -> None:
    """List all campaigns."""
    store = _get_store(data_dir)
    campaigns = store.campaigns.list_all()
    if not campaigns:
        console.print("[yellow]No campaigns found.[/yellow]")
        return
    table = Table("ID", "Name", "Sessions", "Created")
    for c in campaigns:
        table.add_row(c.id[:8], c.name, str(len(c.session_ids)), c.created_at.strftime("%Y-%m-%d"))
    console.print(table)


@campaign_app.command("create")
def campaign_create(
    name: str = typer.Option(..., prompt=True),
    description: str = typer.Option("", prompt=True),
    tone: str = typer.Option("heroic", prompt=True),
    location: str = typer.Option("New York City", prompt=True),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Create a new campaign."""
    store = _get_store(data_dir)
    campaign = Campaign(
        name=name,
        description=description,
        settings=CampaignSettings(tone=tone, location=location),
    )
    store.campaigns.save(campaign)
    console.print(f"[green]Campaign created: {campaign.id}[/green]")


@campaign_app.command("plan")
def campaign_plan(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    brief: str = typer.Option(..., prompt=True, help="Brief description of the campaign"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Use AI to draft a campaign plan."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    campaign = store.campaigns.load(campaign_id)
    if campaign is None:
        console.print(f"[red]Campaign not found: {campaign_id}[/red]")
        raise typer.Exit(1)

    from mmrpg_nai.llm.narrator import Narrator

    narrator = Narrator(cfg, store)
    console.print("[bold blue]Generating campaign plan…[/bold blue]")
    plan = narrator.plan_campaign(brief)
    console.print(Markdown(plan))


# ---------------------------------------------------------------------------
# Session commands
# ---------------------------------------------------------------------------

session_app = typer.Typer(help="Manage and run sessions.")
app.add_typer(session_app, name="session")


@session_app.command("list")
def session_list(
    campaign_id: Optional[str] = typer.Option(None),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """List sessions."""
    store = _get_store(data_dir)
    sessions = store.sessions.find(campaign_id=campaign_id) if campaign_id else store.sessions.list_all()
    if not sessions:
        console.print("[yellow]No sessions found.[/yellow]")
        return
    table = Table("ID", "Campaign", "Title", "#", "Started")
    for s in sessions:
        table.add_row(s.id[:8], s.campaign_id[:8], s.title, str(s.session_number), s.started_at.strftime("%Y-%m-%d"))
    console.print(table)


@session_app.command("create")
def session_create(
    campaign_id: str = typer.Option(..., prompt=True),
    title: str = typer.Option(..., prompt=True),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Create a new session."""
    store = _get_store(data_dir)
    existing = store.sessions.find(campaign_id=campaign_id)
    session = Session(
        campaign_id=campaign_id,
        title=title,
        session_number=len(existing) + 1,
    )
    store.sessions.save(session)
    console.print(f"[green]Session created: {session.id}[/green]")


@session_app.command("run")
def session_run(
    session_id: str = typer.Argument(..., help="Session ID to run"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
    stream: bool = typer.Option(True, help="Stream responses"),
) -> None:
    """Run an interactive narration session from the command line."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    session = store.sessions.load(session_id)
    if session is None:
        console.print(f"[red]Session not found: {session_id}[/red]")
        raise typer.Exit(1)

    campaign = store.campaigns.load(session.campaign_id)
    if campaign is None:
        console.print(f"[red]Campaign not found: {session.campaign_id}[/red]")
        raise typer.Exit(1)

    party = [c for cid in campaign.character_ids if (c := store.characters.load(cid)) is not None]

    from mmrpg_nai.llm.narrator import Narrator

    narrator = Narrator(cfg, store)
    narrator.start_session(session, campaign, party)

    console.print(
        Panel(
            f"[bold]Session:[/bold] {session.title}  (#{session.session_number})\n"
            f"[bold]Campaign:[/bold] {campaign.name}",
            title="🦸 MMRPG Narrator AI",
        )
    )
    console.print("[dim]Type your action or dialogue. Enter 'quit' or 'exit' to end the session.[/dim]\n")

    while True:
        try:
            player_input = Prompt.ask("[bold green]You[/bold green]")
        except (EOFError, KeyboardInterrupt):
            break

        if player_input.strip().lower() in {"quit", "exit", "q"}:
            break

        if not player_input.strip():
            continue

        console.print()
        console.print("[bold blue]Narrator[/bold blue]")
        try:
            narrator.narrate(player_input, stream=stream)
        except Exception as exc:
            console.print(f"[red]Error: {exc}[/red]")
        console.print()

    session.ended_at = datetime.now(timezone.utc)
    store.sessions.save(session)
    console.print("[bold]Session ended. Log saved.[/bold]")


@session_app.command("log")
def session_log(
    session_id: str = typer.Argument(...),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Print the log for a session."""
    store = _get_store(data_dir)
    session = store.sessions.load(session_id)
    if session is None:
        console.print(f"[red]Session not found: {session_id}[/red]")
        raise typer.Exit(1)
    for entry in session.log:
        color = "blue" if entry.role == "narrator" else "green"
        ts = entry.timestamp.strftime("%H:%M:%S")
        console.print(f"[dim]{ts}[/dim] [bold {color}]{entry.role.capitalize()}[/bold {color}]: {entry.content}\n")


# ---------------------------------------------------------------------------
# Character commands
# ---------------------------------------------------------------------------

character_app = typer.Typer(help="Manage characters and stat-blocks.")
app.add_typer(character_app, name="character")


@character_app.command("list")
def character_list(
    npc: Optional[bool] = typer.Option(None, help="Filter NPCs (--npc / --no-npc)"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """List characters."""
    store = _get_store(data_dir)
    chars = store.characters.find(is_npc=npc) if npc is not None else store.characters.list_all()
    if not chars:
        console.print("[yellow]No characters found.[/yellow]")
        return
    table = Table("ID", "Name", "Alias", "Rank", "Tier", "NPC")
    for c in chars:
        table.add_row(c.id[:8], c.name, c.alias, c.rank.value, str(c.tier), str(c.is_npc))
    console.print(table)


@character_app.command("import")
def character_import(
    file: Path = typer.Argument(..., help="Path to a JSON character stat-block file"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Import a character from a JSON stat-block file."""
    store = _get_store(data_dir)
    char = Character.model_validate_json(file.read_text(encoding="utf-8"))
    store.characters.save(char)
    console.print(f"[green]Imported character: {char.name} ({char.id})[/green]")


@character_app.command("show")
def character_show(
    character_id: str = typer.Argument(...),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Show full character stat-block."""
    store = _get_store(data_dir)
    char = store.characters.load(character_id)
    if char is None:
        console.print(f"[red]Character not found: {character_id}[/red]")
        raise typer.Exit(1)
    console.print_json(char.model_dump_json(indent=2))


# ---------------------------------------------------------------------------
# Equipment commands
# ---------------------------------------------------------------------------

equipment_app = typer.Typer(help="Manage equipment.")
app.add_typer(equipment_app, name="equipment")


@equipment_app.command("list")
def equipment_list(data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR")) -> None:
    """List all equipment."""
    store = _get_store(data_dir)
    items = store.equipment.list_all()
    if not items:
        console.print("[yellow]No equipment found.[/yellow]")
        return
    table = Table("ID", "Name", "Type", "Damage", "Source")
    for eq in items:
        table.add_row(eq.id[:8], eq.name, eq.equipment_type.value, eq.damage_dice, eq.source)
    console.print(table)


@equipment_app.command("import")
def equipment_import(
    file: Path = typer.Argument(..., help="JSON file with equipment data"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Import equipment from a JSON file."""
    store = _get_store(data_dir)
    data = json.loads(file.read_text(encoding="utf-8"))
    if isinstance(data, list):
        for item in data:
            eq = Equipment.model_validate(item)
            store.equipment.save(eq)
        console.print(f"[green]Imported {len(data)} equipment items.[/green]")
    else:
        eq = Equipment.model_validate(data)
        store.equipment.save(eq)
        console.print(f"[green]Imported equipment: {eq.name}[/green]")


# ---------------------------------------------------------------------------
# Power Set commands
# ---------------------------------------------------------------------------

powerset_app = typer.Typer(help="Manage power sets.")
app.add_typer(powerset_app, name="powerset")


@powerset_app.command("list")
def powerset_list(data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR")) -> None:
    """List all power sets."""
    store = _get_store(data_dir)
    sets = store.power_sets.list_all()
    if not sets:
        console.print("[yellow]No power sets found.[/yellow]")
        return
    table = Table("ID", "Name", "Powers", "Origin")
    for ps in sets:
        table.add_row(ps.id[:8], ps.name, str(len(ps.powers)), ps.origin)
    console.print(table)


@powerset_app.command("import")
def powerset_import(
    file: Path = typer.Argument(..., help="JSON file with power set data"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Import a power set from a JSON file."""
    store = _get_store(data_dir)
    ps = PowerSet.model_validate_json(file.read_text(encoding="utf-8"))
    store.power_sets.save(ps)
    console.print(f"[green]Imported power set: {ps.name}[/green]")


# ---------------------------------------------------------------------------
# Adventure commands
# ---------------------------------------------------------------------------

adventure_app = typer.Typer(help="Manage adventure templates.")
app.add_typer(adventure_app, name="adventure")


@adventure_app.command("list")
def adventure_list(data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR")) -> None:
    """List all adventures."""
    store = _get_store(data_dir)
    adventures = store.adventures.list_all()
    if not adventures:
        console.print("[yellow]No adventures found.[/yellow]")
        return
    table = Table("ID", "Title", "Acts", "Rank")
    for a in adventures:
        table.add_row(a.id[:8], a.title, str(len(a.acts)), a.recommended_rank.value)
    console.print(table)


@adventure_app.command("import")
def adventure_import_cmd(
    file: Path = typer.Argument(..., help="Path to adventure JSON template"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Import an adventure from a JSON template."""
    store = _get_store(data_dir)
    adventure = import_adventure(file, store)
    console.print(f"[green]Imported adventure: {adventure.title} ({adventure.id})[/green]")


@adventure_app.command("template")
def adventure_template(
    output: Path = typer.Argument(Path("./adventure_template.json")),
) -> None:
    """Export an example adventure template to a file."""
    export_template_schema(output)
    console.print(f"[green]Template written to {output}[/green]")


# ---------------------------------------------------------------------------
# PDF / Source Material commands
# ---------------------------------------------------------------------------

pdf_app = typer.Typer(help="Manage PDF source materials.")
app.add_typer(pdf_app, name="pdf")


@pdf_app.command("ingest")
def pdf_ingest(
    file: Path = typer.Argument(..., help="Path to PDF file"),
    title: str = typer.Option(..., prompt=True),
    categories: str = typer.Option("rules", help="Comma-separated categories"),
    description: str = typer.Option("", help="Short description"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Ingest a PDF as source material (extracts text for AI context)."""
    store = _get_store(data_dir)
    cats = [c.strip() for c in categories.split(",") if c.strip()]
    material = ingest_pdf(file, title, cats, store, description)
    console.print(
        f"[green]Ingested '{material.title}' ({material.page_count} pages) → {material.extracted_text_path}[/green]"
    )


@pdf_app.command("list")
def pdf_list(data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR")) -> None:
    """List source materials."""
    store = _get_store(data_dir)
    materials = store.source_materials.list_all()
    if not materials:
        console.print("[yellow]No source materials found.[/yellow]")
        return
    table = Table("ID", "Title", "Pages", "Categories")
    for m in materials:
        table.add_row(m.id[:8], m.title, str(m.page_count), ", ".join(m.categories))
    console.print(table)


# ---------------------------------------------------------------------------
# MCP server command
# ---------------------------------------------------------------------------


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Start the MCP REST service."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn is required: pip install uvicorn[/red]")
        raise typer.Exit(1)

    from mmrpg_nai.mcp.service import app as fastapi_app, init_app

    init_app(data_dir)
    console.print(f"[bold]MCP Service running at http://{host}:{port}[/bold]")
    console.print(f"[dim]API docs: http://{host}:{port}/docs[/dim]")
    uvicorn.run(fastapi_app, host=host, port=port)


if __name__ == "__main__":
    app()
