"""설정 관리 모듈"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

# 설정 파일 경로
CONFIG_DIR = Path(__file__).parent.parent / "config"
SCHEMA_FILE = CONFIG_DIR / "output_schema.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


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
    """설정 로드"""
    ensure_config_dir()
    default_settings = {
        "selected_model": "gemini-2.0-flash-exp",
        "gemini_api_key": "",
        "openai_api_key": "",
    }
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                default_settings.update(saved)
        except Exception:
            pass
    return default_settings


def save_settings(settings: dict) -> bool:
    """설정 저장"""
    ensure_config_dir()
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def generate_prompt_from_schema(schema: dict, box_type: str, theme_name: str) -> str:
    """스키마를 기반으로 프롬프트 생성"""
    schema_json = json.dumps(schema["schema"], ensure_ascii=False, indent=2)
    # 플레이스홀더 치환
    schema_json = schema_json.replace("{box_type}", box_type)
    schema_json = schema_json.replace("{theme_name}", theme_name or "미지정")

    rules_text = "\n".join(f"{i+1}. {rule}" for i, rule in enumerate(schema.get("rules", [])))

    prompt = f"""이 이미지는 수학 시험지의 {box_type}입니다.
이미지에 있는 모든 텍스트를 빠짐없이 정확하게 추출하여 다음 JSON 형식으로 반환해주세요.

중요: 이미지의 첫 글자부터 마지막 글자까지 모든 텍스트를 누락 없이 추출하세요.

{schema_json}

규칙:
{rules_text}

JSON만 반환하세요."""
    return prompt
