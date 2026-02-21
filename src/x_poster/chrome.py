"""
Chrome browser lifecycle management for macOS.

Handles:
- Finding Chrome executable on macOS
- Launching Chrome with CDP remote debugging
- Port allocation with locking to avoid race conditions
- Exponential backoff connection with process health monitoring
- Reusing existing Chrome CDP instances
- Graceful cleanup on exit
"""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import logging
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import json
import urllib.request
import urllib.error

from .cdp_client import CdpClient

logger = logging.getLogger(__name__)

# macOS Chrome executable candidates (ordered by preference)
CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]

DEFAULT_PROFILE_DIR = os.path.expanduser("~/.local/share/x-poster-profile")


class ChromeError(Exception):
    """Chrome launch or connection error."""
    pass


class ChromeSession:
    """Holds a Chrome CDP session with cleanup capabilities.

    Attributes:
        cdp: The CDP client instance
        session_id: The attached target session ID
        target_id: The page target ID
        process: The Chrome subprocess (None if reusing existing)
        port: The CDP debugging port
    """

    def __init__(
        self,
        cdp: CdpClient,
        session_id: str,
        target_id: str,
        process: Optional[subprocess.Popen] = None,
        port: int = 0,
        profile_dir: str = "",
    ):
        self.cdp = cdp
        self.session_id = session_id
        self.target_id = target_id
        self.process = process
        self.port = port
        self.profile_dir = profile_dir
        self._cleaned_up = False

    async def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        """Shortcut to Runtime.evaluate on this session."""
        params = {
            "expression": expression,
            "returnByValue": True,
        }
        if await_promise:
            params["awaitPromise"] = True
        result = await self.cdp.send(
            "Runtime.evaluate", params, session_id=self.session_id
        )
        if "exceptionDetails" in result:
            exc = result["exceptionDetails"]
            text = exc.get("text", "")
            if "exception" in exc:
                text = exc["exception"].get("description", text)
            raise RuntimeError(f"JS evaluation error: {text}")
        return result.get("result", {}).get("value")

    async def navigate(self, url: str, wait_event: str = "Page.loadEventFired", timeout: float = 30.0) -> None:
        """Navigate to URL and wait for page load."""
        load_future = asyncio.get_event_loop().create_future()

        def on_load(params: dict) -> None:
            if not load_future.done():
                load_future.set_result(True)

        self.cdp.on(wait_event, on_load)
        try:
            await self.cdp.send(
                "Page.navigate", {"url": url}, session_id=self.session_id
            )
            await asyncio.wait_for(load_future, timeout=timeout)
        finally:
            self.cdp.off(wait_event, on_load)

    async def cleanup(self) -> None:
        """Close CDP connection and terminate Chrome process if we launched it."""
        if self._cleaned_up:
            return
        self._cleaned_up = True

        try:
            await self.cdp.close()
        except Exception:
            pass

        if self.process:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            except Exception:
                pass
            logger.debug("Chrome process terminated")


def find_chrome(chrome_path: Optional[str] = None) -> str:
    """Find Chrome executable on macOS.

    Args:
        chrome_path: Optional explicit path override.
                     Also checks CHROME_PATH environment variable.

    Returns:
        Path to Chrome executable

    Raises:
        ChromeError: If Chrome is not found
    """
    # Check explicit path
    if chrome_path:
        if os.path.isfile(chrome_path) and os.access(chrome_path, os.X_OK):
            return chrome_path
        raise ChromeError(f"Chrome not found at specified path: {chrome_path}")

    # Check environment variable
    env_path = os.environ.get("CHROME_PATH")
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path

    # Search known macOS paths
    for path in CHROME_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    raise ChromeError(
        "Chrome not found. Install Google Chrome or set CHROME_PATH environment variable.\n"
        "Searched paths:\n" + "\n".join(f"  - {p}" for p in CHROME_PATHS)
    )


def _get_free_port() -> Tuple[int, socket.socket]:
    """Get a free port and return both port number and the holding socket.

    The socket is kept open to prevent port reuse race conditions.
    Caller must close the socket after Chrome has started binding to the port.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    return port, sock


def _clean_devtools_port_file(profile_dir: str) -> None:
    """Remove stale DevToolsActivePort file from profile directory."""
    port_file = os.path.join(profile_dir, "DevToolsActivePort")
    if os.path.exists(port_file):
        try:
            os.remove(port_file)
            logger.debug("Removed stale DevToolsActivePort file")
        except OSError:
            pass


async def _probe_cdp_http(port: int, timeout: float = 2.0) -> Optional[Dict]:
    """Probe Chrome CDP HTTP endpoint.

    Returns:
        Version info dict if successful, None otherwise
    """
    url = f"http://127.0.0.1:{port}/json/version"

    def _do_request() -> Optional[Dict]:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            pass
        return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_request)


async def _find_existing_instance(profile_dir: str) -> Optional[Tuple[int, Dict]]:
    """Check if there's already a Chrome CDP instance for this profile.

    Reads DevToolsActivePort file and verifies the instance is alive.
    """
    port_file = os.path.join(profile_dir, "DevToolsActivePort")
    if not os.path.exists(port_file):
        return None

    try:
        with open(port_file, "r") as f:
            lines = f.read().strip().split("\n")
            port = int(lines[0])
    except (ValueError, IndexError, OSError):
        return None

    version_info = await _probe_cdp_http(port)
    if version_info:
        logger.info("Found existing Chrome CDP instance on port %d", port)
        return port, version_info

    return None


async def _wait_for_cdp_ready(
    port: int,
    process: Optional[subprocess.Popen],
    total_timeout: float = 30.0,
) -> Dict:
    """Wait for Chrome CDP endpoint to become ready.

    Uses exponential backoff with process health monitoring.

    Args:
        port: The debugging port to probe
        process: Chrome subprocess for health checking (None if reusing)
        total_timeout: Maximum time to wait

    Returns:
        Version info dict from /json/version

    Raises:
        ChromeError: If Chrome process exits or timeout reached
    """
    start = time.monotonic()
    delay = 0.1  # Start at 100ms
    max_delay = 3.0
    attempt = 0

    while (time.monotonic() - start) < total_timeout:
        attempt += 1

        # Check if Chrome process is still alive
        if process is not None:
            retcode = process.poll()
            if retcode is not None:
                stderr_output = ""
                try:
                    stderr_output = process.stderr.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                raise ChromeError(
                    f"Chrome process exited unexpectedly with code {retcode}.\n"
                    f"stderr: {stderr_output[:1000]}"
                )

        # Probe HTTP endpoint
        version_info = await _probe_cdp_http(port, timeout=min(delay, 2.0))
        if version_info:
            elapsed = time.monotonic() - start
            logger.info(
                "Chrome CDP ready on port %d after %.1fs (%d attempts)",
                port, elapsed, attempt,
            )
            return version_info

        # Exponential backoff
        await asyncio.sleep(delay)
        delay = min(delay * 2, max_delay)

    raise ChromeError(
        f"Chrome CDP not ready after {total_timeout}s on port {port}.\n"
        "Possible causes:\n"
        "  1. Chrome failed to start (check if another instance is running)\n"
        "  2. Port conflict (try killing existing Chrome instances)\n"
        "  3. Profile directory locked by another process\n"
        f"  Try: pkill -f 'Chrome.*remote-debugging-port' && rm -f '{DEFAULT_PROFILE_DIR}/DevToolsActivePort'"
    )


async def launch_chrome(
    url: str = "about:blank",
    profile_dir: Optional[str] = None,
    chrome_path: Optional[str] = None,
    reuse_existing: bool = True,
) -> ChromeSession:
    """Launch Chrome with CDP and return a connected session.

    This is the main entry point for starting a Chrome browser session.
    It handles:
    1. Finding or reusing an existing Chrome CDP instance
    2. Launching a new Chrome instance with anti-detection flags
    3. Establishing CDP WebSocket connection
    4. Attaching to the target page

    Args:
        url: Initial URL to open
        profile_dir: Chrome user data directory for persistent sessions
        chrome_path: Optional explicit Chrome executable path
        reuse_existing: Whether to try reusing an existing Chrome instance

    Returns:
        ChromeSession with CDP client and session ID

    Raises:
        ChromeError: If Chrome cannot be launched or connected
    """
    profile_dir = profile_dir or DEFAULT_PROFILE_DIR
    os.makedirs(profile_dir, exist_ok=True)

    chrome_exe = find_chrome(chrome_path)
    process = None
    port = 0

    # Step 1: Try to reuse existing instance
    if reuse_existing:
        existing = await _find_existing_instance(profile_dir)
        if existing:
            port, version_info = existing
            logger.info("Reusing existing Chrome on port %d", port)
        else:
            existing = None

    if not reuse_existing or not existing:
        # Step 2: Clean up stale files
        _clean_devtools_port_file(profile_dir)

        # Step 3: Allocate port with lock
        port, port_sock = _get_free_port()
        logger.info("Allocated port %d for Chrome CDP", port)

        # Step 4: Build Chrome launch arguments
        args = [
            chrome_exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=VizDisplayCompositor",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-translate",
            "--metrics-recording-only",
            "--safebrowsing-disable-auto-update",
            url,
        ]

        # Step 5: Release port lock and launch Chrome
        port_sock.close()

        logger.info("Launching Chrome: %s", chrome_exe)
        logger.debug("Chrome args: %s", " ".join(args))

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            raise ChromeError(f"Chrome executable not found: {chrome_exe}")
        except PermissionError:
            raise ChromeError(f"Permission denied launching Chrome: {chrome_exe}")

        # Register cleanup on exit
        def _cleanup_on_exit():
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        atexit.register(_cleanup_on_exit)

        # Step 6: Wait for CDP to become ready
        version_info = await _wait_for_cdp_ready(port, process)

    # Step 7: Connect CDP WebSocket
    ws_url = version_info.get("webSocketDebuggerUrl", "")
    if not ws_url:
        raise ChromeError("Chrome did not provide webSocketDebuggerUrl")

    # We need the browser-level WebSocket to manage targets
    cdp = CdpClient()
    await cdp.connect(ws_url)

    # Step 8: Find or create a page target
    targets_result = await cdp.send("Target.getTargets")
    targets = targets_result.get("targetInfos", [])

    page_target = None
    for t in targets:
        if t.get("type") == "page":
            target_url = t.get("url", "")
            # Prefer the target matching our URL, or about:blank
            if url != "about:blank" and url in target_url:
                page_target = t
                break
            if not page_target or target_url in ("about:blank", "chrome://newtab/"):
                page_target = t

    if not page_target:
        # Create a new target
        new_target = await cdp.send(
            "Target.createTarget", {"url": url}
        )
        target_id = new_target["targetId"]
    else:
        target_id = page_target["targetId"]

    # Step 9: Attach to the target
    attach_result = await cdp.send(
        "Target.attachToTarget",
        {"targetId": target_id, "flatten": True},
    )
    session_id = attach_result["sessionId"]

    # Step 10: Enable necessary CDP domains
    await cdp.send("Page.enable", session_id=session_id)
    await cdp.send("DOM.enable", session_id=session_id)
    await cdp.send("Runtime.enable", session_id=session_id)

    # Navigate to URL if we reused an existing blank page
    if page_target and url != "about:blank":
        current_url = page_target.get("url", "")
        if current_url != url and current_url in ("about:blank", "chrome://newtab/", ""):
            session = ChromeSession(
                cdp=cdp,
                session_id=session_id,
                target_id=target_id,
                process=process,
                port=port,
                profile_dir=profile_dir,
            )
            await session.navigate(url)
            return session

    session = ChromeSession(
        cdp=cdp,
        session_id=session_id,
        target_id=target_id,
        process=process,
        port=port,
        profile_dir=profile_dir,
    )

    logger.info("Chrome session ready (port=%d, target=%s)", port, target_id)
    return session
