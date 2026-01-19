"""저장/로드 Mixin 모듈

PDFLabeler의 저장, 로드, 자동 저장 및 Undo 기능을 분리한 Mixin 클래스
"""

import json
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from .models import QuestionBox
from .utils import (
    load_themes_from_data, load_box_from_data, create_save_data,
    safe_file_write, safe_file_read
)

if TYPE_CHECKING:
    from .labeler import PDFLabeler


class PersistenceMixin:
    """저장/로드 관련 기능을 제공하는 Mixin 클래스

    PDFLabeler에서 상속받아 사용합니다.
    self는 PDFLabeler 인스턴스를 참조합니다.
    """

    def _schedule_auto_save(self: 'PDFLabeler'):
        """자동 저장 예약 (변경 후 2초 뒤 저장)"""
        if not self.pdf_path:
            return
        self._auto_save_pending = True
        self._auto_save_timer.start(2000)  # 2초 후 저장

    def _do_auto_save(self: 'PDFLabeler'):
        """실제 자동 저장 수행 (두 벌 백업)"""
        if not self.pdf_path or not self._auto_save_pending:
            return

        works_dir = self._get_works_dir()
        if not works_dir:
            return

        try:
            works_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.status_label.setText(f"자동 저장 실패: {e}")
            return

        save_path = self._get_auto_save_path()
        backup_path = self._get_backup_path()

        data = create_save_data(self.pdf_path.name, self.themes, self._sorted_boxes)
        json_str = json.dumps(data, ensure_ascii=False, indent=2)

        if safe_file_write(save_path, json_str, backup_path):
            self._auto_save_pending = False
            self.status_label.setText(f"자동 저장됨 ({len(self._sorted_boxes)}개 박스)")
        else:
            self.status_label.setText("자동 저장 실패")

    def _load_auto_saved_data(self: 'PDFLabeler'):
        """자동 저장된 데이터 로드"""
        save_path = self._get_auto_save_path()
        backup_path = self._get_backup_path()

        data = safe_file_read(save_path, backup_path)
        if data is None:
            return False

        # 테마 로드
        self.themes, self._theme_counter = load_themes_from_data(data.get("themes", []))
        self._update_theme_list()
        self._update_theme_combo()

        # 박스 데이터 로드
        self.boxes = {i: [] for i in range(len(self.pages))}
        self._sorted_boxes = []

        boxes_data = sorted(data.get("boxes", []), key=lambda x: x.get('_sort_order', 0))

        for box_data in boxes_data:
            page_idx = box_data.get("page", 1) - 1
            if 0 <= page_idx < len(self.pages):
                box, counter = load_box_from_data(box_data, self._generate_box_id)
                self._box_counter = max(self._box_counter, counter)
                self.boxes[page_idx].append(box)
                self._sorted_boxes.append((page_idx, box))

        self._update_thumbnail_boxes()
        self._update_review_button_state()
        self.status_label.setText(f"자동 저장 데이터 로드됨 ({len(self._sorted_boxes)}개 박스, {len(self.themes)}개 테마)")
        return True

    def _save_state_for_undo(self: 'PDFLabeler'):
        """현재 상태를 Undo용으로 저장"""
        # 박스 상태 깊은 복사
        boxes_copy = {}
        for page_idx, boxes in self.boxes.items():
            boxes_copy[page_idx] = [
                QuestionBox(
                    x1=b.x1, y1=b.y1, x2=b.x2, y2=b.y2,
                    number=b.number, theme_id=b.theme_id, page=b.page,
                    box_type=b.box_type, linked_box_id=b.linked_box_id, box_id=b.box_id
                ) for b in boxes
            ]
        self._undo_state = {
            'boxes': boxes_copy,
            'box_counter': self._box_counter
        }

    def _undo(self: 'PDFLabeler'):
        """마지막 작업 되돌리기"""
        if self._undo_state is None:
            self.status_label.setText("되돌릴 작업이 없습니다")
            return

        # 상태 복원
        self.boxes = self._undo_state['boxes']
        self._box_counter = self._undo_state['box_counter']
        self._undo_state = None

        # 정렬 목록 재구성
        self._sorted_boxes = []
        for page_idx, boxes in self.boxes.items():
            for box in boxes:
                self._sorted_boxes.append((page_idx, box))
        self._sorted_boxes.sort(key=lambda x: self._get_box_sort_key(x[0], x[1]))

        # UI 갱신
        self._update_box_list()
        self.canvas.update()
        self._refresh_all_thumbnails()
        self._schedule_auto_save()
        self.status_label.setText("작업이 되돌려졌습니다")

    def _save_labels(self: 'PDFLabeler'):
        """레이블 저장"""
        if not self.pdf_path:
            QMessageBox.warning(self, "경고", "PDF 파일이 열려있지 않습니다.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "레이블 저장", f"{self.pdf_path.stem}_labels.json",
            "JSON files (*.json)"
        )
        if not file_path:
            return

        all_boxes = []
        for page_idx, boxes in self.boxes.items():
            for box in boxes:
                all_boxes.append(box.to_dict())

        data = {
            "source_pdf": self.pdf_path.name,
            "created_at": datetime.now().isoformat(),
            "total_boxes": len(all_boxes),
            "boxes": all_boxes
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.status_label.setText(f"저장 완료: {Path(file_path).name}")
        QMessageBox.information(self, "저장 완료", f"{len(all_boxes)}개 박스가 저장되었습니다.")

    def _load_labels(self: 'PDFLabeler'):
        """레이블 불러오기"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "레이블 불러오기", "", "JSON files (*.json)"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 테마 로드
            if "themes" in data:
                self.themes, self._theme_counter = load_themes_from_data(data.get("themes", []))
                self._update_theme_list()
                self._update_theme_combo()

            # 박스 로드
            self.boxes = {i: [] for i in range(len(self.pages))}
            self._box_counter = 0
            for box_data in data.get("boxes", []):
                page_idx = box_data.get("page", 1) - 1
                if 0 <= page_idx < len(self.pages):
                    box, counter = load_box_from_data(box_data, self._generate_box_id)
                    self._box_counter = max(self._box_counter, counter)
                    self.boxes[page_idx].append(box)

            self._rebuild_sorted_boxes()
            self._display_page()
            self._update_review_button_state()
            self.status_label.setText(f"불러오기 완료: {len(data.get('boxes', []))}개 박스")

        except Exception as e:
            QMessageBox.critical(self, "오류", f"불러오기 실패: {e}")
