"""PDF를 페이지별 이미지로 변환하는 모듈"""

from pathlib import Path
from typing import List, Union

from pdf2image import convert_from_path
from PIL import Image


def convert_pdf_to_images(pdf_path: Union[str, Path], dpi: int = 300) -> List[Image.Image]:
    """
    PDF 파일을 페이지별 이미지로 변환합니다.

    Args:
        pdf_path: PDF 파일 경로
        dpi: 렌더링 해상도 (기본값: 300)

    Returns:
        페이지별 PIL Image 객체 리스트
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

    if not pdf_path.suffix.lower() == '.pdf':
        raise ValueError(f"PDF 파일이 아닙니다: {pdf_path}")

    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        fmt='png'
    )

    return images


def get_pdf_info(pdf_path: Union[str, Path]) -> dict:
    """
    PDF 파일의 기본 정보를 반환합니다.

    Args:
        pdf_path: PDF 파일 경로

    Returns:
        PDF 정보 딕셔너리 (파일명, 페이지 수 등)
    """
    pdf_path = Path(pdf_path)

    # 첫 페이지만 로드하여 정보 확인
    images = convert_from_path(
        str(pdf_path),
        dpi=72,  # 낮은 해상도로 빠르게 확인
        first_page=1,
        last_page=1
    )

    # 전체 페이지 수 확인을 위해 다시 로드
    all_images = convert_from_path(str(pdf_path), dpi=72)

    return {
        'filename': pdf_path.name,
        'path': str(pdf_path.absolute()),
        'page_count': len(all_images),
        'page_size': images[0].size if images else (0, 0)
    }
