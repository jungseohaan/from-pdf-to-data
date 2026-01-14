"""결과 저장 관리 모듈"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image

from .question_detector import BoundingBox


def save_question_image(
    image: Image.Image,
    question_id: str,
    output_dir: Union[str, Path],
    format: str = 'png',
    quality: int = 95
) -> Path:
    """
    문항 이미지를 파일로 저장합니다.

    Args:
        image: 저장할 이미지
        question_id: 문항 ID (파일명으로 사용)
        output_dir: 출력 디렉토리
        format: 이미지 포맷 (png, jpg 등)
        quality: 이미지 품질 (1-100)

    Returns:
        저장된 파일 경로
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{question_id}.{format}"
    filepath = output_dir / filename

    if format.lower() == 'png':
        image.save(filepath, format='PNG', optimize=True)
    else:
        image.save(filepath, format=format.upper(), quality=quality)

    return filepath


def save_metadata(
    questions: List[dict],
    output_path: Union[str, Path],
    source_pdf: str = "",
    additional_info: Optional[dict] = None
) -> Path:
    """
    메타정보를 JSON 파일로 저장합니다.

    Args:
        questions: 문항 메타정보 리스트
        output_path: 출력 파일 경로
        source_pdf: 원본 PDF 파일명
        additional_info: 추가 정보 딕셔너리

    Returns:
        저장된 파일 경로
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metadata = {
        'source_pdf': source_pdf,
        'processed_at': datetime.now().isoformat(),
        'total_questions': len(questions),
        'questions': questions
    }

    if additional_info:
        metadata.update(additional_info)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return output_path


def create_question_record(
    question_id: str,
    number: Optional[int],
    theme: Optional[str],
    image_path: str,
    source_pages: List[int],
    column: str,
    bbox: BoundingBox
) -> dict:
    """
    단일 문항의 메타정보 레코드를 생성합니다.

    Args:
        question_id: 문항 ID
        number: 문항 번호
        theme: 테마/주제
        image_path: 이미지 파일 경로 (상대 경로)
        source_pages: 원본 페이지 번호 리스트
        column: 컬럼 위치 ('left' 또는 'right')
        bbox: 원본 이미지에서의 경계 상자

    Returns:
        문항 메타정보 딕셔너리
    """
    return {
        'id': question_id,
        'number': number,
        'theme': theme,
        'image_path': image_path,
        'source_pages': source_pages,
        'column': column,
        'bbox': bbox.to_dict() if isinstance(bbox, BoundingBox) else bbox
    }


class OutputManager:
    """결과 저장을 관리하는 클래스"""

    def __init__(
        self,
        output_dir: Union[str, Path],
        image_format: str = 'png',
        image_quality: int = 95
    ):
        """
        Args:
            output_dir: 출력 기본 디렉토리
            image_format: 이미지 저장 포맷
            image_quality: 이미지 품질
        """
        self.output_dir = Path(output_dir)
        self.images_dir = self.output_dir / 'images'
        self.image_format = image_format
        self.image_quality = image_quality
        self.questions: List[dict] = []

        # 디렉토리 생성
        self.images_dir.mkdir(parents=True, exist_ok=True)

    def add_question(
        self,
        image: Image.Image,
        number: Optional[int],
        theme: Optional[str],
        source_pages: List[int],
        column: str,
        bbox: BoundingBox
    ) -> str:
        """
        문항을 저장하고 레코드를 추가합니다.

        Args:
            image: 문항 이미지
            number: 문항 번호
            theme: 테마/주제
            source_pages: 원본 페이지 번호 리스트
            column: 컬럼 위치
            bbox: 경계 상자

        Returns:
            생성된 문항 ID
        """
        # 문항 ID 생성 (순번 기반)
        idx = len(self.questions) + 1
        question_id = f"q{idx:03d}"

        # 이미지 저장
        image_path = save_question_image(
            image,
            question_id,
            self.images_dir,
            self.image_format,
            self.image_quality
        )

        # 상대 경로로 변환
        relative_path = f"images/{question_id}.{self.image_format}"

        # 레코드 생성 및 추가
        record = create_question_record(
            question_id=question_id,
            number=number,
            theme=theme,
            image_path=relative_path,
            source_pages=source_pages,
            column=column,
            bbox=bbox
        )
        self.questions.append(record)

        return question_id

    def save_all(
        self,
        source_pdf: str = "",
        additional_info: Optional[dict] = None
    ) -> Path:
        """
        모든 메타정보를 JSON 파일로 저장합니다.

        Args:
            source_pdf: 원본 PDF 파일명
            additional_info: 추가 정보

        Returns:
            저장된 메타데이터 파일 경로
        """
        metadata_path = self.output_dir / 'metadata.json'
        return save_metadata(
            self.questions,
            metadata_path,
            source_pdf,
            additional_info
        )

    def get_summary(self) -> dict:
        """처리 결과 요약을 반환합니다."""
        return {
            'total_questions': len(self.questions),
            'output_directory': str(self.output_dir),
            'questions_with_number': sum(
                1 for q in self.questions if q['number'] is not None
            ),
            'questions_with_theme': sum(
                1 for q in self.questions if q['theme'] is not None
            )
        }
