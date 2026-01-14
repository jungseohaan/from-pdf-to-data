"""PDF 수학 문제 추출 배치 처리 CLI"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import yaml

from .pdf_processor import convert_pdf_to_images, get_pdf_info
from .image_stitcher import process_pages_to_single_image, calculate_original_position
from .question_detector import detect_questions, BoundingBox
from .metadata_extractor import extract_question_number_from_top_left
from .output_manager import OutputManager


def load_config(config_path: Optional[str] = None) -> dict:
    """설정 파일을 로드합니다."""
    default_config = {
        'pdf': {'dpi': 300},
        'layout': {'columns': 2, 'column_gap_ratio': 0.05},
        'detection': {
            'min_gap_height': 30,
            'number_pattern': r'^\s*(\d+)\s*[.\):]',
            'whitespace_threshold': 250
        },
        'output': {'image_format': 'png', 'image_quality': 95}
    }

    if config_path and Path(config_path).exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f)
            # 기본 설정에 사용자 설정 병합
            for key, value in user_config.items():
                if key in default_config and isinstance(value, dict):
                    default_config[key].update(value)
                else:
                    default_config[key] = value

    return default_config


def process_single_pdf(
    pdf_path: Path,
    output_dir: Path,
    config: dict,
    verbose: bool = False
) -> dict:
    """
    단일 PDF 파일을 처리합니다.

    Args:
        pdf_path: PDF 파일 경로
        output_dir: 출력 디렉토리
        config: 설정 딕셔너리
        verbose: 상세 출력 여부

    Returns:
        처리 결과 요약
    """
    if verbose:
        print(f"처리 중: {pdf_path.name}")

    # 1단계: PDF를 이미지로 변환
    if verbose:
        print("  [1/4] PDF를 이미지로 변환 중...")

    dpi = config['pdf']['dpi']
    pages = convert_pdf_to_images(pdf_path, dpi=dpi)

    if verbose:
        print(f"        {len(pages)} 페이지 변환 완료")

    # 2단계: 2컬럼 처리 및 수직 연결
    if verbose:
        print("  [2/4] 컬럼 분리 및 이미지 연결 중...")

    gap_ratio = config['layout']['column_gap_ratio']
    stitched_image = process_pages_to_single_image(pages, gap_ratio=gap_ratio)
    page_heights = [p.height for p in pages]

    if verbose:
        print(f"        연결된 이미지 크기: {stitched_image.size}")

    # 3단계: 문항 영역 감지
    if verbose:
        print("  [3/4] 문항 영역 감지 중...")

    min_gap_height = config['detection']['min_gap_height']
    whitespace_threshold = config['detection']['whitespace_threshold']
    min_question_height = config['detection'].get('min_question_height', 100)

    detected_questions = detect_questions(
        stitched_image,
        min_gap_height=min_gap_height,
        whitespace_threshold=whitespace_threshold,
        min_question_height=min_question_height
    )

    if verbose:
        print(f"        {len(detected_questions)} 개 문항 감지됨")

    # 4단계: 문항 번호 확인 및 이미지 저장
    if verbose:
        print("  [4/4] 문항 번호 확인 및 이미지 저장 중...")

    output_manager = OutputManager(
        output_dir=output_dir,
        image_format=config['output']['image_format'],
        image_quality=config['output']['image_quality']
    )

    skipped_count = 0
    for question_image, bbox in detected_questions:
        # 좌상단에서 문항 번호 추출
        question_number = extract_question_number_from_top_left(question_image)

        # 문항 번호가 없으면 폐기
        if question_number is None:
            skipped_count += 1
            continue

        # 원본 위치 계산
        original_pos = calculate_original_position(
            bbox.y,
            page_heights,
            len(pages)
        )

        # 저장
        output_manager.add_question(
            image=question_image,
            number=question_number,
            theme=None,
            source_pages=[original_pos['page']],
            column=original_pos['column'],
            bbox=bbox
        )

    if verbose and skipped_count > 0:
        print(f"        (문항 번호 없음으로 {skipped_count}개 폐기됨)")

    output_manager.save_all(source_pdf=pdf_path.name)

    summary = output_manager.get_summary()

    if verbose:
        print(f"        완료: {summary['total_questions']} 개 문항 이미지 저장됨")

    return summary


def process_batch(
    input_path: Path,
    output_base_dir: Path,
    config: dict,
    verbose: bool = False
) -> List[dict]:
    """
    폴더 내 모든 PDF 파일을 처리합니다.

    Args:
        input_path: 입력 폴더 경로
        output_base_dir: 출력 기본 디렉토리
        config: 설정 딕셔너리
        verbose: 상세 출력 여부

    Returns:
        각 파일 처리 결과 요약 리스트
    """
    pdf_files = list(input_path.glob("*.pdf"))

    if not pdf_files:
        print(f"PDF 파일을 찾을 수 없습니다: {input_path}")
        return []

    print(f"{len(pdf_files)} 개의 PDF 파일을 처리합니다.")

    results = []
    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"\n[{i}/{len(pdf_files)}]")

        # 각 PDF별 출력 폴더 생성
        output_dir = output_base_dir / pdf_file.stem

        try:
            result = process_single_pdf(pdf_file, output_dir, config, verbose)
            result['file'] = pdf_file.name
            result['status'] = 'success'
        except Exception as e:
            result = {
                'file': pdf_file.name,
                'status': 'error',
                'error': str(e)
            }
            print(f"  오류 발생: {e}")

        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser(
        description='PDF 수학 문제 추출 배치 처리 도구'
    )
    parser.add_argument(
        'input',
        type=str,
        help='입력 PDF 파일 또는 폴더 경로'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='output',
        help='출력 디렉토리 (기본값: output)'
    )
    parser.add_argument(
        '-c', '--config',
        type=str,
        help='설정 파일 경로 (YAML)'
    )
    parser.add_argument(
        '--batch',
        action='store_true',
        help='폴더 내 모든 PDF 파일 일괄 처리'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='상세 출력'
    )

    args = parser.parse_args()

    # 설정 로드
    config = load_config(args.config)

    input_path = Path(args.input)
    output_dir = Path(args.output)

    if not input_path.exists():
        print(f"입력 경로를 찾을 수 없습니다: {input_path}")
        sys.exit(1)

    # 배치 모드 또는 단일 파일 모드
    if args.batch or input_path.is_dir():
        if not input_path.is_dir():
            print("배치 모드에서는 폴더 경로를 지정해야 합니다.")
            sys.exit(1)
        results = process_batch(input_path, output_dir, config, args.verbose)

        # 결과 요약
        success = sum(1 for r in results if r['status'] == 'success')
        print(f"\n처리 완료: {success}/{len(results)} 파일 성공")
    else:
        # 단일 파일 처리
        if input_path.is_dir():
            print("단일 파일 모드에서는 PDF 파일 경로를 지정해야 합니다.")
            print("폴더 처리는 --batch 옵션을 사용하세요.")
            sys.exit(1)

        result = process_single_pdf(input_path, output_dir, config, args.verbose)
        print(f"\n처리 완료: {result['total_questions']} 개 문항 추출됨")
        print(f"출력 위치: {output_dir}")


if __name__ == '__main__':
    main()
