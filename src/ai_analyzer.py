"""AI 분석 Mixin 모듈

PDFLabeler의 AI 분석 관련 기능을 분리한 Mixin 클래스
"""

from typing import TYPE_CHECKING
from PIL import Image

from PyQt5.QtWidgets import (
    QProgressDialog, QMessageBox, QDialog
)
from PyQt5.QtCore import Qt

from .models import BOX_TYPE_QUESTION, BOX_TYPE_SOLUTION, QuestionBox
from .config import load_settings, get_model_by_id
from .gemini_api import (
    crop_box_image,
    LLMAnalysisThread, GeminiAnalysisThread,
    extract_graph_images, AnalysisResultDialog,
    get_gemini_client, get_openai_client
)

if TYPE_CHECKING:
    from .labeler import PDFLabeler


class AIAnalyzerMixin:
    """AI 분석 관련 기능을 제공하는 Mixin 클래스

    PDFLabeler에서 상속받아 사용합니다.
    self는 PDFLabeler 인스턴스를 참조합니다.
    """

    def _auto_analyze_box(self: 'PDFLabeler', box: QuestionBox):
        """박스 자동 AI 분석"""
        if not self.pages or self.current_page_idx >= len(self.pages):
            return

        page_image = self.pages[self.current_page_idx]
        box_image = crop_box_image(page_image, box)

        # 테마 이름 가져오기
        theme_name = "미지정"
        if box.theme_id:
            theme = self.get_theme_by_id(box.theme_id)
            if theme:
                theme_name = theme.name

        box_type_str = "question" if box.box_type == BOX_TYPE_QUESTION else "solution"

        # 프로그레스 다이얼로그 표시
        self._auto_progress = QProgressDialog("AI가 이미지를 분석하고 있습니다...", "취소", 0, 0, self)
        self._auto_progress.setWindowTitle("AI 분석")
        self._auto_progress.setWindowModality(Qt.WindowModal)
        self._auto_progress.setMinimumDuration(0)
        self._auto_progress.show()
        from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()

        # 백그라운드 스레드로 분석
        self._analysis_thread = LLMAnalysisThread(box_image, box_type_str, theme_name)
        self._analysis_thread.analysis_finished.connect(
            lambda result: self._on_auto_analysis_finished(box, box_image, result)
        )
        self._analysis_thread.analysis_error.connect(
            lambda err: self._on_auto_analysis_error(box, err)
        )
        self._analysis_thread.start()

    def _on_auto_analysis_finished(self: 'PDFLabeler', box: QuestionBox, box_image: Image.Image, result: dict):
        """자동 AI 분석 완료"""
        # 프로그레스 다이얼로그 닫기
        if hasattr(self, '_auto_progress') and self._auto_progress:
            self._auto_progress.close()
            self._auto_progress = None

        # 그래프 이미지 추출 (base64로)
        result = extract_graph_images(box_image, result)

        # 박스에 AI 결과 저장
        box.ai_result = result

        # 문제 번호 자동 설정
        q_num = result.get("question_number")
        if q_num and not box.number:
            box.number = str(q_num)

        self._update_box_list()
        self._schedule_auto_save()
        self._update_review_button_state()

        # 분석 결과 팝업 표시 (모달리스)
        dialog = AnalysisResultDialog(result, box_image, self)

        # 결과 저장 시그널 연결
        def on_result_saved(updated_result):
            box.ai_result = updated_result
            self._schedule_auto_save()

        dialog.result_saved.connect(on_result_saved)
        dialog.show()

    def _on_auto_analysis_error(self: 'PDFLabeler', box: QuestionBox, error: str):
        """자동 AI 분석 에러"""
        # 프로그레스 다이얼로그 닫기
        if hasattr(self, '_auto_progress') and self._auto_progress:
            self._auto_progress.close()
            self._auto_progress = None

        QMessageBox.warning(self, "AI 분석 실패", f"분석 중 오류가 발생했습니다:\n{error}")

    def _analyze_selected_box(self: 'PDFLabeler'):
        """선택된 박스를 AI로 분석"""
        import sys
        print(f"[DEBUG] _analyze_selected_box 호출됨 (Cmd+G)", file=sys.stderr, flush=True)

        # 현재 선택된 모델 확인
        settings = load_settings()
        model_id = settings.get("selected_model", "gemini-2.0-flash-exp")
        model_info = get_model_by_id(model_id)

        if not model_info:
            QMessageBox.warning(self, "모델 오류", f"알 수 없는 모델: {model_id}")
            return

        # API 키 확인 (선택된 모델의 provider에 따라)
        if model_info.provider == "gemini":
            if not get_gemini_client():
                QMessageBox.warning(
                    self, "API 키 필요",
                    "Gemini API 키가 설정되지 않았습니다.\n\n"
                    "설정 메뉴에서 API 키를 입력하거나\n"
                    ".env 파일에 GEMINI_API_KEY를 설정하세요."
                )
                return
        elif model_info.provider == "openai":
            if not get_openai_client():
                QMessageBox.warning(
                    self, "API 키 필요",
                    "OpenAI API 키가 설정되지 않았습니다.\n\n"
                    "설정 메뉴에서 API 키를 입력하거나\n"
                    ".env 파일에 OPENAI_API_KEY를 설정하세요."
                )
                return

        # 선택된 박스 확인
        selected_items = self.box_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "박스 선택", "분석할 박스를 선택하세요.")
            return

        # 박스 정보 가져오기
        row = self.box_list.row(selected_items[0])
        if row < 0 or row >= len(self._box_index_map):
            return

        page_idx, box = self._box_index_map[row]

        # 해당 페이지 이미지 가져오기
        if page_idx >= len(self.pages):
            QMessageBox.warning(self, "오류", "페이지 이미지를 찾을 수 없습니다.")
            return

        page_image = self.pages[page_idx]

        # 박스 영역 크롭
        cropped = crop_box_image(page_image, box)

        # 테마 이름 가져오기
        theme_name = None
        if box.theme_id:
            for theme in self.themes:
                if theme.id == box.theme_id:
                    theme_name = theme.name
                    break

        # 프로그레스 다이얼로그 표시
        progress = QProgressDialog("AI가 이미지를 분석하고 있습니다...", "취소", 0, 0, self)
        progress.setWindowTitle("AI 분석 중")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()

        # 분석 스레드 저장 (가비지 컬렉션 방지)
        self._analysis_thread = GeminiAnalysisThread(cropped, box.box_type, theme_name)
        self._analysis_cropped_image = cropped  # 결과 다이얼로그용

        def on_finished(result):
            progress.close()
            # 박스에 AI 결과 저장
            box.ai_result = result
            self._update_box_list()
            self._schedule_auto_save()
            self._update_review_button_state()

            # 모달리스 다이얼로그 표시
            dialog = AnalysisResultDialog(result, self._analysis_cropped_image, self)

            def on_result_saved(updated_result):
                box.ai_result = updated_result
                self._schedule_auto_save()

            dialog.result_saved.connect(on_result_saved)
            dialog.show()

        def on_error(error_msg):
            progress.close()
            QMessageBox.critical(self, "분석 실패", f"AI 분석 중 오류가 발생했습니다:\n\n{error_msg}")

        self._analysis_thread.analysis_finished.connect(on_finished)
        self._analysis_thread.analysis_error.connect(on_error)

        # 취소 처리
        def on_canceled():
            if self._analysis_thread.isRunning():
                self._analysis_thread.terminate()

        progress.canceled.connect(on_canceled)

        # 분석 시작
        self._analysis_thread.start()

    def _merge_solutions_to_questions(self: 'PDFLabeler') -> int:
        """해설 분석 결과를 연결된 문제에 통합

        Returns:
            통합된 문제 수
        """
        merged_count = 0

        # 문제 박스 ID -> 문제 박스 매핑
        question_boxes = {}
        for boxes in self.boxes.values():
            for box in boxes:
                if box.box_type == BOX_TYPE_QUESTION:
                    question_boxes[box.id] = box

        # 해설 박스 순회
        for boxes in self.boxes.values():
            for box in boxes:
                if box.box_type != BOX_TYPE_SOLUTION:
                    continue

                # 연결된 문제 찾기
                if not box.linked_box_id:
                    continue

                linked_question = question_boxes.get(box.linked_box_id)
                if not linked_question:
                    continue

                # 해설의 분석 결과가 있는지 확인
                if not box.ai_result:
                    continue

                # 문제의 분석 결과가 있는지 확인
                if not linked_question.ai_result:
                    continue

                # 해설 정보 추출
                solution_content = box.ai_result.get("content", {})
                solution_info = {
                    "solution_text": solution_content.get("solution_text", ""),
                    "answer": solution_content.get("answer", ""),
                    "key_concepts": solution_content.get("key_concepts", []),
                    "graphs": solution_content.get("graphs", [])
                }

                # 문제에 해설 정보 추가/병합
                question_result = linked_question.ai_result
                if "solutions" not in question_result:
                    question_result["solutions"] = []

                # 기존 해설 목록에 추가 (같은 박스 ID가 있으면 교체)
                existing_idx = None
                for i, sol in enumerate(question_result["solutions"]):
                    if sol.get("box_id") == box.id:
                        existing_idx = i
                        break

                solution_info["box_id"] = box.id
                if existing_idx is not None:
                    question_result["solutions"][existing_idx] = solution_info
                else:
                    question_result["solutions"].append(solution_info)

                merged_count += 1

        return merged_count
