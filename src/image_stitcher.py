"""페이지 이미지를 2컬럼 처리 후 수직으로 연결하는 모듈"""

from typing import List, Tuple

import numpy as np
from PIL import Image


def split_columns(
    image: Image.Image,
    gap_ratio: float = 0.05
) -> Tuple[Image.Image, Image.Image]:
    """
    이미지를 좌/우 컬럼으로 분리합니다.

    Args:
        image: 원본 이미지
        gap_ratio: 중앙 여백 비율 (이미지 너비 대비)

    Returns:
        (좌측 컬럼 이미지, 우측 컬럼 이미지) 튜플
    """
    width, height = image.size
    gap_pixels = int(width * gap_ratio)
    mid = width // 2

    # 좌측 컬럼: 시작 ~ 중앙 - 여백/2
    left_col = image.crop((0, 0, mid - gap_pixels // 2, height))

    # 우측 컬럼: 중앙 + 여백/2 ~ 끝
    right_col = image.crop((mid + gap_pixels // 2, 0, width, height))

    return left_col, right_col


def stitch_vertically(images: List[Image.Image]) -> Image.Image:
    """
    여러 이미지를 수직으로 이어붙입니다.

    Args:
        images: 이어붙일 이미지 리스트

    Returns:
        수직으로 연결된 단일 이미지
    """
    if not images:
        raise ValueError("이미지 리스트가 비어있습니다.")

    if len(images) == 1:
        return images[0].copy()

    # 모든 이미지의 너비를 최대 너비로 통일
    max_width = max(img.width for img in images)
    total_height = sum(img.height for img in images)

    # 새 이미지 생성 (흰색 배경)
    result = Image.new('RGB', (max_width, total_height), (255, 255, 255))

    # 이미지들을 순서대로 붙이기
    y_offset = 0
    for img in images:
        # 너비가 다른 경우 중앙 정렬
        x_offset = (max_width - img.width) // 2
        result.paste(img, (x_offset, y_offset))
        y_offset += img.height

    return result


def process_pages_to_single_image(
    pages: List[Image.Image],
    gap_ratio: float = 0.05
) -> Image.Image:
    """
    페이지들을 2컬럼 처리 후 하나의 긴 이미지로 변환합니다.

    처리 순서: 1페이지 좌→우 → 2페이지 좌→우 → ...

    Args:
        pages: 페이지 이미지 리스트
        gap_ratio: 중앙 여백 비율

    Returns:
        모든 컬럼이 수직으로 연결된 단일 이미지
    """
    all_columns = []

    for page in pages:
        left_col, right_col = split_columns(page, gap_ratio)
        all_columns.append(left_col)
        all_columns.append(right_col)

    return stitch_vertically(all_columns)


def get_column_info(
    page_index: int,
    is_right_column: bool,
    y_in_column: int,
    column_height: int
) -> dict:
    """
    연결된 이미지 내 위치에서 원본 페이지/컬럼 정보를 계산합니다.

    Args:
        page_index: 페이지 인덱스 (0부터 시작)
        is_right_column: 우측 컬럼 여부
        y_in_column: 컬럼 내 y 좌표
        column_height: 컬럼 높이

    Returns:
        원본 위치 정보 딕셔너리
    """
    return {
        'page': page_index + 1,  # 1부터 시작하는 페이지 번호
        'column': 'right' if is_right_column else 'left',
        'y_in_column': y_in_column
    }


def calculate_original_position(
    y_in_stitched: int,
    page_heights: List[int],
    num_pages: int
) -> dict:
    """
    연결된 이미지의 y 좌표에서 원본 페이지/컬럼 위치를 역산합니다.

    Args:
        y_in_stitched: 연결된 이미지에서의 y 좌표
        page_heights: 각 페이지의 높이 리스트
        num_pages: 전체 페이지 수

    Returns:
        원본 위치 정보 (페이지 번호, 컬럼, 컬럼 내 y 좌표)
    """
    # 각 컬럼의 시작 y 좌표 계산
    # 순서: [1페이지 좌, 1페이지 우, 2페이지 좌, 2페이지 우, ...]
    column_starts = []
    current_y = 0

    for page_idx in range(num_pages):
        height = page_heights[page_idx] if page_idx < len(page_heights) else page_heights[-1]
        # 좌측 컬럼
        column_starts.append({
            'start': current_y,
            'end': current_y + height,
            'page': page_idx + 1,
            'column': 'left'
        })
        current_y += height
        # 우측 컬럼
        column_starts.append({
            'start': current_y,
            'end': current_y + height,
            'page': page_idx + 1,
            'column': 'right'
        })
        current_y += height

    # y 좌표가 속한 컬럼 찾기
    for col_info in column_starts:
        if col_info['start'] <= y_in_stitched < col_info['end']:
            return {
                'page': col_info['page'],
                'column': col_info['column'],
                'y_in_column': y_in_stitched - col_info['start']
            }

    # 마지막 컬럼 이후인 경우
    last_col = column_starts[-1]
    return {
        'page': last_col['page'],
        'column': last_col['column'],
        'y_in_column': y_in_stitched - last_col['start']
    }
