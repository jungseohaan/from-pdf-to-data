"""설정 다이얼로그 모듈"""

import json
import os
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QComboBox, QTextEdit, QPushButton,
    QGroupBox, QFormLayout, QMessageBox, QSplitter
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from .config import (
    AVAILABLE_MODELS, get_model_by_id, get_vision_models,
    load_settings, save_settings, load_output_schema, save_output_schema,
    SCHEMA_FILE
)


class SettingsDialog(QDialog):
    """설정 다이얼로그"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumSize(700, 550)
        self.settings = load_settings()
        self.schema = load_output_schema()
        self._setup_ui()
        self._load_current_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 탭 위젯
        tabs = QTabWidget()

        # 탭 1: LLM 모델 설정
        model_tab = QWidget()
        model_layout = QVBoxLayout(model_tab)

        # 모델 선택
        model_group = QGroupBox("AI 모델 선택")
        model_group_layout = QFormLayout(model_group)

        self.model_combo = QComboBox()
        vision_models = get_vision_models()
        for model in vision_models:
            self.model_combo.addItem(f"{model.name} ({model.provider.upper()})", model.id)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        model_group_layout.addRow("모델:", self.model_combo)

        # 현재 모델 정보
        self.model_info_label = QLabel()
        self.model_info_label.setStyleSheet("color: #666; font-size: 11px;")
        model_group_layout.addRow("", self.model_info_label)

        model_layout.addWidget(model_group)

        # API 키 설정
        api_group = QGroupBox("API 키")
        api_layout = QFormLayout(api_group)

        # Gemini API 키
        gemini_key_layout = QHBoxLayout()
        self.gemini_key_edit = QLineEdit()
        self.gemini_key_edit.setEchoMode(QLineEdit.Password)
        self.gemini_key_edit.setPlaceholderText("Gemini API 키를 입력하세요")
        gemini_key_layout.addWidget(self.gemini_key_edit)

        self.gemini_show_btn = QPushButton("표시")
        self.gemini_show_btn.setCheckable(True)
        self.gemini_show_btn.clicked.connect(lambda: self._toggle_key_visibility(
            self.gemini_key_edit, self.gemini_show_btn))
        gemini_key_layout.addWidget(self.gemini_show_btn)

        api_layout.addRow("Gemini:", gemini_key_layout)

        gemini_hint = QLabel("Google AI Studio에서 발급: https://makersuite.google.com/app/apikey")
        gemini_hint.setStyleSheet("color: #888; font-size: 10px;")
        gemini_hint.setOpenExternalLinks(True)
        api_layout.addRow("", gemini_hint)

        # OpenAI API 키
        openai_key_layout = QHBoxLayout()
        self.openai_key_edit = QLineEdit()
        self.openai_key_edit.setEchoMode(QLineEdit.Password)
        self.openai_key_edit.setPlaceholderText("OpenAI API 키를 입력하세요")
        openai_key_layout.addWidget(self.openai_key_edit)

        self.openai_show_btn = QPushButton("표시")
        self.openai_show_btn.setCheckable(True)
        self.openai_show_btn.clicked.connect(lambda: self._toggle_key_visibility(
            self.openai_key_edit, self.openai_show_btn))
        openai_key_layout.addWidget(self.openai_show_btn)

        api_layout.addRow("OpenAI:", openai_key_layout)

        openai_hint = QLabel("OpenAI에서 발급: https://platform.openai.com/api-keys")
        openai_hint.setStyleSheet("color: #888; font-size: 10px;")
        openai_hint.setOpenExternalLinks(True)
        api_layout.addRow("", openai_hint)

        # 환경변수 안내
        env_hint = QLabel("💡 .env 파일에 GEMINI_API_KEY, OPENAI_API_KEY를 설정해도 됩니다.")
        env_hint.setStyleSheet("color: #666; font-size: 11px; padding-top: 10px;")
        api_layout.addRow("", env_hint)

        model_layout.addWidget(api_group)

        # Supabase 설정
        supabase_group = QGroupBox("Supabase (문제 저장/검색)")
        supabase_layout = QFormLayout(supabase_group)

        # Supabase URL
        self.supabase_url_edit = QLineEdit()
        self.supabase_url_edit.setPlaceholderText("https://xxxxx.supabase.co")
        supabase_layout.addRow("URL:", self.supabase_url_edit)

        # Supabase API Key
        supabase_key_layout = QHBoxLayout()
        self.supabase_key_edit = QLineEdit()
        self.supabase_key_edit.setEchoMode(QLineEdit.Password)
        self.supabase_key_edit.setPlaceholderText("Supabase anon/service key")
        supabase_key_layout.addWidget(self.supabase_key_edit)

        self.supabase_show_btn = QPushButton("표시")
        self.supabase_show_btn.setCheckable(True)
        self.supabase_show_btn.clicked.connect(lambda: self._toggle_key_visibility(
            self.supabase_key_edit, self.supabase_show_btn))
        supabase_key_layout.addWidget(self.supabase_show_btn)

        supabase_layout.addRow("API Key:", supabase_key_layout)

        # 연결 테스트 버튼
        test_btn_layout = QHBoxLayout()
        self.supabase_test_btn = QPushButton("연결 테스트")
        self.supabase_test_btn.clicked.connect(self._test_supabase_connection)
        test_btn_layout.addWidget(self.supabase_test_btn)

        self.supabase_status_label = QLabel("")
        self.supabase_status_label.setStyleSheet("font-size: 11px;")
        test_btn_layout.addWidget(self.supabase_status_label)
        test_btn_layout.addStretch()

        supabase_layout.addRow("", test_btn_layout)

        supabase_hint = QLabel("💡 Supabase 대시보드 → Settings → API에서 확인")
        supabase_hint.setStyleSheet("color: #888; font-size: 10px;")
        supabase_layout.addRow("", supabase_hint)

        model_layout.addWidget(supabase_group)
        model_layout.addStretch()

        tabs.addTab(model_tab, "LLM 모델")

        # 탭 2: 출력 스키마 설정
        schema_tab = QWidget()
        schema_layout = QVBoxLayout(schema_tab)

        schema_info = QLabel(
            "이미지 분석 시 LLM이 반환할 JSON 형식을 정의합니다.\n"
            f"설정 파일: {SCHEMA_FILE}"
        )
        schema_info.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
        schema_layout.addWidget(schema_info)

        # 스키마 편집기
        self.schema_edit = QTextEdit()
        self.schema_edit.setFont(QFont("Courier", 11))
        self.schema_edit.setPlaceholderText("JSON 스키마를 입력하세요...")
        schema_layout.addWidget(self.schema_edit)

        # 스키마 버튼들
        schema_btn_layout = QHBoxLayout()

        reset_schema_btn = QPushButton("기본값 복원")
        reset_schema_btn.clicked.connect(self._reset_schema)
        schema_btn_layout.addWidget(reset_schema_btn)

        validate_btn = QPushButton("JSON 검증")
        validate_btn.clicked.connect(self._validate_schema)
        schema_btn_layout.addWidget(validate_btn)

        schema_btn_layout.addStretch()
        schema_layout.addLayout(schema_btn_layout)

        tabs.addTab(schema_tab, "출력 스키마")

        layout.addWidget(tabs)

        # 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("저장")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _load_current_settings(self):
        """현재 설정 로드"""
        # 모델 선택
        model_id = self.settings.get("selected_model", "gemini-2.0-flash-exp")
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == model_id:
                self.model_combo.setCurrentIndex(i)
                break
        self._on_model_changed()

        # API 키 (설정 파일에 저장된 값만 표시, 환경변수는 실행 시 fallback으로 사용)
        gemini_key = self.settings.get("gemini_api_key", "")
        if gemini_key and gemini_key != "your-api-key-here":
            self.gemini_key_edit.setText(gemini_key)
        else:
            # 환경변수에 값이 있으면 placeholder로 힌트 표시
            env_gemini = os.getenv("GEMINI_API_KEY", "")
            if env_gemini:
                self.gemini_key_edit.setPlaceholderText("(.env에서 로드됨 - 변경하려면 입력)")

        openai_key = self.settings.get("openai_api_key", "")
        if openai_key:
            self.openai_key_edit.setText(openai_key)
        else:
            # 환경변수에 값이 있으면 placeholder로 힌트 표시
            env_openai = os.getenv("OPENAI_API_KEY", "")
            if env_openai:
                self.openai_key_edit.setPlaceholderText("(.env에서 로드됨 - 변경하려면 입력)")

        # Supabase 설정 (설정 파일에 저장된 값만 표시, 환경변수는 실행 시 fallback으로 사용)
        supabase_url = self.settings.get("supabase_url", "")
        if supabase_url:
            self.supabase_url_edit.setText(supabase_url)
        else:
            # 환경변수에 값이 있으면 placeholder로 힌트 표시
            env_url = os.getenv("SUPABASE_URL", "") or os.getenv("SUPABASE_PROJECT_URL", "")
            if env_url:
                self.supabase_url_edit.setPlaceholderText("(.env에서 로드됨 - 변경하려면 입력)")

        supabase_key = self.settings.get("supabase_key", "")
        if supabase_key:
            self.supabase_key_edit.setText(supabase_key)
        else:
            # 환경변수에 값이 있으면 placeholder로 힌트 표시
            env_key = os.getenv("SUPABASE_KEY", "") or os.getenv("SUPABASE_API_KEY", "")
            if env_key:
                self.supabase_key_edit.setPlaceholderText("(.env에서 로드됨 - 변경하려면 입력)")

        # 스키마
        self.schema_edit.setPlainText(json.dumps(self.schema, ensure_ascii=False, indent=2))

    def _on_model_changed(self):
        """모델 변경 시"""
        model_id = self.model_combo.currentData()
        model = get_model_by_id(model_id)
        if model:
            self.model_info_label.setText(
                f"Provider: {model.provider.upper()} | "
                f"Vision: {'✓' if model.supports_vision else '✗'} | "
                f"API Key: {model.api_key_env}"
            )

    def _toggle_key_visibility(self, edit: QLineEdit, btn: QPushButton):
        """API 키 표시/숨김 토글"""
        if btn.isChecked():
            edit.setEchoMode(QLineEdit.Normal)
            btn.setText("숨김")
        else:
            edit.setEchoMode(QLineEdit.Password)
            btn.setText("표시")

    def _reset_schema(self):
        """스키마 기본값 복원"""
        from .config import DEFAULT_OUTPUT_SCHEMA
        self.schema_edit.setPlainText(json.dumps(DEFAULT_OUTPUT_SCHEMA, ensure_ascii=False, indent=2))
        QMessageBox.information(self, "복원 완료", "기본 스키마로 복원되었습니다.")

    def _validate_schema(self):
        """JSON 스키마 검증"""
        try:
            json.loads(self.schema_edit.toPlainText())
            QMessageBox.information(self, "검증 성공", "유효한 JSON입니다.")
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "검증 실패", f"JSON 파싱 오류:\n{str(e)}")

    def _save_settings(self):
        """설정 저장"""
        # 스키마 검증
        try:
            new_schema = json.loads(self.schema_edit.toPlainText())
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "저장 실패", f"스키마 JSON 오류:\n{str(e)}")
            return

        # 설정 저장
        self.settings["selected_model"] = self.model_combo.currentData()
        self.settings["gemini_api_key"] = self.gemini_key_edit.text()
        self.settings["openai_api_key"] = self.openai_key_edit.text()
        self.settings["supabase_url"] = self.supabase_url_edit.text()
        self.settings["supabase_key"] = self.supabase_key_edit.text()

        # API 클라이언트 리셋 (설정 변경 반영)
        try:
            from .supabase_client import reset_supabase_client
            reset_supabase_client()
        except ImportError:
            pass
        try:
            from .gemini_api import reset_api_clients
            reset_api_clients()
        except ImportError:
            pass

        if save_settings(self.settings):
            # 스키마 저장
            if save_output_schema(new_schema):
                QMessageBox.information(self, "저장 완료", "설정이 저장되었습니다.")
                self.accept()
            else:
                QMessageBox.warning(self, "저장 실패", "스키마 저장에 실패했습니다.")
        else:
            QMessageBox.warning(self, "저장 실패", "설정 저장에 실패했습니다.")

    def get_settings(self) -> dict:
        """현재 설정 반환"""
        return self.settings

    def _test_supabase_connection(self):
        """Supabase 연결 테스트"""
        # 현재 입력값을 임시로 저장
        temp_url = self.supabase_url_edit.text()
        temp_key = self.supabase_key_edit.text()

        if not temp_url or not temp_key:
            self.supabase_status_label.setText("URL과 API Key를 입력하세요")
            self.supabase_status_label.setStyleSheet("color: orange; font-size: 11px;")
            return

        self.supabase_status_label.setText("연결 중...")
        self.supabase_status_label.setStyleSheet("color: gray; font-size: 11px;")
        self.supabase_test_btn.setEnabled(False)

        # UI 업데이트
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            from supabase import create_client

            # 임시 클라이언트로 테스트
            client = create_client(temp_url, temp_key)
            result = client.table("textbooks").select("id").limit(1).execute()

            self.supabase_status_label.setText("연결 성공!")
            self.supabase_status_label.setStyleSheet("color: green; font-size: 11px;")

        except ImportError:
            self.supabase_status_label.setText("supabase 패키지 필요: pip install supabase")
            self.supabase_status_label.setStyleSheet("color: red; font-size: 11px;")
        except Exception as e:
            error_msg = str(e)
            if "relation" in error_msg and "does not exist" in error_msg:
                self.supabase_status_label.setText("테이블 없음 - schema.sql 실행 필요")
            elif "Invalid" in error_msg:
                self.supabase_status_label.setText("잘못된 API Key")
            else:
                self.supabase_status_label.setText(f"오류: {error_msg[:30]}...")
            self.supabase_status_label.setStyleSheet("color: red; font-size: 11px;")

        self.supabase_test_btn.setEnabled(True)
