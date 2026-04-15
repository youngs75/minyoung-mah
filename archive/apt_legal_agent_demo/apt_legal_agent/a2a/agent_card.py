"""Agent card — served at ``/.well-known/agent.json``.

The card advertises the agent's capabilities and endpoints to A2A
clients (ChatGPT Enterprise CustomGPT, other agents). Per the A2A
protocol it is a static JSON document with a small handful of required
fields.
"""

from __future__ import annotations

from typing import Any


def build_agent_card(
    *,
    name: str = "apt-legal-agent",
    version: str = "0.0.1",
    base_url: str = "http://localhost:8000",
    description: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "version": version,
        "description": description
        or "공동주택 법률 질의응답 에이전트 (법령·판례·행정해석 근거 기반).",
        "url": base_url,
        "protocol": "a2a",
        "protocolVersion": "0.1",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "authentication": {"schemes": ["none"]},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "apt-legal-qa",
                "name": "공동주택 법률 상담",
                "description": (
                    "공동주택 입주민·관리사무소의 법률 질문에 법령·판례·행정해석을 "
                    "근거로 답변합니다. 지원 분쟁 유형: 층간소음·주차·반려동물·"
                    "관리비·하자보수·재건축·리모델링·입찰·선거·기타."
                ),
                "tags": ["legal", "apartment", "korean"],
                "examples": [
                    "공동주택에서 층간소음 기준이 몇 데시벨이야?",
                    "윗집 층간소음이 너무 심한데 법적으로 어떻게 대응할 수 있나요?",
                    "재건축 추진하려면 동의율이 얼마나 필요해?",
                ],
            }
        ],
        "endpoints": {
            "tasksSend": f"{base_url}/a2a/tasks/send",
            "tasksStream": f"{base_url}/a2a/stream",
        },
    }


AGENT_CARD: dict[str, Any] = build_agent_card()
