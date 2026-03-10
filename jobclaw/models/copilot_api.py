"""Copilot Chat API client — OpenAI-compatible completions endpoint."""

from __future__ import annotations

import json
import logging

import httpx

from jobclaw.auth.copilot_auth import ensure_copilot_token, load_github_token

logger = logging.getLogger(__name__)

_COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"
_DEFAULT_MODEL = "gpt-4o"  # Copilot uses OpenAI models under the hood


class CopilotClient:
    """Async client for GitHub Copilot Chat completions API.

    The API is OpenAI-compatible and uses a short-lived Copilot token
    obtained by exchanging the GitHub OAuth token.
    """

    def __init__(
        self,
        github_token: str | None = None,
        *,
        model: str = _DEFAULT_MODEL,
        timeout: float = 120.0,
    ) -> None:
        self._github_token = github_token or load_github_token()
        self._copilot_token: str | None = None
        self.model = model
        self.timeout = timeout

    async def _ensure_token(self) -> str:
        """Get or refresh the Copilot session token."""
        if self._copilot_token is None:
            self._copilot_token = await ensure_copilot_token(self._github_token)
        return self._copilot_token

    async def chat(
        self,
        user_message: str,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """Send a chat completion request and return the full response text.

        Args:
            user_message: The user's message.
            system: Optional system prompt.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            The assistant's response text.
        """
        token = await self._ensure_token()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_message})

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Editor-Version": "vscode/1.96.0",
            "Editor-Plugin-Version": "copilot-chat/0.24.0",
            "Openai-Intent": "conversation-panel",
            "Copilot-Integration-Id": "vscode-chat",
        }

        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        parts: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", _COPILOT_CHAT_URL, headers=headers, json=body,
                ) as response:
                    if response.status_code == 401:
                        # Token expired, retry once
                        self._copilot_token = None
                        token = await self._ensure_token()
                        headers["Authorization"] = f"Bearer {token}"
                        # Fall through to non-streaming retry below
                        raise httpx.HTTPStatusError(
                            "401 retry", request=response.request, response=response,
                        )
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        choices = event.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                parts.append(content)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # One retry with fresh token
                self._copilot_token = None
                return await self._chat_no_stream(
                    user_message, system=system,
                    max_tokens=max_tokens, temperature=temperature,
                )
            raise

        return "".join(parts)

    async def _chat_no_stream(
        self,
        user_message: str,
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """Non-streaming fallback (used after token refresh)."""
        token = await self._ensure_token()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_message})

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Editor-Version": "vscode/1.96.0",
            "Editor-Plugin-Version": "copilot-chat/0.24.0",
            "Openai-Intent": "conversation-panel",
            "Copilot-Integration-Id": "vscode-chat",
        }

        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                _COPILOT_CHAT_URL, headers=headers, json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""
