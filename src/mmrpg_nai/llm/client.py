"""LLM client wrapping OpenAI-compatible providers (OpenAI/Copilot/Ollama)."""

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


def _provider_label(provider: str) -> str:
    labels = {
        "openai": "OpenAI",
        "github_copilot": "GitHub Copilot",
        "ollama": "OpenWebUI/Ollama",
    }
    return labels.get(provider, provider)


def _build_client(cfg: LLMConfig) -> OpenAI:
    cfg = cfg.resolved(os.environ)
    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        provider = _provider_label(cfg.provider)
        raise EnvironmentError(
            f"Environment variable {cfg.api_key_env!r} is not set or is empty.\n"
            f"Detected provider: {provider}\n"
            f"  1. Set {cfg.api_key_env} for your {provider} connection\n"
            "  2. Or update llm.provider_settings in config.json\n"
            "  3. Re-run your command."
        )
    return OpenAI(base_url=cfg.api_base, api_key=api_key)


def _wrap_api_error(exc: Exception, cfg: LLMConfig) -> Exception:
    """Convert an OpenAI SDK exception into one with an actionable message."""
    provider = _provider_label(cfg.provider)
    if isinstance(exc, AuthenticationError):
        return PermissionError(
            f"Authentication failed (HTTP 401/403).\n"
            f"  • Check that {cfg.api_key_env!r} is valid for {provider}.\n"
            f"  • Confirm endpoint and provider config (provider={cfg.provider}, api_base={cfg.api_base}).\n"
            "  • Rotate/regenerate the key if needed."
        )
    if isinstance(exc, RateLimitError):
        return RuntimeError(
            f"Rate limit reached on {provider}.\n"
            "  • Wait a moment and try again.\n"
            "  • Check your provider quota and request limits."
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
            "  • Verify the model name is correct (run: mmrpg-nai config models).\n"
            f"  • Check model availability for provider={provider}."
        )
    return exc


class LLMClient:
    """Thin wrapper around the OpenAI client configured per detected provider."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg.resolved()
        self._client = _build_client(self.cfg)

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
        uses_completion_tokens = self.cfg.model.startswith(("gpt-5.", "gpt-5-"))
        token_param = "max_completion_tokens" if uses_completion_tokens else "max_tokens"
        kwargs: dict = dict(
            model=self.cfg.model,
            messages=messages,
            temperature=self.cfg.temperature,
            stream=stream,
        )
        kwargs[token_param] = self.cfg.max_tokens

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
