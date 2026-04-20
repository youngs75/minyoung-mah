"""HITL interrupt marker protocol — SubAgent ↔ outer-loop handshake.
HITL interrupt 마커 프로토콜 — SubAgent ↔ 외부 루프 사이의 핸드셰이크.

When a SubAgent role needs to pause and ask the user a question, it cannot
call the LangGraph ``interrupt()`` primitive directly — doing so would unwind
through the library's tool-calling loop, which the library owns and must not
see a LangGraph exception. The agreed handshake is:

SubAgent 역할이 일시 정지하고 사용자에게 질문해야 할 때, LangGraph 의
``interrupt()`` 프리미티브를 직접 호출할 수 없다 — 그러면 라이브러리가
소유하고 있고 LangGraph 예외를 봐서는 안 되는 tool-calling 루프를 통과해
unwind 되기 때문이다. 합의된 핸드셰이크는:

1. The role's ``ask`` tool adapter returns a :class:`~minyoung_mah.ToolResult`
   whose ``value`` is ``{HITL_INTERRUPT_MARKER: True, "payload": {...}}``.
   역할의 ``ask`` 도구 adapter 가 ``value`` 를
   ``{HITL_INTERRUPT_MARKER: True, "payload": {...}}`` 로 한 :class:`~minyoung_mah.ToolResult`
   를 반환.
2. The role finishes its turn with a short summary (the system prompt steers
   it to stop as soon as it sees this marker).
   역할은 짧은 요약과 함께 턴을 마친다 (system prompt 가 이 마커를 보면
   즉시 멈추도록 유도).
3. The outer driver (e.g. a LangGraph task tool) scans
   ``result.tool_results`` for the marker, extracts the payload via
   :func:`extract_interrupt_payload`, and raises LangGraph ``interrupt(...)``
   from the top level.
   외부 driver(예: LangGraph task 도구)가 ``result.tool_results`` 에서 마커를
   찾아 :func:`extract_interrupt_payload` 로 payload 를 꺼내고, top-level 에서
   LangGraph ``interrupt(...)`` 를 raise 한다.

Consumers use :func:`make_interrupt_marker` when building the adapter and
:func:`extract_interrupt_payload` when bridging to the outer framework.

컨슈머는 adapter 를 만들 때 :func:`make_interrupt_marker` 를, 외부 프레임워크와
연결할 때 :func:`extract_interrupt_payload` 를 사용한다.
"""

from __future__ import annotations

from typing import Any

HITL_INTERRUPT_MARKER: str = "__mm_interrupt__"
"""Dict key that signals "pause the outer loop and ask the user".
"외부 루프를 일시정지하고 사용자에게 묻는다"는 신호의 dict 키.

Consumers MUST use this constant rather than the literal string so that
future rename propagates cleanly.

컨슈머는 리터럴 문자열 대신 반드시 이 상수를 사용해야 향후 rename 이
깔끔하게 전파된다.
"""


def make_interrupt_marker(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap ``payload`` in the standard marker envelope.
    ``payload`` 를 표준 마커 envelope 으로 감싼다.

    Returned dict is safe to use as a ``ToolResult.value`` — the orchestrator
    serializes it through ``json.dumps`` when feeding it to the LLM, and the
    outer driver recovers the payload on the original (pre-serialization)
    object via :func:`extract_interrupt_payload`.

    반환 dict 는 ``ToolResult.value`` 로 안전하게 사용 가능하다 — orchestrator
    가 LLM 에 넘길 때 ``json.dumps`` 로 직렬화하고, 외부 driver 는 직렬화 전의
    원본 객체에 대해 :func:`extract_interrupt_payload` 로 payload 를 복원한다.
    """
    return {HITL_INTERRUPT_MARKER: True, "payload": payload}


def extract_interrupt_payload(tool_result_value: Any) -> dict[str, Any] | None:
    """Return the HITL payload if ``tool_result_value`` carries the marker.
    ``tool_result_value`` 에 마커가 있으면 HITL payload 를 반환한다.

    ``None`` is returned for plain strings, other dicts, and ``None`` itself
    — the caller uses this to distinguish "role asked the user" from "role
    returned normal tool output".

    일반 문자열, 다른 dict, 그리고 ``None`` 자체에 대해서는 ``None`` 을 반환 —
    호출자는 이를 사용해 "역할이 사용자에게 물었다"와 "역할이 정상 도구 출력을
    반환했다"를 구분한다.
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
