"""Unit tests for ``minyoung_mah.hitl.interrupt`` — marker protocol."""

from __future__ import annotations

from minyoung_mah import (
    HITL_INTERRUPT_MARKER,
    extract_interrupt_payload,
    make_interrupt_marker,
)


def test_marker_constant_value():
    # Value is a stable wire-format key. If this ever changes, existing
    # in-flight checkpoints break — treat it like a schema migration.
    assert HITL_INTERRUPT_MARKER == "__mm_interrupt__"


def test_make_interrupt_marker_roundtrip():
    payload = {"kind": "ask_user_question", "questions": [{"id": "q1"}]}
    envelope = make_interrupt_marker(payload)
    assert envelope == {HITL_INTERRUPT_MARKER: True, "payload": payload}
    assert extract_interrupt_payload(envelope) == payload


def test_extract_returns_none_for_non_marker_values():
    assert extract_interrupt_payload("User answered — Tech: React") is None
    assert extract_interrupt_payload({"other": "value"}) is None
    assert extract_interrupt_payload(None) is None
    assert extract_interrupt_payload([1, 2, 3]) is None


def test_extract_returns_none_if_marker_set_but_payload_missing():
    # The sentinel was flipped but the payload never attached — treat as
    # malformed, not as a HITL request. The outer driver would otherwise
    # raise interrupt(None) and fail.
    assert extract_interrupt_payload({HITL_INTERRUPT_MARKER: True}) is None


def test_extract_returns_none_if_payload_not_a_dict():
    assert (
        extract_interrupt_payload({HITL_INTERRUPT_MARKER: True, "payload": "oops"})
        is None
    )
