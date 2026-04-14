"""Dispute taxonomy — the 10 supported dispute types and query intents.

These enums are part of the agent's user-facing contract: the exact set
of dispute types is fixed by the product spec, and classifiers must
return one of these values or ``GENERAL``.
"""

from __future__ import annotations

from enum import Enum


class DisputeType(str, Enum):
    NOISE = "NOISE"              # 층간소음
    PARKING = "PARKING"          # 주차
    PET = "PET"                  # 반려동물
    MGMT_FEE = "MGMT_FEE"        # 관리비
    DEFECT = "DEFECT"            # 하자
    RECON = "RECON"              # 재건축
    REMODEL = "REMODEL"          # 리모델링
    BID = "BID"                  # 입찰
    ELECTION = "ELECTION"        # 동대표 선거
    GENERAL = "GENERAL"          # 분류 애매할 때의 기본값


class QueryIntent(str, Enum):
    LAW_CHECK = "LAW_CHECK"                  # 법령 확인
    PROCEDURE_GUIDE = "PROCEDURE_GUIDE"      # 절차 안내
    DISPUTE_RESOLUTION = "DISPUTE_RESOLUTION"  # 분쟁 해결
    COMPARISON = "COMPARISON"                # 법령 비교
