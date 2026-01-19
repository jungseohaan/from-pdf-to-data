"""LLM API 모듈 (Gemini, OpenAI 지원)"""

import base64
import io
import json
import os
import re
from pathlib import Path
from typing import Optional, List, Tuple

from dotenv import load_dotenv
from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal, QUrl, QRect, QPoint
from PyQt5.QtWidgets import (
    QApplication, QDialog, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget, QRubberBand, QSizePolicy
)
from PyQt5.QtGui import QFont, QImage, QPixmap, QColor, QPainter, QPen, QCursor
from PyQt5.QtCore import Qt
from PyQt5.QtWebEngineWidgets import QWebEngineView

from .models import BOX_TYPE_QUESTION, QuestionBox
from .config import (
    load_settings, load_output_schema, get_model_by_id,
    generate_prompt_from_schema
)

# .env 파일 로드 (프로젝트 루트에서 찾기)
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

# 클라이언트 캐시
_gemini_client = None
_openai_client = None


def get_api_key(provider: str) -> Optional[str]:
    """API 키 조회 (설정 파일 → 환경변수 순서)"""
    settings = load_settings()
    if provider == "gemini":
        key = settings.get("gemini_api_key", "")
        if not key:
            key = os.getenv("GEMINI_API_KEY", "")
        return key if key and key != "your-api-key-here" else None
    elif provider == "openai":
        key = settings.get("openai_api_key", "")
        if not key:
            key = os.getenv("OPENAI_API_KEY", "")
        return key if key else None
    return None


def get_gemini_client():
    """Gemini 클라이언트 반환"""
    global _gemini_client
    if _gemini_client:
        return _gemini_client
    api_key = get_api_key("gemini")
    if not api_key:
        return None
    try:
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
        return _gemini_client
    except Exception:
        return None


def get_openai_client():
    """OpenAI 클라이언트 반환"""
    global _openai_client
    if _openai_client:
        return _openai_client
    api_key = get_api_key("openai")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=api_key)
        return _openai_client
    except Exception:
        return None


def crop_box_image(page_image: Image.Image, box: QuestionBox) -> Image.Image:
    """박스 영역을 이미지에서 크롭"""
    x1, y1, x2, y2 = min(box.x1, box.x2), min(box.y1, box.y2), max(box.x1, box.x2), max(box.y1, box.y2)
    return page_image.crop((x1, y1, x2, y2))


def fix_latex_delimiters(text: str) -> str:
    """LaTeX 수식 구분자가 제대로 닫히지 않은 경우 자동 보정

    예:
    - $$수식 내용 → $$수식 내용$$
    - lim_{x \to 0} ... 의 값은? → $$lim_{x \to 0} ...$$ 의 값은?
    """
    import re

    # 1. $ 구분자 없이 LaTeX 명령어로 시작하는 수식 감지 및 래핑
    # LaTeX 명령어 패턴: \command 또는 일반적인 수학 표현 (lim, sum, int, frac 등)
    latex_commands = r'(?:lim|sum|int|frac|sqrt|sin|cos|tan|log|ln|exp|max|min|sup|inf|prod|bigcup|bigcap|iint|iiint|oint)'

    # 패턴: LaTeX 명령어로 시작하고 "의 값", "을 구", "를 구" 등으로 끝나는 경우
    def wrap_naked_latex(m):
        before = m.group(1) or ""
        content = m.group(2)
        after = m.group(3)
        # 이미 $ 안에 있으면 스킵
        if before.endswith('$'):
            return m.group(0)
        return f'{before}$${content}$${after}'

    # 줄 시작 또는 공백 뒤에 LaTeX 명령어가 오고, 특정 한국어 패턴으로 끝나는 경우
    pattern = rf'(^|\s)({latex_commands}[^$]*?)(\s*(?:의 값|을 구|를 구|이다|입니다|[?]))'
    text = re.sub(pattern, wrap_naked_latex, text, flags=re.MULTILINE)

    # 2. $$ 블록 처리: 열린 $$ 개수와 닫힌 $$ 개수 확인

    # 먼저 $$...$$ 패턴을 찾아서 보호 (정상적인 블록)
    protected = []
    def protect_block(m):
        protected.append(m.group(0))
        return f"__PROTECTED_{len(protected)-1}__"

    # 정상적인 $$...$$ 블록 보호
    text = re.sub(r'\$\$[^$]+\$\$', protect_block, text)

    # 남은 $$ 찾기 (닫히지 않은 블록)
    def fix_unclosed_display(m):
        content = m.group(1)
        if content.strip().endswith('$$'):
            return m.group(0)
        return f'$${content}$$'

    # $$로 시작하고 줄 끝이나 특정 패턴까지
    text = re.sub(r'\$\$([^$]+?)(?=\s*(?:의 값|을 구|를 구|이다|입니다|[.?!]|$))', fix_unclosed_display, text)

    # 보호된 블록 복원
    for i, block in enumerate(protected):
        text = text.replace(f"__PROTECTED_{i}__", block)

    # 3. 인라인 $ 수식 처리: 홀수 개의 $가 있으면 마지막에 $ 추가
    parts = re.split(r'(\$\$[^$]+\$\$)', text)
    result_parts = []

    for part in parts:
        if part.startswith('$$') and part.endswith('$$'):
            result_parts.append(part)
        else:
            dollar_count = part.count('$')
            if dollar_count % 2 == 1:
                part = part + '$'
            result_parts.append(part)

    return ''.join(result_parts)


def generate_katex_html(text: str, choices: list = None, sub_questions: list = None) -> str:
    """텍스트와 LaTeX 수식을 KaTeX로 렌더링하는 HTML 생성"""
    # 수식 구분자 자동 보정
    text = fix_latex_delimiters(text)

    # HTML 이스케이프 (단, $ 기호는 유지)
    def escape_html(s):
        return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # 텍스트에서 수식 부분만 분리하여 처리
    escaped_text = escape_html(text)
    # 줄바꿈을 <br>로 변환
    escaped_text = escaped_text.replace('\n', '<br>')

    # 보기(sub_questions) HTML 생성 - 선택지 위에 표시
    sub_questions_html = ""
    if sub_questions:
        sub_questions_html = "<div class='sub-questions'><div class='sub-questions-title'>〈보기〉</div>"
        for sq in sub_questions:
            label = escape_html(sq.get("label", ""))
            sq_text = escape_html(sq.get("text", ""))
            sub_questions_html += f"<div class='sub-question'><span class='sq-label'>{label}</span>{sq_text}</div>"
        sub_questions_html += "</div>"

    # 선택지 HTML 생성 - 한 줄 배치
    choices_html = ""
    if choices:
        choices_html = "<div class='choices'>"
        for choice in choices:
            label = escape_html(choice.get("label", ""))
            choice_text = escape_html(choice.get("text", ""))
            choices_html += f"<span class='choice'><span class='label'>{label}</span>{choice_text}</span>"
        choices_html += "</div>"

    html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
    <style>
        body {{
            font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', 'Nanum Gothic', sans-serif;
            font-size: 16px;
            line-height: 1.8;
            padding: 20px;
            margin: 0;
            background: white;
            color: #333;
        }}
        .question-text {{
            margin-bottom: 20px;
        }}
        .sub-questions {{
            margin: 15px 0;
            padding: 12px 15px;
            background: #fff8e1;
            border: 1px solid #ffe082;
            border-radius: 6px;
        }}
        .sub-questions-title {{
            font-weight: bold;
            color: #f57c00;
            margin-bottom: 8px;
        }}
        .sub-question {{
            margin: 6px 0;
            padding-left: 10px;
        }}
        .sq-label {{
            font-weight: bold;
            color: #e65100;
            margin-right: 8px;
        }}
        .choices {{
            margin-top: 15px;
            padding: 5px 8px;
            background: #f8f9fa;
            border-radius: 6px;
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            align-items: center;
        }}
        .choice {{
            display: inline-flex;
            align-items: center;
            padding: 4px 8px;
            background: white;
            border-radius: 4px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.08);
        }}
        .choice .label {{
            font-weight: bold;
            margin-right: 6px;
            color: #007bff;
        }}
        .katex {{
            font-size: 1.1em;
        }}
        .katex-display {{
            margin: 15px 0;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="question-text">{escaped_text}</div>
    {sub_questions_html}
    {choices_html}
    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            renderMathInElement(document.body, {{
                delimiters: [
                    {{left: "$$", right: "$$", display: true}},
                    {{left: "$", right: "$", display: false}}
                ],
                throwOnError: false,
                strict: false
            }});
        }});
    </script>
</body>
</html>'''
    return html


def _call_gemini_api(model_id: str, prompt: str, image_bytes: bytes) -> str:
    """Gemini API 호출"""
    import sys
    print(f"[DEBUG] Gemini API 호출 시작: model={model_id}", file=sys.stderr, flush=True)

    client = get_gemini_client()
    if not client:
        raise ValueError("Gemini API 키가 설정되지 않았습니다. 설정에서 API 키를 입력하거나 .env 파일을 확인하세요.")

    from google.genai import types

    try:
        print(f"[DEBUG] generate_content 호출 중...", file=sys.stderr, flush=True)
        response = client.models.generate_content(
            model=model_id,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt),
                        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=8192,  # 출력 토큰 제한 증가
                temperature=0.1,  # 일관된 출력을 위해 낮은 temperature
            )
        )
        print(f"[DEBUG] 응답 수신 완료", file=sys.stderr, flush=True)
        if not response.text:
            raise ValueError("API 응답이 비어있습니다.")
        return response.text
    except Exception as e:
        print(f"[DEBUG] API 에러: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        raise ValueError(f"Gemini API 호출 실패: {str(e)}")


def _call_openai_api(model_id: str, prompt: str, image_bytes: bytes) -> str:
    """OpenAI API 호출"""
    client = get_openai_client()
    if not client:
        raise ValueError("OpenAI API 키가 설정되지 않았습니다. 설정에서 API 키를 입력하거나 .env 파일을 확인하세요.")

    # 이미지를 base64로 인코딩
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        }
                    }
                ]
            }
        ],
        max_tokens=4096
    )
    return response.choices[0].message.content


# 기존 프롬프트 (스키마 기반 프롬프트로 대체되었으나 호환성을 위해 유지)
GEMINI_ANALYSIS_PROMPT = """이 이미지는 수학 시험지의 {box_type}입니다.
이미지에 있는 모든 텍스트를 빠짐없이 정확하게 추출하여 다음 JSON 형식으로 반환해주세요.

중요: 이미지의 첫 글자부터 마지막 글자까지 모든 텍스트를 누락 없이 추출하세요.

{{
  "type": "{box_type}",
  "theme_name": "{theme_name}",
  "question_number": null,
  "content": {{
    "question_text": "문항 본문 전체",
    "choices": [
      {{"label": "①", "text": "선택지 내용"}}
    ],
    "sub_questions": [
      {{"label": "(가)", "text": "보기 내용"}}
    ],
    "graphs": [
      {{
        "description": "그래프 설명",
        "bbox": {{"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}}
      }}
    ]
  }}
}}

규칙:
1. question_text: 이미지에 보이는 문항 본문을 처음부터 끝까지 완전하게 추출
   - 첫 단어부터 빠뜨리지 말 것 (예: "함수", "다음", "그림과 같이" 등 시작 부분 포함)
   - 수식은 LaTeX로 변환:
     * 인라인 수식: $수식$ (문장 속 수식)
     * 블록 수식: $$수식$$ (별도 줄의 큰 수식)
   - 예시: "함수 $f(x)$가 다음과 같을 때" (시작 단어 "함수" 포함)
2. choices: 선택지 ①②③④⑤가 있으면 배열로 (없으면 빈 배열)
3. sub_questions: (가), (나), ㄱ, ㄴ 같은 보기가 있으면 배열로 (없으면 빈 배열)
4. graphs: 그래프/그림이 있으면 상대 좌표(0~1 비율)로 bbox 반환 (없으면 빈 배열)
5. question_number: 문제 번호가 보이면 숫자로 입력 (예: 1, 2, 15 등)

JSON만 반환하세요."""


def analyze_image_with_llm(image: Image.Image, box_type: str, theme_name: str) -> dict:
    """이미지를 선택된 LLM으로 분석하여 구조화된 JSON 반환"""
    import sys
    settings = load_settings()
    model_id = settings.get("selected_model", "gemini-2.0-flash-exp")
    model_info = get_model_by_id(model_id)

    print(f"[DEBUG] analyze_image_with_llm: selected_model={model_id}, provider={model_info.provider if model_info else 'None'}", file=sys.stderr, flush=True)

    if not model_info:
        raise ValueError(f"알 수 없는 모델: {model_id}")

    # 프롬프트 생성 (스키마 기반)
    box_type_korean = "문제" if box_type == BOX_TYPE_QUESTION else "해설"
    schema = load_output_schema()
    prompt = generate_prompt_from_schema(schema, box_type_korean, theme_name)

    # 이미지를 바이트로 변환
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()

    # Provider에 따라 API 호출
    if model_info.provider == "gemini":
        response_text = _call_gemini_api(model_id, prompt, image_bytes)
    elif model_info.provider == "openai":
        response_text = _call_openai_api(model_id, prompt, image_bytes)
    else:
        raise ValueError(f"지원하지 않는 provider: {model_info.provider}")

    # JSON 파싱
    response_text = response_text.strip()
    # JSON 블록 추출 (```json ... ``` 형태일 수 있음)
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        json_lines = []
        in_json = False
        for line in lines:
            if line.startswith("```json"):
                in_json = True
                continue
            elif line.startswith("```"):
                in_json = False
                continue
            if in_json:
                json_lines.append(line)
        response_text = "\n".join(json_lines)

    # LaTeX 백슬래시 이스케이프 처리
    # JSON 파싱 전에 잘못된 이스케이프 시퀀스 수정
    def _add_model_info(result: dict) -> dict:
        """분석 결과에 모델 정보 추가"""
        result["model"] = {
            "id": model_id,
            "name": model_info.name,
            "provider": model_info.provider
        }
        return result

    try:
        result = json.loads(response_text)
        return _add_model_info(result)
    except json.JSONDecodeError:
        # 백슬래시가 제대로 이스케이프되지 않은 경우 처리
        # 일반적인 LaTeX 명령어들의 백슬래시를 이중 백슬래시로 변환
        fixed_text = response_text
        # \로 시작하는 LaTeX 명령어 패턴 (일반적인 것들)
        latex_commands = [
            'frac', 'lim', 'sum', 'int', 'sqrt', 'left', 'right',
            'begin', 'end', 'to', 'infty', 'cdot', 'times', 'div',
            'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'theta',
            'lambda', 'mu', 'pi', 'sigma', 'omega', 'phi', 'psi',
            'leq', 'geq', 'neq', 'approx', 'equiv', 'subset', 'supset',
            'in', 'notin', 'cup', 'cap', 'vee', 'wedge',
            'sin', 'cos', 'tan', 'log', 'ln', 'exp',
            'text', 'mathbf', 'mathrm', 'mathit', 'mathcal',
            'overline', 'underline', 'hat', 'bar', 'vec', 'dot',
            'cases', 'matrix', 'pmatrix', 'bmatrix', 'vmatrix',
            'quad', 'qquad', 'hspace', 'vspace', 'newline',
        ]
        for cmd in latex_commands:
            # \cmd -> \\cmd (단, 이미 \\가 아닌 경우만)
            fixed_text = re.sub(r'(?<!\\)\\(' + cmd + r')', r'\\\\' + cmd, fixed_text)

        try:
            result = json.loads(fixed_text)
            return _add_model_info(result)
        except json.JSONDecodeError:
            # 그래도 실패하면 raw_decode 시도
            # 또는 문자열을 직접 파싱
            import ast
            try:
                # Python literal로 파싱 시도
                result = ast.literal_eval(response_text)
                return _add_model_info(result)
            except:
                raise ValueError(f"JSON 파싱 실패: {response_text[:500]}")


# 호환성을 위한 별칭
analyze_image_with_gemini = analyze_image_with_llm


def extract_graph_images(image: Image.Image, result: dict, use_cv_detection: bool = False) -> dict:
    """AI가 추출한 bbox_percent를 사용하여 그래프 이미지를 base64로 추출

    Args:
        image: 원본 박스 이미지
        result: LLM 분석 결과 (figures에 bbox_percent 포함)
        use_cv_detection: 사용 안 함 (호환성 유지)

    Returns:
        figures에 figure_image_base64가 추가된 result
    """
    content = result.get("content", {})
    figures = content.get("figures", [])

    if not figures or not image:
        return result

    img_width, img_height = image.size

    for fig in figures:
        bbox = fig.get("bbox_percent")
        if not bbox:
            continue

        try:
            # bbox_percent를 실제 픽셀 좌표로 변환
            x1 = int(bbox.get("x1", 0) * img_width)
            y1 = int(bbox.get("y1", 0) * img_height)
            x2 = int(bbox.get("x2", 1) * img_width)
            y2 = int(bbox.get("y2", 1) * img_height)

            # 유효성 검사
            x1, x2 = max(0, min(x1, x2)), min(img_width, max(x1, x2))
            y1, y2 = max(0, min(y1, y2)), min(img_height, max(y1, y2))

            if x2 - x1 < 10 or y2 - y1 < 10:
                continue

            # 크롭 및 base64 인코딩
            cropped = image.crop((x1, y1, x2, y2))
            buffer = io.BytesIO()
            cropped.save(buffer, format='PNG')
            buffer.seek(0)
            fig["figure_image_base64"] = base64.b64encode(buffer.getvalue()).decode('utf-8')

        except Exception as e:
            print(f"그래프 이미지 추출 실패: {e}")
            continue

    return result


class LLMAnalysisThread(QThread):
    """LLM API 호출을 위한 백그라운드 스레드"""
    analysis_finished = pyqtSignal(dict)  # 성공 시 결과
    analysis_error = pyqtSignal(str)  # 실패 시 에러 메시지

    def __init__(self, image: Image.Image, box_type: str, theme_name: str):
        super().__init__()
        self.image = image
        self.box_type = box_type
        self.theme_name = theme_name

    def run(self):
        try:
            result = analyze_image_with_llm(self.image, self.box_type, self.theme_name)
            self.analysis_finished.emit(result)
        except Exception as e:
            self.analysis_error.emit(str(e))


# 호환성을 위한 별칭
GeminiAnalysisThread = LLMAnalysisThread


class GraphBboxEditor(QLabel):
    """그래프 bbox를 드래그로 조정할 수 있는 이미지 위젯

    - 기존 bbox: 클릭하여 선택, 드래그로 이동/리사이즈
    - 그래프 없을 때: 드래그로 새 박스 생성 가능
    """

    bbox_changed = pyqtSignal(int, dict)  # (graph_index, new_bbox)
    graph_added = pyqtSignal(dict)  # 새 그래프 추가됨

    def __init__(self, pil_image: Image.Image, graphs: list, parent=None):
        super().__init__(parent)
        self.pil_image = pil_image
        self.graphs = graphs  # reference to graphs list
        self.scale_factor = 1.0

        # 드래그 상태
        self.dragging = False
        self.drag_type = None  # 'move', 'resize_tl', 'resize_tr', 'resize_bl', 'resize_br', 'create'
        self.active_graph_idx = -1
        self.drag_start = QPoint()
        self.original_bbox = {}

        # 새 박스 생성 상태
        self.creating_new = False
        self.new_box_start = QPoint()
        self.new_box_end = QPoint()

        # 이미지 설정
        self._update_display()

        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)

    def _update_display(self):
        """이미지와 bbox를 다시 그리기"""
        qimage = self._pil_to_qimage(self.pil_image)
        pixmap = QPixmap.fromImage(qimage)

        # 이미지 크기 조정
        max_width = 750
        if pixmap.width() > max_width:
            self.scale_factor = max_width / pixmap.width()
            pixmap = pixmap.scaledToWidth(max_width, Qt.SmoothTransformation)
        else:
            self.scale_factor = 1.0

        # bbox 그리기
        painter = QPainter(pixmap)

        for i, g in enumerate(self.graphs):
            bbox = g.get("bbox", {})
            if not bbox:
                continue

            x1, y1, x2, y2 = self._bbox_to_pixels(bbox, pixmap.width(), pixmap.height())

            # 활성 그래프는 다른 색상
            if i == self.active_graph_idx:
                pen = QPen(QColor(0, 150, 255))  # 파란색
                pen.setWidth(3)
            else:
                pen = QPen(QColor(255, 0, 0))  # 빨간색
                pen.setWidth(2)

            painter.setPen(pen)
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            # 리사이즈 핸들 그리기 (활성 그래프만)
            if i == self.active_graph_idx:
                handle_size = 8
                painter.setBrush(QColor(0, 150, 255))
                # 네 모서리
                painter.drawRect(x1 - handle_size//2, y1 - handle_size//2, handle_size, handle_size)
                painter.drawRect(x2 - handle_size//2, y1 - handle_size//2, handle_size, handle_size)
                painter.drawRect(x1 - handle_size//2, y2 - handle_size//2, handle_size, handle_size)
                painter.drawRect(x2 - handle_size//2, y2 - handle_size//2, handle_size, handle_size)

            # 라벨 표시
            desc = g.get("description", f"그래프 {i+1}")[:15]
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(x1 + 3, y1 + 15, desc)

        # 새 박스 생성 중이면 임시 박스 그리기
        if self.creating_new:
            pen = QPen(QColor(0, 200, 0))  # 녹색
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            x1 = min(self.new_box_start.x(), self.new_box_end.x())
            y1 = min(self.new_box_start.y(), self.new_box_end.y())
            x2 = max(self.new_box_start.x(), self.new_box_end.x())
            y2 = max(self.new_box_start.y(), self.new_box_end.y())
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

        painter.end()
        self.setPixmap(pixmap)

    def _bbox_to_pixels(self, bbox: dict, img_w: int, img_h: int) -> Tuple[int, int, int, int]:
        """상대 좌표 bbox를 픽셀 좌표로 변환"""
        x1 = bbox.get("x1", 0)
        y1 = bbox.get("y1", 0)
        x2 = bbox.get("x2", 0)
        y2 = bbox.get("y2", 0)

        if all(0 <= v <= 1 for v in [x1, y1, x2, y2]):
            return (int(x1 * img_w), int(y1 * img_h),
                    int(x2 * img_w), int(y2 * img_h))
        return (int(x1), int(y1), int(x2), int(y2))

    def _pixels_to_bbox(self, px1: int, py1: int, px2: int, py2: int,
                        img_w: int, img_h: int) -> dict:
        """픽셀 좌표를 상대 좌표 bbox로 변환"""
        return {
            "x1": max(0, min(1, px1 / img_w)),
            "y1": max(0, min(1, py1 / img_h)),
            "x2": max(0, min(1, px2 / img_w)),
            "y2": max(0, min(1, py2 / img_h))
        }

    def _pil_to_qimage(self, pil_image: Image.Image) -> QImage:
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        data = pil_image.tobytes("raw", "RGB")
        return QImage(data, pil_image.width, pil_image.height,
                      pil_image.width * 3, QImage.Format_RGB888)

    def _find_graph_at(self, pos: QPoint) -> Tuple[int, str]:
        """마우스 위치에서 그래프와 드래그 타입 찾기

        Returns: (graph_index, drag_type) or (-1, None)
        """
        if not self.pixmap():
            return -1, None

        img_w = self.pixmap().width()
        img_h = self.pixmap().height()
        handle_margin = 15  # 리사이즈 핸들 감지 범위

        for i, g in enumerate(self.graphs):
            bbox = g.get("bbox", {})
            if not bbox:
                continue

            x1, y1, x2, y2 = self._bbox_to_pixels(bbox, img_w, img_h)

            # 모서리 핸들 체크 (리사이즈)
            corners = [
                ((x1, y1), 'resize_tl'),
                ((x2, y1), 'resize_tr'),
                ((x1, y2), 'resize_bl'),
                ((x2, y2), 'resize_br'),
            ]
            for (cx, cy), drag_type in corners:
                if abs(pos.x() - cx) < handle_margin and abs(pos.y() - cy) < handle_margin:
                    return i, drag_type

            # 박스 내부 체크 (이동)
            if x1 < pos.x() < x2 and y1 < pos.y() < y2:
                return i, 'move'

        return -1, None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx, drag_type = self._find_graph_at(event.pos())
            if idx >= 0:
                # 기존 bbox 편집
                self.dragging = True
                self.drag_type = drag_type
                self.active_graph_idx = idx
                self.drag_start = event.pos()
                self.original_bbox = self.graphs[idx].get("bbox", {}).copy()
                self._update_display()
            elif len(self.graphs) == 0:
                # 그래프가 없을 때 새 박스 생성 시작
                self.creating_new = True
                self.new_box_start = event.pos()
                self.new_box_end = event.pos()
                self.setCursor(Qt.CrossCursor)

    def mouseMoveEvent(self, event):
        if self.creating_new:
            # 새 박스 생성 중
            self.new_box_end = event.pos()
            self._update_display()
        elif self.dragging and self.active_graph_idx >= 0:
            self._handle_drag(event.pos())
        else:
            # 커서 변경
            idx, drag_type = self._find_graph_at(event.pos())
            if drag_type in ('resize_tl', 'resize_br'):
                self.setCursor(Qt.SizeFDiagCursor)
            elif drag_type in ('resize_tr', 'resize_bl'):
                self.setCursor(Qt.SizeBDiagCursor)
            elif drag_type == 'move':
                self.setCursor(Qt.SizeAllCursor)
            elif len(self.graphs) == 0:
                # 그래프가 없으면 새로 그릴 수 있음을 표시
                self.setCursor(Qt.CrossCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.creating_new:
                # 새 박스 생성 완료
                self.creating_new = False
                self.setCursor(Qt.ArrowCursor)

                if not self.pixmap():
                    return

                img_w = self.pixmap().width()
                img_h = self.pixmap().height()

                # 최소 크기 체크 (20x20 픽셀)
                x1 = min(self.new_box_start.x(), self.new_box_end.x())
                y1 = min(self.new_box_start.y(), self.new_box_end.y())
                x2 = max(self.new_box_start.x(), self.new_box_end.x())
                y2 = max(self.new_box_start.y(), self.new_box_end.y())

                if (x2 - x1) >= 20 and (y2 - y1) >= 20:
                    # 새 그래프 추가
                    new_bbox = self._pixels_to_bbox(x1, y1, x2, y2, img_w, img_h)
                    new_graph = {
                        "bbox": new_bbox,
                        "confidence": 1.0,
                        "description": "수동 추가"
                    }
                    self.graphs.append(new_graph)
                    self.active_graph_idx = len(self.graphs) - 1
                    self.graph_added.emit(new_graph)

                self._update_display()

            elif self.dragging:
                self.dragging = False

                if self.active_graph_idx >= 0:
                    new_bbox = self.graphs[self.active_graph_idx].get("bbox", {})
                    self.bbox_changed.emit(self.active_graph_idx, new_bbox)

    def _handle_drag(self, pos: QPoint):
        """드래그 처리"""
        if not self.pixmap() or self.active_graph_idx < 0:
            return

        img_w = self.pixmap().width()
        img_h = self.pixmap().height()

        ox1, oy1, ox2, oy2 = self._bbox_to_pixels(
            self.original_bbox, img_w, img_h)

        dx = pos.x() - self.drag_start.x()
        dy = pos.y() - self.drag_start.y()

        if self.drag_type == 'move':
            # 전체 이동
            new_x1 = ox1 + dx
            new_y1 = oy1 + dy
            new_x2 = ox2 + dx
            new_y2 = oy2 + dy
        elif self.drag_type == 'resize_tl':
            new_x1 = ox1 + dx
            new_y1 = oy1 + dy
            new_x2, new_y2 = ox2, oy2
        elif self.drag_type == 'resize_tr':
            new_x1, new_y1 = ox1, oy1 + dy
            new_x2 = ox2 + dx
            new_y2 = oy2
        elif self.drag_type == 'resize_bl':
            new_x1 = ox1 + dx
            new_y1 = oy1
            new_x2, new_y2 = ox2, oy2 + dy
        elif self.drag_type == 'resize_br':
            new_x1, new_y1 = ox1, oy1
            new_x2 = ox2 + dx
            new_y2 = oy2 + dy
        else:
            return

        # 좌표 정규화 (x1 < x2, y1 < y2 보장)
        if new_x1 > new_x2:
            new_x1, new_x2 = new_x2, new_x1
        if new_y1 > new_y2:
            new_y1, new_y2 = new_y2, new_y1

        # bbox 업데이트
        new_bbox = self._pixels_to_bbox(new_x1, new_y1, new_x2, new_y2, img_w, img_h)
        self.graphs[self.active_graph_idx]["bbox"] = new_bbox

        self._update_display()


class AnalysisResultDialog(QDialog):
    """AI 분석 결과 표시 다이얼로그 (모달리스)"""

    # 결과 저장 시그널 (수정된 result를 전달)
    result_saved = pyqtSignal(dict)

    def __init__(self, result: dict, box_image: Image.Image, parent=None):
        super().__init__(parent)
        self.box_image = box_image
        # 그래프 영역을 크롭하여 base64로 저장
        self.result = extract_graph_images(box_image, result)
        self.setWindowTitle("AI 분석 결과")
        self.setMinimumSize(900, 700)
        # 모달리스로 설정
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 탭 위젯
        tabs = QTabWidget()

        content = self.result.get("content", {})
        # 문제 타입이면 question_text, 해설 타입이면 solution_text 사용
        question_text = content.get("question_text", "") or content.get("solution_text", "")
        choices = content.get("choices", [])
        sub_questions = content.get("sub_questions", [])
        # 해설 타입 전용 필드
        answer = content.get("answer", "")
        key_concepts = content.get("key_concepts", [])

        # 탭 1: KaTeX 렌더링 결과
        render_tab = QWidget()
        render_layout = QVBoxLayout(render_tab)

        # 문제 번호 & 테마 정보
        info_text = ""
        q_num = self.result.get("question_number")
        if q_num:
            info_text += f"문제 번호: {q_num}  |  "
        theme = self.result.get("theme_name", "미지정")
        info_text += f"테마: {theme}"
        info_label = QLabel(info_text)
        info_label.setStyleSheet("font-weight: bold; font-size: 13px; padding: 5px; background: #f0f0f0;")
        render_layout.addWidget(info_label)

        # KaTeX로 렌더링된 웹뷰
        self.web_view = QWebEngineView()
        html = generate_katex_html(question_text, choices, sub_questions)
        self.web_view.setHtml(html)
        self.web_view.setMinimumHeight(300)
        render_layout.addWidget(self.web_view)

        tabs.addTab(render_tab, "수식 렌더링")

        # 탭 2: 원본 이미지 (그래프 bbox 편집 가능)
        image_tab = QWidget()
        image_layout = QVBoxLayout(image_tab)

        # 그래프 bbox 정보 및 안내
        graphs = content.get("graphs", [])

        if graphs:
            self.bbox_info = QLabel(f"그래프 영역 {len(graphs)}개 - 드래그로 이동/크기 조정")
            self.bbox_info.setStyleSheet("color: #0066cc; font-weight: bold; padding: 8px; background: #e8f4ff; border-radius: 4px;")
        else:
            self.bbox_info = QLabel("그래프 영역 없음 - 이미지를 드래그하여 영역을 추가하세요")
            self.bbox_info.setStyleSheet("color: #ffffff; font-weight: bold; padding: 8px; background: #ff6600; border-radius: 4px;")
        self.bbox_info.setMinimumHeight(30)
        image_layout.addWidget(self.bbox_info)

        # 편집 가능한 bbox 에디터 사용
        self.bbox_editor = GraphBboxEditor(self.box_image, graphs, self)
        self.bbox_editor.bbox_changed.connect(self._on_bbox_changed)
        self.bbox_editor.graph_added.connect(self._on_graph_added)
        self.bbox_editor.setAlignment(Qt.AlignCenter)

        image_scroll = QScrollArea()
        image_scroll.setWidget(self.bbox_editor)
        image_scroll.setWidgetResizable(True)
        image_layout.addWidget(image_scroll)

        tabs.addTab(image_tab, "그래프 편집")

        # 탭 3: 텍스트 원문
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)

        # 문항 본문 (문제) 또는 해설 본문 (해설)
        is_solution = bool(content.get("solution_text"))
        if question_text:
            group_title = "해설 본문 (LaTeX 원문)" if is_solution else "문항 본문 (LaTeX 원문)"
            text_group = QGroupBox(group_title)
            group_layout = QVBoxLayout(text_group)
            text_edit = QTextEdit()
            text_edit.setPlainText(question_text)
            text_edit.setReadOnly(True)
            text_edit.setFont(QFont("Courier", 12))
            group_layout.addWidget(text_edit)
            text_layout.addWidget(text_group)

        # 해설 타입: 정답 표시
        if answer:
            answer_group = QGroupBox("정답")
            answer_layout = QVBoxLayout(answer_group)
            answer_label = QLabel(str(answer))
            answer_label.setFont(QFont("Courier", 14, QFont.Bold))
            answer_label.setStyleSheet("color: #0066cc; padding: 10px;")
            answer_layout.addWidget(answer_label)
            text_layout.addWidget(answer_group)

        # 해설 타입: 핵심 개념 표시
        if key_concepts:
            concepts_group = QGroupBox("핵심 개념")
            concepts_layout = QVBoxLayout(concepts_group)
            for concept in key_concepts:
                concept_label = QLabel(f"• {concept}")
                concept_label.setWordWrap(True)
                concepts_layout.addWidget(concept_label)
            text_layout.addWidget(concepts_group)

        # 선택지 (문제 타입)
        if choices:
            choices_group = QGroupBox("선택지")
            choices_layout = QVBoxLayout(choices_group)
            for choice in choices:
                label = choice.get("label", "")
                text = choice.get("text", "")
                choice_label = QLabel(f"{label} {text}")
                choice_label.setWordWrap(True)
                choice_label.setFont(QFont("Courier", 11))
                choices_layout.addWidget(choice_label)
            text_layout.addWidget(choices_group)

        # 보기 (sub_questions)
        sub_qs = content.get("sub_questions", [])
        if sub_qs:
            sub_group = QGroupBox("보기")
            sub_layout = QVBoxLayout(sub_group)
            for sq in sub_qs:
                label = sq.get("label", "")
                text = sq.get("text", "")
                sq_label = QLabel(f"{label} {text}")
                sq_label.setWordWrap(True)
                sub_layout.addWidget(sq_label)
            text_layout.addWidget(sub_group)

        # 그래프
        graphs = content.get("graphs", [])
        if graphs:
            graph_group = QGroupBox(f"그래프/그림 ({len(graphs)}개)")
            graph_layout = QVBoxLayout(graph_group)
            for i, g in enumerate(graphs):
                desc = g.get("description", f"그래프 {i+1}")
                bbox = g.get("bbox", {})
                bbox_str = f"({bbox.get('x1', 0):.2f}, {bbox.get('y1', 0):.2f}) ~ ({bbox.get('x2', 1):.2f}, {bbox.get('y2', 1):.2f})"
                g_label = QLabel(f"{desc}: {bbox_str}")
                graph_layout.addWidget(g_label)
            text_layout.addWidget(graph_group)

        text_layout.addStretch()
        tabs.addTab(text_tab, "텍스트 원문")

        # 탭 4: 도형 해석 (수학적 해석 데이터)
        figures = content.get("figures", []) or content.get("graphs", [])
        if figures:
            figure_tab = QWidget()
            figure_layout = QVBoxLayout(figure_tab)

            # 안내 메시지
            render_info = QLabel("AI가 도형/그래프를 수학적으로 해석한 결과입니다.")
            render_info.setStyleSheet("color: #0066cc; font-weight: bold; padding: 8px; background: #e8f4ff; border-radius: 4px;")
            figure_layout.addWidget(render_info)

            scroll_content = QWidget()
            scroll_layout = QVBoxLayout(scroll_content)

            for i, fig in enumerate(figures):
                fig_type = fig.get("figure_type", "") or fig.get("graph_type", "unknown")
                verbal = fig.get("verbal_description", "") or fig.get("description", "")

                group = QGroupBox(f"도형 {i+1}: {fig_type}")
                group_layout = QVBoxLayout(group)

                # 자연어 설명
                if verbal:
                    desc_label = QLabel(f"<b>설명:</b> {verbal}")
                    desc_label.setWordWrap(True)
                    desc_label.setStyleSheet("padding: 5px; background: #e8f4fc; border-radius: 4px;")
                    group_layout.addWidget(desc_label)

                # 수학적 요소
                math_elem = fig.get("mathematical_elements", {})

                # 방정식
                equations = math_elem.get("equations", [])
                if equations:
                    eq_text = "<b>방정식:</b><br>" + "<br>".join(f"  • {eq}" for eq in equations)
                    eq_label = QLabel(eq_text)
                    eq_label.setWordWrap(True)
                    group_layout.addWidget(eq_label)

                # 제약 조건
                constraints = math_elem.get("constraints", [])
                if constraints:
                    const_text = "<b>조건:</b><br>" + "<br>".join(f"  • {c}" for c in constraints)
                    const_label = QLabel(const_text)
                    const_label.setWordWrap(True)
                    group_layout.addWidget(const_label)

                # 주요 점
                key_points = math_elem.get("key_points", [])
                if key_points:
                    pts_lines = []
                    for pt in key_points:
                        name = pt.get("name", "")
                        coords = pt.get("coords", [])
                        sig = pt.get("significance", "")
                        line = f"  • {name}: {coords}"
                        if sig:
                            line += f" ({sig})"
                        pts_lines.append(line)
                    pts_text = "<b>주요 점:</b><br>" + "<br>".join(pts_lines)
                    pts_label = QLabel(pts_text)
                    pts_label.setWordWrap(True)
                    group_layout.addWidget(pts_label)

                # 주요 값
                key_values = math_elem.get("key_values", [])
                if key_values:
                    vals_lines = []
                    for val in key_values:
                        name = val.get("name", "")
                        value = val.get("value", "")
                        of = val.get("of", "")
                        line = f"  • {name} = {value}"
                        if of:
                            line += f" ({of})"
                        vals_lines.append(line)
                    vals_text = "<b>주요 값:</b><br>" + "<br>".join(vals_lines)
                    vals_label = QLabel(vals_text)
                    vals_label.setWordWrap(True)
                    group_layout.addWidget(vals_label)

                # 성질
                props = fig.get("properties", {})
                if props and isinstance(props, dict):
                    props_lines = []
                    for k, v in props.items():
                        if v:
                            props_lines.append(f"  • {k}: {v}")
                    if props_lines:
                        props_text = "<b>성질:</b><br>" + "<br>".join(props_lines)
                        props_label = QLabel(props_text)
                        props_label.setWordWrap(True)
                        group_layout.addWidget(props_label)

                # 관계
                relationships = fig.get("relationships", [])
                if relationships:
                    rel_text = "<b>관계:</b><br>" + "<br>".join(f"  • {r}" for r in relationships)
                    rel_label = QLabel(rel_text)
                    rel_label.setWordWrap(True)
                    group_layout.addWidget(rel_label)

                # 라벨
                labels = fig.get("labels_in_figure", [])
                if labels:
                    labels_label = QLabel(f"<b>라벨:</b> {', '.join(str(l) for l in labels)}")
                    group_layout.addWidget(labels_label)

                scroll_layout.addWidget(group)

            scroll_layout.addStretch()

            scroll_area = QScrollArea()
            scroll_area.setWidget(scroll_content)
            scroll_area.setWidgetResizable(True)
            figure_layout.addWidget(scroll_area)

            tabs.addTab(figure_tab, "도형 해석")

        # 탭 5: JSON 원본
        json_tab = QWidget()
        json_layout = QVBoxLayout(json_tab)
        json_edit = QTextEdit()
        json_edit.setPlainText(json.dumps(self.result, ensure_ascii=False, indent=2))
        json_edit.setReadOnly(True)
        json_edit.setFont(QFont("Courier", 11))
        json_layout.addWidget(json_edit)
        tabs.addTab(json_tab, "JSON 원본")

        layout.addWidget(tabs)

        # 버튼
        btn_layout = QHBoxLayout()
        copy_btn = QPushButton("JSON 복사")
        copy_btn.clicked.connect(self._copy_json)
        btn_layout.addWidget(copy_btn)

        btn_layout.addStretch()

        save_btn = QPushButton("저장 후 닫기")
        save_btn.clicked.connect(self._save_and_close)
        save_btn.setStyleSheet("QPushButton { background-color: #4a90d9; color: white; font-weight: bold; padding: 8px 16px; }")
        btn_layout.addWidget(save_btn)

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def _save_and_close(self):
        """결과 저장 후 닫기"""
        self.result_saved.emit(self.result)
        self.close()

    def _pil_to_qimage(self, pil_image: Image.Image) -> QImage:
        """PIL 이미지를 QImage로 변환"""
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        data = pil_image.tobytes("raw", "RGB")
        return QImage(data, pil_image.width, pil_image.height, pil_image.width * 3, QImage.Format_RGB888)

    def _on_bbox_changed(self, graph_idx: int, new_bbox: dict):
        """그래프 bbox가 변경되었을 때 base64 이미지 재생성"""
        graphs = self.result.get("content", {}).get("graphs", [])
        if 0 <= graph_idx < len(graphs):
            # bbox 업데이트
            graphs[graph_idx]["bbox"] = new_bbox

            # base64 이미지 재생성
            self._update_graph_image(graphs[graph_idx], new_bbox)

    def _on_graph_added(self, new_graph: dict):
        """새 그래프가 추가되었을 때"""
        # result에 그래프 추가
        content = self.result.get("content", {})
        if "graphs" not in content:
            content["graphs"] = []
        content["graphs"].append(new_graph)
        self.result["content"] = content

        # base64 이미지 생성
        self._update_graph_image(new_graph, new_graph.get("bbox", {}))

        # 안내 메시지 업데이트
        graphs = content.get("graphs", [])
        self.bbox_info.setText(f"그래프 영역 {len(graphs)}개 - 드래그로 이동/크기 조정")
        self.bbox_info.setStyleSheet("color: #0066cc; font-weight: bold; padding: 8px; background: #e8f4ff; border-radius: 4px;")

    def _update_graph_image(self, graph: dict, bbox: dict):
        """그래프의 base64 이미지 업데이트"""
        img_w, img_h = self.box_image.size
        x1 = int(bbox.get("x1", 0) * img_w)
        y1 = int(bbox.get("y1", 0) * img_h)
        x2 = int(bbox.get("x2", 1) * img_w)
        y2 = int(bbox.get("y2", 1) * img_h)

        # 좌표 유효성 검사
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img_w, x2), min(img_h, y2)

        if x2 > x1 and y2 > y1:
            cropped = self.box_image.crop((x1, y1, x2, y2))
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
            graph["image_base64"] = base64.b64encode(buffer.getvalue()).decode("utf-8")

    def _copy_json(self):
        """JSON을 클립보드에 복사"""
        clipboard = QApplication.clipboard()
        clipboard.setText(json.dumps(self.result, ensure_ascii=False, indent=2))
        QMessageBox.information(self, "복사 완료", "JSON이 클립보드에 복사되었습니다.")
