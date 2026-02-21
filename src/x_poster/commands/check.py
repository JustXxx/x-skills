"""
Check command - Verify environment setup for x-poster.

Checks:
1. Chrome installation
2. Chrome profile directory
3. Python version
4. Accessibility permissions (osascript)
5. Swift/clipboard compilation
6. Existing Chrome CDP instances
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import List, Tuple

import click

from ..chrome import CHROME_PATHS, DEFAULT_PROFILE_DIR, find_chrome

logger = logging.getLogger(__name__)


def _check_chrome() -> Tuple[bool, str]:
    """Check if Chrome is installed and accessible."""
    try:
        path = find_chrome()
        return True, f"Chrome found: {path}"
    except Exception as e:
        return False, str(e)


def _check_profile(profile_dir: str) -> Tuple[bool, str]:
    """Check Chrome profile directory."""
    if os.path.isdir(profile_dir):
        # Check for login indicators
        cookies = os.path.join(profile_dir, "Default", "Cookies")
        if os.path.exists(cookies):
            return True, f"Profile exists with cookies: {profile_dir}"
        return True, f"Profile exists (may need login): {profile_dir}"
    return True, f"Profile will be created at: {profile_dir}"


def _check_python() -> Tuple[bool, str]:
    """Check Python version."""
    version = sys.version_info
    if version >= (3, 9):
        return True, f"Python {version.major}.{version.minor}.{version.micro}"
    return False, f"Python {version.major}.{version.minor} (need >= 3.9)"


def _check_accessibility() -> Tuple[bool, str]:
    """Check macOS Accessibility permissions for osascript."""
    try:
        result = subprocess.run(
            [
                "osascript", "-e",
                'tell application "System Events" to return name of first process',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, "Accessibility permissions granted"
        if "not allowed" in result.stderr.lower() or "1002" in result.stderr:
            return False, (
                "Accessibility permissions not granted.\n"
                "  Go to: System Preferences > Privacy & Security > Accessibility\n"
                "  Add your terminal app (Terminal.app / iTerm2 / VS Code)"
            )
        return False, f"osascript error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "osascript timed out"
    except FileNotFoundError:
        return False, "osascript not found (not macOS?)"


def _check_swift() -> Tuple[bool, str]:
    """Check Swift compiler availability."""
    swiftc = shutil.which("swiftc")
    if swiftc:
        try:
            result = subprocess.run(
                ["swiftc", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            version_line = result.stdout.strip().split("\n")[0]
            return True, f"Swift: {version_line}"
        except Exception:
            return True, f"Swift found: {swiftc}"
    return False, (
        "Swift compiler (swiftc) not found.\n"
        "  Install Xcode Command Line Tools: xcode-select --install"
    )


def _check_clipboard() -> Tuple[bool, str]:
    """Check clipboard functionality."""
    try:
        from ..clipboard import _ensure_compiled, SWIFT_IMAGE_SOURCE
        binary = _ensure_compiled(SWIFT_IMAGE_SOURCE, "clipboard-image")
        return True, f"Clipboard binary ready: {binary}"
    except Exception as e:
        return False, f"Clipboard compilation failed: {e}"


def _check_chrome_instances() -> Tuple[bool, str]:
    """Check for existing Chrome CDP instances."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "Chrome.*remote-debugging-port"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split("\n")
            return True, (
                f"Found {len(pids)} existing Chrome CDP instance(s) (PIDs: {', '.join(pids)})\n"
                f"  These can be reused or kill with: pkill -f 'Chrome.*remote-debugging-port'"
            )
        return True, "No existing Chrome CDP instances"
    except Exception:
        return True, "Could not check Chrome instances"


def _check_dependencies() -> Tuple[bool, str]:
    """Check Python package dependencies."""
    missing = []
    packages = ["click", "websockets", "markdown", "pygments", "yaml"]
    import_names = {
        "yaml": "pyyaml",
        "pygments": "Pygments",
    }

    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            pip_name = import_names.get(pkg, pkg)
            missing.append(pip_name)

    if missing:
        return False, f"Missing packages: {', '.join(missing)}\n  pip install {' '.join(missing)}"
    return True, "All dependencies installed"


@click.command()
@click.pass_context
def check(ctx: click.Context) -> None:
    """Check environment setup and permissions.

    Verifies that all prerequisites are met for using x-poster.
    """
    profile = ctx.obj.get("profile") or DEFAULT_PROFILE_DIR

    checks = [
        ("Chrome", _check_chrome),
        ("Profile", lambda: _check_profile(profile)),
        ("Python", _check_python),
        ("Dependencies", _check_dependencies),
        ("Swift Compiler", _check_swift),
        ("Accessibility", _check_accessibility),
        ("Clipboard", _check_clipboard),
        ("Chrome Instances", _check_chrome_instances),
    ]

    click.echo("🔍 x-poster Environment Check\n")

    all_passed = True
    for name, check_fn in checks:
        try:
            passed, message = check_fn()
        except Exception as e:
            passed = False
            message = f"Check error: {e}"

        icon = "✅" if passed else "❌"
        if not passed:
            all_passed = False

        click.echo(f"  {icon} {name}: {message}")
        click.echo()

    if all_passed:
        click.echo("🎉 All checks passed! Ready to post.")
    else:
        click.echo("⚠️  Some checks failed. Fix the issues above before posting.")
        raise SystemExit(1)
