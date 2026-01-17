"""구글 OAuth 인증 모듈"""

import json
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

# OAuth 스코프 (기본 프로필 정보만)
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# 설정 파일 경로
CONFIG_DIR = Path(__file__).parent.parent / "config"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
TOKEN_FILE = CONFIG_DIR / "token.json"


class GoogleAuth:
    """구글 인증 관리 클래스"""

    def __init__(self):
        self._credentials: Optional[Credentials] = None
        self._user_info: Optional[dict] = None

    @property
    def is_logged_in(self) -> bool:
        """로그인 상태 확인"""
        return self._credentials is not None and self._credentials.valid

    @property
    def user_info(self) -> Optional[dict]:
        """현재 로그인한 사용자 정보"""
        return self._user_info

    @property
    def user_email(self) -> Optional[str]:
        """현재 로그인한 사용자 이메일"""
        if self._user_info:
            return self._user_info.get("email")
        return None

    @property
    def user_name(self) -> Optional[str]:
        """현재 로그인한 사용자 이름"""
        if self._user_info:
            return self._user_info.get("name")
        return None

    def try_auto_login(self) -> bool:
        """저장된 토큰으로 자동 로그인 시도"""
        if not TOKEN_FILE.exists():
            return False

        try:
            self._credentials = Credentials.from_authorized_user_file(
                str(TOKEN_FILE), SCOPES
            )

            # 토큰이 만료되었으면 갱신 시도
            if self._credentials.expired and self._credentials.refresh_token:
                self._credentials.refresh(Request())
                self._save_token()

            if self._credentials.valid:
                self._fetch_user_info()
                return True

        except Exception:
            # 토큰 파일이 손상되었거나 갱신 실패
            self._credentials = None
            if TOKEN_FILE.exists():
                TOKEN_FILE.unlink()

        return False

    def login(self) -> bool:
        """구글 로그인 수행 (브라우저 열림)"""
        if not CREDENTIALS_FILE.exists():
            raise FileNotFoundError(
                f"credentials.json 파일이 없습니다: {CREDENTIALS_FILE}"
            )

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            # 로컬 서버를 통한 OAuth 플로우 (브라우저 자동 열림)
            self._credentials = flow.run_local_server(
                port=0,
                prompt='consent',
                success_message='로그인 성공! 이 창을 닫아도 됩니다.',
                open_browser=True
            )

            # 토큰 저장
            self._save_token()

            # 사용자 정보 가져오기
            self._fetch_user_info()

            return True

        except Exception as e:
            self._credentials = None
            raise RuntimeError(f"로그인 실패: {str(e)}")

    def logout(self):
        """로그아웃 (토큰 삭제)"""
        self._credentials = None
        self._user_info = None

        if TOKEN_FILE.exists():
            TOKEN_FILE.unlink()

    def _save_token(self):
        """토큰을 파일에 저장"""
        if self._credentials:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_FILE, 'w') as f:
                f.write(self._credentials.to_json())

    def _fetch_user_info(self):
        """Google API로 사용자 정보 가져오기"""
        if not self._credentials:
            return

        try:
            from googleapiclient.discovery import build
            service = build('oauth2', 'v2', credentials=self._credentials)
            self._user_info = service.userinfo().get().execute()
        except Exception:
            # API 호출 실패해도 로그인은 유지
            self._user_info = {"email": "unknown", "name": "Unknown User"}


# 싱글톤 인스턴스
_auth_instance: Optional[GoogleAuth] = None


def get_auth() -> GoogleAuth:
    """GoogleAuth 싱글톤 인스턴스 반환"""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = GoogleAuth()
    return _auth_instance
