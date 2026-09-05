"""Main CLI entry point for the MMRPG Narrator AI."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

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
    User,
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


def _mask_token(token: str) -> str:
    token = token.strip()
    if not token:
        return "(empty)"
    if len(token) <= 8:
        return "*" * len(token)
    if len(token) <= 12:
        return f"{token[:2]}{'*' * (len(token) - 4)}{token[-2:]}"
    return f"{token[:4]}{'*' * (len(token) - 8)}{token[-4:]}"


def _mcp_get_json(base_url: str, path: str) -> dict[str, Any]:
    req = urlrequest.Request(f"{base_url.rstrip('/')}{path}", method="GET")
    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Could not reach MCP service at {base_url}: {exc}") from exc


def _mcp_post_json(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Could not reach MCP service at {base_url}: {exc}") from exc


def _select_users_for_session(store: Store, campaign: Campaign) -> list[User]:
    users = store.users.list_all()
    if not users:
        console.print("[yellow]No users found.[/yellow]")
        create_now = Prompt.ask("Create a new user now? [Y/n]", default="y").strip().lower()
        if create_now not in {"", "y", "yes"}:
            return []
        new_user = _create_user_for_session(store)
        return [new_user]
    table = Table("#", "ID", "Name", "Email", "Last Login")
    for i, user in enumerate(users, 1):
        last_login = user.last_login_at.isoformat(timespec="seconds") if user.last_login_at else "—"
        table.add_row(str(i), user.id[:8], user.display_name, user.email or "—", last_login)
    console.print("\n[bold]Available players/users:[/bold]")
    console.print(table)
    default_ids = campaign.user_ids or [u.id for u in users]
    console.print("[dim]Enter user numbers/IDs separated by commas, or Enter for defaults.[/dim]")
    while True:
        raw = Prompt.ask("Players in this session", default="default")
        if raw.strip().lower() in {"", "default", "all"}:
            return [u for uid in default_ids if (u := store.users.load(uid)) is not None] or users
        selected: list[User] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            if token.isdigit():
                idx = int(token) - 1
                if 0 <= idx < len(users):
                    selected.append(users[idx])
            else:
                matched = [u for u in users if u.id.startswith(token) or u.display_name.lower() == token.lower()]
                selected.extend(matched)
        dedup: dict[str, User] = {}
        for u in selected:
            dedup[u.id] = u
        selected_users = list(dedup.values())
        if selected_users:
            return selected_users
        console.print("[red]No matching users found. Try again.[/red]")


def _create_user_for_session(store: Store) -> User:
    first_name = Prompt.ask("First name").strip()
    while not first_name:
        console.print("[red]First name is required.[/red]")
        first_name = Prompt.ask("First name").strip()
    last_name = Prompt.ask("Last name", default="").strip()
    email = Prompt.ask("Email", default="").strip()
    notes = Prompt.ask("Notes", default="")
    user = User(first_name=first_name, last_name=last_name, email=email, notes=notes)
    store.users.save(user)
    console.print(f"[green]Created user: {user.display_name} ({user.id[:8]})[/green]")
    return user


def _create_unnamed_character_for_session(store: Store) -> Character:
    existing = {c.name for c in store.characters.list_all()}
    base = "Unnamed Character"
    name = base
    idx = 2
    while name in existing:
        name = f"{base} {idx}"
        idx += 1
    character = Character(name=name, alias="", background="", is_npc=False)
    store.characters.save(character)
    console.print(f"[green]Created character: {character.name} ({character.id[:8]})[/green]")
    return character


def _create_character_for_session(store: Store, allow_unnamed: bool = False) -> Character:
    name = Prompt.ask("Character name").strip()
    while not name:
        if allow_unnamed:
            use_unnamed = Prompt.ask("Use unnamed character? [Y/n]", default="y").strip().lower()
            if use_unnamed in {"", "y", "yes"}:
                return _create_unnamed_character_for_session(store)
        console.print("[red]Character name is required.[/red]")
        name = Prompt.ask("Character name").strip()
    alias = Prompt.ask("Alias", default="").strip()
    background = Prompt.ask("Background", default="")
    character = Character(name=name, alias=alias, background=background, is_npc=False)
    store.characters.save(character)
    console.print(f"[green]Created character: {character.name} ({character.id[:8]})[/green]")
    return character


# ---------------------------------------------------------------------------
# Config commands
# ---------------------------------------------------------------------------

config_app = typer.Typer(help="Manage narrator configuration.")
app.add_typer(config_app, name="config")
provider_app = typer.Typer(help="Manage AI providers.")
config_app.add_typer(provider_app, name="provider")


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


@provider_app.command("list")
def config_provider_list(
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """List all available AI provider profiles."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    llm_cfg = cfg.llm
    resolved = llm_cfg.resolved(os.environ)
    table = Table("Provider", "Model", "API Base", "API Key Env", "Selected", "Detected")
    detected_provider = llm_cfg.detect_provider(os.environ)
    for name in sorted(llm_cfg.provider_settings):
        ps = llm_cfg.provider_settings[name]
        table.add_row(
            name,
            ps.model,
            ps.api_base,
            ps.api_key_env,
            "✓" if llm_cfg.provider == name else "",
            "✓" if detected_provider == name else "",
        )
    console.print(table)
    console.print(f"[dim]Available providers: {', '.join(sorted(llm_cfg.provider_settings.keys()))}[/dim]")
    console.print(f"[dim]Runtime active provider: {resolved.provider}[/dim]")


@provider_app.command("show")
def config_provider_show(
    provider: Optional[str] = typer.Argument(None, help="Provider name (default: currently selected provider)"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Show provider configuration."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    llm_cfg = cfg.llm
    selected_provider = provider or llm_cfg.provider
    ps = llm_cfg.provider_settings.get(selected_provider)
    if ps is None:
        console.print(f"[red]Unknown provider: {selected_provider}[/red]")
        console.print(f"[yellow]Available: {', '.join(sorted(llm_cfg.provider_settings.keys()))}[/yellow]")
        raise typer.Exit(1)
    data = {
        "provider": selected_provider,
        "model": ps.model,
        "api_base": ps.api_base,
        "api_key_env": ps.api_key_env,
        "max_tokens": ps.max_tokens,
        "temperature": ps.temperature,
        "selected": llm_cfg.provider == selected_provider,
        "detected": llm_cfg.detect_provider(os.environ) == selected_provider,
    }
    console.print_json(json.dumps(data, indent=2))


@provider_app.command("select")
def config_provider_select(
    provider: str = typer.Argument(..., help="Provider name to select"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Select default provider profile."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    llm_cfg = cfg.llm
    ps = llm_cfg.provider_settings.get(provider)
    if ps is None:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        console.print(f"[yellow]Available: {', '.join(sorted(llm_cfg.provider_settings.keys()))}[/yellow]")
        raise typer.Exit(1)

    cfg.llm.provider = provider
    cfg.llm.model = ps.model
    cfg.llm.api_base = ps.api_base
    cfg.llm.api_key_env = ps.api_key_env
    cfg.llm.max_tokens = ps.max_tokens
    cfg.llm.temperature = ps.temperature
    store.save_config(cfg)
    console.print(
        f"[green]Selected provider: {provider}[/green]\n"
        f"[dim]Model: {ps.model} • API base: {ps.api_base} • API key env: {ps.api_key_env}[/dim]"
    )


@provider_app.command("model")
def config_provider_model(
    model: str = typer.Argument(..., help="New model ID for the currently selected provider"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Set the model for the currently selected provider."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    provider = cfg.llm.provider
    ps = cfg.llm.provider_settings.get(provider)
    if ps is None:
        console.print(f"[red]Selected provider {provider!r} has no provider_settings entry.[/red]")
        raise typer.Exit(1)

    ps.model = model
    cfg.llm.model = model
    store.save_config(cfg)
    console.print(f"[green]Set model for provider {provider}: {model}[/green]")


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
    """List models available on the currently detected AI provider endpoint.

    Reads your token from the environment variable configured in llm.api_key_env
    and queries the /models endpoint. The current model in use is highlighted.

    After choosing a model, apply it with:

        mmrpg-nai config set llm.provider_settings.<provider>.model <model-id>
    """
    import os as _os

    store = _get_store(data_dir)
    cfg = store.load_config()
    llm_cfg = cfg.llm.resolved(_os.environ)

    api_key = _os.environ.get(llm_cfg.api_key_env, "").strip()
    if not api_key:
        console.print(
            Panel(
                f"Environment variable [bold]{llm_cfg.api_key_env!r}[/bold] is not set.\n"
                f"  1. Detected provider: [bold]{llm_cfg.provider}[/bold]\n"
                f"  2. Export a key/token: [bold]export {llm_cfg.api_key_env}=...[/bold]\n"
                "  3. Or update llm.provider_settings in config.json",
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

        client = _OpenAI(base_url=llm_cfg.api_base, api_key=api_key)
        models_response = client.models.list()
    except (_APIConnectionError, _APIStatusError, _AuthenticationError, _RateLimitError) as exc:
        wrapped = _wrap_api_error(exc, llm_cfg)
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
                f"{exc}\n\nEndpoint: {llm_cfg.api_base}",
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
        title=f"Models at {llm_cfg.api_base} ({llm_cfg.provider})",
        show_lines=False,
    )
    for m in model_data:
        is_active = m.id == llm_cfg.model
        owner = getattr(m, "owned_by", "") or ""
        table.add_row(
            f"[bold green]{m.id}[/bold green]" if is_active else m.id,
            owner,
            "[bold green]✓[/bold green]" if is_active else "",
        )

    console.print(table)
    console.print(
        f"\n[dim]Detected provider: [bold]{llm_cfg.provider}[/bold] • Active model: [bold]{llm_cfg.model}[/bold]\n"
        f"Change with: mmrpg-nai config set llm.provider_settings.{llm_cfg.provider}.model <id>[/dim]"
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
    """Use AI to draft a campaign plan (saved to the campaign record)."""
    store = _get_store(data_dir)
    cfg = store.load_config()
    campaign = _load_campaign_or_exit(store, campaign_id)

    from mmrpg_nai.llm.narrator import Narrator

    narrator = Narrator(cfg, store)
    console.print("[bold blue]Generating campaign plan…[/bold blue]")
    plan = narrator.plan_campaign(brief)
    console.print(Markdown(plan))

    # Persist the plan into the campaign record
    campaign.plan = plan
    store.campaigns.save(campaign)
    console.print("[dim]Plan saved. View anytime with: mmrpg-nai campaign show " + campaign.id[:8] + "[/dim]")


@campaign_app.command("show")
def campaign_show(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Show full details for a campaign, including the saved AI plan."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)

    # Header panel
    source_titles = []
    for mid in campaign.source_material_ids:
        m = store.source_materials.load(mid)
        if m:
            source_titles.append(m.title)

    enemy_names = []
    for eid in campaign.enemy_ids:
        e = store.characters.load(eid)
        if e:
            enemy_names.append(e.name)

    player_names = []
    for uid in campaign.user_ids:
        u = store.users.load(uid)
        if u:
            player_names.append(u.display_name)

    info = (
        f"[bold]Name:[/bold]        {campaign.name}\n"
        f"[bold]ID:[/bold]          {campaign.id}\n"
        f"[bold]Description:[/bold] {campaign.description or '—'}\n"
        f"[bold]Tone:[/bold]        {campaign.settings.tone}\n"
        f"[bold]Era:[/bold]         {campaign.settings.era}\n"
        f"[bold]Location:[/bold]    {campaign.settings.location}\n"
        f"[bold]Sessions:[/bold]    {len(campaign.session_ids)}\n"
        f"[bold]Players:[/bold]     {', '.join(player_names) or '—'}\n"
        f"[bold]Source Materials:[/bold] {', '.join(source_titles) or '—'}\n"
        f"[bold]Enemy Roster:[/bold]    {', '.join(enemy_names) or '—'}\n"
        f"[bold]Created:[/bold]     {campaign.created_at.strftime('%Y-%m-%d')}"
    )
    console.print(Panel(info, title=f"📖 {campaign.name}", expand=False))

    if campaign.plan:
        console.print("\n[bold yellow]Campaign Plan[/bold yellow]")
        console.print(Markdown(campaign.plan))
    else:
        console.print("\n[dim]No plan generated yet. Run: mmrpg-nai campaign plan " + campaign.id[:8] + "[/dim]")


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
            hp = e.health.score if hasattr(e.health, "score") else e.health
            table.add_row(e.id[:8], e.name, e.alias, e.rank.value, str(e.tier), str(hp))
    console.print(table)


@campaign_app.command("add-character")
def campaign_add_character(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    character_id: str = typer.Argument(..., help="Character ID (from 'character list')"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Add a player character to a campaign's default character list."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    char = _load_by_prefix_or_exact(store.characters, character_id, "Character")
    character_id = char.id
    if character_id in campaign.character_ids:
        console.print(f"[yellow]{char.name!r} is already in this campaign's character list.[/yellow]")
        return
    campaign.character_ids.append(character_id)
    store.campaigns.save(campaign)
    console.print(f"[green]Added {char.name!r} to campaign {campaign.name!r}.[/green]")


@campaign_app.command("remove-character")
def campaign_remove_character(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    character_id: str = typer.Argument(..., help="Character ID"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Remove a character from a campaign's default character list."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    char = _load_by_prefix_or_exact(store.characters, character_id, "Character")
    character_id = char.id
    if character_id not in campaign.character_ids:
        console.print(f"[yellow]{char.name!r} is not in this campaign's character list.[/yellow]")
        return
    campaign.character_ids.remove(character_id)
    store.campaigns.save(campaign)
    console.print(f"[green]Removed {char.name!r} from campaign {campaign.name!r}.[/green]")


@campaign_app.command("characters")
def campaign_characters(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """List characters in a campaign's default character list."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    if not campaign.character_ids:
        console.print("[yellow]No characters in this campaign's list. Add one with: campaign add-character[/yellow]")
        return
    table = Table("ID", "Name", "Alias", "Rank", "Tier", "HP")
    for cid in campaign.character_ids:
        c = store.characters.load(cid)
        if c is None:
            table.add_row(cid[:8], "[dim]<deleted>[/dim]", "", "", "", "")
        else:
            hp = c.health.score if hasattr(c.health, "score") else c.health
            table.add_row(c.id[:8], c.name, c.alias, c.rank.value, str(c.tier), str(hp))
    console.print(table)


@campaign_app.command("add-user")
def campaign_add_user(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    user_id: str = typer.Argument(..., help="User ID (from 'user list')"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Add a user/player to a campaign."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    user = _load_by_prefix_or_exact(store.users, user_id, "User")
    if user.id in campaign.user_ids:
        console.print(f"[yellow]{user.display_name!r} is already in this campaign.[/yellow]")
        return
    campaign.user_ids.append(user.id)
    store.campaigns.save(campaign)
    console.print(f"[green]Added user {user.display_name!r} to campaign {campaign.name!r}.[/green]")


@campaign_app.command("remove-user")
def campaign_remove_user(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    user_id: str = typer.Argument(..., help="User ID"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Remove a user/player from a campaign."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    user = _load_by_prefix_or_exact(store.users, user_id, "User")
    if user.id not in campaign.user_ids:
        console.print(f"[yellow]{user.display_name!r} is not in this campaign.[/yellow]")
        return
    campaign.user_ids.remove(user.id)
    store.campaigns.save(campaign)
    console.print(f"[green]Removed user {user.display_name!r} from campaign {campaign.name!r}.[/green]")


@campaign_app.command("users")
def campaign_users(
    campaign_id: str = typer.Argument(..., help="Campaign ID or prefix"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """List users/players tracked in a campaign."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    if not campaign.user_ids:
        console.print("[yellow]No users in this campaign yet. Add one with: campaign add-user[/yellow]")
        return
    table = Table("ID", "Name", "Email", "Last Login")
    for uid in campaign.user_ids:
        user = store.users.load(uid)
        if user is None:
            table.add_row(uid[:8], "[dim]<deleted>[/dim]", "", "")
            continue
        last_login = user.last_login_at.isoformat(timespec="seconds") if user.last_login_at else "—"
        table.add_row(user.id[:8], user.display_name, user.email or "—", last_login)
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
    table = Table("ID", "Campaign", "Title", "#", "Players", "Started")
    for s in sessions:
        table.add_row(
            s.id[:8],
            s.campaign_id[:8],
            s.title,
            str(s.session_number),
            str(len(s.user_ids)),
            s.started_at.strftime("%Y-%m-%d"),
        )
    console.print(table)


@session_app.command("create")
def session_create(
    campaign_id: str = typer.Option(..., prompt=True),
    title: str = typer.Option(..., prompt=True),
    user_ids: str = typer.Option("", help="Comma-separated user IDs/prefixes (optional)"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Create a new session."""
    store = _get_store(data_dir)
    campaign = _load_campaign_or_exit(store, campaign_id)
    campaign_id = campaign.id
    existing = store.sessions.find(campaign_id=campaign_id)
    chosen_user_ids: list[str] = []
    raw_ids = [part.strip() for part in user_ids.split(",") if part.strip()]
    if raw_ids:
        for uid in raw_ids:
            user = _load_by_prefix_or_exact(store.users, uid, "User")
            if user.id not in chosen_user_ids:
                chosen_user_ids.append(user.id)
    else:
        chosen_user_ids = list(campaign.user_ids)
    session = Session(
        campaign_id=campaign_id,
        title=title,
        session_number=len(existing) + 1,
        user_ids=chosen_user_ids,
    )
    store.sessions.save(session)
    # Link session to campaign
    campaign.session_ids.append(session.id)
    for uid in chosen_user_ids:
        if uid not in campaign.user_ids:
            campaign.user_ids.append(uid)
    store.campaigns.save(campaign)
    console.print(f"[green]Session created: {session.id}[/green]")


@session_app.command("add-character")
def session_add_character(
    session_id: str = typer.Argument(..., help="Session ID or prefix"),
    character_id: str = typer.Argument(..., help="Character ID (from 'character list')"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Add a character participant to a session."""
    store = _get_store(data_dir)
    session = _load_by_prefix_or_exact(store.sessions, session_id, "Session")
    char = _load_by_prefix_or_exact(store.characters, character_id, "Character")
    character_id = char.id
    if character_id in session.participants:
        console.print(f"[yellow]{char.name!r} is already a participant in this session.[/yellow]")
        return
    session.participants.append(character_id)
    store.sessions.save(session)
    console.print(f"[green]Added {char.name!r} to session '{session.title}'.[/green]")


@session_app.command("remove-character")
def session_remove_character(
    session_id: str = typer.Argument(..., help="Session ID or prefix"),
    character_id: str = typer.Argument(..., help="Character ID"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Remove a character participant from a session."""
    store = _get_store(data_dir)
    session = _load_by_prefix_or_exact(store.sessions, session_id, "Session")
    char = _load_by_prefix_or_exact(store.characters, character_id, "Character")
    character_id = char.id
    if character_id not in session.participants:
        console.print(f"[yellow]{char.name!r} is not a participant in this session.[/yellow]")
        return
    session.participants.remove(character_id)
    store.sessions.save(session)
    console.print(f"[green]Removed {char.name!r} from session '{session.title}'.[/green]")


@session_app.command("add-user")
def session_add_user(
    session_id: str = typer.Argument(..., help="Session ID or prefix"),
    user_id: str = typer.Argument(..., help="User ID (from 'user list')"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Add a user/player participant to a session."""
    store = _get_store(data_dir)
    session = _load_by_prefix_or_exact(store.sessions, session_id, "Session")
    user = _load_by_prefix_or_exact(store.users, user_id, "User")
    if user.id in session.user_ids:
        console.print(f"[yellow]{user.display_name!r} is already a participant in this session.[/yellow]")
        return
    session.user_ids.append(user.id)
    store.sessions.save(session)
    campaign = store.campaigns.load(session.campaign_id)
    if campaign and user.id not in campaign.user_ids:
        campaign.user_ids.append(user.id)
        store.campaigns.save(campaign)
    console.print(f"[green]Added user {user.display_name!r} to session '{session.title}'.[/green]")


@session_app.command("remove-user")
def session_remove_user(
    session_id: str = typer.Argument(..., help="Session ID or prefix"),
    user_id: str = typer.Argument(..., help="User ID"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Remove a user/player participant from a session."""
    store = _get_store(data_dir)
    session = _load_by_prefix_or_exact(store.sessions, session_id, "Session")
    user = _load_by_prefix_or_exact(store.users, user_id, "User")
    if user.id not in session.user_ids:
        console.print(f"[yellow]{user.display_name!r} is not a participant in this session.[/yellow]")
        return
    session.user_ids.remove(user.id)
    store.sessions.save(session)
    console.print(f"[green]Removed user {user.display_name!r} from session '{session.title}'.[/green]")


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
            console.print(
                "[dim]Enter numbers/IDs (e.g. 1,3), 'new' to create, 'unnamed' for a placeholder, or Enter for all.[/dim]"
            )
            raw_chars = Prompt.ask("Characters playing today", default="all")
            if raw_chars.strip().lower() in {"", "all"}:
                party = pc_pool
            else:
                selected: list[Character] = []
                for token in raw_chars.split(","):
                    token = token.strip()
                    lowered = token.lower()
                    if lowered in {"new", "create"}:
                        selected.append(_create_character_for_session(store, allow_unnamed=True))
                        continue
                    if lowered in {"unnamed", "anon", "anonymous"}:
                        selected.append(_create_unnamed_character_for_session(store))
                        continue
                    if token.isdigit():
                        idx = int(token) - 1
                        if 0 <= idx < len(pc_pool):
                            selected.append(pc_pool[idx])
                    else:
                        matched = [c for c in pc_pool if c.id.startswith(token) or c.name.lower() == token.lower()]
                        selected.extend(matched)
                dedup: dict[str, Character] = {}
                for c in selected:
                    dedup[c.id] = c
                party = list(dedup.values()) or pc_pool
        else:
            console.print("[yellow]No player characters found.[/yellow]")
            create_char = Prompt.ask("Create a new player character now? [Y/n]", default="y").strip().lower()
            if create_char in {"", "y", "yes"}:
                created_character = _create_character_for_session(store, allow_unnamed=True)
                party = [created_character]

        session_users = _select_users_for_session(store, campaign)
        for character in party:
            if character.id not in campaign.character_ids:
                campaign.character_ids.append(character.id)

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
            user_ids=[u.id for u in session_users],
        )
        store.sessions.save(session)
        # Link session to campaign
        campaign.session_ids.append(session.id)
        for user in session_users:
            if user.id not in campaign.user_ids:
                campaign.user_ids.append(user.id)
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
        if not session.user_ids:
            session.user_ids = list(campaign.user_ids)
            store.sessions.save(session)
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
    store.touch_users_for_session(session.user_ids)

    party_names = ", ".join(c.name for c in party) if party else "Unknown party"
    session_user_names = ", ".join(
        user.display_name for uid in session.user_ids if (user := store.users.load(uid)) is not None
    ) or "—"
    sources_line = (
        f"\n[bold]Source Materials:[/bold] {', '.join(m.title for m in source_materials)}"
        if source_materials
        else ""
    )
    console.print(
        Panel(
            f"[bold]Session:[/bold] {session.title}  (#{session.session_number})\n"
            f"[bold]Campaign:[/bold] {campaign.name}\n"
            f"[bold]Party:[/bold] {party_names}\n"
            f"[bold]Players:[/bold] {session_user_names}"
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

    # ------------------------------------------------------------------
    # 7. Update campaign progress
    # ------------------------------------------------------------------
    if campaign.plan or campaign.campaign_progress:
        console.print("[dim italic]Updating campaign progress…[/dim italic]")
        try:
            completed_sessions = store.sessions.find(campaign_id=campaign.id)
            progress = narrator.summarise_campaign_progress(campaign, completed_sessions)
            campaign.campaign_progress = progress
            store.campaigns.save(campaign)
            console.print(Panel(Markdown(progress), title="[bold cyan]Campaign Progress[/bold cyan]"))
        except Exception as exc:
            console.print(f"[yellow]Could not update campaign progress: {exc}[/yellow]")


@session_app.command("query")
def session_query(
    question: str = typer.Argument(..., help="Rules/stats/checks question for the LLM"),
    campaign_id: Optional[str] = typer.Option(None, help="Campaign ID or prefix"),
    session_id: Optional[str] = typer.Option(None, help="Session ID or prefix"),
    character_ids: str = typer.Option(
        "",
        help="Comma-separated character IDs/prefixes to include in context (optional)",
    ),
    include_source_materials: bool = typer.Option(
        True,
        "--include-source-materials/--no-include-source-materials",
        help="Include campaign source materials in context",
    ),
    stream: bool = typer.Option(False, help="Stream response"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Query the LLM with loaded context for rules, stats, and checks."""
    from mmrpg_nai.llm.narrator import Narrator

    if bool(campaign_id) == bool(session_id):
        console.print("[red]Provide exactly one of --campaign-id or --session-id.[/red]")
        raise typer.Exit(1)

    store = _get_store(data_dir)
    cfg = store.load_config()

    if session_id:
        session = _load_by_prefix_or_exact(store.sessions, session_id, "Session")
        campaign = store.campaigns.load(session.campaign_id)
        if campaign is None:
            console.print(f"[red]Campaign not found: {session.campaign_id}[/red]")
            raise typer.Exit(1)
    else:
        campaign = _load_campaign_or_exit(store, campaign_id or "")
        session = Session(
            campaign_id=campaign.id,
            title="Context Query",
            session_number=0,
            participants=[],
            user_ids=[],
        )

    party: list[Character] = []
    requested_ids = [part.strip() for part in character_ids.split(",") if part.strip()]
    if requested_ids:
        seen_char_ids: set[str] = set()
        for rid in requested_ids:
            ch = _load_by_prefix_or_exact(store.characters, rid, "Character")
            if ch.id not in seen_char_ids:
                party.append(ch)
                seen_char_ids.add(ch.id)
    else:
        base_ids = session.participants or campaign.character_ids
        party = [c for cid in base_ids if (c := store.characters.load(cid)) is not None]

    source_materials = []
    if include_source_materials:
        source_materials = [
            m
            for mid in campaign.source_material_ids
            if (m := store.source_materials.load(mid)) is not None
        ]

    narrator = Narrator(cfg, store)
    narrator.start_session(session, campaign, party, source_materials=source_materials)
    try:
        answer = narrator.query_rules(question, stream=stream)
    except Exception as exc:
        console.print(Panel(str(exc), title="[bold red]⚠ Query failed[/bold red]", border_style="red"))
        raise typer.Exit(1)

    console.print(Panel(Markdown(answer), title="[bold cyan]Rules Query[/bold cyan]"))


@session_app.command("attach")
def session_attach(
    session_id: Optional[str] = typer.Option(None, help="Active session ID or prefix (optional)"),
    mcp_base_url: str = typer.Option("http://127.0.0.1:8000", help="Base URL of running MCP service"),
) -> None:
    """Attach CLI to an active MCP web session and chat through it."""
    import re as _re

    try:
        active = _mcp_get_json(mcp_base_url, "/web/active-sessions")
    except Exception as exc:
        console.print(Panel(str(exc), title="[bold red]⚠ MCP connection error[/bold red]", border_style="red"))
        raise typer.Exit(1)

    sessions = active.get("sessions", [])
    if not sessions:
        console.print("[yellow]No active sessions found on MCP service.[/yellow]")
        raise typer.Exit(1)

    selected: dict[str, Any] | None = None
    if session_id:
        exact = next((s for s in sessions if s.get("id") == session_id), None)
        if exact is not None:
            selected = exact
        else:
            matches = [s for s in sessions if str(s.get("id", "")).startswith(session_id)]
            if len(matches) == 1:
                selected = matches[0]
            elif len(matches) > 1:
                console.print("[red]Session prefix matches multiple active sessions; be more specific.[/red]")
                raise typer.Exit(1)
    else:
        table = Table("#", "Session ID", "Campaign ID", "Title", "Players")
        for i, s in enumerate(sessions, 1):
            table.add_row(
                str(i),
                str(s.get("id", ""))[:8],
                str(s.get("campaign_id", ""))[:8],
                str(s.get("title", "")),
                str(len(s.get("user_ids", []) or [])),
            )
        console.print(table)
        raw = Prompt.ask("Select active session by number or ID prefix")
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(sessions):
                selected = sessions[idx]
        if selected is None:
            matches = [s for s in sessions if str(s.get("id", "")).startswith(raw.strip())]
            if len(matches) == 1:
                selected = matches[0]
            elif len(matches) > 1:
                console.print("[red]Session prefix matches multiple active sessions; be more specific.[/red]")
                raise typer.Exit(1)

    if selected is None:
        console.print(f"[red]Active session not found: {session_id or '(selection)'}[/red]")
        raise typer.Exit(1)

    selected_id = str(selected.get("id", ""))
    _META_RE = _re.compile(r"^\s*\[(.+)\]\s*$")
    console.print(
        Panel(
            f"[bold]Attached Session:[/bold] {selected.get('title', '—')} ({selected_id[:8]})\n"
            f"[bold]Campaign:[/bold] {str(selected.get('campaign_id', ''))[:8]}\n"
            f"[dim]MCP: {mcp_base_url}[/dim]\n\n"
            f"[dim]Type your action/dialogue. Use [square brackets] for meta. "
            f"Enter 'quit' or 'exit' to detach.[/dim]",
            title="🔗 Attached to Active Session",
        )
    )

    while True:
        try:
            player_input = Prompt.ask("[bold green]You[/bold green]")
        except (EOFError, KeyboardInterrupt):
            break
        if player_input.strip().lower() in {"quit", "exit", "q"}:
            break
        if not player_input.strip():
            continue

        try:
            resp = _mcp_post_json(mcp_base_url, f"/web/session/{selected_id}/chat", {"message": player_input})
        except Exception as exc:
            console.print(Panel(str(exc), title="[bold red]⚠ MCP chat error[/bold red]", border_style="red"))
            break

        mode = str(resp.get("mode", "narrate"))
        output = str(resp.get("response", ""))
        if mode == "meta":
            console.print("[bold yellow]Narrator (meta)[/bold yellow]")
        else:
            console.print("[bold blue]Narrator[/bold blue]")
        if mode == "meta":
            console.print(Panel(Markdown(output), border_style="yellow"))
        else:
            console.print(Panel(Markdown(output), border_style="blue"))
        console.print()

    console.print("[bold]Detached from active session.[/bold]")


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
# User commands
# ---------------------------------------------------------------------------

user_app = typer.Typer(help="Manage users/players.")
app.add_typer(user_app, name="user")


@user_app.command("list")
def user_list(data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR")) -> None:
    """List users/players and last login."""
    store = _get_store(data_dir)
    users = store.users.list_all()
    if not users:
        console.print("[yellow]No users found.[/yellow]")
        return
    table = Table("ID", "Name", "Email", "Last Login", "Sessions")
    for user in users:
        last_login = user.last_login_at.isoformat(timespec="seconds") if user.last_login_at else "—"
        table.add_row(user.id[:8], user.display_name, user.email or "—", last_login, str(len(user.session_timestamps)))
    console.print(table)


@user_app.command("create")
def user_create(
    first_name: str = typer.Option(..., prompt=True),
    last_name: str = typer.Option("", prompt=True),
    email: str = typer.Option("", prompt=True),
    notes: str = typer.Option("", prompt=True),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Create a user/player."""
    store = _get_store(data_dir)
    clean_first = first_name.strip()
    if not clean_first:
        console.print("[red]first_name is required.[/red]")
        raise typer.Exit(1)
    user = User(first_name=clean_first, last_name=last_name.strip(), email=email.strip(), notes=notes)
    store.users.save(user)
    console.print(f"[green]User created: {user.id}[/green]")


@user_app.command("show")
def user_show(
    user_id: str = typer.Argument(..., help="User ID or prefix"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Show full details for a user."""
    store = _get_store(data_dir)
    user = _load_by_prefix_or_exact(store.users, user_id, "User")
    last_login = user.last_login_at.isoformat(timespec="seconds") if user.last_login_at else "—"
    info = (
        f"[bold]Name:[/bold]       {user.display_name}\n"
        f"[bold]ID:[/bold]         {user.id}\n"
        f"[bold]First Name:[/bold] {user.first_name}\n"
        f"[bold]Last Name:[/bold]  {user.last_name or '—'}\n"
        f"[bold]Email:[/bold]      {user.email or '—'}\n"
        f"[bold]Last Login:[/bold] {last_login}\n"
        f"[bold]Sessions:[/bold]   {len(user.session_timestamps)}\n"
        f"[bold]Notes:[/bold]      {user.notes or '—'}"
    )
    console.print(Panel(info, title=f"👤 {user.display_name}", expand=False))


@user_app.command("update")
def user_update(
    user_id: str = typer.Argument(..., help="User ID or prefix"),
    first_name: Optional[str] = typer.Option(None),
    last_name: Optional[str] = typer.Option(None),
    email: Optional[str] = typer.Option(None),
    notes: Optional[str] = typer.Option(None),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Update a user/player."""
    store = _get_store(data_dir)
    user = _load_by_prefix_or_exact(store.users, user_id, "User")
    if first_name is not None:
        clean_first = first_name.strip()
        if not clean_first:
            console.print("[red]first_name cannot be empty.[/red]")
            raise typer.Exit(1)
        user.first_name = clean_first
    if last_name is not None:
        user.last_name = last_name.strip()
    if email is not None:
        user.email = email.strip()
    if notes is not None:
        user.notes = notes
    user.updated_at = datetime.now(timezone.utc)
    store.users.save(user)
    console.print(f"[green]Updated user: {user.display_name} ({user.id[:8]})[/green]")


@user_app.command("delete")
def user_delete(
    user_id: str = typer.Argument(..., help="User ID or prefix"),
    data_dir: str = typer.Option(_default_data_dir(), envvar="MMRPG_DATA_DIR"),
) -> None:
    """Delete a user/player."""
    store = _get_store(data_dir)
    user = _load_by_prefix_or_exact(store.users, user_id, "User")
    if not store.users.delete(user.id):
        console.print(f"[red]Could not delete user: {user.id}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Deleted user: {user.display_name} ({user.id[:8]})[/green]")


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
    table = Table("ID", "Name", "Alias", "Rank", "Tier", "HP", "NPC")
    for c in chars:
        hp = c.health.score if hasattr(c.health, "score") else c.health
        table.add_row(c.id[:8], c.name, c.alias, c.rank.value, str(c.tier), str(hp), str(c.is_npc))
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

    cfg = _get_store(data_dir).load_config()
    llm_cfg = cfg.llm.resolved(os.environ)
    token_env = llm_cfg.api_key_env
    token_value = os.environ.get(token_env, "")
    if token_value.strip():
        console.print(f"[dim]{llm_cfg.provider} detected via {token_env}: {_mask_token(token_value)}[/dim]")
    else:
        console.print(
            f"[yellow]{token_env} is not set for provider '{llm_cfg.provider}'; "
            "web chat requests will fail until it is configured.[/yellow]"
        )

    init_app(data_dir)
    console.print(f"[bold]MCP Service running at http://{host}:{port}[/bold]")
    console.print(f"[dim]API docs: http://{host}:{port}/docs[/dim]")
    uvicorn.run(fastapi_app, host=host, port=port)


@app.command("serve-discord")
def serve_discord(
    session_id: Optional[str] = typer.Option(None, help="Active/resumable session ID (optional)"),
    channel_id: int = typer.Option(..., help="Discord channel ID to listen and post in"),
    mcp_base_url: str = typer.Option("http://127.0.0.1:8000", help="Base URL of running MCP service"),
    token_env: str = typer.Option("DISCORD_BOT_TOKEN", help="Environment variable containing Discord bot token"),
    resume_if_inactive: bool = typer.Option(
        True,
        "--resume-if-inactive/--no-resume-if-inactive",
        help="Auto-resume session through MCP if target session is inactive",
    ),
    command_prefix: str = typer.Option(
        "",
        help="Optional command prefix to filter messages (e.g. !nai)",
    ),
) -> None:
    """Start Discord bridge process that relays channel messages to an MCP session."""
    from mmrpg_nai.discord.bridge import DiscordBridgeSettings, run_discord_bridge

    token_value = os.environ.get(token_env, "").strip()
    if not token_value:
        console.print(f"[red]{token_env} is not set.[/red]")
        raise typer.Exit(1)

    target = session_id or "(none; use /campaign new and /session start in Discord)"
    console.print(f"[dim]Starting Discord bridge on channel {channel_id} -> session {target} via {mcp_base_url}[/dim]")
    run_discord_bridge(
        DiscordBridgeSettings(
            discord_token=token_value,
            channel_id=channel_id,
            session_id=session_id,
            mcp_base_url=mcp_base_url,
            resume_if_inactive=resume_if_inactive,
            command_prefix=command_prefix,
        )
    )


if __name__ == "__main__":
    app()
