"""LangGraph adapters — optional extras for consumers on a LangGraph outer loop.

Importing this subpackage requires the ``langgraph`` extra::

    pip install minyoung-mah[langgraph]

The library's core stays framework-neutral; LangGraph-specific glue (tool
schemas that use ``InjectedToolCallId``, interrupt replay-safety) lives here
so consumers that pick a different driver are not forced to install
LangGraph.
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
