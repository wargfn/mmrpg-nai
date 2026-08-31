"""Main CLI entry point for the MMRPG Narrator AI."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


@config_app.command("models")
def config_models(
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
    filter_text: Optional[str] = typer.Option(None, "--filter", "-f", help="Case-insensitive substring to filter model IDs"),
) -> None:
    """List models available on the GitHub Copilot API endpoint.

    Reads your token from the environment variable configured in llm.api_key_env
    (default: GITHUB_TOKEN) and queries the /models endpoint.  The current model
    in use is highlighted.

    After choosing a model, apply it with:

        mmrpg-nai config set llm.model <model-id>
    """
    import os as _os

    store = _get_store(data_dir)
    cfg = store.load_config()

    api_key = _os.environ.get(cfg.llm.api_key_env, "").strip()
    if not api_key:
        console.print(
            Panel(
                f"Environment variable [bold]{cfg.llm.api_key_env!r}[/bold] is not set.\n"
                "  1. Create a GitHub token at https://github.com/settings/tokens\n"
                "  2. Enable GitHub Copilot on your account (https://github.com/features/copilot)\n"
                "  3. Export it:  export GITHUB_TOKEN=ghp_...",
                title="[bold red]⚠ Token not set[/bold red]",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    try:
        from openai import (
            APIConnectionError as _APIConnectionError,
            APIStatusError as _APIStatusError,
            AuthenticationError as _AuthenticationError,
            OpenAI as _OpenAI,
            RateLimitError as _RateLimitError,
        )
        from mmrpg_nai.llm.client import _wrap_api_error

        client = _OpenAI(base_url=cfg.llm.api_base, api_key=api_key)
        models_response = client.models.list()
    except (_APIConnectionError, _APIStatusError, _AuthenticationError, _RateLimitError) as exc:
        wrapped = _wrap_api_error(exc, cfg.llm)
        if isinstance(wrapped, PermissionError):
            console.print(Panel(str(wrapped), title="[bold red]⚠ Authentication error[/bold red]", border_style="red"))
        elif isinstance(wrapped, ConnectionError):
            console.print(Panel(str(wrapped), title="[bold red]⚠ Connection error[/bold red]", border_style="red"))
        else:
            console.print(Panel(str(wrapped), title="[bold red]⚠ API error[/bold red]", border_style="red"))
        raise typer.Exit(1)
    except Exception as exc:
        console.print(
            Panel(
                f"{exc}\n\nEndpoint: {cfg.llm.api_base}",
                title="[bold red]⚠ Failed to fetch models[/bold red]",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    model_data = sorted(models_response.data, key=lambda m: m.id.lower())

    if filter_text:
        model_data = [m for m in model_data if filter_text.lower() in m.id.lower()]

    if not model_data:
        console.print(f"[yellow]No models found{f' matching {filter_text!r}' if filter_text else ''}.[/yellow]")
        raise typer.Exit(0)

    table = Table(
        "Model ID",
        "Owner / Provider",
        "Active",
        title=f"Models at {cfg.llm.api_base}",
        show_lines=False,
    )
    for m in model_data:
        is_active = m.id == cfg.llm.model
        owner = getattr(m, "owned_by", "") or ""
        table.add_row(
            f"[bold green]{m.id}[/bold green]" if is_active else m.id,
            owner,
            "[bold green]✓[/bold green]" if is_active else "",
        )

    console.print(table)
    console.print(
        f"\n[dim]Currently active model: [bold]{cfg.llm.model}[/bold]  "
        f"(change with: mmrpg-nai config set llm.model <id>)[/dim]"
    )


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
    campaign = _load_campaign_or_exit(store, campaign_id)

    from mmrpg_nai.llm.narrator import Narrator

    narrator = Narrator(cfg, store)
    console.print("[bold blue]Generating campaign plan…[/bold blue]")
    plan = narrator.plan_campaign(brief)
    console.print(Markdown(plan))


def _load_by_prefix_or_exact(repo: "_Repo", id_: str, label: str) -> "Any":
    """Load by exact ID first; fall back to prefix match. Exit with error if not found."""
    obj = repo.load(id_)
    if obj is None:
        obj = repo.load_by_prefix(id_)
    if obj is None:
        console.print(f"[red]{label} not found: {id_}[/red]")
        raise typer.Exit(1)
    return obj


def _load_campaign_or_exit(store: "Store", campaign_id: str) -> "Campaign":
    return _load_by_prefix_or_exact(store.campaigns, campaign_id, "Campaign")


@campaign_app.command("add-source")
def campaign_add_source(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    source_id: str = typer.Argument(..., help="Source material ID (from 'pdf list')"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Link a PDF source material to a campaign."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    material = _load_by_prefix_or_exact(store.source_materials, source_id, "Source material")
    source_id = material.id  # normalise to full ID
    if source_id in campaign.source_material_ids:
        console.print(f"[yellow]{material.title!r} is already linked to this campaign.[/yellow]")
        return
    campaign.source_material_ids.append(source_id)
    store.campaigns.save(campaign)
    console.print(f"[green]Linked source material {material.title!r} to campaign {campaign.name!r}.[/green]")


@campaign_app.command("remove-source")
def campaign_remove_source(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    source_id: str = typer.Argument(..., help="Source material ID"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Unlink a PDF source material from a campaign."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    # Support prefix match — normalise to full ID
    material = _load_by_prefix_or_exact(store.source_materials, source_id, "Source material")
    source_id = material.id
    if source_id not in campaign.source_material_ids:
        console.print(f"[yellow]Source material {source_id[:8]!r} is not linked to this campaign.[/yellow]")
        return
    campaign.source_material_ids.remove(source_id)
    store.campaigns.save(campaign)
    console.print(f"[green]Removed {material.title!r} from campaign {campaign.name!r}.[/green]")


@campaign_app.command("add-enemy")
def campaign_add_enemy(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    character_id: str = typer.Argument(..., help="Character ID of the enemy (from 'character list')"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Add an enemy/antagonist stat-block to the campaign enemy roster."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    enemy = _load_by_prefix_or_exact(store.characters, character_id, "Character")
    character_id = enemy.id  # normalise to full ID
    if character_id in campaign.enemy_ids:
        console.print(f"[yellow]{enemy.name!r} is already in the enemy roster.[/yellow]")
        return
    campaign.enemy_ids.append(character_id)
    store.campaigns.save(campaign)
    console.print(f"[green]Added {enemy.name!r} ({enemy.alias}) to enemy roster of {campaign.name!r}.[/green]")


@campaign_app.command("remove-enemy")
def campaign_remove_enemy(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    character_id: str = typer.Argument(..., help="Character ID of the enemy"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Remove an enemy/antagonist from the campaign enemy roster."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    enemy = _load_by_prefix_or_exact(store.characters, character_id, "Character")
    character_id = enemy.id  # normalise to full ID
    if character_id not in campaign.enemy_ids:
        console.print(f"[yellow]{enemy.name!r} is not in the enemy roster.[/yellow]")
        return
    campaign.enemy_ids.remove(character_id)
    store.campaigns.save(campaign)
    console.print(f"[green]Removed {enemy.name!r} from enemy roster of {campaign.name!r}.[/green]")


@campaign_app.command("enemies")
def campaign_enemies(
    campaign_id: str = typer.Argument(..., help="Campaign ID"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """List enemies/antagonists saved to a campaign."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    if not campaign.enemy_ids:
        console.print("[yellow]No enemies in this campaign's roster yet.[/yellow]")
        return
    table = Table("ID", "Name", "Alias", "Rank", "Tier", "HP")
    for eid in campaign.enemy_ids:
        e = store.characters.load(eid)
        if e is None:
            table.add_row(eid[:8], "[dim]<deleted>[/dim]", "", "", "", "")
        else:
            table.add_row(e.id[:8], e.name, e.alias, e.rank.value, str(e.tier), str(e.health))
    console.print(table)


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
    # Link session to campaign
    campaign = store.campaigns.load(campaign_id)
    if campaign is not None:
        campaign.session_ids.append(session.id)
        store.campaigns.save(campaign)
    console.print(f"[green]Session created: {session.id}[/green]")


@session_app.command("run")
def session_run(
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
    stream: bool = typer.Option(True, help="Stream responses"),
    session_id: Optional[str] = typer.Option(None, help="Resume a specific session by ID (skips startup prompts)"),
) -> None:
    """Run an interactive narration session from the command line.

    At startup you will be asked which campaign and characters are playing.
    The AI will then deliver a brief recap of the previous session before play begins.

    During play, wrap any text in [square brackets] to send an out-of-game meta
    direction to the Narrator without it being treated as in-world action.
    For example: [make the next encounter harder] or [skip ahead to the boss fight].
    """
    import re as _re
    from mmrpg_nai.llm.narrator import Narrator

    store = _get_store(data_dir)
    cfg = store.load_config()

    # ------------------------------------------------------------------
    # 1. Choose campaign
    # ------------------------------------------------------------------
    if session_id is None:
        campaigns = store.campaigns.list_all()
        if not campaigns:
            console.print("[red]No campaigns found. Create one first with: mmrpg-nai campaign create[/red]")
            raise typer.Exit(1)

        console.print("\n[bold]Available campaigns:[/bold]")
        table = Table("#", "ID", "Name", "Sessions")
        for i, c in enumerate(campaigns, 1):
            table.add_row(str(i), c.id[:8], c.name, str(len(c.session_ids)))
        console.print(table)

        while True:
            raw = Prompt.ask("Enter campaign number or ID prefix")
            campaign: Optional[Campaign] = None
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < len(campaigns):
                    campaign = campaigns[idx]
            else:
                matches = [c for c in campaigns if c.id.startswith(raw) or c.name.lower() == raw.lower()]
                if len(matches) == 1:
                    campaign = matches[0]
                elif len(matches) > 1:
                    console.print("[yellow]Multiple matches – be more specific.[/yellow]")
            if campaign is not None:
                break
            console.print("[red]Not found, try again.[/red]")

        # ------------------------------------------------------------------
        # 2. Choose characters
        # ------------------------------------------------------------------
        all_chars = store.characters.list_all()
        pc_pool = [c for c in all_chars if not c.is_npc]
        party: list[Character] = []

        if pc_pool:
            console.print("\n[bold]Available player characters:[/bold]")
            ctable = Table("#", "ID", "Name", "Alias", "Rank")
            for i, ch in enumerate(pc_pool, 1):
                ctable.add_row(str(i), ch.id[:8], ch.name, ch.alias, ch.rank.value)
            console.print(ctable)
            console.print("[dim]Enter character numbers separated by commas (e.g. 1,3) or press Enter to use all.[/dim]")
            raw_chars = Prompt.ask("Characters playing today", default="all")
            if raw_chars.strip().lower() in {"", "all"}:
                party = pc_pool
            else:
                selected: list[Character] = []
                for token in raw_chars.split(","):
                    token = token.strip()
                    if token.isdigit():
                        idx = int(token) - 1
                        if 0 <= idx < len(pc_pool):
                            selected.append(pc_pool[idx])
                    else:
                        matched = [c for c in pc_pool if c.id.startswith(token) or c.name.lower() == token.lower()]
                        selected.extend(matched)
                party = selected or pc_pool

        # ------------------------------------------------------------------
        # 3. Create a new session for this run
        # ------------------------------------------------------------------
        session_title = Prompt.ask("Session title", default=f"Session {len(campaign.session_ids) + 1}")
        existing = store.sessions.find(campaign_id=campaign.id)
        session = Session(
            campaign_id=campaign.id,
            title=session_title,
            session_number=len(existing) + 1,
            participants=[c.id for c in party],
        )
        store.sessions.save(session)
        # Link session to campaign
        campaign.session_ids.append(session.id)
        store.campaigns.save(campaign)
        console.print(f"[green]Created session #{session.session_number}: {session.id}[/green]")

        # Find the previous session for recap
        prev_session = existing[-1] if existing else None

    else:
        # Resume by explicit session ID
        session = _load_by_prefix_or_exact(store.sessions, session_id, "Session")
        session_id = session.id  # normalise
        campaign = store.campaigns.load(session.campaign_id)
        if campaign is None:
            console.print(f"[red]Campaign not found: {session.campaign_id}[/red]")
            raise typer.Exit(1)
        party = [c for cid in session.participants if (c := store.characters.load(cid)) is not None]
        if not party:
            party = [c for cid in campaign.character_ids if (c := store.characters.load(cid)) is not None]
        prev_sessions = store.sessions.find(campaign_id=campaign.id)
        prev_session = next(
            (s for s in reversed(prev_sessions) if s.id != session.id),
            None,
        )

    # ------------------------------------------------------------------
    # 4. Start narrator
    # ------------------------------------------------------------------
    # Load source materials linked to this campaign
    source_materials = [
        m
        for mid in campaign.source_material_ids
        if (m := store.source_materials.load(mid)) is not None
    ]

    narrator = Narrator(cfg, store)
    narrator.start_session(session, campaign, party, source_materials=source_materials)

    party_names = ", ".join(c.name for c in party) if party else "Unknown party"
    sources_line = (
        f"\n[bold]Source Materials:[/bold] {', '.join(m.title for m in source_materials)}"
        if source_materials
        else ""
    )
    console.print(
        Panel(
            f"[bold]Session:[/bold] {session.title}  (#{session.session_number})\n"
            f"[bold]Campaign:[/bold] {campaign.name}\n"
            f"[bold]Party:[/bold] {party_names}"
            f"{sources_line}",
            title="🦸 MMRPG Narrator AI",
        )
    )

    # ------------------------------------------------------------------
    # 5. AI recap of last session
    # ------------------------------------------------------------------
    if prev_session is not None:
        console.print("[dim italic]Generating recap of last session…[/dim italic]")
        try:
            recap = narrator.recap_last_session(prev_session)
            if recap:
                console.print(Panel(Markdown(recap), title="[bold yellow]Previously…[/bold yellow]"))
        except Exception as exc:
            console.print(f"[yellow]Could not generate recap: {exc}[/yellow]")

    console.print(
        "[dim]Type your action or dialogue. "
        "Wrap text in [square brackets] for out-of-game meta directions. "
        "Enter 'quit' or 'exit' to end the session.[/dim]\n"
    )

    # ------------------------------------------------------------------
    # 6. Main input loop
    # ------------------------------------------------------------------
    _META_RE = _re.compile(r"^\s*\[(.+)\]\s*$")

    def _print_llm_error(exc: Exception) -> None:
        """Print a structured, actionable error panel for LLM failures."""
        if isinstance(exc, EnvironmentError):
            console.print(Panel(str(exc), title="[bold red]⚠ Token not set[/bold red]", border_style="red"))
        elif isinstance(exc, PermissionError):
            console.print(Panel(str(exc), title="[bold red]⚠ Authentication error[/bold red]", border_style="red"))
        elif isinstance(exc, ConnectionError):
            console.print(Panel(str(exc), title="[bold red]⚠ Connection error[/bold red]", border_style="red"))
        elif isinstance(exc, RuntimeError):
            console.print(Panel(str(exc), title="[bold red]⚠ API error[/bold red]", border_style="red"))
        else:
            console.print(f"[red]Error: {exc}[/red]")

    while True:
        try:
            player_input = Prompt.ask("[bold green]You[/bold green]")
        except (EOFError, KeyboardInterrupt):
            break

        if player_input.strip().lower() in {"quit", "exit", "q"}:
            break

        if not player_input.strip():
            continue

        meta_match = _META_RE.match(player_input)
        console.print()

        if meta_match:
            direction = meta_match.group(1).strip()
            console.print("[bold yellow]Narrator (meta)[/bold yellow]")
            try:
                narrator.meta_direction(direction, stream=stream)
            except Exception as exc:
                _print_llm_error(exc)
        else:
            console.print("[bold blue]Narrator[/bold blue]")
            try:
                narrator.narrate(player_input, stream=stream)
            except Exception as exc:
                _print_llm_error(exc)
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
    session = _load_by_prefix_or_exact(store.sessions, session_id, "Session")
    for entry in session.log:
        if entry.role == "narrator":
            color = "blue"
        elif entry.role == "meta":
            color = "yellow"
        else:
            color = "green"
        prefix = "(meta) " if entry.role == "meta" else ""
        ts = entry.timestamp.strftime("%H:%M:%S")
        console.print(f"[dim]{ts}[/dim] [bold {color}]{prefix}{entry.role.capitalize()}[/bold {color}]: {entry.content}\n")


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
    char = _load_by_prefix_or_exact(store.characters, character_id, "Character")
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
    table = Table("ID", "Title", "Pages", "Chars", "Categories")
    for m in materials:
        txt = Path(m.extracted_text_path)
        char_count = f"{txt.stat().st_size:,}" if m.extracted_text_path and txt.exists() else "—"
        table.add_row(m.id[:8], m.title, str(m.page_count), char_count, ", ".join(m.categories))
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
