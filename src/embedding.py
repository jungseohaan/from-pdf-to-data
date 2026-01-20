"""임베딩 생성 모듈

OpenAI text-embedding-3-small을 사용하여 문제 텍스트의 벡터 임베딩 생성
"""

import re
from typing import Optional


def normalize_latex(text: str) -> str:
    """LaTeX 텍스트 정규화

    유사 문제 검색 정확도를 높이기 위해 변수명 등을 추상화

    Args:
        text: 원본 텍스트 (LaTeX 포함)

    Returns:
        정규화된 텍스트
    """
    if not text:
        return ""

    normalized = text

    # 1. 연속 공백을 단일 공백으로
    normalized = re.sub(r'\s+', ' ', normalized)

    # 2. LaTeX 명령어 정규화 (선택적)
    # \frac{a}{b} 형태 유지 (구조는 보존)

    # 3. 일반적인 변수명 추상화 (선택적 - 필요시 활성화)
    # 주의: 너무 공격적인 추상화는 검색 품질을 떨어뜨릴 수 있음
    # normalized = re.sub(r'\b[a-z]\b(?![^$]*\$)', 'VAR', normalized)

    # 4. 숫자 정규화 (선택적)
    # 특정 숫자를 NUM으로 치환하면 "같은 유형"의 문제를 찾기 쉬워짐
    # normalized = re.sub(r'\b\d+\b', 'NUM', normalized)

    # 5. 불필요한 문자 제거
    normalized = normalized.strip()

    return normalized


def create_embedding(text: str) -> Optional[list[float]]:
    """OpenAI 임베딩 생성

    Args:
        text: 임베딩할 텍스트

    Returns:
        1536차원 벡터 리스트 또는 None (실패 시)
    """
    if not text or not text.strip():
        return None

    # 텍스트 정규화
    normalized = normalize_latex(text)

    # OpenAI API 키 확인
    from .config import load_settings
    settings = load_settings()
    api_key = settings.get("openai_api_key", "")

    if not api_key:
        print("[WARNING] OpenAI API 키가 설정되지 않았습니다.")
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=normalized
        )

        return response.data[0].embedding

    except ImportError:
        print("[WARNING] openai 패키지가 설치되지 않았습니다. pip install openai")
        return None
    except Exception as e:
        print(f"[ERROR] 임베딩 생성 실패: {e}")
        return None


def create_embeddings_batch(texts: list[str]) -> list[Optional[list[float]]]:
    """배치 임베딩 생성

    여러 텍스트를 한 번에 임베딩 (API 호출 최적화)

    Args:
        texts: 임베딩할 텍스트 리스트

    Returns:
        임베딩 벡터 리스트 (각각 1536차원 또는 None)
    """
    if not texts:
        return []

    # 빈 텍스트 인덱스 추적
    empty_indices = set()
    normalized_texts = []

    for i, text in enumerate(texts):
        if not text or not text.strip():
            empty_indices.add(i)
            normalized_texts.append("")  # 플레이스홀더
        else:
            normalized_texts.append(normalize_latex(text))

    # 비어있지 않은 텍스트만 추출
    non_empty_texts = [t for i, t in enumerate(normalized_texts) if i not in empty_indices]

    if not non_empty_texts:
        return [None] * len(texts)

    # OpenAI API 키 확인
    from .config import load_settings
    settings = load_settings()
    api_key = settings.get("openai_api_key", "")

    if not api_key:
        print("[WARNING] OpenAI API 키가 설정되지 않았습니다.")
        return [None] * len(texts)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=non_empty_texts
        )

        # 결과 재구성
        embeddings = [None] * len(texts)
        non_empty_idx = 0

        for i in range(len(texts)):
            if i not in empty_indices:
                embeddings[i] = response.data[non_empty_idx].embedding
                non_empty_idx += 1

        return embeddings

    except ImportError:
        print("[WARNING] openai 패키지가 설치되지 않았습니다. pip install openai")
        return [None] * len(texts)
    except Exception as e:
        print(f"[ERROR] 배치 임베딩 생성 실패: {e}")
        return [None] * len(texts)


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """두 벡터의 코사인 유사도 계산

    Args:
        vec1: 첫 번째 벡터
        vec2: 두 번째 벡터

    Returns:
        -1 ~ 1 사이의 유사도 값 (1에 가까울수록 유사)
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    import math

    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)
