"""설정 관리 모듈"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from dotenv import load_dotenv, set_key

# .env 파일 경로 결정
if getattr(sys, 'frozen', False):
    # 빌드된 앱: ~/Library/Application Support/PDFLabeler/
    USER_CONFIG_DIR = Path.home() / "Library" / "Application Support" / "PDFLabeler"
    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE = USER_CONFIG_DIR / ".env"
    # 번들 내 기본 스키마 경로
    BUNDLE_CONFIG_DIR = Path(sys._MEIPASS) / "config"
else:
    # 개발 환경: 프로젝트 루트의 .env
    USER_CONFIG_DIR = Path(__file__).parent.parent / "config"
    ENV_FILE = Path(__file__).parent.parent / ".env"
    BUNDLE_CONFIG_DIR = USER_CONFIG_DIR

CONFIG_DIR = USER_CONFIG_DIR
SCHEMA_FILE = USER_CONFIG_DIR / "output_schema.json"
SOLUTION_SCHEMA_FILE = USER_CONFIG_DIR / "solution_schema.json"

# .env 파일 로드
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    # .env 파일이 없으면 생성
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.touch()
    load_dotenv(ENV_FILE)

# 번들에서 기본 스키마 복사 (없는 경우)
def _ensure_config_files():
    """설정 파일이 없으면 기본값 복사"""
    if getattr(sys, 'frozen', False):
        for filename in ["output_schema.json", "solution_schema.json"]:
            user_file = USER_CONFIG_DIR / filename
            bundle_file = BUNDLE_CONFIG_DIR / filename
            if not user_file.exists() and bundle_file.exists():
                import shutil
                shutil.copy(bundle_file, user_file)

_ensure_config_files()


@dataclass
class LLMModel:
    """LLM 모델 정보"""
    id: str
    name: str
    provider: str  # "gemini", "openai"
    api_key_env: str  # 환경변수 이름
    supports_vision: bool = True


# 지원하는 LLM 모델 목록 (2024년 기준 최신)
AVAILABLE_MODELS: List[LLMModel] = [
    # Google Gemini 모델
    LLMModel("gemini-2.0-flash-exp", "Gemini 2.0 Flash (실험)", "gemini", "GEMINI_API_KEY"),
    LLMModel("gemini-1.5-pro", "Gemini 1.5 Pro", "gemini", "GEMINI_API_KEY"),
    LLMModel("gemini-1.5-flash", "Gemini 1.5 Flash", "gemini", "GEMINI_API_KEY"),
    LLMModel("gemini-1.5-flash-8b", "Gemini 1.5 Flash 8B", "gemini", "GEMINI_API_KEY"),
    # OpenAI 모델
    LLMModel("gpt-4o", "GPT-4o", "openai", "OPENAI_API_KEY"),
    LLMModel("gpt-4o-mini", "GPT-4o Mini", "openai", "OPENAI_API_KEY"),
    LLMModel("gpt-4-turbo", "GPT-4 Turbo", "openai", "OPENAI_API_KEY"),
    LLMModel("o1", "OpenAI o1", "openai", "OPENAI_API_KEY", supports_vision=False),
    LLMModel("o1-mini", "OpenAI o1-mini", "openai", "OPENAI_API_KEY", supports_vision=False),
]


def get_model_by_id(model_id: str) -> Optional[LLMModel]:
    """모델 ID로 모델 정보 조회"""
    for model in AVAILABLE_MODELS:
        if model.id == model_id:
            return model
    return None


def get_models_by_provider(provider: str) -> List[LLMModel]:
    """프로바이더별 모델 목록"""
    return [m for m in AVAILABLE_MODELS if m.provider == provider]


def get_vision_models() -> List[LLMModel]:
    """비전 지원 모델 목록"""
    return [m for m in AVAILABLE_MODELS if m.supports_vision]


# 기본 출력 스키마
DEFAULT_OUTPUT_SCHEMA = {
    "description": "수학 문항 분석 결과 스키마",
    "schema": {
        "type": "{box_type}",
        "theme_name": "{theme_name}",
        "question_number": "문제 번호 (숫자 또는 null)",
        "content": {
            "question_text": "문항 본문 전체 (수식은 LaTeX)",
            "choices": [
                {"label": "①②③④⑤", "text": "선택지 내용"}
            ],
            "sub_questions": [
                {"label": "(가)(나) 또는 ㄱㄴㄷ", "text": "보기 내용"}
            ],
            "graphs": [
                {
                    "description": "그래프/그림 설명",
                    "bbox": {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
                }
            ]
        }
    },
    "rules": [
        "question_text: 이미지의 모든 텍스트를 빠짐없이 추출. 첫 단어부터 끝까지 완전하게.",
        "수식은 LaTeX로 변환: 인라인 $수식$, 블록 $$수식$$",
        "choices: 선택지가 있으면 배열로 (없으면 빈 배열)",
        "sub_questions: 보기가 있으면 배열로 (없으면 빈 배열)",
        "graphs: 그래프/그림이 있으면 상대 좌표(0~1)로 bbox 반환",
        "question_number: 문제 번호가 보이면 숫자로"
    ]
}


def ensure_config_dir():
    """설정 디렉토리 생성"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_output_schema() -> dict:
    """출력 스키마 로드 (없으면 기본값 생성)"""
    ensure_config_dir()
    if SCHEMA_FILE.exists():
        try:
            with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    # 기본 스키마 저장
    save_output_schema(DEFAULT_OUTPUT_SCHEMA)
    return DEFAULT_OUTPUT_SCHEMA


# 기본 해설 스키마
DEFAULT_SOLUTION_SCHEMA = {
    "description": "수학 해설 분석 결과 스키마",
    "schema": {
        "type": "{box_type}",
        "theme_name": "{theme_name}",
        "question_number": "문제 번호 (숫자 또는 null)",
        "content": {
            "solution_text": "해설 본문 전체 (수식은 LaTeX로 변환)",
            "answer": "정답 (숫자, 문자, 수식 등)",
            "key_concepts": ["핵심 개념 1", "핵심 개념 2"],
            "graphs": [
                {
                    "description": "그래프/그림 설명",
                    "bbox": {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
                }
            ]
        }
    },
    "rules": [
        "solution_text: 해설의 모든 텍스트를 빠짐없이 추출. 풀이 과정 전체를 완전하게 포함.",
        "모든 수식은 반드시 LaTeX로 변환: 인라인 수식은 $...$로, 독립 수식은 $$...$$로 감싸기.",
        "answer: 최종 정답을 추출. 수식이면 LaTeX로 변환",
        "key_concepts: 해설에서 사용된 핵심 수학 개념을 배열로 추출. 없으면 빈 배열 []",
        "graphs: 그래프/그림이 있으면 상대 좌표(0~1)로 bbox 반환. 없으면 빈 배열 []",
        "question_number: 해설이 어떤 문제 번호의 풀이인지 숫자로"
    ]
}


def load_solution_schema() -> dict:
    """해설 스키마 로드 (없으면 기본값 생성)"""
    ensure_config_dir()
    if SOLUTION_SCHEMA_FILE.exists():
        try:
            with open(SOLUTION_SCHEMA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    # 기본 스키마 저장
    save_solution_schema(DEFAULT_SOLUTION_SCHEMA)
    return DEFAULT_SOLUTION_SCHEMA


def save_solution_schema(schema: dict) -> bool:
    """해설 스키마 저장"""
    ensure_config_dir()
    try:
        with open(SOLUTION_SCHEMA_FILE, 'w', encoding='utf-8') as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def save_output_schema(schema: dict) -> bool:
    """출력 스키마 저장"""
    ensure_config_dir()
    try:
        with open(SCHEMA_FILE, 'w', encoding='utf-8') as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_settings() -> dict:
    """설정 로드 (.env 환경변수에서)"""
    # .env 다시 로드 (변경 반영)
    load_dotenv(ENV_FILE, override=True)

    return {
        "selected_model": os.getenv("SELECTED_MODEL", "gemini-2.0-flash-exp"),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "supabase_url": os.getenv("SUPABASE_URL", ""),
        "supabase_key": os.getenv("SUPABASE_KEY", ""),
    }


def save_settings(settings: dict) -> bool:
    """설정 저장 (.env 파일에)"""
    try:
        # 환경변수 이름 매핑
        env_mapping = {
            "selected_model": "SELECTED_MODEL",
            "gemini_api_key": "GEMINI_API_KEY",
            "openai_api_key": "OPENAI_API_KEY",
            "supabase_url": "SUPABASE_URL",
            "supabase_key": "SUPABASE_KEY",
        }

        for key, env_name in env_mapping.items():
            if key in settings:
                value = settings[key] or ""
                set_key(str(ENV_FILE), env_name, value)
                os.environ[env_name] = value

        return True
    except Exception as e:
        print(f"설정 저장 실패: {e}", file=sys.stderr)
        return False


def generate_prompt_from_schema(schema: dict, box_type: str, theme_name: str) -> str:
    """스키마를 기반으로 프롬프트 생성

    box_type이 "solution" 또는 "해설"이면 해설용 스키마 사용
    """
    # 해설 타입인지 확인
    is_solution = box_type.lower() in ("solution", "해설")

    # 해설이면 해설 스키마 사용
    if is_solution:
        schema = load_solution_schema()
        type_name = "해설"
    else:
        type_name = "문제"

    schema_json = json.dumps(schema["schema"], ensure_ascii=False, indent=2)
    # 플레이스홀더 치환
    schema_json = schema_json.replace("{box_type}", box_type)
    schema_json = schema_json.replace("{theme_name}", theme_name or "미지정")

    rules_text = "\n".join(f"{i+1}. {rule}" for i, rule in enumerate(schema.get("rules", [])))

    if is_solution:
        prompt = f"""이 이미지는 수학 시험지의 해설/풀이입니다.
이미지에 있는 모든 텍스트를 빠짐없이 정확하게 추출하여 다음 JSON 형식으로 반환해주세요.

중요:
- 풀이 과정의 첫 글자부터 마지막 글자까지 모든 텍스트를 누락 없이 추출하세요.
- 해설에는 선택지(①②③④⑤)나 보기((가)(나))가 없습니다.
- 풀이 과정과 최종 정답을 정확히 추출하세요.

{schema_json}

규칙:
{rules_text}

JSON만 반환하세요."""
    else:
        prompt = f"""이 이미지는 수학 시험지의 {type_name}입니다.
이미지에 있는 모든 텍스트를 빠짐없이 정확하게 추출하여 다음 JSON 형식으로 반환해주세요.

중요: 이미지의 첫 글자부터 마지막 글자까지 모든 텍스트를 누락 없이 추출하세요.

{schema_json}

규칙:
{rules_text}

JSON만 반환하세요."""
    return prompt
