"""Discord bridge process for relaying chat to MCP web sessions."""

from __future__ import annotations

import asyncio
import json
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
    session_id: str
    mcp_base_url: str = "http://127.0.0.1:8000"
    resume_if_inactive: bool = True
    command_prefix: str = ""


def run_discord_bridge(settings: DiscordBridgeSettings) -> None:
    try:
        import discord
    except ImportError as exc:
        raise RuntimeError("discord.py is required. Install with: pip install discord.py") from exc

    mcp = MCPWebClient(settings.mcp_base_url)

    class _DiscordBridgeClient(discord.Client):
        def __init__(self) -> None:
            intents = discord.Intents.default()
            intents.message_content = True
            super().__init__(intents=intents)
            self.active_session_id = settings.session_id

        async def on_ready(self) -> None:
            print(
                f"Discord bridge connected as {self.user} "
                f"(channel={settings.channel_id}, session={self.active_session_id})"
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

