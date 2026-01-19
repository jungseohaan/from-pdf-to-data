"""Supabase 클라이언트 모듈

Supabase 연결 및 기본 작업을 위한 싱글톤 클라이언트
"""

import os
from typing import Optional
from pathlib import Path

# .env 파일 로드
from dotenv import load_dotenv

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

# 싱글톤 클라이언트
_supabase_client = None


def get_supabase_credentials() -> tuple[Optional[str], Optional[str]]:
    """Supabase 자격 증명 조회 (설정 파일 → 환경변수 순서)"""
    from .config import load_settings

    settings = load_settings()

    # 설정 파일에서 먼저 확인
    url = settings.get("supabase_url", "")
    key = settings.get("supabase_key", "")

    # 환경변수에서 확인 (여러 변수명 지원)
    if not url:
        url = os.getenv("SUPABASE_URL", "") or os.getenv("SUPABASE_PROJECT_URL", "")
    if not key:
        key = os.getenv("SUPABASE_KEY", "") or os.getenv("SUPABASE_API_KEY", "")

    return (url if url else None, key if key else None)


def get_supabase_client():
    """Supabase 클라이언트 싱글톤 반환

    Returns:
        supabase.Client 또는 None (자격 증명 없는 경우)
    """
    global _supabase_client

    if _supabase_client is not None:
        return _supabase_client

    url, key = get_supabase_credentials()
    if not url or not key:
        return None

    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        return _supabase_client
    except ImportError:
        print("[WARNING] supabase 패키지가 설치되지 않았습니다. pip install supabase")
        return None
    except Exception as e:
        print(f"[ERROR] Supabase 클라이언트 생성 실패: {e}")
        return None


def reset_supabase_client():
    """클라이언트 리셋 (설정 변경 시 사용)"""
    global _supabase_client
    _supabase_client = None


def test_supabase_connection() -> tuple[bool, str]:
    """Supabase 연결 테스트

    Returns:
        (성공 여부, 메시지)
    """
    url, key = get_supabase_credentials()

    if not url:
        return False, "Supabase URL이 설정되지 않았습니다."
    if not key:
        return False, "Supabase API Key가 설정되지 않았습니다."

    try:
        from supabase import create_client
        client = create_client(url, key)

        # 간단한 쿼리로 연결 테스트
        # textbooks 테이블 존재 여부 확인
        result = client.table("textbooks").select("id").limit(1).execute()
        return True, "Supabase 연결 성공!"

    except ImportError:
        return False, "supabase 패키지가 설치되지 않았습니다.\npip install supabase"
    except Exception as e:
        error_msg = str(e)
        if "relation" in error_msg and "does not exist" in error_msg:
            return False, "테이블이 존재하지 않습니다.\nsupabase/schema.sql을 실행해주세요."
        elif "Invalid API key" in error_msg or "invalid" in error_msg.lower():
            return False, "유효하지 않은 API Key입니다."
        elif "network" in error_msg.lower() or "connection" in error_msg.lower():
            return False, f"네트워크 연결 오류: {error_msg}"
        else:
            return False, f"연결 오류: {error_msg}"
