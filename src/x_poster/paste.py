"""
macOS paste key simulation via osascript.

Sends real Cmd+V keystrokes through macOS System Events,
which bypasses X's detection of synthetic clipboard events.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TARGET_APP = "Google Chrome"


def send_paste(
    target_app: Optional[str] = None,
    retries: int = 1,
    delay: float = 0.5,
    pre_delay: float = 0.3,
) -> None:
    """Send a real Cmd+V paste keystroke via osascript.

    This activates the target application and sends a keystroke "v"
    using command down through System Events, which produces a real
    paste event that X cannot distinguish from human input.

    Args:
        target_app: Application name to activate before pasting
                   (default: "Google Chrome")
        retries: Number of retry attempts on failure
        delay: Delay between retries in seconds
        pre_delay: Delay before sending keystroke (to let app focus)

    Raises:
        RuntimeError: If paste fails after all retries
    """
    target_app = target_app or DEFAULT_TARGET_APP

    script = f'''
tell application "{target_app}"
    activate
end tell
delay {pre_delay}
tell application "System Events"
    keystroke "v" using command down
end tell
'''

    last_error = None
    for attempt in range(retries):
        if attempt > 0:
            time.sleep(delay)
            logger.debug("Paste retry %d/%d", attempt + 1, retries)

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                logger.debug("Paste keystroke sent to %s", target_app)
                return

            last_error = result.stderr.strip()
            logger.warning("osascript failed (attempt %d): %s", attempt + 1, last_error)

        except subprocess.TimeoutExpired:
            last_error = "osascript timed out"
            logger.warning("osascript timed out (attempt %d)", attempt + 1)

    raise RuntimeError(
        f"Failed to send paste keystroke after {retries} attempts: {last_error}\n"
        "Make sure:\n"
        "  1. Terminal/IDE has Accessibility permissions in System Preferences\n"
        "  2. Google Chrome is running and not minimized\n"
        "  3. System Preferences > Privacy & Security > Accessibility"
    )


def send_key(
    key: str,
    modifiers: Optional[str] = None,
    target_app: Optional[str] = None,
) -> None:
    """Send an arbitrary keystroke via osascript.

    Args:
        key: Key to press (e.g. "v", "a", "return")
        modifiers: Modifier string (e.g. "command down", "command down, shift down")
        target_app: App to activate first
    """
    target_app = target_app or DEFAULT_TARGET_APP

    if modifiers:
        keystroke_line = f'keystroke "{key}" using {{{modifiers}}}'
    else:
        keystroke_line = f'keystroke "{key}"'

    script = f'''
tell application "{target_app}"
    activate
end tell
delay 0.2
tell application "System Events"
    {keystroke_line}
end tell
'''

    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        raise RuntimeError(f"osascript keystroke failed: {result.stderr}")
