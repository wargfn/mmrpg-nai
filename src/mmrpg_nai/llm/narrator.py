"""Narrator engine: builds prompts and manages conversation state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

from mmrpg_nai.llm.client import LLMClient
from mmrpg_nai.models.core import (
    Campaign,
    Character,
    LogEntry,
    NarratorConfig,
    Session,
    SourceMaterial,
)
from mmrpg_nai.storage.store import Store


class Narrator:
    """Drives a live session, maintaining the message history and persisting the log."""

    def __init__(self, cfg: NarratorConfig, store: Store) -> None:
        self.cfg = cfg
        self.store = store
        self.llm = LLMClient(cfg.llm)
        self._messages: list[dict] = []

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(
        self,
        session: Session,
        campaign: Campaign,
        party: list[Character],
        source_materials: list[SourceMaterial] | None = None,
    ) -> None:
        """Initialise the conversation context for a new or resumed session."""
        self._session = session
        self._campaign = campaign
        self._party = party
        self._source_materials: list[SourceMaterial] = source_materials or []
        self._messages = self._build_system_messages(session, campaign, party)

    def _build_system_messages(
        self,
        session: Session,
        campaign: Campaign,
        party: list[Character],
    ) -> list[dict]:
        parts = [self.cfg.system_prompt]

        # Campaign context
        parts.append(
            f"\n## Campaign: {campaign.name}\n{campaign.description}\n"
            f"Tone: {campaign.settings.tone}  Era: {campaign.settings.era}  "
            f"Location: {campaign.settings.location}"
        )

        # Campaign plan and progress
        if campaign.plan:
            parts.append(f"\n## Campaign Plan\n{campaign.plan}")
        if campaign.campaign_progress:
            parts.append(
                f"\n## Campaign Progress\n"
                f"The following summarises what has happened so far in this campaign "
                f"and where the story currently stands against the plan:\n\n"
                f"{campaign.campaign_progress}"
            )

        # Party
        if party:
            parts.append("\n## Player Characters")
            for ch in party:
                parts.append(
                    f"- **{ch.name}** ({ch.alias}) Rank: {ch.rank.value} Tier {ch.tier}. {ch.background}"
                )

        # Resume from log
        if session.synopsis:
            parts.append(f"\n## Session Synopsis\n{session.synopsis}")

        # Inject any extra system prompts from config
        for key, prompt in self.cfg.extra_prompts.items():
            parts.append(f"\n## {key}\n{prompt}")

        # Source material injection
        if self.cfg.max_source_chars > 0 and getattr(self, "_source_materials", None):
            from mmrpg_nai.pdf.ingestion import load_source_text

            remaining = self.cfg.max_source_chars
            source_parts: list[str] = []
            for mat in self._source_materials:
                if remaining <= 0:
                    break
                text = load_source_text(mat, max_chars=remaining)
                if text:
                    source_parts.append(f"### {mat.title}\n{text}")
                    remaining -= len(text)
            if source_parts:
                parts.append("\n## Rules & Source Materials\n" + "\n\n".join(source_parts))

        system_content = "\n".join(parts)
        messages: list[dict] = [{"role": "system", "content": system_content}]

        # Replay existing log entries as conversation history
        for entry in session.log:
            role = "assistant" if entry.role == "narrator" else "user"
            messages.append({"role": role, "content": entry.content})

        return messages

    # ------------------------------------------------------------------
    # Narration
    # ------------------------------------------------------------------

    def narrate(
        self,
        player_input: str,
        stream: bool = True,
        output_callback=None,
    ) -> str:
        """Send player input to the LLM and return the narrator response.

        Args:
            player_input: The player's action or dialogue.
            stream: Whether to stream the response token-by-token.
            output_callback: Optional callable(chunk: str) called for each
                streamed chunk.  Defaults to ``print`` when streaming is
                enabled and no callback is provided.
        """
        self._messages.append({"role": "user", "content": player_input})
        self._log(role="player", content=player_input)

        result = self.llm.complete(self._messages, stream=stream)

        if isinstance(result, str):
            response = result
        else:
            # Streaming: deliver chunks via callback
            if output_callback is None:
                def output_callback(chunk: str) -> None:
                    print(chunk, end="", flush=True)

            chunks: list[str] = []
            for chunk in result:
                output_callback(chunk)
                chunks.append(chunk)
            print()
            response = "".join(chunks)

        self._messages.append({"role": "assistant", "content": response})
        self._log(role="narrator", content=response)
        self.store.append_log(self._session)
        return response

    def meta_direction(self, direction: str, stream: bool = True, output_callback=None) -> str:
        """Handle an out-of-game meta direction from the player.

        The direction is injected into the conversation as a system-level note
        so the LLM understands it is a narrator/GM instruction, not in-world
        dialogue.  It is logged with role ``"meta"`` so it can be distinguished
        from regular play in the session log.
        """
        system_note = f"[OUT-OF-GAME NARRATOR DIRECTION]: {direction}"
        self._messages.append({"role": "system", "content": system_note})
        self._log(role="meta", content=direction)

        result = self.llm.complete(self._messages, stream=stream)

        if isinstance(result, str):
            response = result
        else:
            if output_callback is None:
                def output_callback(chunk: str) -> None:
                    print(chunk, end="", flush=True)

            chunks: list[str] = []
            for chunk in result:
                output_callback(chunk)
                chunks.append(chunk)
            print()
            response = "".join(chunks)

        self._messages.append({"role": "assistant", "content": response})
        self._log(role="narrator", content=response)
        self.store.append_log(self._session)
        return response

    def recap_last_session(self, last_session: "Session") -> str:
        """Generate a brief AI recap of the previous session to open the current one."""
        if not last_session.log:
            if last_session.synopsis:
                raw = last_session.synopsis
            else:
                return ""
        else:
            # Build a condensed transcript from the last session log
            lines = []
            for entry in last_session.log:
                if entry.role in ("player", "narrator"):
                    lines.append(f"{entry.role.capitalize()}: {entry.content}")
            raw = "\n".join(lines[-60:])  # last 60 exchanges max

        messages = [
            {"role": "system", "content": self.cfg.system_prompt},
            {
                "role": "user",
                "content": (
                    "Write a brief (3-5 sentence) 'previously on…' recap of the last session "
                    "suitable for reading aloud at the start of tonight's game. "
                    "Draw only from the session content below.\n\n"
                    f"{raw}"
                ),
            },
        ]
        return self.llm.complete(messages, stream=False)  # type: ignore[return-value]

    def plan_campaign(self, brief: str) -> str:
        """Ask the LLM to draft a campaign plan from a brief description."""
        messages = [
            {"role": "system", "content": self.cfg.system_prompt},
            {
                "role": "user",
                "content": (
                    f"Draft a detailed Marvel Multiverse RPG campaign plan based on this brief:\n\n{brief}\n\n"
                    "Include: title, synopsis, 3-5 adventure hooks, major NPCs, key locations, "
                    "and recommended rank/tier progression."
                ),
            },
        ]
        return self.llm.complete(messages, stream=False)  # type: ignore[return-value]

    def summarise_campaign_progress(
        self,
        campaign: Campaign,
        completed_sessions: "list[Session]",
    ) -> str:
        """Generate an updated campaign-progress summary after a session.

        The summary reflects how far the story has progressed against the plan and
        what major beats, reveals, and unresolved threads remain.
        """
        # Build a condensed transcript of all completed sessions
        session_summaries: list[str] = []
        for i, s in enumerate(completed_sessions, 1):
            lines = [f"### Session {i}: {s.title}"]
            if s.synopsis:
                lines.append(s.synopsis)
            for entry in s.log:
                if entry.role in ("player", "narrator"):
                    lines.append(f"{entry.role.capitalize()}: {entry.content}")
            session_summaries.append("\n".join(lines[-40:]))  # cap per session

        history = "\n\n".join(session_summaries[-5:])  # last 5 sessions max

        plan_section = f"\n\nCampaign Plan:\n{campaign.plan}" if campaign.plan else ""
        prior_progress = (
            f"\n\nPrevious progress summary:\n{campaign.campaign_progress}"
            if campaign.campaign_progress
            else ""
        )

        messages = [
            {"role": "system", "content": self.cfg.system_prompt},
            {
                "role": "user",
                "content": (
                    f"You are tracking the narrative progress of a Marvel Multiverse RPG campaign "
                    f"called '{campaign.name}'."
                    f"{plan_section}"
                    f"{prior_progress}"
                    f"\n\nSession history (most recent sessions):\n{history}\n\n"
                    "Write a concise (5-8 sentences) progress update that:\n"
                    "1. States which plan milestones have been completed\n"
                    "2. Describes where the story currently stands\n"
                    "3. Lists key unresolved threads and upcoming beats\n"
                    "Write in past tense, factual, suitable as a briefing for the next session's Narrator."
                ),
            },
        ]
        return self.llm.complete(messages, stream=False)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, role: str, content: str) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            role=role,
            content=content,
        )
        self._session.log.append(entry)
