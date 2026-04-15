"""System prompts for the three apt-legal roles."""

from .classifier import CLASSIFIER_SYSTEM_PROMPT
from .responder import RESPONDER_SYSTEM_PROMPT
from .retrieval_planner import PLANNER_SYSTEM_PROMPT

__all__ = [
    "CLASSIFIER_SYSTEM_PROMPT",
    "PLANNER_SYSTEM_PROMPT",
    "RESPONDER_SYSTEM_PROMPT",
]
