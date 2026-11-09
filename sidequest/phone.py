"""The phone step: hand a side-event registration to an agent on the attendee's own phone.

Sidequest does not hold anyone's Luma login. Instead it asks ARTEMIS, an open-source Android UI agent
(github.com/google/artemis) that the attendee runs on their own laptop with their own phone plugged in,
to open the Luma app, find the event, start the registration and stop with the final button on screen.
The attendee presses that button. The agent never submits.

ARTEMIS exposes an MCP server over HTTP; this module is a thin client for two of its tools:
``mobile_run_task`` (start) and ``mobile_manage_task`` (status). Configure with:

  ARTEMIS_MCP_URL   default http://127.0.0.1:8012/mcp (the laptop next to the phone)
  ARTEMIS_DEVICE    optional ADB serial when several phones are attached
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

ARTEMIS_MCP_URL = os.environ.get("ARTEMIS_MCP_URL", "http://127.0.0.1:8012/mcp")
ARTEMIS_DEVICE = os.environ.get("ARTEMIS_DEVICE") or None


class PhoneUnavailable(RuntimeError):
    """The phone agent is not reachable; the UI falls back to a plain link."""


def task_text(event_name: str, event_url: str | None) -> str:
    link = f" Its web link is {event_url}." if event_url else ""
    return (
        f'In the Luma app (package com.luma.mobile), register for the event named "{event_name}".{link} '
        "Steps: open Luma; use the search or the Discover tab to find the event by its name; open the event page; "
        "tap the Register, Request to Join or Get Ticket button; if a form appears, fill only the fields that are "
        "already known on this phone (name and email are usually prefilled) and answer yes/no questions truthfully "
        "with the most neutral option. STOP when the final confirm button (Register, Submit, Request, Confirm) is "
        "visible and NOT yet pressed. Never press that final button. Then report: the event name shown, the button "
        "text that is waiting, and any field that was left empty."
    )


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:  # pragma: no cover
        raise PhoneUnavailable("the mcp client package is not installed") from exc
    try:
        async with streamable_http_client(
            ARTEMIS_MCP_URL
        ) as streams:  # 2 or 3 values depending on mcp version
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
    except Exception as exc:
        raise PhoneUnavailable(f"phone agent not reachable at {ARTEMIS_MCP_URL}: {exc}") from exc
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _run(factory):
    """Run ``factory()`` (which builds a coroutine) to completion, whether or not a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    import concurrent.futures  # inside a running loop (async caller): use a fresh loop in a helper thread

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


def start_registration(event_name: str, event_url: str | None = None) -> dict[str, Any]:
    args: dict[str, Any] = {
        "task_desc": task_text(event_name, event_url),
        "model": "Flash",
        "locked_app_package": "com.luma.mobile",
    }
    if ARTEMIS_DEVICE:
        args["device_serial"] = ARTEMIS_DEVICE
    out = _run(lambda: _call_tool("mobile_run_task", args))
    return {
        "task_id": out.get("trace_id") or out.get("session_id") or "",
        "device": out.get("device_serial"),
        "state": "started",
        "message": "The phone is opening Luma. Watch the screen; it stops before the final button.",
        "raw": out,
    }


def status(task_id: str) -> dict[str, Any]:
    out = _run(lambda: _call_tool("mobile_manage_task", {"action": "status", "trace_id": task_id}))
    progress = out.get("progress") or {}
    return {
        "task_id": task_id,
        "state": out.get("status", "unknown"),
        "elapsed_seconds": out.get("elapsed_seconds"),
        "turn": progress.get("turn") or progress.get("current_turn"),
        "thought": progress.get("latest_thought") or progress.get("thought"),
        "action": progress.get("latest_action") or progress.get("action"),
        "raw": out,
    }
