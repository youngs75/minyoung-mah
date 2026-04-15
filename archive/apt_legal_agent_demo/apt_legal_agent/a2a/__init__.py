"""A2A protocol layer — FastAPI adapters that sit on top of the
orchestrator. minyoung-mah itself knows nothing about A2A; everything
here is pure application glue.
"""

from .agent_card import AGENT_CARD, build_agent_card
from .hitl_channel import A2AHITLChannel
from .sse_handler import SseEmitter, SseObserver, stream_events
from .task_handler import TASKS, TaskState, handle_tasks_send, run_task

__all__ = [
    "AGENT_CARD",
    "A2AHITLChannel",
    "SseEmitter",
    "SseObserver",
    "TASKS",
    "TaskState",
    "build_agent_card",
    "handle_tasks_send",
    "run_task",
    "stream_events",
]
