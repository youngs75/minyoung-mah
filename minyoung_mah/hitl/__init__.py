"""Human-in-the-loop channels — default implementations + interrupt protocol."""

from .channels import NullHITLChannel, QueueHITLChannel, TerminalHITLChannel
from .interrupt import (
    HITL_INTERRUPT_MARKER,
    extract_interrupt_payload,
    make_interrupt_marker,
)

__all__ = [
    "HITL_INTERRUPT_MARKER",
    "NullHITLChannel",
    "QueueHITLChannel",
    "TerminalHITLChannel",
    "extract_interrupt_payload",
    "make_interrupt_marker",
]
