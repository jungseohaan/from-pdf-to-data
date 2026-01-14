"""문항 번호 및 테마/주제 추출 모듈"""

import re
from typing import Optional, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image


def extract_cyan_text(image: Image.Image) -> Image.Image:
    """
    이미지에서 하늘색(cyan) 텍스트만 추출하여 흑백 이미지로 반환합니다.

    Args:
        image: 원본 이미지

    Returns:
        하늘색 영역이 검은색으로 표시된 흑백 이미지
    """
    # PIL -> OpenCV 변환
    cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

    # BGR -> HSV 변환
    hsv = cv2.cvtColor(cv_image, cv2.COLOR_BGR2HSV)

    # 하늘색(cyan) 범위 정의 (HSV)
    # Hue: 70-105 (하늘색~청록색 범위, 실제 측정값 75-99)
    # Saturation: 20-255 (채도가 있는 색상)
    # Value: 50-255 (어느 정도 밝기 이상)
    lower_cyan = np.array([70, 20, 50])
    upper_cyan = np.array([105, 255, 255])

    # 마스크 생성
    mask = cv2.inRange(hsv, lower_cyan, upper_cyan)

    # 마스크 반전 (하늘색 -> 검은색, 나머지 -> 흰색)
    result = cv2.bitwise_not(mask)

    return Image.fromarray(result)


def extract_question_number_from_top_left(
    image: Image.Image,
    crop_width: int = 150,
    crop_height: int = 100
) -> Optional[int]:
    """
    문항 이미지의 좌상단 영역에서 하늘색 문항 번호를 추출합니다.

    Args:
        image: 문항 이미지
        crop_width: 좌상단 크롭 너비 (픽셀)
        crop_height: 좌상단 크롭 높이 (픽셀)

    Returns:
        문항 번호 (정수) 또는 None
    """
    width, height = image.size

    # 좌상단 영역만 크롭
    top_left = image.crop((
        0,
        0,
        min(width, crop_width),
        min(height, crop_height)
    ))

    # 하늘색 텍스트만 추출
    cyan_only = extract_cyan_text(top_left)

    # OCR 실행 (하늘색 추출 이미지)
    try:
        text = pytesseract.image_to_string(
            cyan_only,
            lang='eng',  # 숫자만 인식하므로 영어로 충분
            config='--psm 6 -c tessedit_char_whitelist=0123456789'
        )
    except Exception:
        try:
            text = pytesseract.image_to_string(cyan_only)
        except Exception:
            return None

    # 숫자 패턴 찾기
    text = text.strip()

    # 숫자만 추출
    match = re.search(r'(\d{1,3})', text)
    if match:
        try:
            num = int(match.group(1))
            # 합리적인 문항 번호 범위 (1~999)
            if 1 <= num <= 999:
                return num
        except ValueError:
            pass

    return None


def extract_question_number(
    image: Image.Image,
    pattern: str = r"^\s*(\d+)\s*[.\):]"
) -> Optional[int]:
    """
    문항 이미지에서 문항 번호를 추출합니다. (기존 호환용)

    Args:
        image: 문항 이미지
        pattern: 문항 번호를 찾기 위한 정규식 패턴

    Returns:
        문항 번호 (정수) 또는 None
    """
    return extract_question_number_from_top_left(image)


def extract_theme(
    image: Image.Image,
    keywords: Optional[list] = None
) -> Optional[str]:
    """
    문항 이미지에서 테마/주제를 추출합니다.

    Args:
        image: 문항 이미지
        keywords: 찾을 테마 키워드 리스트 (None이면 기본 목록 사용)

    Returns:
        감지된 테마 문자열 또는 None
    """
    if keywords is None:
        keywords = [
            # 수학 주제들
            "방정식", "부등식", "함수", "미분", "적분",
            "확률", "통계", "수열", "급수", "극한",
            "삼각함수", "지수", "로그", "행렬", "벡터",
            "도형", "좌표", "기하", "집합", "명제",
            # 일반적인 분류
            "기본", "응용", "심화", "유형", "단원"
        ]

    # 상단 영역만 크롭 (테마 정보는 보통 상단에 있음)
    width, height = image.size
    top_region = image.crop((0, 0, width, min(height, 200)))

    try:
        text = pytesseract.image_to_string(
            top_region,
            lang='kor+eng',
            config='--psm 6'
        )
    except Exception:
        try:
            text = pytesseract.image_to_string(top_region)
        except Exception:
            return None

    # 키워드 매칭
    text_lower = text.lower()
    for keyword in keywords:
        if keyword.lower() in text_lower:
            return keyword

    # 대괄호나 괄호 안의 텍스트 추출 시도
    bracket_patterns = [
        r"\[([^\]]+)\]",      # [테마]
        r"【([^】]+)】",       # 【테마】
        r"<([^>]+)>",         # <테마>
        r"\(([^)]+)\)",       # (테마) - 짧은 것만
    ]

    for pattern in bracket_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if 2 <= len(match) <= 10:  # 적절한 길이의 테마만
                return match.strip()

    return None


def extract_metadata(
    image: Image.Image,
    number_pattern: str = r"^\s*(\d+)\s*[.\):]",
    theme_keywords: Optional[list] = None
) -> dict:
    """
    문항 이미지에서 메타정보를 추출합니다.

    Args:
        image: 문항 이미지
        number_pattern: 문항 번호 정규식 패턴
        theme_keywords: 테마 키워드 리스트

    Returns:
        메타정보 딕셔너리 {'number': int|None, 'theme': str|None}
    """
    return {
        'number': extract_question_number(image, number_pattern),
        'theme': extract_theme(image, theme_keywords)
    }


def batch_extract_metadata(
    images: list,
    number_pattern: str = r"^\s*(\d+)\s*[.\):]",
    theme_keywords: Optional[list] = None
) -> list:
    """
    여러 문항 이미지에서 메타정보를 일괄 추출합니다.

    Args:
        images: 문항 이미지 리스트
        number_pattern: 문항 번호 정규식 패턴
        theme_keywords: 테마 키워드 리스트

    Returns:
        메타정보 딕셔너리 리스트
    """
    results = []
    for image in images:
        metadata = extract_metadata(image, number_pattern, theme_keywords)
        results.append(metadata)
    return results
