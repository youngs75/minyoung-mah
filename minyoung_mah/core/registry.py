"""Role and Tool registries — simple name-keyed lookup tables.

These registries are intentionally minimal: they map names to instances,
validate allowlists against registered names, and nothing more. Everything
else (discovery, versioning, hot reload) is deliberately out of scope.
"""

from __future__ import annotations

from typing import Iterable

from .protocols import SubAgentRole, ToolAdapter


class UnknownRoleError(KeyError):
    """Raised when a role name is not present in the registry."""


class UnknownToolError(KeyError):
    """Raised when a tool name is not present in the registry."""


class DuplicateRegistrationError(ValueError):
    """Raised when registering a name that already exists."""


# ---------------------------------------------------------------------------
# RoleRegistry
# ---------------------------------------------------------------------------


class RoleRegistry:
    """Name → :class:`SubAgentRole` lookup.

    Use :meth:`of` for the common case of building a registry from a list
    of role instances at startup.
    """

    def __init__(self) -> None:
        self._roles: dict[str, SubAgentRole] = {}

    @classmethod
    def of(cls, *roles: SubAgentRole) -> "RoleRegistry":
        reg = cls()
        for role in roles:
            reg.register(role)
        return reg

    def register(self, role: SubAgentRole) -> None:
        if role.name in self._roles:
            raise DuplicateRegistrationError(
                f"Role '{role.name}' is already registered"
            )
        self._roles[role.name] = role

    def get(self, name: str) -> SubAgentRole:
        try:
            return self._roles[name]
        except KeyError as exc:
            raise UnknownRoleError(f"No role registered under '{name}'") from exc

    def __contains__(self, name: str) -> bool:
        return name in self._roles

    def names(self) -> list[str]:
        return list(self._roles.keys())


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Name → :class:`ToolAdapter` lookup with allowlist filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolAdapter] = {}

    @classmethod
    def of(cls, *adapters: ToolAdapter) -> "ToolRegistry":
        reg = cls()
        for adapter in adapters:
            reg.register(adapter)
        return reg

    def register(self, adapter: ToolAdapter) -> None:
        if adapter.name in self._tools:
            raise DuplicateRegistrationError(
                f"Tool '{adapter.name}' is already registered"
            )
        self._tools[adapter.name] = adapter

    def get(self, name: str) -> ToolAdapter:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"No tool registered under '{name}'") from exc

    def filter(self, allowlist: Iterable[str]) -> list[ToolAdapter]:
        """Return adapters whose names appear in ``allowlist``.

        Unknown names raise :class:`UnknownToolError` — silent skips would
        violate the Safety responsibility by letting typos pass through.
        """
        out: list[ToolAdapter] = []
        for name in allowlist:
            out.append(self.get(name))
        return out

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools.keys())
