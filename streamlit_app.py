"""Streamlit 웹 앱 - PDF 수학 문제 추출 및 라벨링"""

import json
import os
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import zipfile

import streamlit as st
from PIL import Image
from pdf2image import convert_from_bytes

# 페이지 설정
st.set_page_config(
    page_title="PDF 문항 추출기",
    page_icon="📄",
    layout="wide"
)


@dataclass
class QuestionBox:
    """문항 박스 정보"""
    id: int
    x: int
    y: int
    width: int
    height: int
    question_number: Optional[int] = None
    theme: Optional[str] = None


def init_session_state():
    """세션 상태 초기화"""
    if 'pdf_bytes' not in st.session_state:
        st.session_state.pdf_bytes = None
    if 'pages' not in st.session_state:
        st.session_state.pages = []
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 0
    if 'boxes' not in st.session_state:
        st.session_state.boxes = {}  # {page_idx: [QuestionBox, ...]}
    if 'drawing' not in st.session_state:
        st.session_state.drawing = False
    if 'start_point' not in st.session_state:
        st.session_state.start_point = None
    if 'next_box_id' not in st.session_state:
        st.session_state.next_box_id = 1


def load_pdf(uploaded_file):
    """PDF 파일 로드"""
    st.session_state.pdf_bytes = uploaded_file.read()
    st.session_state.pages = convert_from_bytes(
        st.session_state.pdf_bytes,
        dpi=150  # 미리보기용 낮은 해상도
    )
    st.session_state.current_page = 0
    st.session_state.boxes = {}
    st.session_state.next_box_id = 1


def get_page_boxes(page_idx: int) -> List[QuestionBox]:
    """현재 페이지의 박스 목록 반환"""
    return st.session_state.boxes.get(page_idx, [])


def add_box(page_idx: int, x: int, y: int, width: int, height: int):
    """박스 추가"""
    if page_idx not in st.session_state.boxes:
        st.session_state.boxes[page_idx] = []

    box = QuestionBox(
        id=st.session_state.next_box_id,
        x=x, y=y, width=width, height=height
    )
    st.session_state.boxes[page_idx].append(box)
    st.session_state.next_box_id += 1
    return box.id


def update_box_label(page_idx: int, box_id: int, question_number: Optional[int], theme: Optional[str]):
    """박스 라벨 업데이트"""
    if page_idx in st.session_state.boxes:
        for box in st.session_state.boxes[page_idx]:
            if box.id == box_id:
                box.question_number = question_number
                box.theme = theme
                break


def delete_box(page_idx: int, box_id: int):
    """박스 삭제"""
    if page_idx in st.session_state.boxes:
        st.session_state.boxes[page_idx] = [
            box for box in st.session_state.boxes[page_idx] if box.id != box_id
        ]


def draw_boxes_on_image(image: Image.Image, boxes: List[QuestionBox]) -> Image.Image:
    """이미지에 박스 그리기"""
    from PIL import ImageDraw, ImageFont

    img_copy = image.copy()
    draw = ImageDraw.Draw(img_copy)

    for box in boxes:
        # 박스 그리기 (빨간색 테두리)
        draw.rectangle(
            [box.x, box.y, box.x + box.width, box.y + box.height],
            outline='red',
            width=3
        )

        # 라벨 표시
        label_parts = []
        if box.question_number is not None:
            label_parts.append(f"#{box.question_number}")
        if box.theme:
            label_parts.append(box.theme)

        if label_parts:
            label = " ".join(label_parts)
        else:
            label = f"ID:{box.id}"

        # 라벨 배경
        text_bbox = draw.textbbox((box.x, box.y - 25), label)
        draw.rectangle(text_bbox, fill='red')
        draw.text((box.x, box.y - 25), label, fill='white')

    return img_copy


def export_to_zip() -> bytes:
    """결과를 ZIP 파일로 내보내기"""
    # 고해상도로 다시 변환
    hires_pages = convert_from_bytes(st.session_state.pdf_bytes, dpi=300)
    scale_factor = 300 / 150  # 150 DPI에서 300 DPI로 스케일

    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        metadata = {
            "exported_at": datetime.now().isoformat(),
            "questions": []
        }

        for page_idx, boxes in st.session_state.boxes.items():
            if page_idx >= len(hires_pages):
                continue

            page_image = hires_pages[page_idx]

            for box in boxes:
                # 좌표 스케일링
                x = int(box.x * scale_factor)
                y = int(box.y * scale_factor)
                w = int(box.width * scale_factor)
                h = int(box.height * scale_factor)

                # 이미지 자르기
                cropped = page_image.crop((x, y, x + w, y + h))

                # 파일명 생성
                if box.question_number is not None:
                    filename = f"q{box.question_number:03d}.png"
                else:
                    filename = f"box_{box.id:03d}.png"

                # ZIP에 이미지 추가
                img_buffer = BytesIO()
                cropped.save(img_buffer, format='PNG')
                zf.writestr(f"images/{filename}", img_buffer.getvalue())

                # 메타데이터 추가
                metadata["questions"].append({
                    "id": box.id,
                    "question_number": box.question_number,
                    "theme": box.theme,
                    "image_path": f"images/{filename}",
                    "source_page": page_idx + 1,
                    "bbox": {"x": x, "y": y, "width": w, "height": h}
                })

        # 메타데이터 JSON 추가
        zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    return zip_buffer.getvalue()


def save_labels_json() -> str:
    """라벨 데이터를 JSON으로 저장"""
    data = {
        "saved_at": datetime.now().isoformat(),
        "pages": {}
    }

    for page_idx, boxes in st.session_state.boxes.items():
        data["pages"][str(page_idx)] = [asdict(box) for box in boxes]

    return json.dumps(data, ensure_ascii=False, indent=2)


def load_labels_json(json_str: str):
    """JSON에서 라벨 데이터 로드"""
    data = json.loads(json_str)

    st.session_state.boxes = {}
    max_id = 0

    for page_idx_str, boxes_data in data.get("pages", {}).items():
        page_idx = int(page_idx_str)
        st.session_state.boxes[page_idx] = []

        for box_data in boxes_data:
            box = QuestionBox(**box_data)
            st.session_state.boxes[page_idx].append(box)
            max_id = max(max_id, box.id)

    st.session_state.next_box_id = max_id + 1


def inject_scroll_navigation_js():
    """페이지 하단 스크롤 시 다음 페이지로 이동하는 JavaScript 삽입"""
    js_code = """
    <script>
    (function() {
        // 이미 초기화된 경우 스킵
        if (window.scrollNavInitialized) return;
        window.scrollNavInitialized = true;

        let lastScrollTop = 0;
        let bottomReachedCount = 0;
        let topReachedCount = 0;
        const scrollThreshold = 2;  // 2번 연속 스크롤해야 페이지 이동

        function isAtBottom() {
            const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
            const windowHeight = window.innerHeight;
            const documentHeight = document.documentElement.scrollHeight;
            return (scrollTop + windowHeight) >= (documentHeight - 10);
        }

        function isAtTop() {
            const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
            return scrollTop <= 10;
        }

        function clickButton(selector) {
            const buttons = document.querySelectorAll('button');
            for (let btn of buttons) {
                if (btn.textContent.includes(selector) && !btn.disabled) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }

        let scrollTimeout = null;

        window.addEventListener('wheel', function(e) {
            clearTimeout(scrollTimeout);

            scrollTimeout = setTimeout(function() {
                const scrollingDown = e.deltaY > 0;
                const scrollingUp = e.deltaY < 0;

                if (scrollingDown && isAtBottom()) {
                    bottomReachedCount++;
                    topReachedCount = 0;

                    if (bottomReachedCount >= scrollThreshold) {
                        if (clickButton('다음')) {
                            bottomReachedCount = 0;
                            window.scrollTo(0, 0);
                        }
                    }
                } else if (scrollingUp && isAtTop()) {
                    topReachedCount++;
                    bottomReachedCount = 0;

                    if (topReachedCount >= scrollThreshold) {
                        if (clickButton('이전')) {
                            topReachedCount = 0;
                            window.scrollTo(0, document.documentElement.scrollHeight);
                        }
                    }
                } else {
                    // 스크롤 중간이면 카운트 리셋
                    if (!isAtBottom()) bottomReachedCount = 0;
                    if (!isAtTop()) topReachedCount = 0;
                }
            }, 50);
        }, { passive: true });
    })();
    </script>
    """
    st.components.v1.html(js_code, height=0)


def main():
    init_session_state()

    st.title("📄 PDF 문항 추출기")
    st.markdown("PDF 파일에서 수학 문제를 박스로 선택하고 라벨링합니다.")

    # 스크롤 네비게이션 JavaScript 삽입
    inject_scroll_navigation_js()

    # 사이드바: 파일 업로드 및 설정
    with st.sidebar:
        st.header("📁 파일")

        uploaded_file = st.file_uploader(
            "PDF 파일 업로드",
            type=['pdf'],
            key='pdf_uploader'
        )

        if uploaded_file is not None:
            if st.button("PDF 로드", type="primary"):
                with st.spinner("PDF 변환 중..."):
                    load_pdf(uploaded_file)
                st.success(f"{len(st.session_state.pages)} 페이지 로드됨")

        st.divider()

        # 라벨 저장/불러오기
        st.header("💾 라벨 데이터")

        if st.session_state.boxes:
            json_data = save_labels_json()
            st.download_button(
                "라벨 저장 (JSON)",
                json_data,
                "labels.json",
                "application/json"
            )

        uploaded_labels = st.file_uploader(
            "라벨 불러오기",
            type=['json'],
            key='label_uploader'
        )

        if uploaded_labels is not None:
            if st.button("라벨 적용"):
                load_labels_json(uploaded_labels.read().decode('utf-8'))
                st.success("라벨 로드됨")
                st.rerun()

        st.divider()

        # 내보내기
        st.header("📤 내보내기")

        if st.session_state.boxes:
            if st.button("ZIP으로 내보내기", type="primary"):
                with st.spinner("이미지 추출 중..."):
                    zip_data = export_to_zip()
                st.download_button(
                    "다운로드",
                    zip_data,
                    "questions.zip",
                    "application/zip"
                )

    # 메인 영역
    if not st.session_state.pages:
        st.info("👈 사이드바에서 PDF 파일을 업로드하세요.")
        return

    # 페이지 네비게이션
    col1, col2, col3 = st.columns([1, 3, 1])

    with col1:
        if st.button("◀ 이전", disabled=st.session_state.current_page == 0):
            st.session_state.current_page -= 1
            st.rerun()

    with col2:
        page_num = st.selectbox(
            "페이지",
            range(len(st.session_state.pages)),
            index=st.session_state.current_page,
            format_func=lambda x: f"페이지 {x + 1} / {len(st.session_state.pages)}",
            label_visibility="collapsed"
        )
        if page_num != st.session_state.current_page:
            st.session_state.current_page = page_num
            st.rerun()

    with col3:
        if st.button("다음 ▶", disabled=st.session_state.current_page >= len(st.session_state.pages) - 1):
            st.session_state.current_page += 1
            st.rerun()

    # 이미지 표시 및 박스 관리
    current_page_idx = st.session_state.current_page
    current_image = st.session_state.pages[current_page_idx]
    current_boxes = get_page_boxes(current_page_idx)

    # 2열 레이아웃: 이미지 | 박스 관리
    img_col, ctrl_col = st.columns([3, 1])

    with img_col:
        # 박스가 그려진 이미지 표시
        display_image = draw_boxes_on_image(current_image, current_boxes)
        st.image(display_image, use_container_width=True)

        # 박스 추가 폼
        st.subheader("➕ 새 박스 추가")

        with st.form("add_box_form"):
            bcol1, bcol2, bcol3, bcol4 = st.columns(4)

            with bcol1:
                new_x = st.number_input("X", min_value=0, max_value=current_image.width, value=0)
            with bcol2:
                new_y = st.number_input("Y", min_value=0, max_value=current_image.height, value=0)
            with bcol3:
                new_w = st.number_input("너비", min_value=10, max_value=current_image.width, value=200)
            with bcol4:
                new_h = st.number_input("높이", min_value=10, max_value=current_image.height, value=300)

            if st.form_submit_button("박스 추가", type="primary"):
                add_box(current_page_idx, new_x, new_y, new_w, new_h)
                st.rerun()

    with ctrl_col:
        st.subheader(f"📦 박스 목록 ({len(current_boxes)}개)")

        if not current_boxes:
            st.info("박스가 없습니다.")
        else:
            for box in current_boxes:
                with st.expander(f"ID {box.id}: #{box.question_number or '?'}", expanded=False):
                    # 라벨 수정
                    q_num = st.number_input(
                        "문항 번호",
                        min_value=0,
                        value=box.question_number or 0,
                        key=f"qnum_{box.id}"
                    )
                    theme = st.text_input(
                        "테마",
                        value=box.theme or "",
                        key=f"theme_{box.id}"
                    )

                    col_save, col_del = st.columns(2)

                    with col_save:
                        if st.button("저장", key=f"save_{box.id}"):
                            update_box_label(
                                current_page_idx,
                                box.id,
                                q_num if q_num > 0 else None,
                                theme if theme else None
                            )
                            st.rerun()

                    with col_del:
                        if st.button("삭제", key=f"del_{box.id}", type="secondary"):
                            delete_box(current_page_idx, box.id)
                            st.rerun()

    # 하단 통계
    st.divider()
    total_boxes = sum(len(boxes) for boxes in st.session_state.boxes.values())
    labeled_boxes = sum(
        1 for boxes in st.session_state.boxes.values()
        for box in boxes if box.question_number is not None
    )

    st.metric("전체 박스", f"{total_boxes}개 ({labeled_boxes}개 라벨링됨)")


if __name__ == "__main__":
    main()
