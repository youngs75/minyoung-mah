"""HITL interrupt marker protocol — SubAgent ↔ outer-loop handshake.

When a SubAgent role needs to pause and ask the user a question, it cannot
call the LangGraph ``interrupt()`` primitive directly — doing so would unwind
through the library's tool-calling loop, which the library owns and must not
see a LangGraph exception. The agreed handshake is:

1. The role's ``ask`` tool adapter returns a :class:`~minyoung_mah.ToolResult`
   whose ``value`` is ``{HITL_INTERRUPT_MARKER: True, "payload": {...}}``.
2. The role finishes its turn with a short summary (the system prompt steers
   it to stop as soon as it sees this marker).
3. The outer driver (e.g. a LangGraph task tool) scans
   ``result.tool_results`` for the marker, extracts the payload via
   :func:`extract_interrupt_payload`, and raises LangGraph ``interrupt(...)``
   from the top level.

Consumers use :func:`make_interrupt_marker` when building the adapter and
:func:`extract_interrupt_payload` when bridging to the outer framework.
"""

from __future__ import annotations

from typing import Any

HITL_INTERRUPT_MARKER: str = "__mm_interrupt__"
"""Dict key that signals "pause the outer loop and ask the user".

Consumers MUST use this constant rather than the literal string so that
future rename propagates cleanly.
"""


def make_interrupt_marker(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap ``payload`` in the standard marker envelope.

    Returned dict is safe to use as a ``ToolResult.value`` — the orchestrator
    serializes it through ``json.dumps`` when feeding it to the LLM, and the
    outer driver recovers the payload on the original (pre-serialization)
    object via :func:`extract_interrupt_payload`.
    """
    return {HITL_INTERRUPT_MARKER: True, "payload": payload}


def extract_interrupt_payload(tool_result_value: Any) -> dict[str, Any] | None:
    """Return the HITL payload if ``tool_result_value`` carries the marker.

    ``None`` is returned for plain strings, other dicts, and ``None`` itself
    — the caller uses this to distinguish "role asked the user" from "role
    returned normal tool output".
    """
    if isinstance(tool_result_value, dict) and tool_result_value.get(HITL_INTERRUPT_MARKER):
        payload = tool_result_value.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


__all__ = [
    "HITL_INTERRUPT_MARKER",
    "extract_interrupt_payload",
    "make_interrupt_marker",
]
