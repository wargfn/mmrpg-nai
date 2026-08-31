"""LLM client wrapping the OpenAI-compatible GitHub Copilot / GPT-5.4 API."""

from __future__ import annotations

import os
import time
from typing import Iterator

from openai import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from mmrpg_nai.models.core import LLMConfig

# Maximum number of automatic retries for transient connection errors.
_MAX_RETRIES = 2
_RETRY_DELAY = 2.0  # seconds between retries


def _build_client(cfg: LLMConfig) -> OpenAI:
    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        raise EnvironmentError(
            f"Environment variable {cfg.api_key_env!r} is not set or is empty.\n"
            "  1. Create a GitHub Personal Access Token at https://github.com/settings/tokens\n"
            "  2. Enable GitHub Copilot on your account (https://github.com/features/copilot)\n"
            "  3. Export it:  export GITHUB_TOKEN=ghp_...\n"
            "  Or add it to your .env file and re-run."
        )
    return OpenAI(base_url=cfg.api_base, api_key=api_key)


def _wrap_api_error(exc: Exception, cfg: LLMConfig) -> Exception:
    """Convert an OpenAI SDK exception into one with an actionable message."""
    if isinstance(exc, AuthenticationError):
        return PermissionError(
            f"Authentication failed (HTTP 401/403).\n"
            f"  • Check that {cfg.api_key_env!r} is a valid GitHub token.\n"
            "  • You need an active GitHub Copilot subscription (https://github.com/features/copilot).\n"
            "  • Tokens expire — generate a new one at https://github.com/settings/tokens"
        )
    if isinstance(exc, RateLimitError):
        return RuntimeError(
            "Rate limit reached on the GitHub Copilot API.\n"
            "  • Wait a moment and try again.\n"
            "  • Free-tier accounts have per-minute request limits."
        )
    if isinstance(exc, APIConnectionError):
        return ConnectionError(
            f"Could not reach the API endpoint: {cfg.api_base}\n"
            "  • Check your internet connection.\n"
            f"  • Verify 'api_base' in your config (current: {cfg.api_base}).\n"
            "  • If behind a proxy, set HTTPS_PROXY in your environment."
        )
    if isinstance(exc, APIStatusError):
        return RuntimeError(
            f"API returned HTTP {exc.status_code}.\n"
            f"  Response: {exc.message}\n"
            f"  Model requested: {cfg.model}\n"
            "  • Verify the model name is correct (e.g. 'gpt-5.4').\n"
            "  • Check https://github.com/marketplace/models for available models."
        )
    return exc


class LLMClient:
    """Thin wrapper around the OpenAI client configured for GitHub Copilot models."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self._client = _build_client(cfg)

    def complete(self, messages: list[dict], stream: bool = False) -> str | Iterator[str]:
        """Send messages and return the full assistant response (or a streaming iterator).

        Non-streaming calls retry on ``APIConnectionError`` up to ``_MAX_RETRIES``
        additional times (so at most ``_MAX_RETRIES + 1`` total attempts) with an
        exponential back-off delay.  Authentication and rate-limit errors are surfaced
        immediately without retrying.

        Streaming calls return a generator; the initial ``create()`` call participates
        in the retry loop, but errors raised *during* iteration are wrapped and
        re-raised without a retry (retrying mid-stream is not safe).
        """
        kwargs: dict = dict(
            model=self.cfg.model,
            messages=messages,
            max_tokens=self.cfg.max_tokens,
            temperature=self.cfg.temperature,
            stream=stream,
        )

        last_exc: Exception | None = None
        # attempt is 0-indexed: attempt 0 is the first try, 1..._MAX_RETRIES are retries.
        for attempt in range(_MAX_RETRIES + 1):
            try:
                if stream:
                    response = self._client.chat.completions.create(**kwargs)

                    def _iter(resp=response) -> Iterator[str]:
                        try:
                            for chunk in resp:
                                delta = chunk.choices[0].delta
                                if delta.content:
                                    yield delta.content
                        except (APIConnectionError, APIStatusError, AuthenticationError, RateLimitError) as exc:
                            raise _wrap_api_error(exc, self.cfg) from exc

                    return _iter()
                else:
                    response = self._client.chat.completions.create(**kwargs)
                    return response.choices[0].message.content or ""

            except (AuthenticationError, RateLimitError, APIStatusError) as exc:
                # Non-retryable errors — surface immediately.
                raise _wrap_api_error(exc, self.cfg) from exc
            except APIConnectionError as exc:
                last_exc = _wrap_api_error(exc, self.cfg)
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                    continue
            except Exception:
                raise

        assert last_exc is not None
        raise last_exc
