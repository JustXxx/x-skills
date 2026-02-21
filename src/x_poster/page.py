"""
Page DOM operation helpers via CDP.

Provides high-level abstractions for common page interactions:
- Waiting for elements to appear
- Clicking elements
- Typing text into editors
- Uploading files via file input
- Evaluating JavaScript
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from .cdp_client import CdpClient

logger = logging.getLogger(__name__)


class PageHelper:
    """High-level page operation helper using CDP.

    Args:
        cdp: Connected CdpClient instance
        session_id: CDP session ID for the target page
    """

    def __init__(self, cdp: CdpClient, session_id: str):
        self.cdp = cdp
        self.session_id = session_id

    async def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        """Execute JavaScript in the page context.

        Args:
            expression: JavaScript expression to evaluate
            await_promise: Whether to await if expression returns a Promise

        Returns:
            The evaluated result value
        """
        params = {"expression": expression, "returnByValue": True}
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
            raise RuntimeError(f"JS error: {text}")

        return result.get("result", {}).get("value")

    async def wait_for_selector(
        self,
        selector: str,
        timeout: float = 15.0,
        poll_interval: float = 0.3,
        visible: bool = False,
    ) -> bool:
        """Wait for a CSS selector to appear in the DOM.

        Args:
            selector: CSS selector string
            timeout: Maximum wait time in seconds
            poll_interval: Time between checks
            visible: If True, also check element is visible (offsetParent != null)

        Returns:
            True if element found

        Raises:
            TimeoutError: If element not found within timeout
        """
        js_selector = selector.replace("'", "\\'")
        if visible:
            check_js = (
                f"(() => {{"
                f"  const el = document.querySelector('{js_selector}');"
                f"  return el && el.offsetParent !== null;"
                f"}})()"
            )
        else:
            check_js = f"!!document.querySelector('{js_selector}')"

        elapsed = 0.0
        while elapsed < timeout:
            found = await self.evaluate(check_js)
            if found:
                return True
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"Selector '{selector}' not found after {timeout}s"
        )

    async def wait_for_any_selector(
        self,
        selectors: List[str],
        timeout: float = 15.0,
        poll_interval: float = 0.3,
    ) -> Tuple[int, str]:
        """Wait for any of the given selectors to appear.

        Returns:
            Tuple of (index, matched_selector)

        Raises:
            TimeoutError: If none found within timeout
        """
        escaped = [s.replace("'", "\\'") for s in selectors]
        selectors_js = ", ".join(f"'{s}'" for s in escaped)
        check_js = (
            f"(() => {{"
            f"  const sels = [{selectors_js}];"
            f"  for (let i = 0; i < sels.length; i++) {{"
            f"    if (document.querySelector(sels[i])) return i;"
            f"  }}"
            f"  return -1;"
            f"}})()"
        )

        elapsed = 0.0
        while elapsed < timeout:
            idx = await self.evaluate(check_js)
            if idx is not None and idx >= 0:
                return idx, selectors[idx]
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(
            f"None of selectors {selectors} found after {timeout}s"
        )

    async def click_selector(
        self, selector: str, timeout: float = 10.0
    ) -> None:
        """Click an element matching the CSS selector.

        Finds the element center and dispatches a click via CDP Input.

        Args:
            selector: CSS selector
            timeout: Wait timeout before clicking
        """
        await self.wait_for_selector(selector, timeout=timeout)

        # Get element position
        js_selector = selector.replace("'", "\\'")
        box = await self.evaluate(
            f"(() => {{"
            f"  const el = document.querySelector('{js_selector}');"
            f"  if (!el) return null;"
            f"  const rect = el.getBoundingClientRect();"
            f"  return {{x: rect.x + rect.width/2, y: rect.y + rect.height/2}};"
            f"}})()"
        )

        if not box:
            raise RuntimeError(f"Element '{selector}' not found for click")

        x, y = box["x"], box["y"]

        # Dispatch mouse events via CDP Input domain
        for event_type in ["mousePressed", "mouseReleased"]:
            await self.cdp.send(
                "Input.dispatchMouseEvent",
                {
                    "type": event_type,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clickCount": 1,
                },
                session_id=self.session_id,
            )
            if event_type == "mousePressed":
                await asyncio.sleep(0.05)

    async def type_text(self, selector: str, text: str) -> None:
        """Type text into an element using execCommand('insertText').

        This method focuses the element first, then uses insertText
        which is compatible with contenteditable and input elements.

        Args:
            selector: CSS selector of the target element
            text: Text to insert
        """
        js_selector = selector.replace("'", "\\'")
        escaped_text = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")

        await self.evaluate(
            f"(() => {{"
            f"  const el = document.querySelector('{js_selector}');"
            f"  if (!el) throw new Error('Element not found: {js_selector}');"
            f"  el.focus();"
            f"  document.execCommand('insertText', false, '{escaped_text}');"
            f"}})()"
        )

    async def upload_file(self, file_path: str, selector: str = 'input[type="file"]') -> None:
        """Upload a file by setting it on a file input element.

        Uses CDP DOM.setFileInputFiles to bypass the file dialog.

        Args:
            file_path: Absolute path to the file
            selector: CSS selector of the file input
        """
        # Get the DOM node
        doc = await self.cdp.send(
            "DOM.getDocument", {"depth": 0}, session_id=self.session_id
        )
        root_node_id = doc["root"]["nodeId"]

        js_selector = selector.replace("'", "\\'")
        node = await self.cdp.send(
            "DOM.querySelector",
            {"nodeId": root_node_id, "selector": selector},
            session_id=self.session_id,
        )
        node_id = node.get("nodeId", 0)

        if node_id == 0:
            raise RuntimeError(f"File input '{selector}' not found")

        await self.cdp.send(
            "DOM.setFileInputFiles",
            {"files": [file_path], "nodeId": node_id},
            session_id=self.session_id,
        )
        logger.debug("File uploaded: %s", file_path)

    async def count_elements(self, selector: str) -> int:
        """Count elements matching a CSS selector."""
        js_selector = selector.replace("'", "\\'")
        count = await self.evaluate(
            f"document.querySelectorAll('{js_selector}').length"
        )
        return count or 0

    async def get_element_text(self, selector: str) -> Optional[str]:
        """Get text content of an element."""
        js_selector = selector.replace("'", "\\'")
        return await self.evaluate(
            f"(() => {{"
            f"  const el = document.querySelector('{js_selector}');"
            f"  return el ? el.textContent : null;"
            f"}})()"
        )

    async def get_element_attribute(self, selector: str, attribute: str) -> Optional[str]:
        """Get an attribute value of an element."""
        js_selector = selector.replace("'", "\\'")
        attr = attribute.replace("'", "\\'")
        return await self.evaluate(
            f"(() => {{"
            f"  const el = document.querySelector('{js_selector}');"
            f"  return el ? el.getAttribute('{attr}') : null;"
            f"}})()"
        )

    async def is_element_enabled(self, selector: str) -> bool:
        """Check if a button/input element is not disabled."""
        js_selector = selector.replace("'", "\\'")
        result = await self.evaluate(
            f"(() => {{"
            f"  const el = document.querySelector('{js_selector}');"
            f"  if (!el) return false;"
            f"  return !el.disabled && !el.getAttribute('aria-disabled');"
            f"}})()"
        )
        return bool(result)

    async def scroll_to_element(self, selector: str) -> None:
        """Scroll an element into view."""
        js_selector = selector.replace("'", "\\'")
        await self.evaluate(
            f"(() => {{"
            f"  const el = document.querySelector('{js_selector}');"
            f"  if (el) el.scrollIntoView({{behavior: 'smooth', block: 'center'}});"
            f"}})()"
        )

    async def paste_html_content(self, html: str, selector: str) -> bool:
        """Paste HTML content into a contenteditable element using ClipboardEvent.

        Falls back to execCommand('insertHTML') if ClipboardEvent fails.

        Args:
            html: HTML string to paste
            selector: CSS selector of the target element

        Returns:
            True if paste was successful
        """
        js_selector = selector.replace("'", "\\'")
        escaped_html = (
            html.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("$", "\\$")
        )

        # Try ClipboardEvent first
        success = await self.evaluate(
            f"(() => {{"
            f"  const el = document.querySelector('{js_selector}');"
            f"  if (!el) return false;"
            f"  el.focus();"
            f"  const html = `{escaped_html}`;"
            f"  const dt = new DataTransfer();"
            f"  dt.setData('text/html', html);"
            f"  dt.setData('text/plain', el.textContent || '');"
            f"  const evt = new ClipboardEvent('paste', {{"
            f"    clipboardData: dt, bubbles: true, cancelable: true"
            f"  }});"
            f"  return el.dispatchEvent(evt);"
            f"}})()"
        )

        if success:
            return True

        # Fallback to execCommand
        logger.debug("ClipboardEvent paste failed, trying execCommand")
        await self.evaluate(
            f"(() => {{"
            f"  const el = document.querySelector('{js_selector}');"
            f"  if (!el) return;"
            f"  el.focus();"
            f"  document.execCommand('insertHTML', false, `{escaped_html}`);"
            f"}})()"
        )
        return True
