"""GitHub Copilot OAuth device flow authentication.

Uses GitHub's device code flow to obtain an OAuth token,
then exchanges it for a Copilot chat token that can call
the Copilot Chat completions API (OpenAI-compatible).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# GitHub OAuth app client ID (VS Code Copilot)
_GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"
_GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
_GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
_COPILOT_CHAT_URL = "https://api.githubcopilot.com/chat/completions"

_CREDENTIALS_DIR = Path.home() / ".jobclaw" / "auth"
_CREDENTIALS_FILE = _CREDENTIALS_DIR / "copilot.json"

_SCOPES = "read:user"


class CopilotToken:
    """Holds GitHub OAuth token + Copilot session token."""

    def __init__(
        self,
        github_token: str,
        copilot_token: str | None = None,
        copilot_expires_at: int = 0,
    ) -> None:
        self.github_token = github_token
        self.copilot_token = copilot_token
        self.copilot_expires_at = copilot_expires_at

    @property
    def is_copilot_valid(self) -> bool:
        return (
            self.copilot_token is not None
            and self.copilot_expires_at > time.time() + 60
        )


def _save_credentials(github_token: str) -> None:
    """Persist GitHub OAuth token to disk."""
    _CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "github_token": github_token,
        "saved_at": int(time.time()),
    }
    _CREDENTIALS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Best-effort permission restriction
    try:
        import os, stat
        os.chmod(_CREDENTIALS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    logger.info("GitHub token saved to %s", _CREDENTIALS_FILE)


def load_github_token() -> str | None:
    """Load persisted GitHub OAuth token, or None."""
    if not _CREDENTIALS_FILE.exists():
        return None
    try:
        data = json.loads(_CREDENTIALS_FILE.read_text(encoding="utf-8"))
        return data.get("github_token")
    except Exception:
        return None


async def device_flow_login(timeout_minutes: int = 5) -> str:
    """Run GitHub device code OAuth flow.

    Prints a URL + code for the user to enter in their browser.
    Polls until authorized or timeout.

    Returns:
        GitHub OAuth access token.

    Raises:
        TimeoutError: If user doesn't authorize in time.
        RuntimeError: If the flow fails.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Request device code
        resp = await client.post(
            _GITHUB_DEVICE_CODE_URL,
            data={
                "client_id": _GITHUB_CLIENT_ID,
                "scope": _SCOPES,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        device_data = resp.json()

        device_code = device_data["device_code"]
        user_code = device_data["user_code"]
        verification_uri = device_data["verification_uri"]
        interval = device_data.get("interval", 5)

        print(f"\n🔐 GitHub Copilot Login")
        print(f"{'='*50}")
        print(f"1. Open this URL in your browser:")
        print(f"   → {verification_uri}")
        print(f"2. Enter this code: {user_code}")
        print(f"{'='*50}")
        print(f"Waiting for authorization...\n")

        # Step 2: Poll for access token
        deadline = time.time() + timeout_minutes * 60
        while time.time() < deadline:
            await _async_sleep(interval)

            token_resp = await client.post(
                _GITHUB_ACCESS_TOKEN_URL,
                data={
                    "client_id": _GITHUB_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            token_data = token_resp.json()

            error = token_data.get("error")
            if error == "authorization_pending":
                continue
            elif error == "slow_down":
                interval += 5
                continue
            elif error == "expired_token":
                raise TimeoutError("Device code expired. Please try again.")
            elif error == "access_denied":
                raise RuntimeError("Authorization denied by user.")
            elif error:
                raise RuntimeError(f"OAuth error: {error} — {token_data.get('error_description', '')}")

            access_token = token_data.get("access_token")
            if access_token:
                _save_credentials(access_token)
                print("✅ GitHub Copilot login successful!")
                return access_token

        raise TimeoutError(f"Login timed out after {timeout_minutes} minutes.")


async def get_copilot_token(github_token: str | None = None) -> CopilotToken:
    """Exchange GitHub OAuth token for a Copilot session token.

    The Copilot token is short-lived (~30 min) and used to call
    the Copilot Chat completions API.

    Args:
        github_token: GitHub OAuth token. If None, loads from disk.

    Returns:
        CopilotToken with both GitHub and Copilot tokens.

    Raises:
        RuntimeError: If token exchange fails (e.g. no Copilot subscription).
    """
    if github_token is None:
        github_token = load_github_token()
        if not github_token:
            raise RuntimeError(
                "No GitHub token found. Run: jobclaw login --platform copilot"
            )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _COPILOT_TOKEN_URL,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/json",
            },
        )

        if resp.status_code == 401:
            raise RuntimeError(
                "GitHub token is invalid or expired. "
                "Run: jobclaw login --platform copilot"
            )
        if resp.status_code == 403:
            raise RuntimeError(
                "No GitHub Copilot subscription found for this account. "
                "Make sure you have an active Copilot Individual or Business subscription."
            )
        resp.raise_for_status()
        data = resp.json()

    copilot_token = data.get("token")
    expires_at = data.get("expires_at", 0)

    if not copilot_token:
        raise RuntimeError("Failed to obtain Copilot token from GitHub.")

    logger.info("Copilot token obtained, expires at %d", expires_at)
    return CopilotToken(
        github_token=github_token,
        copilot_token=copilot_token,
        copilot_expires_at=expires_at,
    )


async def ensure_copilot_token(github_token: str | None = None) -> str:
    """Get a valid Copilot chat token, refreshing if needed.

    Returns:
        Copilot session token string ready for API calls.
    """
    token = await get_copilot_token(github_token)
    if not token.copilot_token:
        raise RuntimeError("Failed to get Copilot token.")
    return token.copilot_token


async def _async_sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)
