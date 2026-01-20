"""다이얼로그 모듈

AI 분석, 결과 리뷰, 해설 연결 등의 다이얼로그를 제공합니다.
"""

import json
from typing import List, Optional, Dict, Callable, TYPE_CHECKING

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QComboBox, QCheckBox, QProgressBar, QTextEdit,
    QRadioButton, QButtonGroup, QDialogButtonBox, QListWidget,
    QListWidgetItem, QSplitter, QFrame, QScrollArea,
    QTabWidget, QFileDialog, QMessageBox, QApplication
)
from PyQt5.QtGui import QFont, QPixmap, QImage
from PyQt5.QtCore import Qt, QTimer

from PIL import Image

if TYPE_CHECKING:
    from .labeler import PDFLabeler

from .models import QuestionBox, BOX_TYPE_QUESTION, BOX_TYPE_SOLUTION
from .gemini_api import (
    crop_box_image, GeminiAnalysisThread, generate_katex_html, get_api_key
)
from .config import (
    load_settings, save_settings, get_model_by_id,
    get_vision_models, AVAILABLE_MODELS
)


class BatchAnalysisDialog(QDialog):
    """AI 배치 분석 다이얼로그"""

    def __init__(self, parent: 'PDFLabeler'):
        super().__init__(parent)
        self.labeler = parent
        self.setWindowTitle("AI 분석")
        self.setMinimumSize(600, 550)

        self._running = False
        self._canceled = False
        self._batch_boxes = []
        self._batch_current_idx = 0
        self._batch_results = {}
        self._batch_errors = []
        self._batch_merge_solutions = True
        self._batch_thread = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 모델 선택
        model_group = QGroupBox("AI 모델 선택")
        model_layout = QVBoxLayout(model_group)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumHeight(30)

        # 비전 지원 모델만 표시
        vision_models = get_vision_models()
        settings = load_settings()
        current_model_id = settings.get("selected_model", "gemini-2.0-flash-exp")
        current_index = 0

        # Gemini 모델
        gemini_models = [m for m in vision_models if m.provider == "gemini"]
        if gemini_models:
            self.model_combo.addItem("── Google Gemini ──", None)
            self.model_combo.model().item(self.model_combo.count() - 1).setEnabled(False)
            for model in gemini_models:
                has_key = bool(get_api_key("gemini"))
                status = "" if has_key else " (API 키 필요)"
                self.model_combo.addItem(f"  {model.name}{status}", model.id)
                if model.id == current_model_id:
                    current_index = self.model_combo.count() - 1

        # OpenAI 모델
        openai_models = [m for m in vision_models if m.provider == "openai"]
        if openai_models:
            self.model_combo.addItem("── OpenAI ──", None)
            self.model_combo.model().item(self.model_combo.count() - 1).setEnabled(False)
            for model in openai_models:
                has_key = bool(get_api_key("openai"))
                status = "" if has_key else " (API 키 필요)"
                self.model_combo.addItem(f"  {model.name}{status}", model.id)
                if model.id == current_model_id:
                    current_index = self.model_combo.count() - 1

        self.model_combo.setCurrentIndex(current_index)
        model_layout.addWidget(self.model_combo)

        # API 키 상태 표시
        self.api_status_label = QLabel()
        self.api_status_label.setStyleSheet("padding: 4px;")
        model_layout.addWidget(self.api_status_label)

        self.model_combo.currentIndexChanged.connect(self._update_api_status)
        self._update_api_status()

        layout.addWidget(model_group)

        # 분석 범위 선택
        scope_group = QGroupBox("분석 범위")
        scope_layout = QVBoxLayout(scope_group)

        self.scope_btn_group = QButtonGroup(self)

        # 1. 선택된 박스만
        self.selected_radio = QRadioButton("선택된 박스만 분석")
        selected_items = self.labeler.box_list.selectedItems()
        self.selected_count = len(selected_items)
        if self.selected_count == 0:
            self.selected_radio.setEnabled(False)
            self.selected_radio.setText("선택된 박스만 분석 (선택된 항목 없음)")
        else:
            self.selected_radio.setText(f"선택된 박스만 분석 ({self.selected_count}개)")
        self.scope_btn_group.addButton(self.selected_radio, 1)
        scope_layout.addWidget(self.selected_radio)

        # 2. 전체 분석
        self.total_boxes = sum(len(boxes) for boxes in self.labeler.boxes.values())
        self.all_radio = QRadioButton(f"전체 분석 ({self.total_boxes}개)")
        if self.total_boxes == 0:
            self.all_radio.setEnabled(False)
        self.scope_btn_group.addButton(self.all_radio, 2)
        scope_layout.addWidget(self.all_radio)

        # 3. 테마별 분석 (멀티 선택)
        self.theme_radio = QRadioButton("테마별 분석 (복수 선택 가능):")
        self.scope_btn_group.addButton(self.theme_radio, 3)
        scope_layout.addWidget(self.theme_radio)

        # 테마 리스트 위젯 (멀티 선택)
        self.theme_list = QListWidget()
        self.theme_list.setSelectionMode(QListWidget.MultiSelection)
        self.theme_list.setMaximumHeight(120)

        for theme in self.labeler.themes:
            # 테마별 박스 수 계산
            theme_boxes = []
            analyzed_count = 0
            for boxes in self.labeler.boxes.values():
                for box in boxes:
                    if box.theme_id == theme.id:
                        theme_boxes.append(box)
                        if box.ai_result:
                            analyzed_count += 1

            total_count = len(theme_boxes)
            # 분석 상태 표시
            if analyzed_count == 0:
                status = ""
            elif analyzed_count == total_count:
                status = " ✓ 분석완료"
            else:
                status = f" ({analyzed_count}/{total_count} 분석됨)"

            item = QListWidgetItem(f"{theme.name} ({total_count}개){status}")
            item.setData(Qt.UserRole, theme.id)
            # 분석 완료된 테마는 색상 변경
            if analyzed_count == total_count and total_count > 0:
                item.setForeground(Qt.gray)
            self.theme_list.addItem(item)

        if self.theme_list.count() == 0:
            self.theme_radio.setEnabled(False)
            self.theme_list.setEnabled(False)
        else:
            # 테마 리스트 클릭 시 자동으로 테마별 분석 라디오 체크
            self.theme_list.itemClicked.connect(lambda: self.theme_radio.setChecked(True))
        scope_layout.addWidget(self.theme_list)

        # 기본 선택
        if self.selected_count > 0:
            self.selected_radio.setChecked(True)
        elif self.total_boxes > 0:
            self.all_radio.setChecked(True)

        layout.addWidget(scope_group)

        # 분석 옵션
        options_group = QGroupBox("분석 옵션")
        options_layout = QVBoxLayout(options_group)

        self.overwrite_checkbox = QCheckBox("기존 분석 결과 덮어쓰기")
        self.overwrite_checkbox.setToolTip("체크 해제 시 이미 분석된 박스는 건너뜁니다")
        options_layout.addWidget(self.overwrite_checkbox)

        self.merge_solutions_checkbox = QCheckBox("해설 분석 결과를 연결된 문제에 통합")
        self.merge_solutions_checkbox.setChecked(True)
        self.merge_solutions_checkbox.setToolTip("해설 박스의 분석 결과를 연결된 문제 박스의 JSON에 추가합니다")
        options_layout.addWidget(self.merge_solutions_checkbox)

        layout.addWidget(options_group)

        # 진행 상태
        progress_group = QGroupBox("진행 상태")
        progress_layout_v = QVBoxLayout(progress_group)

        self.status_label = QLabel("대기 중...")
        self.status_label.setStyleSheet("font-weight: bold;")
        progress_layout_v.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        progress_layout_v.addWidget(self.progress_bar)

        layout.addWidget(progress_group)

        # 로그 영역
        log_group = QGroupBox("분석 로그")
        log_layout = QVBoxLayout(log_group)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Courier", 10))
        self.log_edit.setMinimumHeight(150)
        log_layout.addWidget(self.log_edit)

        layout.addWidget(log_group)

        # 버튼
        btn_layout = QHBoxLayout()

        self.start_btn = QPushButton("분석 시작")
        self.start_btn.setStyleSheet("font-weight: bold; padding: 8px 16px;")
        self.start_btn.clicked.connect(self._on_start)
        btn_layout.addWidget(self.start_btn)

        self.close_btn = QPushButton("닫기")
        self.close_btn.setStyleSheet("padding: 8px 16px;")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

    def _update_api_status(self):
        """선택된 모델의 API 키 상태 업데이트"""
        model_id = self.model_combo.currentData()
        if not model_id:
            self.api_status_label.setText("")
            return

        model_info = get_model_by_id(model_id)
        if not model_info:
            self.api_status_label.setText("")
            return

        has_key = bool(get_api_key(model_info.provider))
        if has_key:
            self.api_status_label.setText(f"✅ {model_info.provider.upper()} API 키 설정됨")
            self.api_status_label.setStyleSheet("color: green; padding: 4px;")
        else:
            self.api_status_label.setText(f"❌ {model_info.provider.upper()} API 키가 필요합니다 (설정 메뉴에서 입력)")
            self.api_status_label.setStyleSheet("color: red; padding: 4px;")

    def _get_boxes_to_analyze(self):
        """선택된 범위에 따라 분석할 박스 목록 반환"""
        boxes_list = []
        scope = self.scope_btn_group.checkedId()
        overwrite = self.overwrite_checkbox.isChecked()

        if scope == 1:  # 선택된 박스만
            for item in self.labeler.box_list.selectedItems():
                row = self.labeler.box_list.row(item)
                if 0 <= row < len(self.labeler._box_index_map):
                    data = self.labeler._box_index_map[row]
                    if data is not None:
                        page_idx, box = data
                        if overwrite or not box.ai_result:
                            boxes_list.append((page_idx, box))

        elif scope == 2:  # 전체
            for page_idx, boxes in self.labeler.boxes.items():
                for box in boxes:
                    if overwrite or not box.ai_result:
                        boxes_list.append((page_idx, box))

        elif scope == 3:  # 테마별 (멀티 선택)
            selected_theme_ids = set()
            for item in self.theme_list.selectedItems():
                theme_id = item.data(Qt.UserRole)
                if theme_id:
                    selected_theme_ids.add(theme_id)

            for page_idx, boxes in self.labeler.boxes.items():
                for box in boxes:
                    if box.theme_id in selected_theme_ids:
                        if overwrite or not box.ai_result:
                            boxes_list.append((page_idx, box))

        return boxes_list

    def _on_start(self):
        """분석 시작"""
        if self._running:
            # 취소 요청
            self._canceled = True
            self.start_btn.setEnabled(False)
            self.start_btn.setText("취소 중...")
            self.log_edit.append("\n[취소 요청됨] 현재 분석 완료 후 중단됩니다...")
            return

        # 선택된 모델 확인
        selected_model_id = self.model_combo.currentData()
        if not selected_model_id:
            self.log_edit.append("❌ 모델을 선택해주세요.")
            return

        selected_model_info = get_model_by_id(selected_model_id)
        if not selected_model_info:
            self.log_edit.append(f"❌ 알 수 없는 모델: {selected_model_id}")
            return

        # API 키 확인
        gemini_key = get_api_key("gemini")

        if selected_model_info.provider == "gemini":
            if not gemini_key:
                self.log_edit.append("❌ Gemini API 키가 설정되지 않았습니다.")
                self.log_edit.append("   설정 메뉴에서 API 키를 입력하거나 .env 파일에 GEMINI_API_KEY를 설정하세요.")
                return
        elif selected_model_info.provider == "openai":
            if not get_api_key("openai"):
                self.log_edit.append("❌ OpenAI API 키가 설정되지 않았습니다.")
                self.log_edit.append("   설정 메뉴에서 API 키를 입력하거나 .env 파일에 OPENAI_API_KEY를 설정하세요.")
                return

        # 선택된 모델을 설정에 저장
        settings = load_settings()
        settings["selected_model"] = selected_model_id
        save_settings(settings)
        self.labeler._update_current_model_display()

        boxes_to_analyze = self._get_boxes_to_analyze()
        if not boxes_to_analyze:
            self.log_edit.append("분석할 박스가 없습니다. (이미 분석 완료되었거나 선택된 항목이 없습니다)")
            return

        # UI 상태 변경
        self._running = True
        self._canceled = False
        self.start_btn.setText("취소")
        self.close_btn.setEnabled(False)
        self.model_combo.setEnabled(False)
        self.selected_radio.setEnabled(False)
        self.all_radio.setEnabled(False)
        self.theme_radio.setEnabled(False)
        self.theme_list.setEnabled(False)
        self.overwrite_checkbox.setEnabled(False)
        self.merge_solutions_checkbox.setEnabled(False)

        # 진행 상태 초기화
        self.progress_bar.setMaximum(len(boxes_to_analyze))
        self.progress_bar.setValue(0)
        self.status_label.setText(f"0 / {len(boxes_to_analyze)} 분석 중...")
        self.log_edit.append(f"=== 분석 시작: {len(boxes_to_analyze)}개 박스 ===")
        self.log_edit.append(f"모델: {selected_model_info.name} ({selected_model_info.provider.upper()})\n")

        # 분석 상태 변수
        self._batch_boxes = boxes_to_analyze
        self._batch_current_idx = 0
        self._batch_results = {}
        self._batch_errors = []
        self._batch_merge_solutions = self.merge_solutions_checkbox.isChecked()

        # 분석 시작
        QTimer.singleShot(100, self._analyze_next)

    def _analyze_next(self):
        """다음 박스 분석"""
        if self._canceled or self._batch_current_idx >= len(self._batch_boxes):
            self._on_complete()
            return

        page_idx, box = self._batch_boxes[self._batch_current_idx]
        self._batch_current_idx += 1

        # 상태 업데이트
        self.status_label.setText(f"{self._batch_current_idx} / {len(self._batch_boxes)} 분석 중...")
        self.progress_bar.setValue(self._batch_current_idx)

        # 테마 이름 가져오기
        theme_name = None
        for theme in self.labeler.themes:
            if theme.id == box.theme_id:
                theme_name = theme.name
                break

        box_type_str = "문제" if box.box_type == BOX_TYPE_QUESTION else "해설"
        self.log_edit.append(f"[{self._batch_current_idx}/{len(self._batch_boxes)}] {box_type_str}: {theme_name or '테마없음'} - 페이지 {page_idx + 1}")
        self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

        # 이미지 크롭
        if page_idx >= len(self.labeler.pages):
            self.log_edit.append(f"  ⚠️ 페이지 이미지 없음")
            self._batch_errors.append((box, "페이지 이미지 없음"))
            QTimer.singleShot(100, self._analyze_next)
            return

        page_image = self.labeler.pages[page_idx]
        cropped = crop_box_image(page_image, box)

        # 분석 스레드 시작
        self._batch_thread = GeminiAnalysisThread(cropped, box.box_type, theme_name)

        def on_finished(result):
            content = result.get("content", {})
            if box.box_type == BOX_TYPE_QUESTION:
                text = content.get("question_text", "")[:50]
            else:
                text = content.get("solution_text", "")[:50]
                answer = content.get("answer", "")
                if answer:
                    text += f" [정답: {answer}]"
            self.log_edit.append(f"  ✅ 완료: {text}...")

            box.ai_result = result
            self._batch_results[box.id] = result
            self.labeler._schedule_auto_save()

            self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())
            QTimer.singleShot(100, self._analyze_next)

        def on_error(error_msg):
            self.log_edit.append(f"  ❌ 오류: {error_msg}")
            self._batch_errors.append((box, error_msg))
            self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())
            QTimer.singleShot(100, self._analyze_next)

        self._batch_thread.analysis_finished.connect(on_finished)
        self._batch_thread.analysis_error.connect(on_error)
        self._batch_thread.start()

    def _on_complete(self):
        """분석 완료"""
        self._running = False

        # UI 복원
        self.start_btn.setText("분석 시작")
        self.start_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        self.model_combo.setEnabled(True)
        if self.selected_count > 0:
            self.selected_radio.setEnabled(True)
        if self.total_boxes > 0:
            self.all_radio.setEnabled(True)
        if self.theme_list.count() > 0:
            self.theme_radio.setEnabled(True)
            self.theme_list.setEnabled(True)
        self.overwrite_checkbox.setEnabled(True)
        self.merge_solutions_checkbox.setEnabled(True)

        # 결과 요약
        success_count = len(self._batch_results)
        error_count = len(self._batch_errors)

        self.log_edit.append(f"\n=== 분석 완료 ===")
        self.log_edit.append(f"성공: {success_count}개")
        if error_count > 0:
            self.log_edit.append(f"실패: {error_count}개")
        if self._canceled:
            self.log_edit.append("(사용자에 의해 중단됨)")

        # 해설 통합
        if self._batch_merge_solutions and success_count > 0:
            merged_count = self.labeler._merge_solutions_to_questions()
            if merged_count > 0:
                self.log_edit.append(f"해설 통합: {merged_count}개 문제에 적용")

        self.status_label.setText(f"완료: 성공 {success_count}개, 실패 {error_count}개")
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

        # 자동 저장
        self.labeler._schedule_auto_save()


class AnalysisReviewDialog(QDialog):
    """분석 결과 리뷰 다이얼로그"""

    def __init__(self, parent: 'PDFLabeler'):
        super().__init__(parent)
        self.labeler = parent
        self.setWindowTitle("분석 결과 리뷰")
        self.setMinimumSize(1100, 700)

        self.analyzed_boxes = []
        self.current_box_data = None

        self._collect_analyzed_boxes()

        if not self.analyzed_boxes:
            QMessageBox.information(
                self, "분석 결과 없음",
                "분석된 항목이 없습니다.\n\nAI 분석 메뉴에서 먼저 분석을 실행하세요."
            )
            QTimer.singleShot(0, self.close)
            return

        self._setup_ui()

    def _collect_analyzed_boxes(self):
        """분석된 박스 수집 (문제 타입만)"""
        for page_idx, boxes in self.labeler.boxes.items():
            for box in boxes:
                # 문제 타입만 수집 (해설은 문제에 포함되므로 제외)
                if box.ai_result and box.box_type == BOX_TYPE_QUESTION:
                    theme_name = "미지정"
                    for theme in self.labeler.themes:
                        if theme.id == box.theme_id:
                            theme_name = theme.name
                            break
                    self.analyzed_boxes.append((page_idx, box, theme_name))

    def _setup_ui(self):
        from PyQt5.QtWebEngineWidgets import QWebEngineView

        layout = QVBoxLayout(self)

        # 상단 정보
        info_label = QLabel(f"총 {len(self.analyzed_boxes)}개 문제 분석됨")
        info_label.setStyleSheet("font-weight: bold; padding: 8px; background: #e8f4ff; border-radius: 4px;")
        layout.addWidget(info_label)

        # 메인 스플리터
        main_splitter = QSplitter(Qt.Horizontal)

        # 좌측: 박스 목록
        left_panel = self._create_left_panel()
        main_splitter.addWidget(left_panel)

        # 우측: 상세 보기
        right_panel = self._create_right_panel()
        main_splitter.addWidget(right_panel)

        main_splitter.setSizes([300, 800])
        layout.addWidget(main_splitter)

        # 하단 버튼
        btn_layout = QHBoxLayout()

        copy_json_btn = QPushButton("JSON 복사")
        copy_json_btn.clicked.connect(self._copy_current_json)
        btn_layout.addWidget(copy_json_btn)

        export_all_btn = QPushButton("전체 내보내기...")
        export_all_btn.clicked.connect(self._export_all_results)
        btn_layout.addWidget(export_all_btn)

        btn_layout.addStretch()

        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

        # 첫 번째 문제 항목 선택
        if self.box_tree_widget.topLevelItemCount() > 0:
            first_theme = self.box_tree_widget.topLevelItem(0)
            if first_theme.childCount() > 0:
                first_item = first_theme.child(0)
                self.box_tree_widget.setCurrentItem(first_item)

    def _create_left_panel(self):
        """좌측 패널 생성 (테마별 트리 뷰)"""
        from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem

        left_panel = QFrame()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 접기/펼치기 버튼
        btn_layout = QHBoxLayout()
        expand_btn = QPushButton("모두 펼치기")
        expand_btn.setFixedHeight(26)
        expand_btn.clicked.connect(lambda: self.box_tree_widget.expandAll())
        btn_layout.addWidget(expand_btn)

        collapse_btn = QPushButton("모두 접기")
        collapse_btn.setFixedHeight(26)
        collapse_btn.clicked.connect(lambda: self.box_tree_widget.collapseAll())
        btn_layout.addWidget(collapse_btn)

        btn_layout.addStretch()
        left_layout.addLayout(btn_layout)

        # 트리 위젯
        self.box_tree_widget = QTreeWidget()
        self.box_tree_widget.setMinimumWidth(280)
        self.box_tree_widget.setHeaderHidden(True)
        self.box_tree_widget.setIndentation(20)
        self.box_tree_widget.itemSelectionChanged.connect(self._on_tree_item_selected)
        self._populate_tree()
        left_layout.addWidget(self.box_tree_widget)

        return left_panel

    def _populate_tree(self):
        """트리 위젯 채우기 (테마별 그룹화)"""
        from PyQt5.QtWidgets import QTreeWidgetItem
        from collections import defaultdict

        self.box_tree_widget.clear()

        # 테마별로 그룹화
        theme_groups = defaultdict(list)
        for page_idx, box, theme_name in self.analyzed_boxes:
            theme_groups[theme_name].append((page_idx, box))

        # 테마별 트리 아이템 생성
        for theme_name in sorted(theme_groups.keys()):
            boxes = theme_groups[theme_name]

            # 테마 그룹 아이템
            theme_item = QTreeWidgetItem()
            theme_item.setText(0, f"📁 {theme_name} ({len(boxes)}개)")
            theme_item.setData(0, Qt.UserRole, None)  # 테마 아이템은 데이터 없음
            self.box_tree_widget.addTopLevelItem(theme_item)

            # 박스 아이템들
            for page_idx, box in boxes:
                q_num = box.ai_result.get("question_number", "")
                q_num_str = f"#{q_num}" if q_num else "(번호없음)"

                box_item = QTreeWidgetItem()
                box_item.setText(0, f"📝 {q_num_str}")
                box_item.setData(0, Qt.UserRole, (page_idx, box))
                theme_item.addChild(box_item)

            # 기본적으로 펼쳐두기
            theme_item.setExpanded(True)

    def _create_right_panel(self):
        """우측 패널 생성"""
        from PyQt5.QtWebEngineWidgets import QWebEngineView

        right_panel = QFrame()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 상세 스플리터
        detail_splitter = QSplitter(Qt.Vertical)

        # 이미지 + 렌더링 (수평 분할)
        top_splitter = QSplitter(Qt.Horizontal)

        # 원본 이미지
        image_frame = QFrame()
        image_frame.setFrameStyle(QFrame.StyledPanel)
        image_layout_v = QVBoxLayout(image_frame)
        image_title = QLabel("원본 이미지")
        image_title.setStyleSheet("font-weight: bold; padding: 4px;")
        image_layout_v.addWidget(image_title)

        self.image_label = QLabel("항목을 선택하세요")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(300, 200)
        self.image_label.setStyleSheet("background: #f5f5f5; border: 1px solid #ddd;")

        self.image_scroll = QScrollArea()
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.setWidgetResizable(True)
        image_layout_v.addWidget(self.image_scroll)

        top_splitter.addWidget(image_frame)

        # 수식 렌더링
        render_frame = QFrame()
        render_frame.setFrameStyle(QFrame.StyledPanel)
        render_layout_v = QVBoxLayout(render_frame)
        render_title = QLabel("수식 렌더링")
        render_title.setStyleSheet("font-weight: bold; padding: 4px;")
        render_layout_v.addWidget(render_title)

        self.web_view = QWebEngineView()
        self.web_view.setMinimumSize(300, 200)
        render_layout_v.addWidget(self.web_view)

        top_splitter.addWidget(render_frame)
        top_splitter.setSizes([400, 400])

        detail_splitter.addWidget(top_splitter)

        # 하단: 상세 정보 탭
        detail_tabs = QTabWidget()

        # 탭 1: 추출된 텍스트
        text_tab = QFrame()
        text_tab_layout = QVBoxLayout(text_tab)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Courier", 11))
        text_tab_layout.addWidget(self.text_edit)
        detail_tabs.addTab(text_tab, "추출된 텍스트")

        # 탭 2: 선택지/보기
        choices_tab = QFrame()
        choices_tab_layout = QVBoxLayout(choices_tab)
        self.choices_edit = QTextEdit()
        self.choices_edit.setReadOnly(True)
        self.choices_edit.setFont(QFont("Courier", 11))
        choices_tab_layout.addWidget(self.choices_edit)
        detail_tabs.addTab(choices_tab, "선택지/보기")

        # 탭 3: 해설 정보 (좌: 이미지, 우: LaTeX 렌더링)
        solution_tab = QFrame()
        solution_tab_layout = QHBoxLayout(solution_tab)
        solution_tab_layout.setContentsMargins(0, 0, 0, 0)

        # 해설 이미지 (좌측)
        self.solution_image_scroll = QScrollArea()
        self.solution_image_label = QLabel("해설 이미지")
        self.solution_image_label.setAlignment(Qt.AlignCenter)
        self.solution_image_label.setMinimumWidth(250)
        self.solution_image_label.setStyleSheet("background: #f5f5f5;")
        self.solution_image_scroll.setWidget(self.solution_image_label)
        self.solution_image_scroll.setWidgetResizable(True)
        solution_tab_layout.addWidget(self.solution_image_scroll, 1)

        # 해설 정보 (우측)
        self.solution_web_view = QWebEngineView()
        solution_tab_layout.addWidget(self.solution_web_view, 1)

        detail_tabs.addTab(solution_tab, "해설 정보")

        # 탭 4: 도형 해석
        figure_tab = QFrame()
        figure_layout = QVBoxLayout(figure_tab)
        self.figure_scroll = QScrollArea()
        self.figure_content = QLabel("도형/그래프 해석 정보가 여기에 표시됩니다")
        self.figure_content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.figure_content.setWordWrap(True)
        self.figure_content.setStyleSheet("background: #f5f5f5; padding: 10px;")
        self.figure_scroll.setWidget(self.figure_content)
        self.figure_scroll.setWidgetResizable(True)
        figure_layout.addWidget(self.figure_scroll)
        detail_tabs.addTab(figure_tab, "도형 해석")

        # 탭 5: JSON 원본
        json_tab = QFrame()
        json_tab_layout = QVBoxLayout(json_tab)
        self.json_edit = QTextEdit()
        self.json_edit.setReadOnly(True)
        self.json_edit.setFont(QFont("Courier", 10))
        json_tab_layout.addWidget(self.json_edit)
        detail_tabs.addTab(json_tab, "JSON")

        detail_splitter.addWidget(detail_tabs)
        detail_splitter.setSizes([350, 250])

        right_layout.addWidget(detail_splitter)
        return right_panel

    def _on_tree_item_selected(self):
        """트리 항목 선택 시 상세 정보 표시"""
        items = self.box_tree_widget.selectedItems()
        if not items:
            return

        data = items[0].data(0, Qt.UserRole)
        if data is None:
            # 테마 그룹 아이템 선택 시 무시
            return

        page_idx, box = data
        self.current_box_data = box

        # 이미지 표시
        self._show_box_image(page_idx, box)

        # 분석 결과 표시
        result = box.ai_result
        content = result.get("content", {})

        # 수식 렌더링
        main_text = content.get("question_text", "") or content.get("solution_text", "")
        choices = content.get("choices", [])
        sub_questions = content.get("sub_questions", [])
        html = generate_katex_html(main_text, choices, sub_questions)
        self.web_view.setHtml(html)

        # 추출된 텍스트 탭
        self.text_edit.setPlainText(main_text)

        # 선택지/보기 탭
        self._populate_choices_tab(content)

        # 해설 정보 탭
        self._populate_solution_tab(page_idx, box, content, result)

        # 도형 해석 탭
        self._populate_figure_tab(result)

        # JSON 탭
        self.json_edit.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))

    def _show_box_image(self, page_idx, box):
        """박스 이미지 표시"""
        if page_idx < len(self.labeler.pages):
            page_image = self.labeler.pages[page_idx]
            cropped = crop_box_image(page_image, box)

            if cropped.mode != "RGB":
                cropped = cropped.convert("RGB")
            data = cropped.tobytes("raw", "RGB")
            qimage = QImage(data, cropped.width, cropped.height,
                           cropped.width * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimage)

            scroll_size = self.image_scroll.size()
            available_w = scroll_size.width() - 20
            available_h = scroll_size.height() - 20

            if available_w > 50 and available_h > 50:
                scaled_pixmap = pixmap.scaled(
                    available_w, available_h,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
            else:
                self.image_label.setPixmap(pixmap)
        else:
            self.image_label.setText("이미지 없음")

    def _populate_choices_tab(self, content):
        """선택지/보기 탭 채우기"""
        choices = content.get("choices", [])
        choices_text = ""
        if choices:
            choices_text += "【선택지】\n"
            for c in choices:
                choices_text += f"{c.get('label', '')} {c.get('text', '')}\n"

        sub_qs = content.get("sub_questions", [])
        if sub_qs:
            if choices_text:
                choices_text += "\n"
            choices_text += "【보기】\n"
            for sq in sub_qs:
                choices_text += f"{sq.get('label', '')} {sq.get('text', '')}\n"

        if not choices_text:
            choices_text = "(선택지/보기 없음)"
        self.choices_edit.setPlainText(choices_text)

    def _populate_solution_tab(self, page_idx, box, content, result):
        """해설 정보 탭 채우기"""
        # 연결된 해설 박스들 찾기
        linked_solutions = []
        linked_solution_boxes = []
        if box.box_type == BOX_TYPE_QUESTION and box.box_id:
            for p_idx, p_boxes in self.labeler.boxes.items():
                for b in p_boxes:
                    if b.box_type == BOX_TYPE_SOLUTION and b.linked_box_id == box.box_id:
                        linked_solution_boxes.append((p_idx, b))
                        if b.ai_result:
                            sol_content = b.ai_result.get("content", {})
                            linked_solutions.append(sol_content)

        # 해설 HTML 생성
        solution_html = self._generate_solution_html(content, result, linked_solutions)
        self.solution_web_view.setHtml(solution_html)

        # 해설 이미지 표시
        self._show_solution_images(page_idx, box, linked_solution_boxes)

    def _show_solution_images(self, page_idx, box, linked_solution_boxes):
        """해설 이미지 표시"""
        images_to_merge = []

        # 현재 박스가 해설이면 그 이미지 사용
        if box.box_type == BOX_TYPE_SOLUTION:
            if page_idx < len(self.labeler.pages):
                cropped = crop_box_image(self.labeler.pages[page_idx], box)
                images_to_merge.append(cropped)

        # 연결된 해설 박스들의 이미지 수집
        for sol_page_idx, sol_box in linked_solution_boxes:
            if sol_page_idx < len(self.labeler.pages):
                sol_cropped = crop_box_image(self.labeler.pages[sol_page_idx], sol_box)
                images_to_merge.append(sol_cropped)

        if not images_to_merge:
            self.solution_image_label.setText("해설 없음")
            return

        # 이미지들 세로로 합치기
        if len(images_to_merge) == 1:
            merged = images_to_merge[0]
        else:
            total_height = sum(img.height for img in images_to_merge)
            max_width = max(img.width for img in images_to_merge)
            merged = Image.new('RGB', (max_width, total_height), (255, 255, 255))
            y_offset = 0
            for img in images_to_merge:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                merged.paste(img, (0, y_offset))
                y_offset += img.height

        # PIL to QPixmap
        if merged.mode != "RGB":
            merged = merged.convert("RGB")
        data = merged.tobytes("raw", "RGB")
        qimage = QImage(data, merged.width, merged.height,
                       merged.width * 3, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimage)

        # FIT 스케일링
        scroll_size = self.solution_image_scroll.size()
        available_w = scroll_size.width() - 20
        available_h = scroll_size.height() - 20

        if available_w > 50 and available_h > 50:
            scaled = pixmap.scaled(
                available_w, available_h,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.solution_image_label.setPixmap(scaled)
        else:
            self.solution_image_label.setPixmap(pixmap)

    def _generate_solution_html(self, content_data, result_data, linked_solutions=None):
        """해설 정보를 LaTeX 렌더링 가능한 HTML로 생성"""
        if linked_solutions is None:
            linked_solutions = []

        def escape_html(s):
            return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        sections = []

        # 정답
        answer = content_data.get("answer", "")
        if not answer and linked_solutions:
            for sol in linked_solutions:
                if sol.get("answer"):
                    answer = sol.get("answer")
                    break

        if answer:
            sections.append(f'''
                <div class="section">
                    <div class="section-title">정답</div>
                    <div class="answer">{escape_html(str(answer))}</div>
                </div>
            ''')

        # 핵심 개념
        all_key_concepts = set()
        key_concepts = content_data.get("key_concepts", [])
        all_key_concepts.update(key_concepts)
        for sol in linked_solutions:
            all_key_concepts.update(sol.get("key_concepts", []))

        if all_key_concepts:
            concepts_html = "".join(f"<li>{escape_html(kc)}</li>" for kc in all_key_concepts)
            sections.append(f'''
                <div class="section">
                    <div class="section-title">핵심 개념</div>
                    <ul>{concepts_html}</ul>
                </div>
            ''')

        # 해설 본문
        all_solution_texts = []
        solution_text = content_data.get("solution_text", "")
        if solution_text:
            all_solution_texts.append(solution_text)

        for i, sol in enumerate(linked_solutions):
            sol_text = sol.get("solution_text", "")
            if sol_text:
                if len(linked_solutions) > 1:
                    all_solution_texts.append(f"[해설 {i+1}]\n{sol_text}")
                else:
                    all_solution_texts.append(sol_text)

        combined_solution = "\n\n".join(all_solution_texts)
        if combined_solution:
            sections.append(f'''
                <div class="section">
                    <div class="section-title">해설</div>
                    <div class="solution-text">{escape_html(combined_solution).replace(chr(10), '<br>')}</div>
                </div>
            ''')

        if not sections:
            sections.append('<div class="empty">(해설 정보 없음)</div>')

        return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
    <style>
        body {{
            font-family: 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;
            font-size: 14px;
            line-height: 1.6;
            padding: 15px;
            margin: 0;
            background: white;
        }}
        .section {{
            margin-bottom: 20px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 6px;
        }}
        .section-title {{
            font-weight: bold;
            font-size: 15px;
            color: #333;
            margin-bottom: 8px;
            padding-bottom: 5px;
            border-bottom: 2px solid #007bff;
        }}
        .answer {{
            font-size: 18px;
            font-weight: bold;
            color: #007bff;
            padding: 10px;
            background: #e8f4ff;
            border-radius: 4px;
        }}
        ul {{
            margin: 5px 0;
            padding-left: 20px;
        }}
        li {{
            margin: 3px 0;
        }}
        .solution-text {{
            padding: 8px;
            background: white;
            border-radius: 4px;
        }}
        .empty {{
            color: #999;
            text-align: center;
            padding: 20px;
        }}
        .katex {{
            font-size: 1.1em;
        }}
    </style>
</head>
<body>
    {"".join(sections)}
    <script>
        document.addEventListener("DOMContentLoaded", function() {{
            renderMathInElement(document.body, {{
                delimiters: [
                    {{left: "$$", right: "$$", display: true}},
                    {{left: "$", right: "$", display: false}}
                ],
                throwOnError: false
            }});
        }});
    </script>
</body>
</html>'''

    def _populate_figure_tab(self, result):
        """도형 해석 탭 채우기"""
        content = result.get("content", {})

        # 새 스키마: figures / 구 스키마: graphs
        figures = content.get("figures", []) or content.get("graphs", [])

        if not figures:
            self.figure_content.setText("도형/그래프 정보가 없습니다.")
            self.figure_content.setStyleSheet("background: #f5f5f5; padding: 20px; color: #666;")
            return

        # 여러 도형을 세로로 배치할 위젯 생성
        container = QFrame()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(10, 10, 10, 10)

        for i, fig in enumerate(figures):
            fig_type = fig.get("figure_type", "") or fig.get("graph_type", "unknown")

            group = QGroupBox(f"도형 {i+1}: {fig_type}")
            group_layout = QVBoxLayout(group)

            # 추출된 이미지 표시 (figure_image_base64)
            fig_image_b64 = fig.get("figure_image_base64")
            if fig_image_b64:
                try:
                    import base64
                    image_data = base64.b64decode(fig_image_b64)
                    pixmap = QPixmap()
                    pixmap.loadFromData(image_data)
                    if not pixmap.isNull():
                        # 최대 너비 300px로 스케일
                        if pixmap.width() > 300:
                            pixmap = pixmap.scaledToWidth(300, Qt.SmoothTransformation)
                        img_label = QLabel()
                        img_label.setPixmap(pixmap)
                        img_label.setAlignment(Qt.AlignCenter)
                        img_label.setStyleSheet("padding: 10px; background: #fff; border: 1px solid #ddd; border-radius: 4px;")
                        group_layout.addWidget(img_label)
                except Exception:
                    pass

            # 재현 설명 (새 스키마)
            repro_desc = fig.get("reproduction_description", "")
            if repro_desc:
                repro_label = QLabel(f"<b>재현 설명:</b> {repro_desc}")
                repro_label.setWordWrap(True)
                repro_label.setStyleSheet("padding: 5px; background: #e8f4fc; border-radius: 4px;")
                group_layout.addWidget(repro_label)

            # 자연어 설명 (구 스키마 호환)
            verbal = fig.get("verbal_description", "") or fig.get("description", "")
            if verbal and verbal != repro_desc:
                desc_label = QLabel(f"<b>설명:</b> {verbal}")
                desc_label.setWordWrap(True)
                desc_label.setStyleSheet("padding: 5px; background: #f0f8ff; border-radius: 4px;")
                group_layout.addWidget(desc_label)

            # 좌표계 정보 (새 스키마)
            coord_sys = fig.get("coordinate_system", {})
            if coord_sys and isinstance(coord_sys, dict):
                coord_type = coord_sys.get("type", "")
                x_range = coord_sys.get("x_range", [])
                y_range = coord_sys.get("y_range", [])
                coord_text = f"<b>좌표계:</b> {coord_type}"
                if x_range:
                    coord_text += f", x: {x_range}"
                if y_range:
                    coord_text += f", y: {y_range}"
                coord_label = QLabel(coord_text)
                group_layout.addWidget(coord_label)

            # 곡선 정보 (새 스키마)
            curves = fig.get("curves", [])
            if curves:
                curves_lines = []
                for curve in curves:
                    curve_type = curve.get("type", "")
                    eq = curve.get("equation", "")
                    domain = curve.get("domain", [])
                    style = curve.get("style", "")
                    line = f"  • [{curve_type}] {eq}"
                    if domain:
                        line += f" (정의역: {domain})"
                    if style:
                        line += f" ({style})"
                    curves_lines.append(line)
                curves_text = "<b>곡선:</b><br>" + "<br>".join(curves_lines)
                curves_label = QLabel(curves_text)
                curves_label.setWordWrap(True)
                group_layout.addWidget(curves_label)

            # 점 정보 (새 스키마)
            points = fig.get("points", [])
            if points:
                pts_lines = []
                for pt in points:
                    coords = pt.get("coords", [])
                    label = pt.get("label", "")
                    style = pt.get("style", "filled")
                    line = f"  • {label}: {coords}" if label else f"  • {coords}"
                    if style != "filled":
                        line += f" ({style})"
                    pts_lines.append(line)
                pts_text = "<b>점:</b><br>" + "<br>".join(pts_lines)
                pts_label = QLabel(pts_text)
                pts_label.setWordWrap(True)
                group_layout.addWidget(pts_label)

            # 선분/직선 정보 (새 스키마)
            lines = fig.get("lines", [])
            if lines:
                lines_list = []
                for ln in lines:
                    ln_type = ln.get("type", "segment")
                    from_pt = ln.get("from", [])
                    to_pt = ln.get("to", [])
                    eq = ln.get("equation", "")
                    label = ln.get("label", "")
                    if eq:
                        line_str = f"  • [{ln_type}] {eq}"
                    else:
                        line_str = f"  • [{ln_type}] {from_pt} → {to_pt}"
                    if label:
                        line_str += f" ({label})"
                    lines_list.append(line_str)
                lines_text = "<b>선:</b><br>" + "<br>".join(lines_list)
                lines_label = QLabel(lines_text)
                lines_label.setWordWrap(True)
                group_layout.addWidget(lines_label)

            # 도형 정보 (새 스키마)
            shapes = fig.get("shapes", [])
            if shapes:
                shapes_lines = []
                for shape in shapes:
                    shape_type = shape.get("type", "")
                    vertices = shape.get("vertices", [])
                    center = shape.get("center", [])
                    radius = shape.get("radius", "")
                    if shape_type == "circle" and center:
                        line = f"  • 원: 중심 {center}, 반지름 {radius}"
                    elif vertices:
                        line = f"  • {shape_type}: 꼭짓점 {vertices}"
                    else:
                        line = f"  • {shape_type}"
                    shapes_lines.append(line)
                shapes_text = "<b>도형:</b><br>" + "<br>".join(shapes_lines)
                shapes_label = QLabel(shapes_text)
                shapes_label.setWordWrap(True)
                group_layout.addWidget(shapes_label)

            # 주석 (새 스키마)
            annotations = fig.get("annotations", [])
            if annotations:
                ann_lines = []
                for ann in annotations:
                    text = ann.get("text", "")
                    pos = ann.get("position", [])
                    ann_lines.append(f"  • \"{text}\" at {pos}")
                ann_text = "<b>주석:</b><br>" + "<br>".join(ann_lines)
                ann_label = QLabel(ann_text)
                ann_label.setWordWrap(True)
                group_layout.addWidget(ann_label)

            # 음영 영역 (새 스키마)
            shaded = fig.get("shaded_regions", [])
            if shaded:
                shaded_lines = []
                for region in shaded:
                    desc = region.get("description", "")
                    bounds = region.get("bounds", "")
                    line = f"  • {desc}" if desc else f"  • {bounds}"
                    shaded_lines.append(line)
                shaded_text = "<b>음영 영역:</b><br>" + "<br>".join(shaded_lines)
                shaded_label = QLabel(shaded_text)
                shaded_label.setWordWrap(True)
                group_layout.addWidget(shaded_label)

            # 특수 표시 (새 스키마)
            special = fig.get("special_marks", [])
            if special:
                special_lines = []
                for mark in special:
                    mark_type = mark.get("type", "")
                    location = mark.get("location", "")
                    special_lines.append(f"  • [{mark_type}] {location}")
                special_text = "<b>특수 표시:</b><br>" + "<br>".join(special_lines)
                special_label = QLabel(special_text)
                special_label.setWordWrap(True)
                group_layout.addWidget(special_label)

            # 구 스키마 호환: mathematical_elements
            math_elem = fig.get("mathematical_elements", {})
            if math_elem:
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
                    kpts_lines = []
                    for pt in key_points:
                        name = pt.get("name", "")
                        coords = pt.get("coords", [])
                        sig = pt.get("significance", "")
                        line = f"  • {name}: {coords}"
                        if sig:
                            line += f" ({sig})"
                        kpts_lines.append(line)
                    kpts_text = "<b>주요 점:</b><br>" + "<br>".join(kpts_lines)
                    kpts_label = QLabel(kpts_text)
                    kpts_label.setWordWrap(True)
                    group_layout.addWidget(kpts_label)

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
                labels_label = QLabel(f"<b>라벨:</b> {', '.join(labels)}")
                group_layout.addWidget(labels_label)

            container_layout.addWidget(group)

        container_layout.addStretch()

        # 기존 위젯 교체
        self.figure_scroll.setWidget(container)
        self.figure_content = container

    def _copy_current_json(self):
        """현재 선택된 항목의 JSON 복사"""
        if self.current_box_data and self.current_box_data.ai_result:
            clipboard = QApplication.clipboard()
            clipboard.setText(json.dumps(self.current_box_data.ai_result, ensure_ascii=False, indent=2))
            self.labeler.status_label.setText("JSON이 클립보드에 복사되었습니다")

    def _export_all_results(self):
        """전체 분석 결과 내보내기 - 형식 선택 다이얼로그"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QRadioButton, QButtonGroup, QDialogButtonBox, QGroupBox

        # 형식 선택 다이얼로그
        dialog = QDialog(self)
        dialog.setWindowTitle("내보내기 형식 선택")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)

        # 로컬 파일 저장 옵션
        local_group = QGroupBox("로컬 파일 저장")
        local_layout = QVBoxLayout(local_group)

        btn_group = QButtonGroup(dialog)

        single_radio = QRadioButton("단일 파일 (모든 문제를 하나의 JSON에)")
        single_radio.setChecked(True)
        btn_group.addButton(single_radio, 1)
        local_layout.addWidget(single_radio)

        split_radio = QRadioButton("테마별 분리 (테마별 JSON + 인덱스 파일)")
        btn_group.addButton(split_radio, 2)
        local_layout.addWidget(split_radio)

        layout.addWidget(local_group)

        # Supabase 업로드 옵션
        supabase_group = QGroupBox("Supabase 업로드")
        supabase_layout = QVBoxLayout(supabase_group)

        supabase_radio = QRadioButton("Supabase에 업로드 (유사 문제 검색 가능)")
        btn_group.addButton(supabase_radio, 3)
        supabase_layout.addWidget(supabase_radio)

        # Supabase 연결 상태 및 테스트 버튼
        supabase_status_layout = QHBoxLayout()

        # 연결 상태 라벨
        supabase_status = QLabel("")
        supabase_status_layout.addWidget(supabase_status)

        # 연결 테스트 버튼
        test_btn = QPushButton("연결 테스트")
        test_btn.setFixedWidth(100)
        supabase_status_layout.addWidget(test_btn)
        supabase_status_layout.addStretch()

        supabase_layout.addLayout(supabase_status_layout)

        # Supabase 연결 상태 확인 및 테스트 함수
        def check_supabase_status():
            try:
                from .supabase_client import get_supabase_credentials
                url, key = get_supabase_credentials()
                if url and key:
                    supabase_status.setText("<small style='color: blue;'>설정됨 - 테스트 필요</small>")
                    supabase_radio.setEnabled(True)
                    test_btn.setEnabled(True)
                    return True
                else:
                    supabase_status.setText("<small style='color: orange;'>설정 → Supabase 연결 필요</small>")
                    supabase_radio.setEnabled(False)
                    test_btn.setEnabled(False)
                    return False
            except ImportError:
                supabase_status.setText("<small style='color: red;'>pip install supabase 필요</small>")
                supabase_radio.setEnabled(False)
                test_btn.setEnabled(False)
                return False

        def test_supabase_connection():
            test_btn.setEnabled(False)
            supabase_status.setText("<small style='color: gray;'>연결 테스트 중...</small>")
            QApplication.processEvents()

            try:
                from .supabase_client import get_supabase_credentials
                from supabase import create_client

                url, key = get_supabase_credentials()
                if not url or not key:
                    supabase_status.setText("<small style='color: orange;'>Supabase 설정 필요</small>")
                    supabase_radio.setEnabled(False)
                    test_btn.setEnabled(True)
                    return

                client = create_client(url, key)
                result = client.table("textbooks").select("id").limit(1).execute()

                supabase_status.setText("<small style='color: green;'>연결 성공!</small>")
                supabase_radio.setEnabled(True)
                supabase_radio.setChecked(True)

            except Exception as e:
                error_msg = str(e)
                if "relation" in error_msg and "does not exist" in error_msg:
                    supabase_status.setText("<small style='color: red;'>테이블 없음 - schema.sql 실행 필요</small>")
                elif "Invalid" in error_msg.lower():
                    supabase_status.setText("<small style='color: red;'>잘못된 API Key</small>")
                else:
                    supabase_status.setText(f"<small style='color: red;'>오류: {error_msg[:30]}...</small>")
                supabase_radio.setEnabled(False)

            test_btn.setEnabled(True)

        test_btn.clicked.connect(test_supabase_connection)

        # 초기 상태 확인
        check_supabase_status()

        layout.addWidget(supabase_group)

        # 설명
        desc_label = QLabel(
            "<small style='color: #666;'>"
            "Supabase 업로드 시 벡터 임베딩이 생성되어<br>"
            "유사 문제 검색이 가능합니다."
            "</small>"
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        selected_id = btn_group.checkedId()
        if selected_id == 1:
            self._export_single_file()
        elif selected_id == 2:
            self._export_by_theme()
        elif selected_id == 3:
            self._export_to_supabase()

    def _export_single_file(self):
        """단일 파일로 내보내기"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "분석 결과 내보내기", "", "JSON 파일 (*.json)"
        )
        if not file_path:
            return

        all_results = []
        for page_idx, box, theme_name in self.analyzed_boxes:
            result_entry = {
                "page": page_idx + 1,
                "box_id": box.id,
                "box_type": box.box_type,
                "theme_name": theme_name,
                "analysis": box.ai_result
            }
            all_results.append(result_entry)

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)
            QMessageBox.information(
                self, "내보내기 완료",
                f"총 {len(all_results)}개 항목이 저장되었습니다.\n\n{file_path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "내보내기 실패", f"파일 저장 중 오류:\n{str(e)}")

    def _export_by_theme(self):
        """테마별 분리 내보내기"""
        from pathlib import Path
        from collections import defaultdict
        from datetime import datetime

        # 폴더 선택
        folder_path = QFileDialog.getExistingDirectory(
            self, "내보내기 폴더 선택", ""
        )
        if not folder_path:
            return

        folder = Path(folder_path)

        # 테마별로 그룹화
        theme_groups = defaultdict(list)
        for page_idx, box, theme_name in self.analyzed_boxes:
            result_entry = {
                "page": page_idx + 1,
                "box_id": box.id,
                "question_number": box.ai_result.get("question_number"),
                "analysis": box.ai_result
            }
            theme_groups[theme_name].append(result_entry)

        # 인덱스 파일 생성
        index_data = {
            "created_at": datetime.now().isoformat(),
            "source_pdf": self.labeler.pdf_path.name if self.labeler.pdf_path else "unknown",
            "total_questions": len(self.analyzed_boxes),
            "themes": []
        }

        saved_files = []

        try:
            for theme_name, questions in sorted(theme_groups.items()):
                # 파일명에 사용할 수 없는 문자 제거
                safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in theme_name)
                safe_name = safe_name.strip() or "untitled"
                file_name = f"{safe_name}.json"
                file_path = folder / file_name

                # 테마 파일 저장
                theme_data = {
                    "theme_name": theme_name,
                    "question_count": len(questions),
                    "questions": questions
                }

                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(theme_data, f, ensure_ascii=False, indent=2)

                saved_files.append(file_name)

                # 인덱스에 추가
                index_data["themes"].append({
                    "name": theme_name,
                    "file": file_name,
                    "question_count": len(questions)
                })

            # 인덱스 파일 저장
            index_path = folder / "index.json"
            with open(index_path, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)

            QMessageBox.information(
                self, "내보내기 완료",
                f"테마별 내보내기 완료!\n\n"
                f"폴더: {folder_path}\n"
                f"인덱스: index.json\n"
                f"테마 파일: {len(saved_files)}개\n"
                f"총 문제: {len(self.analyzed_boxes)}개"
            )

        except Exception as e:
            QMessageBox.critical(self, "내보내기 실패", f"파일 저장 중 오류:\n{str(e)}")

    def _export_to_supabase(self):
        """Supabase에 업로드 (문제+해설 통합)"""
        from PyQt5.QtWidgets import QInputDialog, QProgressDialog
        from .models import BOX_TYPE_SOLUTION

        # 교재 정보 입력
        title, ok = QInputDialog.getText(
            self, "교재 정보",
            "교재 제목을 입력하세요:",
            text=self.labeler.pdf_path.stem if self.labeler.pdf_path else ""
        )
        if not ok or not title:
            return

        # 프로그레스 다이얼로그
        progress = QProgressDialog("Supabase에 업로드 중...", "취소", 0, 100, self)
        progress.setWindowTitle("업로드")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(10)
        QApplication.processEvents()

        try:
            from .supabase_sync import get_supabase_sync

            sync = get_supabase_sync()

            # 테마 데이터 준비
            themes = [{"name": t.name, "color": t.color, "deleted": t.deleted} for t in self.labeler.themes]

            # 해설 박스 인덱스 생성 (linked_box_id → solution_box)
            solution_map = {}  # question_box_id → [(page_idx, solution_box), ...]
            for page_idx, page_boxes in enumerate(self.labeler.boxes):
                for box in page_boxes:
                    if box.box_type == BOX_TYPE_SOLUTION and box.linked_box_id:
                        if box.linked_box_id not in solution_map:
                            solution_map[box.linked_box_id] = []
                        solution_map[box.linked_box_id].append((page_idx, box))

            # 문제 데이터 준비 (문제 + 연결된 해설 통합)
            questions = []
            for page_idx, box, theme_name in self.analyzed_boxes:
                question_data = {
                    "page": page_idx + 1,
                    "x1": box.x1,
                    "y1": box.y1,
                    "x2": box.x2,
                    "y2": box.y2,
                    "theme_name": theme_name,
                    "ai_result": box.ai_result
                }

                # 연결된 해설 찾기
                linked_solutions = solution_map.get(box.box_id, [])
                if linked_solutions:
                    # 첫 번째 해설 사용 (여러 개면 첫 번째)
                    sol_page_idx, sol_box = linked_solutions[0]
                    question_data["solution_ai_result"] = sol_box.ai_result
                    question_data["solution_page"] = sol_page_idx + 1
                    question_data["solution_x1"] = sol_box.x1
                    question_data["solution_y1"] = sol_box.y1
                    question_data["solution_x2"] = sol_box.x2
                    question_data["solution_y2"] = sol_box.y2

                questions.append(question_data)

            progress.setValue(30)
            progress.setLabelText("임베딩 생성 및 업로드 중...")
            QApplication.processEvents()

            # 업로드
            result = sync.upload_textbook(
                title=title,
                themes=themes,
                questions=questions,
                source_pdf=self.labeler.pdf_path.name if self.labeler.pdf_path else None
            )

            progress.setValue(100)
            progress.close()

            if result.success:
                # 해설 연결 통계
                linked_count = sum(1 for q in questions if q.get("solution_ai_result"))
                QMessageBox.information(
                    self, "업로드 완료",
                    f"Supabase 업로드 완료!\n\n"
                    f"교재: {title}\n"
                    f"문제 수: {result.question_count}개\n"
                    f"해설 연결: {linked_count}개\n"
                    f"교재 ID: {result.textbook_id[:8]}..."
                )
            else:
                QMessageBox.critical(
                    self, "업로드 실패",
                    f"업로드 중 오류:\n{result.error_message}"
                )

        except ImportError as e:
            progress.close()
            QMessageBox.critical(
                self, "패키지 오류",
                f"필요한 패키지가 없습니다:\n{str(e)}\n\npip install supabase openai"
            )
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "업로드 실패", f"오류:\n{str(e)}")


class SolutionLinkDialog(QDialog):
    """해설 연결 다이얼로그"""

    def __init__(self, parent: 'PDFLabeler', solution_boxes: list, position=None):
        super().__init__(parent)
        self.labeler = parent
        self.solution_boxes = solution_boxes if isinstance(solution_boxes, list) else [solution_boxes]
        self.position = position
        self.selected_question = None

        self.setWindowTitle("해설 연결")
        self.setModal(True)
        self.setMinimumWidth(200)

        self._setup_ui()

        if position:
            self.move(position)

    def _setup_ui(self):
        solution_theme_id = self.solution_boxes[0].theme_id

        # 같은 테마의 문항 목록 수집
        questions_in_theme = []
        for page_idx, page_boxes in self.labeler.boxes.items():
            for box in page_boxes:
                if box.box_type != BOX_TYPE_QUESTION:
                    continue
                if solution_theme_id and box.theme_id != solution_theme_id:
                    continue
                questions_in_theme.append((page_idx, box))

        # 문항 정렬
        questions_in_theme.sort(key=lambda x: self.labeler._get_box_sort_key(x[0], x[1]))
        self.questions_in_theme = questions_in_theme

        if not questions_in_theme:
            return

        # 테마 이름
        theme = self.labeler.get_theme_by_id(solution_theme_id) if solution_theme_id else None
        display_theme = theme.name if theme else "미지정"

        # 문항 목록 생성
        self.question_labels = []
        for idx, (page_idx, box) in enumerate(questions_in_theme, 1):
            label = f"📝 {idx:02d}"
            self.question_labels.append(label)

        count_text = f"{len(self.solution_boxes)}개 해설" if len(self.solution_boxes) > 1 else "해설"

        # 기본 선택 인덱스
        default_idx = getattr(self.labeler, '_next_solution_link_idx', 0)
        if default_idx >= len(self.question_labels):
            default_idx = 0

        # UI 구성
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.addWidget(QLabel(f"[{display_theme}] {count_text} 연결:"))

        self.list_widget = QListWidget()
        self.list_widget.addItems(self.question_labels)
        self.list_widget.setCurrentRow(default_idx)

        item_height = 25
        visible_items = min(len(self.question_labels), 10)
        self.list_widget.setFixedHeight(item_height * visible_items + 5)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.adjustSize()

    def get_selected_question(self):
        """선택된 문항 반환"""
        if not self.questions_in_theme:
            return None

        selected = self.list_widget.currentItem()
        if not selected:
            return None

        try:
            selected_idx = self.question_labels.index(selected.text())
            return self.questions_in_theme[selected_idx][1]
        except (ValueError, IndexError):
            return None

    def accept(self):
        """다이얼로그 수락"""
        self.selected_question = self.get_selected_question()
        if self.selected_question and self.question_labels:
            selected_idx = self.list_widget.currentRow()
            self.labeler._next_solution_link_idx = selected_idx + 1
        super().accept()
