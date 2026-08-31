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
    ) -> None:
        """Initialise the conversation context for a new or resumed session."""
        self._session = session
        self._campaign = campaign
        self._party = party
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
