"""
CDP WebSocket client for Chrome DevTools Protocol communication.

Provides an async CDP client that handles:
- WebSocket connection to Chrome's debugging endpoint
- Message ID tracking with Future-based responses
- Event subscription and callback dispatch
- Timeout management and graceful shutdown
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

import websockets
import websockets.client

logger = logging.getLogger(__name__)


class CdpError(Exception):
    """Error returned by CDP protocol."""

    def __init__(self, code: int, message: str, data: Optional[str] = None):
        self.code = code
        self.error_message = message
        self.data = data
        super().__init__(f"CDP Error {code}: {message}" + (f" ({data})" if data else ""))


class CdpClient:
    """Async Chrome DevTools Protocol client over WebSocket.

    Usage::

        client = CdpClient()
        await client.connect("ws://localhost:9222/devtools/page/...")
        result = await client.send("Runtime.evaluate", {"expression": "1+1"})
        await client.close()
    """

    def __init__(self, default_timeout: float = 15.0):
        self._ws: Optional[websockets.client.WebSocketClientProtocol] = None
        self._msg_id: int = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_listeners: Dict[str, List[Callable]] = {}
        self._recv_task: Optional[asyncio.Task] = None
        self._default_timeout = default_timeout
        self._closed = False

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._closed

    async def connect(self, ws_url: str, timeout: float = 10.0) -> None:
        """Connect to Chrome CDP WebSocket endpoint."""
        logger.debug("Connecting to CDP: %s", ws_url)
        self._ws = await asyncio.wait_for(
            websockets.connect(
                ws_url,
                max_size=100 * 1024 * 1024,  # 100MB for large payloads
                ping_interval=None,
                close_timeout=5,
            ),
            timeout=timeout,
        )
        self._closed = False
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.debug("CDP connected")

    async def send(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Send a CDP command and wait for the response.

        Args:
            method: CDP method name (e.g. "Runtime.evaluate")
            params: Optional parameters dict
            session_id: Optional session ID for target-specific commands
            timeout: Override default timeout (seconds)

        Returns:
            The 'result' field of the CDP response

        Raises:
            CdpError: If CDP returns an error response
            asyncio.TimeoutError: If response not received within timeout
            ConnectionError: If not connected
        """
        if not self.connected:
            raise ConnectionError("CDP client not connected")

        self._msg_id += 1
        msg_id = self._msg_id

        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        if session_id:
            msg["sessionId"] = session_id

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        try:
            await self._ws.send(json.dumps(msg))
            logger.debug("CDP send [%d]: %s", msg_id, method)
            result = await asyncio.wait_for(
                future, timeout=timeout or self._default_timeout
            )
            return result
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise asyncio.TimeoutError(
                f"CDP command '{method}' timed out after {timeout or self._default_timeout}s"
            )

    def on(self, event: str, callback: Callable) -> None:
        """Register an event listener for a CDP event.

        Args:
            event: Event name (e.g. "Page.loadEventFired")
            callback: Callable that receives the event params dict.
                      Can be sync or async.
        """
        if event not in self._event_listeners:
            self._event_listeners[event] = []
        self._event_listeners[event].append(callback)

    def off(self, event: str, callback: Optional[Callable] = None) -> None:
        """Remove event listener(s).

        If callback is None, removes all listeners for the event.
        """
        if callback is None:
            self._event_listeners.pop(event, None)
        elif event in self._event_listeners:
            self._event_listeners[event] = [
                cb for cb in self._event_listeners[event] if cb != callback
            ]

    async def close(self) -> None:
        """Close the CDP connection and cleanup resources."""
        self._closed = True

        # Cancel receive loop
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass

        # Reject all pending requests
        for msg_id, future in self._pending.items():
            if not future.done():
                future.set_exception(ConnectionError("CDP connection closed"))
        self._pending.clear()

        # Close WebSocket
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        logger.debug("CDP connection closed")

    async def _recv_loop(self) -> None:
        """Background task to receive and dispatch CDP messages."""
        try:
            async for raw_msg in self._ws:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from CDP: %s", raw_msg[:200])
                    continue

                # Response to a command
                if "id" in msg:
                    msg_id = msg["id"]
                    future = self._pending.pop(msg_id, None)
                    if future and not future.done():
                        if "error" in msg:
                            err = msg["error"]
                            future.set_exception(
                                CdpError(
                                    err.get("code", -1),
                                    err.get("message", "Unknown error"),
                                    err.get("data"),
                                )
                            )
                        else:
                            future.set_result(msg.get("result", {}))

                # Event notification
                if "method" in msg and "id" not in msg:
                    event_name = msg["method"]
                    params = msg.get("params", {})
                    listeners = self._event_listeners.get(event_name, [])
                    for cb in listeners:
                        try:
                            result = cb(params)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            logger.exception(
                                "Error in event listener for %s", event_name
                            )

        except websockets.exceptions.ConnectionClosed:
            logger.debug("CDP WebSocket connection closed")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Unexpected error in CDP recv loop")
        finally:
            # Reject remaining pending
            for msg_id, future in self._pending.items():
                if not future.done():
                    future.set_exception(ConnectionError("CDP connection lost"))
            self._pending.clear()
