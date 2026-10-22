"""
python/utils.py

Shared utilities for the IBM Cloud ToolKit Python implementation.

This module is the Python counterpart of bash/utils.sh.
It provides:
- Color constants for terminal output
- IBM Cloud CLI helper functions (access token, account ID, etc.)
- Dependency checks (ibmcloud CLI + plugins)
- Common output helpers (failure, warning)

Requirements: Python 3.8+, IBM Cloud CLI in PATH, authenticated session.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── Terminal Colors ───────────────────────────────────────────────────────────
# ANSI escape codes – disabled automatically when stdout is not a TTY.

def _ansi(code: str) -> str:
    """Return ANSI escape code only when stdout is a TTY."""
    if sys.stdout.isatty():
        return f"\033[{code}m"
    return ""


BOLD       = _ansi("1")
RESET      = _ansi("0")
BRIGHT_RED = _ansi("91")
CYAN       = _ansi("36")
YELLOW     = _ansi("33")
MAGENTA    = _ansi("35")
ORANGE     = _ansi("38;5;208")
BLUE       = _ansi("34")
GREEN      = _ansi("32")
RED        = _ansi("31")

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_OUTPUT_DIR = "output"
SEPARATOR = "=" * 82

# ── Low-level CLI runner ──────────────────────────────────────────────────────

def _run(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a command; returns CompletedProcess (stdout/stderr as str)."""
    return subprocess.run(
        args,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )


def _ibmcloud(*args: str) -> subprocess.CompletedProcess:
    return _run(["ibmcloud"] + list(args))


# ── IBM Cloud helpers ─────────────────────────────────────────────────────────

def ibmcloud_access_token() -> str:
    """Extract the bare IAM bearer token from the active CLI session."""
    result = _ibmcloud("iam", "oauth-tokens", "--output", "json")
    if result.returncode != 0:
        failure("Failed to retrieve IAM token. Are you logged in?")
    try:
        data = json.loads(result.stdout)
        token_with_bearer: str = data.get("iam_token", "")
        # Format is "Bearer eyJ..."
        parts = token_with_bearer.split(" ", 1)
        return parts[1] if len(parts) == 2 else parts[0]
    except (json.JSONDecodeError, IndexError):
        failure("Failed to parse IAM token response.")
    return ""  # unreachable; satisfies type checker


def ibmcloud_account_id() -> str:
    """Return the GUID of the currently targeted account."""
    result = _ibmcloud("target", "-o", "JSON")
    if result.returncode != 0:
        failure("Failed to retrieve account ID.")
    try:
        data = json.loads(result.stdout)
        return data["account"]["guid"]
    except (json.JSONDecodeError, KeyError):
        failure("Failed to parse account ID from 'ibmcloud target' output.")
    return ""


def ibmcloud_account_name() -> str:
    """Return the name of the currently targeted account."""
    result = _ibmcloud("target", "-o", "JSON")
    if result.returncode != 0:
        return "-"
    try:
        data = json.loads(result.stdout)
        return data["account"]["name"]
    except (json.JSONDecodeError, KeyError):
        return "-"


def is_ibmcloud_logged_in() -> bool:
    """Return True if the CLI has a valid session."""
    result = _ibmcloud("iam", "oauth-tokens")
    return result.returncode == 0


def get_regions() -> list[str]:
    """Return a list of enabled IBM Cloud region names."""
    result = _ibmcloud("regions", "--output", "json")
    if result.returncode != 0:
        failure("Could not retrieve regions. Retry.")
    try:
        data = json.loads(result.stdout)
        regions = [r["Name"] for r in data]
    except (json.JSONDecodeError, KeyError):
        failure("Failed to parse regions response.")
        regions = []
    if not regions:
        failure("No regions found. Please ensure you are logged in to IBM Cloud.")
    return regions


# ── Dependency checks ─────────────────────────────────────────────────────────

def check_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def require_ibmcloud() -> None:
    if not check_command("ibmcloud"):
        failure(
            f"Unable to find the {BOLD}IBM Cloud CLI{RESET}. "
            "Please install it and run this script again."
        )


def require_ibmcloud_login() -> None:
    require_ibmcloud()
    if not is_ibmcloud_logged_in():
        failure(
            f"IBM Cloud CLI not logged in. Please run {BOLD}'ibmcloud login'{RESET}."
        )


def _require_plugin(plugin_name: str, display_name: str) -> None:
    result = _ibmcloud("plugin", "list")
    if plugin_name not in result.stdout:
        failure(
            f"IBM Cloud plugin '{display_name}' is not installed. "
            f"Please run: ibmcloud plugin install {plugin_name}"
        )


def require_ibmcloud_cdb() -> None:
    _require_plugin("cloud-databases", "cloud-databases (cdb)")


def require_ibmcloud_is() -> None:
    _require_plugin("vpc-infrastructure", "vpc-infrastructure (is)")


def require_ibmcloud_sl() -> None:
    _require_plugin("sl", "sl")


def require_ibmcloud_schematics() -> None:
    _require_plugin("schematics", "schematics")


def require_ibmcloud_cos() -> None:
    _require_plugin("cloud-object-storage", "cloud-object-storage")


def require_ibmcloud_ce() -> None:
    _require_plugin("code-engine", "code-engine (ce)")


# ── Output helpers ────────────────────────────────────────────────────────────

def failure(msg: str) -> None:
    """Print an error message and exit with code 1."""
    print(f"{BOLD}{BRIGHT_RED}FAILED: {RESET}{msg}", file=sys.stderr)
    sys.exit(1)


def warning(msg: str) -> None:
    print(f"{BOLD}WARNING: {RESET}{msg}")


def print_console_link(label: str, url: str) -> None:
    """Print a styled IBM Cloud console link at the end of a module run."""
    print(f"{CYAN}IBM Cloud Console:{RESET} {label}")
    print(f"  {BOLD}{url}{RESET}")


def ensure_output_dir(path: str) -> Path:
    """Create the output directory if it does not exist."""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        failure(f"Error while creating the output directory: {path} ({exc})")
    return p


# ── Date helpers ──────────────────────────────────────────────────────────────

def days_since_iso(iso_timestamp: str) -> Optional[int]:
    """Return the number of days since *iso_timestamp* (ISO 8601), or None."""
    import datetime  # local import to keep module-level imports lean

    try:
        # Handle both 'Z' and '+00:00' suffixes
        ts = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        return (now - dt).days
    except (ValueError, TypeError):
        return None


# ── REST API helpers ──────────────────────────────────────────────────────────

def ibmcloud_get(url: str, token: str) -> Optional[dict]:
    """Perform a GET request to the IBM Cloud REST API.

    Returns the parsed JSON response, or None on failure.
    Uses only the standard library (urllib).
    """
    import urllib.request  # local import
    import urllib.error

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        warning(f"HTTP {exc.code} for {url}")
        return None
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        warning(f"Request failed for {url}: {exc}")
        return None
