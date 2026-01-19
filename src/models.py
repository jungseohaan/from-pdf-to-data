"""데이터 모델 정의"""

from dataclasses import dataclass, asdict
from typing import Optional


# 박스 유형 상수
BOX_TYPE_QUESTION = "question"  # 문제
BOX_TYPE_SOLUTION = "solution"  # 풀이


@dataclass
class Theme:
    """테마/단원 정보"""
    id: str
    name: str
    color: str = "#3498db"  # 기본 파란색
    deleted: bool = False  # 삭제 표시 (실제 삭제 아님)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QuestionBox:
    """문항 박스 정보"""
    x1: int
    y1: int
    x2: int
    y2: int
    number: Optional[int] = None
    theme_id: Optional[str] = None  # 테마 ID로 연결
    page: int = 1
    box_type: str = BOX_TYPE_QUESTION  # 문제 또는 풀이
    linked_box_id: Optional[str] = None  # 연결된 박스 ID (풀이→문제)
    box_id: Optional[str] = None  # 고유 ID
    ai_result: Optional[dict] = None  # AI 분석 결과 (JSON)

    @property
    def id(self) -> Optional[str]:
        """box_id의 별칭"""
        return self.box_id

    def to_dict(self) -> dict:
        return asdict(self)
