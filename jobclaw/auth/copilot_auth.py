"""GitHub Copilot authentication.

Strategy:
1. Try to read token from VS Code's Copilot extension storage (SQLite DB)
2. Fall back to manually saved token (~/.jobclaw/auth/copilot.json)
3. Offer device flow login with the correct VS Code client ID

The key insight: GitHub's /copilot_internal/v2/token endpoint only accepts
tokens issued by approved OAuth apps (VS Code, JetBrains, etc.). We read
the token that VS Code already obtained.
"""

from __future__ import annotations

import json
import logging
import platform
import sqlite3
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# VS Code's GitHub OAuth App client IDs
_VSCODE_CLIENT_ID = "01ab8ac9400c4e429b23"  # VS Code GitHub Auth
_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"

_CREDENTIALS_DIR = Path.home() / ".jobclaw" / "auth"
_CREDENTIALS_FILE = _CREDENTIALS_DIR / "copilot.json"


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


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

def _save_credentials(github_token: str, source: str = "manual") -> None:
    """Persist GitHub OAuth token to disk."""
    _CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "github_token": github_token,
        "source": source,
        "saved_at": int(time.time()),
    }
    _CREDENTIALS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        import os
        import stat
        os.chmod(_CREDENTIALS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    logger.info("GitHub token saved to %s (source=%s)", _CREDENTIALS_FILE, source)


def load_github_token() -> str | None:
    """Load persisted GitHub OAuth token, or None."""
    if not _CREDENTIALS_FILE.exists():
        return None
    try:
        data = json.loads(_CREDENTIALS_FILE.read_text(encoding="utf-8"))
        return data.get("github_token")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# VS Code token extraction
# ---------------------------------------------------------------------------

def _get_vscode_db_paths() -> list[Path]:
    """Return possible paths for VS Code's state.vscdb / github auth DB."""
    system = platform.system()
    candidates: list[Path] = []

    if system == "Windows":
        appdata = Path.home() / "AppData" / "Roaming"
        for variant in ["Code", "Code - Insiders"]:
            candidates.append(appdata / variant / "User" / "globalStorage" / "state.vscdb")
    elif system == "Darwin":
        support = Path.home() / "Library" / "Application Support"
        for variant in ["Code", "Code - Insiders"]:
            candidates.append(support / variant / "User" / "globalStorage" / "state.vscdb")
    else:  # Linux
        config = Path.home() / ".config"
        for variant in ["Code", "Code - Insiders"]:
            candidates.append(config / variant / "User" / "globalStorage" / "state.vscdb")

    return candidates


def _extract_token_from_vscode_db(db_path: Path) -> str | None:
    """Try to extract the GitHub Copilot OAuth token from VS Code's SQLite DB.

    VS Code stores auth sessions in state.vscdb under keys like:
    - github.auth (JSON with sessions containing accessToken)
    - github.copilot (may contain token directly)
    """
    if not db_path.exists():
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Try common key patterns for GitHub auth sessions
        key_patterns = [
            "github.auth",
            "github-enterprise.auth",
        ]

        for key_pattern in key_patterns:
            try:
                cursor.execute(
                    "SELECT value FROM ItemTable WHERE key = ?",
                    (key_pattern,),
                )
                row = cursor.fetchone()
                if not row:
                    continue

                raw = row[0]
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")

                data = json.loads(raw)

                # data is typically a JSON string containing sessions
                if isinstance(data, str):
                    data = json.loads(data)

                # Look for sessions with accessToken
                sessions = []
                if isinstance(data, list):
                    sessions = data
                elif isinstance(data, dict):
                    sessions = data.get("sessions", data.get("accounts", []))
                    if not sessions and "accessToken" in data:
                        return data["accessToken"]

                for session in sessions:
                    if isinstance(session, dict):
                        token = session.get("accessToken")
                        if token and isinstance(token, str):
                            # Prefer tokens that start with gho_ (OAuth) or ghu_ (user)
                            if token.startswith(("gho_", "ghu_")):
                                conn.close()
                                return token
                        # Sometimes nested
                        account = session.get("account", {})
                        if isinstance(account, dict):
                            token = account.get("accessToken")
                            if token:
                                conn.close()
                                return token

            except (json.JSONDecodeError, sqlite3.OperationalError):
                continue

        conn.close()
    except Exception as e:
        logger.debug("Failed to read VS Code DB %s: %s", db_path, e)

    return None


def extract_vscode_copilot_token() -> str | None:
    """Try all known VS Code DB locations and extract the GitHub token.

    Returns:
        GitHub OAuth token string, or None if not found.
    """
    for db_path in _get_vscode_db_paths():
        logger.debug("Checking VS Code DB: %s", db_path)
        token = _extract_token_from_vscode_db(db_path)
        if token:
            logger.info("Found GitHub token in VS Code DB: %s", db_path)
            return token
    return None


# ---------------------------------------------------------------------------
# Copilot token exchange
# ---------------------------------------------------------------------------

async def get_copilot_token(github_token: str | None = None) -> CopilotToken:
    """Exchange GitHub OAuth token for a Copilot session token.

    Tries multiple token sources:
    1. Provided github_token parameter
    2. Saved token from ~/.jobclaw/auth/copilot.json
    3. VS Code's local storage (auto-extract)
    """
    if github_token is None:
        github_token = load_github_token()

    if github_token is None:
        # Try VS Code extraction
        github_token = extract_vscode_copilot_token()
        if github_token:
            _save_credentials(github_token, source="vscode-auto")
            logger.info("Auto-extracted token from VS Code")

    if not github_token:
        raise RuntimeError(
            "No GitHub token found.\n"
            "Options:\n"
            "  1. Run: jobclaw login-llm --provider copilot  (if you have VS Code + Copilot)\n"
            "  2. Set OPENAI_API_KEY or ANTHROPIC_API_KEY in .env"
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            _COPILOT_TOKEN_URL,
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/json",
                "Editor-Version": "vscode/1.96.0",
                "Editor-Plugin-Version": "copilot/1.250.0",
                "User-Agent": "GithubCopilot/1.250.0",
            },
        )

        if resp.status_code == 401:
            raise RuntimeError(
                "GitHub token is invalid or expired.\n"
                "Run: jobclaw login-llm --provider copilot"
            )
        if resp.status_code == 403:
            detail = resp.text[:500] if resp.text else "No details"
            raise RuntimeError(
                f"Copilot token exchange returned 403.\n"
                f"  Response: {detail}\n\n"
                f"  This usually means the token was not issued by an approved Copilot client.\n"
                f"  Solution: Make sure VS Code + GitHub Copilot extension is installed and signed in,\n"
                f"  then run: jobclaw login-llm --provider copilot\n"
                f"  Subscription: https://github.com/settings/copilot"
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
    """Get a valid Copilot chat token, refreshing if needed."""
    token = await get_copilot_token(github_token)
    if not token.copilot_token:
        raise RuntimeError("Failed to get Copilot token.")
    return token.copilot_token


# ---------------------------------------------------------------------------
# CLI login flow
# ---------------------------------------------------------------------------

def login_interactive() -> str | None:
    """Interactive login: try VS Code extraction first, then manual token input.

    Returns:
        GitHub OAuth token, or None if user cancels.
    """
    import click

    click.echo("\n🔐 GitHub Copilot Login")
    click.echo("=" * 50)

    # Step 1: Try auto-extraction from VS Code
    click.echo("\n📂 Searching for VS Code Copilot token...")
    token = extract_vscode_copilot_token()
    if token:
        click.echo(click.style("  ✅ Found token in VS Code!", fg="green"))
        click.echo(f"  Token: {token[:8]}...{token[-4:]}")
        _save_credentials(token, source="vscode-auto")
        return token

    click.echo("  ❌ VS Code token not found.")
    click.echo("\n  Possible reasons:")
    click.echo("    - VS Code is not installed")
    click.echo("    - GitHub Copilot extension not installed/signed in")
    click.echo("    - VS Code stores credentials in system keychain (not SQLite)")

    # Step 2: Manual token input
    click.echo("\n📋 Manual token input:")
    click.echo("  1. Open VS Code")
    click.echo("  2. Press Ctrl+Shift+P → 'GitHub Copilot: Sign In'")
    click.echo("  3. After signing in, press Ctrl+Shift+P → 'Developer: Open State DB'")
    click.echo("     or check: https://github.com/settings/tokens")
    click.echo("  4. Create a token with 'copilot' scope")
    click.echo()

    manual_token = click.prompt(
        "Paste your GitHub token (or 'skip' to cancel)",
        default="skip",
        show_default=False,
    )

    if manual_token.lower() == "skip":
        click.echo("Skipped.")
        return None

    manual_token = manual_token.strip()
    if not manual_token:
        click.echo("Empty token, skipped.")
        return None

    _save_credentials(manual_token, source="manual-input")
    click.echo(click.style("  ✅ Token saved!", fg="green"))
    return manual_token
