"""SubAgentRole declarations for the apt-legal pipeline."""

from .classifier import CLASSIFIER_ROLE
from .responder import RESPONDER_ROLE
from .retrieval_planner import RETRIEVAL_PLANNER_ROLE

__all__ = [
    "CLASSIFIER_ROLE",
    "RESPONDER_ROLE",
    "RETRIEVAL_PLANNER_ROLE",
]
