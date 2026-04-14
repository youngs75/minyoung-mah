"""RoleRegistry / ToolRegistry basics."""

from __future__ import annotations

import pytest

from minyoung_mah import (
    DuplicateRegistrationError,
    RoleRegistry,
    ToolRegistry,
    UnknownRoleError,
    UnknownToolError,
)

from .conftest import EchoToolAdapter, make_role


def test_role_registry_register_and_get() -> None:
    reg = RoleRegistry.of(make_role("planner"), make_role("verifier"))
    assert "planner" in reg
    assert reg.get("planner").name == "planner"
    assert sorted(reg.names()) == ["planner", "verifier"]


def test_role_registry_unknown_raises() -> None:
    reg = RoleRegistry()
    with pytest.raises(UnknownRoleError):
        reg.get("missing")


def test_role_registry_duplicate_raises() -> None:
    reg = RoleRegistry()
    reg.register(make_role("planner"))
    with pytest.raises(DuplicateRegistrationError):
        reg.register(make_role("planner"))


def test_tool_registry_filter_rejects_unknown() -> None:
    reg = ToolRegistry.of(EchoToolAdapter())
    assert reg.filter(["echo"])[0].name == "echo"
    with pytest.raises(UnknownToolError):
        reg.filter(["echo", "nonexistent"])
