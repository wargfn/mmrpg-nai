"""Discord bridge process for relaying chat to MCP web sessions."""

from __future__ import annotations

import asyncio
import json
import shlex
from dataclasses import dataclass
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


class MCPBridgeError(RuntimeError):
    """Base MCP bridge error."""


class MCPSessionInactiveError(MCPBridgeError):
    """Raised when target session is not active."""


class MCPWebClient:
    def __init__(self, base_url: str, timeout_seconds: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _get(self, path: str) -> Any:
        req = urlrequest.Request(f"{self.base_url}{path}", method="GET")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            detail = raw
            try:
                data = json.loads(raw)
                detail = str(data.get("detail", raw))
            except Exception:
                pass
            status = getattr(exc, "code", 500)
            raise MCPBridgeError(f"HTTP {status}: {detail}") from exc
        except urlerror.URLError as exc:
            if "timed out" in str(exc.reason).lower():
                raise MCPBridgeError(f"MCP request timed out after {self.timeout_seconds:.0f}s") from exc
            raise MCPBridgeError(f"Could not reach MCP service at {self.base_url}: {exc}") from exc

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urlerror.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            detail = raw
            try:
                data = json.loads(raw)
                detail = str(data.get("detail", raw))
            except Exception:
                pass
            status = getattr(exc, "code", 500)
            if status == 404 and "not active" in detail.lower():
                raise MCPSessionInactiveError(detail) from exc
            raise MCPBridgeError(f"HTTP {status}: {detail}") from exc
        except urlerror.URLError as exc:
            if "timed out" in str(exc.reason).lower():
                raise MCPBridgeError(f"MCP request timed out after {self.timeout_seconds:.0f}s") from exc
            raise MCPBridgeError(f"Could not reach MCP service at {self.base_url}: {exc}") from exc

    def chat(self, session_id: str, message: str) -> tuple[str, str]:
        data = self._post(f"/web/session/{session_id}/chat", {"message": message})
        return str(data.get("response", "")), str(data.get("mode", "narrate"))

    def resume(self, session_id: str) -> str:
        data = self._post("/web/session/start", {"session_id": session_id})
        session = data.get("session") or {}
        new_session_id = str(session.get("id", "")).strip()
        if not new_session_id:
            raise MCPBridgeError("Resume call succeeded but response had no session.id")
        return new_session_id

    def list_campaigns(self) -> list[dict[str, Any]]:
        data = self._get("/campaigns")
        return data if isinstance(data, list) else []

    def create_campaign(self, name: str, description: str = "") -> dict[str, Any]:
        return self._post("/campaigns", {"name": name, "description": description})

    def start_session(self, campaign_id: str, title: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"campaign_id": campaign_id}
        if title:
            payload["title"] = title
        return self._post("/web/session/start", payload)


def split_discord_message(text: str, limit: int = 1800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


@dataclass
class DiscordBridgeSettings:
    discord_token: str
    channel_id: int
    session_id: str | None = None
    mcp_base_url: str = "http://127.0.0.1:8000"
    mcp_timeout_seconds: float = 120.0
    resume_if_inactive: bool = True
    command_prefix: str = ""


def process_bridge_command(
    text: str,
    mcp: MCPWebClient,
    active_session_id: str | None,
    last_campaign_id: str | None,
) -> tuple[bool, str | None, str | None, str | None]:
    if not text.startswith("/"):
        return False, None, active_session_id, last_campaign_id

    try:
        parts = shlex.split(text[1:].strip())
    except ValueError:
        return True, "Malformed command syntax. Check quotes and try again.", active_session_id, last_campaign_id
    if parts and parts[0].lower() in {"mmrpg-nai", "mmrpg_nai"}:
        parts = parts[1:]
    if not parts:
        return True, "Use /help for available commands.", active_session_id, last_campaign_id

    cmd = parts[0].lower()
    if cmd == "help":
        return (
            True,
            (
                "Commands:\n"
                "• /campaign list\n"
                "• /campaign new <name>\n"
                "• /session start [campaign-id-or-prefix] [title]\n"
                "• /session use <session-id>\n"
                "• /session status"
            ),
            active_session_id,
            last_campaign_id,
        )

    if cmd == "campaign":
        if len(parts) < 2:
            return True, "Usage: /campaign list|new ...", active_session_id, last_campaign_id
        action = parts[1].lower()
        if action == "list":
            campaigns = mcp.list_campaigns()
            if not campaigns:
                return True, "No campaigns found.", active_session_id, last_campaign_id
            lines: list[str] = ["Campaigns:"]
            for c in campaigns[:20]:
                cid = str(c.get("id", ""))[:8]
                name = str(c.get("name", ""))
                lines.append(f"• {cid}  {name}")
            if len(campaigns) > 20:
                lines.append(f"…and {len(campaigns) - 20} more")
            return True, "\n".join(lines), active_session_id, last_campaign_id
        if action in {"new", "create"} and len(parts) >= 3:
            name = " ".join(parts[2:]).strip()
            if not name:
                return True, "Usage: /campaign new <name>", active_session_id, last_campaign_id
            campaign = mcp.create_campaign(name)
            campaign_id = str(campaign.get("id", "")).strip()
            if not campaign_id:
                return True, "Campaign created but response did not include an id.", active_session_id, last_campaign_id
            return (
                True,
                f"Created campaign '{campaign.get('name', name)}' ({campaign_id}). Now run /session start {campaign_id}",
                active_session_id,
                campaign_id,
            )
        return True, "Usage: /campaign list or /campaign new <name>", active_session_id, last_campaign_id

    if cmd == "session":
        if len(parts) < 2:
            return True, "Usage: /session start|use|status ...", active_session_id, last_campaign_id
        action = parts[1].lower()
        if action == "status":
            sid = active_session_id or "none"
            cid = last_campaign_id or "none"
            return True, f"Active session: {sid}\nLast campaign: {cid}", active_session_id, last_campaign_id
        if action == "use":
            if len(parts) < 3 or not parts[2].strip():
                return True, "Usage: /session use <session-id>", active_session_id, last_campaign_id
            session_id = parts[2].strip()
            return True, f"Active session set to {session_id}", session_id, last_campaign_id
        if action in {"start", "new"}:
            if len(parts) >= 3:
                campaign_ref = parts[2].strip()
                title = " ".join(parts[3:]).strip() or None
                campaign_id = campaign_ref
            else:
                if not last_campaign_id:
                    return True, "No campaign selected. Run /campaign new <name> first.", active_session_id, last_campaign_id
                campaign_id = last_campaign_id
                title = None

            try:
                started = mcp.start_session(campaign_id, title=title)
            except MCPBridgeError as exc:
                if len(parts) >= 3 and "campaign not found" in str(exc).lower():
                    campaigns = mcp.list_campaigns()
                    exact_match: dict[str, Any] | None = None
                    prefix_matches: list[dict[str, Any]] = []
                    name_matches: list[dict[str, Any]] = []
                    ref_lower = campaign_ref.lower()
                    for campaign_item in campaigns:
                        cid = str(campaign_item.get("id", ""))
                        cname = str(campaign_item.get("name", ""))
                        if cid == campaign_ref:
                            exact_match = campaign_item
                            break
                        if cid.startswith(campaign_ref):
                            prefix_matches.append(campaign_item)
                        if cname.lower() == ref_lower:
                            name_matches.append(campaign_item)
                    if exact_match is not None:
                        campaign_id = str(exact_match.get("id", "")).strip()
                    elif len(prefix_matches) == 1:
                        campaign_id = str(prefix_matches[0].get("id", "")).strip()
                    elif len(name_matches) == 1:
                        campaign_id = str(name_matches[0].get("id", "")).strip()
                    else:
                        if last_campaign_id:
                            title = " ".join(parts[2:]).strip() or None
                            campaign_id = last_campaign_id
                        else:
                            return (
                                True,
                                "Campaign not found or ambiguous. Use exact campaign ID.",
                                active_session_id,
                                last_campaign_id,
                            )
                    started = mcp.start_session(campaign_id, title=title)
                else:
                    raise
            session = started.get("session") or {}
            campaign = started.get("campaign") or {}
            new_session_id = str(session.get("id", "")).strip()
            if not new_session_id:
                return True, "Session start succeeded but no session id was returned.", active_session_id, campaign_id
            resolved_campaign_id = str(campaign.get("id", campaign_id)).strip() or campaign_id
            campaign_name = str(campaign.get("name", resolved_campaign_id))
            return (
                True,
                f"Started session '{session.get('title', 'Session')}' ({new_session_id}) in campaign '{campaign_name}'.",
                new_session_id,
                resolved_campaign_id,
            )

    return True, "Unknown command. Use /help.", active_session_id, last_campaign_id


def run_discord_bridge(settings: DiscordBridgeSettings) -> None:
    try:
        import discord
    except ImportError as exc:
        raise RuntimeError("discord.py is required. Install with: pip install discord.py") from exc

    mcp = MCPWebClient(settings.mcp_base_url, timeout_seconds=settings.mcp_timeout_seconds)

    class _DiscordBridgeClient(discord.Client):
        def __init__(self) -> None:
            intents = discord.Intents.default()
            intents.message_content = True
            super().__init__(intents=intents)
            self.active_session_id = settings.session_id
            self.last_campaign_id: str | None = None

        async def on_ready(self) -> None:
            print(
                f"Discord bridge connected as {self.user} "
                f"(channel={settings.channel_id}, session={self.active_session_id or 'none'})"
            )

        async def on_message(self, message: "discord.Message") -> None:
            if message.author == self.user or message.author.bot:
                return
            if message.channel.id != settings.channel_id:
                return

            text = message.content.strip()
            if not text:
                return
            if settings.command_prefix:
                if not text.startswith(settings.command_prefix):
                    return
                text = text[len(settings.command_prefix):].strip()
                if not text:
                    return

            if text.startswith("/"):
                try:
                    handled, reply, new_session_id, new_campaign_id = await asyncio.to_thread(
                        process_bridge_command,
                        text,
                        mcp,
                        self.active_session_id,
                        self.last_campaign_id,
                    )
                except Exception as exc:
                    await message.reply(f"Command error: {exc}")
                    return
                if handled:
                    self.active_session_id = new_session_id
                    self.last_campaign_id = new_campaign_id
                    if reply:
                        await message.reply(reply)
                    return

            if not self.active_session_id:
                await message.reply("No active session. Use /campaign new <name> then /session start.")
                return

            async with message.channel.typing():
                try:
                    response, mode = await asyncio.to_thread(mcp.chat, self.active_session_id, text)
                except MCPSessionInactiveError:
                    if not settings.resume_if_inactive:
                        await message.reply("Session is not active. Start/resume it in MCP first.")
                        return
                    try:
                        self.active_session_id = await asyncio.to_thread(mcp.resume, self.active_session_id)
                        response, mode = await asyncio.to_thread(mcp.chat, self.active_session_id, text)
                    except Exception as exc:
                        await message.reply(f"Could not resume session: {exc}")
                        return
                except Exception as exc:
                    await message.reply(f"MCP error: {exc}")
                    return

            speaker = "Narrator (meta)" if mode == "meta" else "Narrator"
            out = f"**{speaker}:** {response}"
            for chunk in split_discord_message(out):
                await message.channel.send(chunk)

    client = _DiscordBridgeClient()
    client.run(settings.discord_token)
