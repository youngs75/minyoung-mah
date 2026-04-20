"""Role and Tool registries — simple name-keyed lookup tables.
역할/도구 레지스트리 — 이름을 키로 하는 단순 lookup 테이블.

These registries are intentionally minimal: they map names to instances,
validate allowlists against registered names, and nothing more. Everything
else (discovery, versioning, hot reload) is deliberately out of scope.

이 레지스트리들은 의도적으로 미니멀하다: 이름→인스턴스 매핑과 등록된 이름에
대한 allowlist 검증만 한다. 그 외 기능(discovery, versioning, hot reload)은
의도적으로 범위 밖에 둔다.
"""

from __future__ import annotations

from typing import Iterable

from .protocols import SubAgentRole, ToolAdapter


class UnknownRoleError(KeyError):
    """Raised when a role name is not present in the registry.
    레지스트리에 없는 역할 이름을 조회할 때 발생."""


class UnknownToolError(KeyError):
    """Raised when a tool name is not present in the registry.
    레지스트리에 없는 도구 이름을 조회할 때 발생."""


class DuplicateRegistrationError(ValueError):
    """Raised when registering a name that already exists.
    이미 존재하는 이름을 다시 등록하려 할 때 발생."""


# ---------------------------------------------------------------------------
# RoleRegistry
# ---------------------------------------------------------------------------


class RoleRegistry:
    """Name → :class:`SubAgentRole` lookup.
    이름 → :class:`SubAgentRole` 조회.

    Use :meth:`of` for the common case of building a registry from a list
    of role instances at startup.

    시작 시점에 역할 인스턴스 목록으로 레지스트리를 만드는 일반적인 경우에는
    :meth:`of` 를 사용한다.
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
    """Name → :class:`ToolAdapter` lookup with allowlist filtering.
    이름 → :class:`ToolAdapter` 조회 + allowlist 필터링."""

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
        이름이 ``allowlist`` 에 있는 adapter 들을 반환한다.

        Unknown names raise :class:`UnknownToolError` — silent skips would
        violate the Safety responsibility by letting typos pass through.

        모르는 이름은 :class:`UnknownToolError` 를 발생시킨다 — 조용히 건너뛰면
        오타가 그대로 통과해 Safety 책임을 위반하기 때문.
        """
        out: list[ToolAdapter] = []
        for name in allowlist:
            out.append(self.get(name))
        return out

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return list(self._tools.keys())
