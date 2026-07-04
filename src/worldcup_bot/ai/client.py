"""Thin async wrapper around an OpenAI-compatible endpoint (e.g. LiteLLM).

Keeps the external SDK out of handlers/jobs so it stays mockable in tests.
Accepts an optional _client argument for dependency injection in tests.
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

log = logging.getLogger(__name__)


class AIError(Exception):
    """Raised when the AI backend returns an error."""


class AIClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        _client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        self._client = _client or AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def aclose(self) -> None:
        """Close the underlying AsyncOpenAI httpx client.

        Per-event AIClient instances (goal enrichment, match recap) must be
        closed after use or their httpx connection pools accumulate and leak
        memory.  Best-effort: never raises.
        """
        try:
            await self._client.close()
        except Exception as exc:
            log.debug("AIClient.aclose error: %s", exc)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.7,
        max_completion_tokens: int = 600,
    ) -> str:
        """Call the chat completions endpoint and return the stripped response text."""
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            log.error("AIClient.complete error: %s", exc)
            raise AIError(str(exc)) from exc
