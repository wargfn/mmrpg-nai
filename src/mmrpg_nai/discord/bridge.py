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

    def end_session(self, session_id: str) -> dict[str, Any]:
        return self._post(f"/web/session/{session_id}/end", {})

    def get_session_state(self, session_id: str) -> dict[str, Any]:
        data = self._get(f"/web/session/{session_id}")
        return data if isinstance(data, dict) else {}

    def list_active_sessions(self) -> list[dict[str, Any]]:
        data = self._get("/web/active-sessions")
        sessions = data.get("sessions", []) if isinstance(data, dict) else []
        return sessions if isinstance(sessions, list) else []

    def list_sessions(self) -> list[dict[str, Any]]:
        data = self._get("/web/bootstrap")
        sessions = data.get("sessions", []) if isinstance(data, dict) else []
        return sessions if isinstance(sessions, list) else []

    def resolve_session_id(self, session_ref: str) -> str:
        def _match(ref: str, sessions: list[dict[str, Any]]) -> tuple[str | None, bool]:
            exact = [s for s in sessions if str(s.get("id", "")).strip() == ref]
            if len(exact) == 1:
                return str(exact[0].get("id", "")).strip(), False
            prefix = [s for s in sessions if str(s.get("id", "")).strip().startswith(ref)]
            if len(prefix) == 1:
                return str(prefix[0].get("id", "")).strip(), False
            if len(prefix) > 1:
                return None, True
            return None, False

        ref = session_ref.strip()
        active_match, active_ambiguous = _match(ref, self.list_active_sessions())
        if active_ambiguous:
            raise MCPBridgeError("Session prefix matches multiple active sessions; be more specific.")
        if active_match:
            return active_match

        all_match, all_ambiguous = _match(ref, self.list_sessions())
        if all_ambiguous:
            raise MCPBridgeError("Session prefix matches multiple sessions; be more specific.")
        if all_match:
            return all_match

        raise MCPBridgeError("Session not found. Use /session list to view active sessions.")

    def ensure_active_session(self, session_id: str, resume_if_inactive: bool = True) -> tuple[str, bool]:
        state = self.get_session_state(session_id)
        session = state.get("session") or {}
        canonical_session_id = str(session.get("id", "")).strip() or session_id
        is_active = bool(state.get("is_active"))
        listed = self.is_session_listed_active(canonical_session_id)
        if is_active and listed:
            return canonical_session_id, False
        if is_active and not listed:
            raise MCPBridgeError("Session reports active but is not listed in MCP web active sessions.")
        if not resume_if_inactive:
            if not (is_active and listed):
                raise MCPBridgeError("Session could not be confirmed as active in MCP web active sessions.")
            return canonical_session_id, False
        resumed_id = self.resume(canonical_session_id)
        if not self.is_session_listed_active(resumed_id):
            raise MCPBridgeError("Session could not be confirmed in MCP web active sessions after resume.")
        return resumed_id, True

    def is_session_listed_active(self, session_id: str) -> bool:
        sessions = self.list_active_sessions()
        for item in sessions:
            if str(item.get("id", "")).strip() == session_id:
                return True
        return False


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


def _format_session_log_entry(entry: dict[str, Any]) -> str | None:
    role = str(entry.get("role", "")).strip().lower()
    content = str(entry.get("content", "")).strip()
    if not content:
        return None
    if role == "player":
        speaker = "Player"
    elif role == "narrator":
        speaker = "Narrator"
    elif role == "system":
        speaker = "System"
    else:
        speaker = role.title() if role else "Log"
    return f"**{speaker}:** {content}"


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
                "• /session list\n"
                "• /session use <session-id-or-prefix>\n"
                "• /session end\n"
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
            return True, "Usage: /session list|start|use|end|status ...", active_session_id, last_campaign_id
        action = parts[1].lower()
        if action == "list":
            sessions = mcp.list_active_sessions()
            if not sessions:
                return True, "No active sessions found.", active_session_id, last_campaign_id
            lines: list[str] = ["Active sessions:"]
            for s in sessions[:20]:
                sid = str(s.get("id", "")).strip()
                cid = str(s.get("campaign_id", "")).strip()
                title = str(s.get("title", "")).strip()
                marker = " (current)" if active_session_id and sid == active_session_id else ""
                lines.append(f"• {sid}  {cid[:8]}  {title}{marker}".rstrip())
            if len(sessions) > 20:
                lines.append(f"…and {len(sessions) - 20} more")
            return True, "\n".join(lines), active_session_id, last_campaign_id
        if action == "status":
            sid = active_session_id or "none"
            cid = last_campaign_id or "none"
            return True, f"Active session: {sid}\nLast campaign: {cid}", active_session_id, last_campaign_id
        if action == "end":
            if not active_session_id:
                return True, "No active session to end.", active_session_id, last_campaign_id
            ended = mcp.end_session(active_session_id)
            if bool(ended.get("ended")):
                return True, f"Ended and detached from session {active_session_id}.", None, last_campaign_id
            return True, f"Detached from session {active_session_id}.", None, last_campaign_id
        if action == "use":
            if len(parts) < 3 or not parts[2].strip():
                return True, "Usage: /session use <session-id-or-prefix>", active_session_id, last_campaign_id
            try:
                session_id = mcp.resolve_session_id(parts[2].strip())
                state = mcp.get_session_state(session_id)
            except MCPBridgeError as exc:
                return True, str(exc), active_session_id, last_campaign_id
            session = state.get("session") or {}
            canonical_session_id = str(session.get("id", "")).strip() or session_id
            campaign = state.get("campaign") or {}
            campaign_id = str(campaign.get("id", "")).strip() or last_campaign_id
            status = "active" if bool(state.get("is_active")) else "inactive"
            return (
                True,
                f"Active session set to {canonical_session_id} ({status})",
                canonical_session_id,
                campaign_id,
            )
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
            self._session_log_cursor: dict[str, int] = {}
            self._pending_narrator_echo: dict[str, str] = {}
            self._relay_task: asyncio.Task[None] | None = None
            self._relay_lock = asyncio.Lock()

        async def _sync_session_cursor(self, session_id: str, initialize: bool = True) -> None:
            state = await asyncio.to_thread(mcp.get_session_state, session_id)
            log = (state.get("session") or {}).get("log") or []
            current = self._session_log_cursor.get(session_id, 0)
            fetched = len(log) if isinstance(log, list) else 0
            self._session_log_cursor[session_id] = fetched if initialize else max(current, fetched)
            campaign = state.get("campaign") or {}
            campaign_id = str(campaign.get("id", "")).strip()
            if campaign_id:
                self.last_campaign_id = campaign_id

        async def _relay_active_session_updates(self) -> None:
            while not self.is_closed():
                session_id = self.active_session_id
                if not session_id:
                    await asyncio.sleep(1.0)
                    continue
                try:
                    async with self._relay_lock:
                        state = await asyncio.to_thread(mcp.get_session_state, session_id)
                except Exception:
                    await asyncio.sleep(2.0)
                    continue
                log = (state.get("session") or {}).get("log") or []
                if not isinstance(log, list):
                    await asyncio.sleep(1.0)
                    continue
                last_seen = self._session_log_cursor.get(session_id)
                if last_seen is None:
                    self._session_log_cursor[session_id] = len(log)
                    await asyncio.sleep(1.0)
                    continue
                if len(log) < last_seen:
                    self._session_log_cursor[session_id] = len(log)
                    await asyncio.sleep(1.0)
                    continue
                if len(log) > last_seen:
                    channel = self.get_channel(settings.channel_id)
                    if channel is not None:
                        async with self._relay_lock:
                            for entry in log[last_seen:]:
                                if not isinstance(entry, dict):
                                    continue
                                if str(entry.get("role", "")).strip().lower() == "player":
                                    continue
                                if str(entry.get("role", "")).strip().lower() == "narrator":
                                    pending = self._pending_narrator_echo.get(session_id, "")
                                    content = str(entry.get("content", "")).strip()
                                    if pending and content == pending:
                                        self._pending_narrator_echo.pop(session_id, None)
                                        continue
                                rendered = _format_session_log_entry(entry)
                                if not rendered:
                                    continue
                                for chunk in split_discord_message(rendered):
                                    await channel.send(chunk)
                    self._session_log_cursor[session_id] = len(log)
                await asyncio.sleep(1.0)

        async def on_ready(self) -> None:
            if self.active_session_id:
                try:
                    ensured_session_id, resumed = await asyncio.to_thread(
                        mcp.ensure_active_session,
                        self.active_session_id,
                        settings.resume_if_inactive,
                    )
                    if resumed:
                        previous = self.active_session_id
                        self.active_session_id = ensured_session_id
                        if previous and previous != ensured_session_id:
                            self._pending_narrator_echo.pop(previous, None)
                            self._session_log_cursor.pop(previous, None)
                        print(f"Discord bridge resumed session {previous} -> {ensured_session_id}")
                    else:
                        self.active_session_id = ensured_session_id
                    await self._sync_session_cursor(self.active_session_id)
                except Exception as exc:
                    print(f"Discord bridge could not validate active session {self.active_session_id}: {exc}")
            if self._relay_task is not None and not self._relay_task.done():
                self._relay_task.cancel()
                try:
                    await self._relay_task
                except asyncio.CancelledError:
                    pass
            self._relay_task = asyncio.create_task(self._relay_active_session_updates())
            print(
                f"Discord bridge connected as {self.user} "
                f"(channel={settings.channel_id}, session={self.active_session_id or 'none'})"
            )

        async def close(self) -> None:
            if self._relay_task is not None and not self._relay_task.done():
                self._relay_task.cancel()
                try:
                    await self._relay_task
                except asyncio.CancelledError:
                    pass
            await super().close()

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
                    normalized = text[1:].strip().lower()
                    if normalized.startswith("mmrpg-nai "):
                        normalized = normalized[len("mmrpg-nai "):]
                    elif normalized.startswith("mmrpg_nai "):
                        normalized = normalized[len("mmrpg_nai "):]
                    needs_activation = (
                        normalized.startswith("session use")
                        or normalized.startswith("session start")
                        or normalized.startswith("session new")
                    )
                    previous_active = self.active_session_id
                    if needs_activation and new_session_id:
                        try:
                            ensured_session_id, resumed = await asyncio.to_thread(
                                mcp.ensure_active_session,
                                new_session_id,
                                settings.resume_if_inactive,
                            )
                            self.active_session_id = ensured_session_id
                            if resumed and previous_active and previous_active != ensured_session_id:
                                self._pending_narrator_echo.pop(previous_active, None)
                                self._session_log_cursor.pop(previous_active, None)
                            await self._sync_session_cursor(ensured_session_id, initialize=True)
                            if resumed:
                                reply = f"{reply}\nResumed and attached to session {ensured_session_id}."
                        except Exception as exc:
                            await message.reply(f"Could not attach session {new_session_id}: {exc}")
                            return
                    else:
                        self.active_session_id = new_session_id
                        if previous_active and previous_active != self.active_session_id:
                            self._pending_narrator_echo.pop(previous_active, None)
                            self._session_log_cursor.pop(previous_active, None)
                        if self.active_session_id and self.active_session_id != previous_active:
                            await self._sync_session_cursor(self.active_session_id, initialize=True)
                    if new_campaign_id:
                        self.last_campaign_id = new_campaign_id
                    if reply:
                        await message.reply(reply)
                    return

            if not self.active_session_id:
                await message.reply("No active session. Use /campaign new <name> then /session start.")
                return

            async with message.channel.typing():
                try:
                    async with self._relay_lock:
                        response, mode = await asyncio.to_thread(mcp.chat, self.active_session_id, text)
                except MCPSessionInactiveError:
                    if not settings.resume_if_inactive:
                        await message.reply("Session is not active. Start/resume it in MCP first.")
                        return
                    try:
                        async with self._relay_lock:
                            previous_active = self.active_session_id
                            self.active_session_id = await asyncio.to_thread(mcp.resume, self.active_session_id)
                            if previous_active and previous_active != self.active_session_id:
                                self._pending_narrator_echo.pop(previous_active, None)
                                self._session_log_cursor.pop(previous_active, None)
                            await self._sync_session_cursor(self.active_session_id, initialize=True)
                            response, mode = await asyncio.to_thread(mcp.chat, self.active_session_id, text)
                    except Exception as exc:
                        await message.reply(f"Could not resume session: {exc}")
                        return
                except Exception as exc:
                    await message.reply(f"MCP error: {exc}")
                    return

            self._pending_narrator_echo[self.active_session_id] = response.strip()

            speaker = "Narrator (meta)" if mode == "meta" else "Narrator"
            out = f"**{speaker}:** {response}"
            for chunk in split_discord_message(out):
                await message.channel.send(chunk)

    client = _DiscordBridgeClient()
    client.run(settings.discord_token)
