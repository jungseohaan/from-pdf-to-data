"""OpenCV 기반 문항 영역 감지 모듈"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image


@dataclass
class BoundingBox:
    """문항 영역의 경계 상자"""
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict:
        return {
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height
        }


@dataclass
class QuestionRegion:
    """감지된 문항 영역 정보"""
    bbox: BoundingBox
    question_number: Optional[int] = None
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            'bbox': self.bbox.to_dict(),
            'question_number': self.question_number,
            'confidence': self.confidence
        }


def pil_to_cv2(image: Image.Image) -> np.ndarray:
    """PIL 이미지를 OpenCV 형식으로 변환"""
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def cv2_to_pil(image: np.ndarray) -> Image.Image:
    """OpenCV 이미지를 PIL 형식으로 변환"""
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def detect_horizontal_gaps(
    image: Image.Image,
    min_gap_height: int = 30,
    whitespace_threshold: int = 250,
    min_white_ratio: float = 0.95
) -> List[Tuple[int, int]]:
    """
    이미지에서 수평 여백 영역(문항 사이 구분)을 감지합니다.

    Args:
        image: 분석할 이미지
        min_gap_height: 최소 여백 높이 (픽셀)
        whitespace_threshold: 여백으로 인식할 밝기 임계값 (0-255)
        min_white_ratio: 여백 행으로 인식할 최소 흰색 비율

    Returns:
        여백 영역 리스트 [(시작_y, 끝_y), ...]
    """
    # 그레이스케일 변환
    cv_image = pil_to_cv2(image)
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)

    height, width = gray.shape

    # 각 행의 흰색 비율 계산
    white_ratios = []
    for y in range(height):
        row = gray[y, :]
        white_pixels = np.sum(row >= whitespace_threshold)
        white_ratios.append(white_pixels / width)

    # 여백 행 찾기
    is_gap_row = [ratio >= min_white_ratio for ratio in white_ratios]

    # 연속된 여백 영역 그룹화
    gaps = []
    gap_start = None

    for y, is_gap in enumerate(is_gap_row):
        if is_gap and gap_start is None:
            gap_start = y
        elif not is_gap and gap_start is not None:
            if y - gap_start >= min_gap_height:
                gaps.append((gap_start, y))
            gap_start = None

    # 마지막 여백 처리
    if gap_start is not None and height - gap_start >= min_gap_height:
        gaps.append((gap_start, height))

    return gaps


def find_question_boundaries(
    image: Image.Image,
    min_gap_height: int = 30,
    whitespace_threshold: int = 250
) -> List[BoundingBox]:
    """
    이미지에서 문항 경계를 찾아 BoundingBox 리스트로 반환합니다.

    Args:
        image: 분석할 이미지 (수직으로 연결된 전체 이미지)
        min_gap_height: 최소 여백 높이
        whitespace_threshold: 여백 인식 밝기 임계값

    Returns:
        문항별 BoundingBox 리스트
    """
    width, height = image.size

    # 여백 영역 감지
    gaps = detect_horizontal_gaps(
        image,
        min_gap_height=min_gap_height,
        whitespace_threshold=whitespace_threshold
    )

    # 여백 사이를 문항 영역으로 처리
    boundaries = []

    # 첫 여백 이전 영역
    if gaps:
        first_gap_start = gaps[0][0]
        if first_gap_start > min_gap_height:
            boundaries.append(BoundingBox(
                x=0, y=0, width=width, height=first_gap_start
            ))

        # 여백 사이 영역들
        for i in range(len(gaps) - 1):
            current_gap_end = gaps[i][1]
            next_gap_start = gaps[i + 1][0]

            if next_gap_start - current_gap_end > min_gap_height:
                boundaries.append(BoundingBox(
                    x=0,
                    y=current_gap_end,
                    width=width,
                    height=next_gap_start - current_gap_end
                ))

        # 마지막 여백 이후 영역
        last_gap_end = gaps[-1][1]
        if height - last_gap_end > min_gap_height:
            boundaries.append(BoundingBox(
                x=0, y=last_gap_end, width=width, height=height - last_gap_end
            ))
    else:
        # 여백이 없으면 전체를 하나의 영역으로
        boundaries.append(BoundingBox(x=0, y=0, width=width, height=height))

    return boundaries


def crop_question_regions(
    image: Image.Image,
    boundaries: List[BoundingBox]
) -> List[Image.Image]:
    """
    경계 정보를 사용하여 이미지에서 문항 영역들을 잘라냅니다.

    Args:
        image: 원본 이미지
        boundaries: 문항 경계 리스트

    Returns:
        잘라낸 문항 이미지 리스트
    """
    regions = []
    for bbox in boundaries:
        region = image.crop((
            bbox.x,
            bbox.y,
            bbox.x + bbox.width,
            bbox.y + bbox.height
        ))
        regions.append(region)
    return regions


def trim_whitespace(
    image: Image.Image,
    threshold: int = 250,
    padding: int = 10
) -> Image.Image:
    """
    이미지의 상하좌우 여백을 제거합니다.

    Args:
        image: 원본 이미지
        threshold: 여백 인식 밝기 임계값
        padding: 유지할 여백 크기 (픽셀)

    Returns:
        여백이 제거된 이미지
    """
    cv_image = pil_to_cv2(image)
    gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)

    # 컨텐츠가 있는 영역 찾기
    content_mask = gray < threshold
    rows = np.any(content_mask, axis=1)
    cols = np.any(content_mask, axis=0)

    if not np.any(rows) or not np.any(cols):
        return image  # 컨텐츠가 없으면 원본 반환

    y_min, y_max = np.where(rows)[0][[0, -1]]
    x_min, x_max = np.where(cols)[0][[0, -1]]

    # 패딩 적용
    height, width = gray.shape
    y_min = max(0, y_min - padding)
    y_max = min(height, y_max + padding + 1)
    x_min = max(0, x_min - padding)
    x_max = min(width, x_max + padding + 1)

    return image.crop((x_min, y_min, x_max, y_max))


def detect_questions(
    image: Image.Image,
    min_gap_height: int = 30,
    whitespace_threshold: int = 250,
    trim_whitespace_enabled: bool = True,
    min_question_height: int = 100
) -> List[Tuple[Image.Image, BoundingBox]]:
    """
    이미지에서 문항들을 감지하고 추출합니다.

    Args:
        image: 분석할 이미지 (수직으로 연결된 전체 이미지)
        min_gap_height: 최소 여백 높이
        whitespace_threshold: 여백 인식 밝기 임계값
        trim_whitespace_enabled: 각 문항의 여백 제거 여부
        min_question_height: 최소 문항 높이 (이보다 작은 영역은 무시)

    Returns:
        (문항 이미지, 원본 위치 BoundingBox) 튜플 리스트
    """
    # 문항 경계 찾기
    boundaries = find_question_boundaries(
        image,
        min_gap_height=min_gap_height,
        whitespace_threshold=whitespace_threshold
    )

    # 문항 영역 추출 (최소 높이 필터링 적용)
    results = []
    for bbox in boundaries:
        # 최소 높이보다 작은 영역은 건너뛰기
        if bbox.height < min_question_height:
            continue

        region = image.crop((
            bbox.x,
            bbox.y,
            bbox.x + bbox.width,
            bbox.y + bbox.height
        ))

        if trim_whitespace_enabled:
            region = trim_whitespace(region, threshold=whitespace_threshold)

        # 트리밍 후에도 최소 높이 체크
        if region.height >= min_question_height:
            results.append((region, bbox))

    return results
