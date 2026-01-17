"""유틸리티 함수 모듈"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from .models import Theme, QuestionBox, BOX_TYPE_QUESTION


def parse_theme_id_counter(theme_id: str) -> int:
    """테마 ID에서 카운터 숫자 추출"""
    if theme_id.startswith("theme_"):
        try:
            return int(theme_id.split("_")[1])
        except (ValueError, IndexError):
            pass
    return 0


def parse_box_id_counter(box_id: str) -> int:
    """박스 ID에서 카운터 숫자 추출"""
    if box_id.startswith("box_"):
        try:
            return int(box_id.split("_")[1])
        except (ValueError, IndexError):
            pass
    return 0


def load_themes_from_data(themes_data: List[dict]) -> Tuple[List[Theme], int]:
    """테마 데이터 로드. (테마 리스트, 최대 카운터) 반환"""
    themes = []
    max_counter = 0

    for theme_data in themes_data:
        theme = Theme(
            id=theme_data["id"],
            name=theme_data["name"],
            color=theme_data.get("color", "#3498db"),
            deleted=theme_data.get("deleted", False)
        )
        themes.append(theme)
        max_counter = max(max_counter, parse_theme_id_counter(theme.id))

    return themes, max_counter


def load_box_from_data(box_data: dict, generate_id_func=None) -> Tuple[QuestionBox, int]:
    """박스 데이터 로드. (박스, 카운터) 반환"""
    box = QuestionBox(
        x1=box_data["x1"],
        y1=box_data["y1"],
        x2=box_data["x2"],
        y2=box_data["y2"],
        number=box_data.get("number"),
        theme_id=box_data.get("theme_id"),
        page=box_data.get("page", 1),
        box_type=box_data.get("box_type", BOX_TYPE_QUESTION),
        linked_box_id=box_data.get("linked_box_id"),
        box_id=box_data.get("box_id"),
        ai_result=box_data.get("ai_result")
    )

    counter = 0
    if not box.box_id and generate_id_func:
        box.box_id = generate_id_func()
    elif box.box_id:
        counter = parse_box_id_counter(box.box_id)

    return box, counter


def serialize_boxes(sorted_boxes: List[Tuple[int, QuestionBox]]) -> List[dict]:
    """박스 리스트를 JSON 직렬화 가능한 형태로 변환"""
    result = []
    for idx, (page_idx, box) in enumerate(sorted_boxes):
        box_dict = box.to_dict()
        box_dict['_sort_order'] = idx
        result.append(box_dict)
    return result


def create_save_data(
    pdf_name: str,
    themes: List[Theme],
    sorted_boxes: List[Tuple[int, QuestionBox]]
) -> dict:
    """저장용 데이터 구조 생성"""
    return {
        "source_pdf": pdf_name,
        "saved_at": datetime.now().isoformat(),
        "themes": [theme.to_dict() for theme in themes],
        "total_boxes": len(sorted_boxes),
        "boxes": serialize_boxes(sorted_boxes)
    }


def safe_file_write(path: Path, content: str, backup_path: Optional[Path] = None) -> bool:
    """안전한 파일 쓰기 (백업 지원)"""
    import shutil

    try:
        # 기존 파일이 있으면 백업
        if backup_path and path.exists():
            shutil.copy2(path, backup_path)

        # 새 파일 저장
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

        return True
    except Exception:
        # 저장 실패 시 백업에서 복구
        if backup_path and backup_path.exists():
            try:
                shutil.copy2(backup_path, path)
            except Exception:
                pass
        return False


def safe_file_read(path: Path, backup_path: Optional[Path] = None) -> Optional[dict]:
    """안전한 JSON 파일 읽기 (백업 폴백)"""
    # 메인 파일 시도
    if path and path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    # 백업 파일 시도
    if backup_path and backup_path.exists():
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    return None


def get_box_sort_key(page_idx: int, box: QuestionBox, column_guides: List[Tuple[int, int]] = None) -> tuple:
    """박스 정렬 키 생성 (페이지 → 컬럼 → Y좌표 → X좌표)"""
    box_center_x = (box.x1 + box.x2) / 2

    column_idx = 0
    if column_guides:
        for i, (col_x1, col_x2) in enumerate(column_guides):
            if col_x1 <= box_center_x <= col_x2:
                column_idx = i
                break

    return (page_idx, column_idx, box.y1, box.x1)
