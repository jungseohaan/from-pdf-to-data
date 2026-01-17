# PDF to Data

PDF 파일(특히 수학 시험지)에서 개별 문항을 자동으로 감지하고 추출하는 도구입니다.

## 주요 기능

- **자동 문항 감지**: 수평 여백 분석을 통해 문항 영역 자동 감지
- **2컬럼 레이아웃 지원**: 좌/우 컬럼을 분리하여 순차적으로 처리
- **문항 번호 자동 추출**: OCR을 통해 문항 번호 인식
- **다양한 인터페이스**: CLI, Streamlit 웹앱, PyQt5 데스크톱 앱

## 설치

### 시스템 요구사항

- Python 3.8+
- Tesseract OCR
- Poppler (pdf2image 의존성)

```bash
# macOS
brew install tesseract poppler

# Ubuntu/Debian
sudo apt-get install tesseract-ocr poppler-utils
```

### Python 패키지 설치

```bash
pip install -r requirements.txt
```

## 사용법

### CLI (배치 처리)

```bash
# 단일 PDF 처리
python3 -m src.main input.pdf -o output_dir -v

# 폴더 내 모든 PDF 일괄 처리
python3 -m src.main pdf_folder/ --batch -o output_dir -v

# 설정 파일 사용
python3 -m src.main input.pdf -c config.yaml -o output_dir
```

### Streamlit 웹앱

```bash
streamlit run streamlit_app.py
```

브라우저에서 `http://localhost:8501` 접속

## 프로젝트 구조

```
from-pdf-to-data/
├── streamlit_app.py          # Streamlit 웹 애플리케이션
├── requirements.txt          # 의존성 패키지
├── src/
│   ├── main.py              # CLI 엔트리포인트
│   ├── pdf_processor.py     # PDF → 이미지 변환
│   ├── image_stitcher.py    # 2컬럼 처리 및 이미지 연결
│   ├── question_detector.py # 문항 영역 자동 감지
│   ├── metadata_extractor.py# 문항 번호/테마 추출 (OCR)
│   ├── labeler.py           # PyQt5 데스크톱 라벨링 도구
│   └── output_manager.py    # 결과 저장 및 메타데이터 관리
```

## 처리 흐름

```
PDF 파일
    ↓
[pdf_processor] PDF → 이미지 변환 (300 DPI)
    ↓
[image_stitcher] 2컬럼 분리 → 수직 연결
    ↓
[question_detector] 문항 영역 자동 감지
    ↓
[metadata_extractor] 문항 번호 OCR 추출
    ↓
[output_manager] 이미지 + 메타데이터 저장
```

## 출력 형식

```
output/
├── images/
│   ├── q001.png
│   ├── q002.png
│   └── ...
└── metadata.json
```

### metadata.json 예시

```json
{
  "source_pdf": "exam.pdf",
  "processed_at": "2025-01-15T10:30:00",
  "total_questions": 30,
  "questions": [
    {
      "id": "q001",
      "number": 1,
      "theme": null,
      "image_path": "images/q001.png",
      "source_pages": [1],
      "column": "left",
      "bbox": {"x": 0, "y": 100, "width": 400, "height": 200}
    }
  ]
}
```

## 설정

`config.yaml` 파일로 동작을 커스터마이즈할 수 있습니다:

```yaml
pdf:
  dpi: 300                    # PDF 렌더링 해상도

layout:
  columns: 2                  # 컬럼 수
  column_gap_ratio: 0.05      # 컬럼 사이 여백 비율

detection:
  min_gap_height: 30          # 문항 사이 최소 여백 (픽셀)
  whitespace_threshold: 250   # 여백 판단 기준 (0-255)
  min_question_height: 100    # 최소 문항 높이

output:
  image_format: png
  image_quality: 95
```

## 기술 스택

| 기능 | 라이브러리 |
|------|-----------|
| PDF 처리 | pdf2image |
| 이미지 처리 | Pillow, OpenCV |
| OCR | Tesseract (pytesseract) |
| 웹 UI | Streamlit |
| 데스크톱 UI | PyQt5 |

## 라이선스

MIT License
