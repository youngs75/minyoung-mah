"""LangGraph adapters — optional extras for consumers on a LangGraph outer loop.
LangGraph adapter — LangGraph 외부 루프를 쓰는 컨슈머용 선택적 extras.

Importing this subpackage requires the ``langgraph`` extra::
이 서브패키지를 import 하려면 ``langgraph`` extra 가 필요하다::

    pip install minyoung-mah[langgraph]

The library's core stays framework-neutral; LangGraph-specific glue (tool
schemas that use ``InjectedToolCallId``, interrupt replay-safety) lives here
so consumers that pick a different driver are not forced to install
LangGraph.

라이브러리 코어는 프레임워크 중립을 유지한다. LangGraph 전용 접착 코드
(``InjectedToolCallId`` 를 쓰는 도구 스키마, interrupt replay-safety)는 여기에
두어, 다른 driver 를 선택한 컨슈머가 LangGraph 를 강제로 설치하지 않도록 한다.
"""

from .subagent_task_tool import (
    SubAgentTaskInput,
    build_subagent_task_tool,
    replay_safe_tool_call,
)

__all__ = [
    "SubAgentTaskInput",
    "build_subagent_task_tool",
    "replay_safe_tool_call",
]
