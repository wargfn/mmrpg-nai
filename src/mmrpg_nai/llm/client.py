"""LLM client wrapping the OpenAI-compatible GitHub Copilot / GPT-5.4 API."""

from __future__ import annotations

import os
from typing import Iterator

from openai import OpenAI

from mmrpg_nai.models.core import LLMConfig


def _build_client(cfg: LLMConfig) -> OpenAI:
    api_key = os.environ.get(cfg.api_key_env, "")
    if not api_key:
        raise EnvironmentError(
            f"Environment variable {cfg.api_key_env!r} is not set. "
            "Export your GitHub token (with 'models' permission) before running."
        )
    return OpenAI(base_url=cfg.api_base, api_key=api_key)


class LLMClient:
    """Thin wrapper around the OpenAI client configured for GitHub Copilot models."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._client = _build_client(cfg)

    def complete(self, messages: list[dict], stream: bool = False) -> str | Iterator[str]:
        """Send messages and return the full assistant response (or a streaming iterator)."""
        kwargs = dict(
            model=self.cfg.model,
            messages=messages,
            max_tokens=self.cfg.max_tokens,
            temperature=self.cfg.temperature,
            stream=stream,
        )
        if stream:
            response = self._client.chat.completions.create(**kwargs)

            def _iter() -> Iterator[str]:
                for chunk in response:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content

            return _iter()
        else:
            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
