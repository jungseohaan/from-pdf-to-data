"""테마 관리 Mixin 모듈

PDFLabeler의 테마 CRUD 및 관련 기능을 분리한 Mixin 클래스
"""

import re
from typing import TYPE_CHECKING, Optional

from PyQt5.QtWidgets import QListWidgetItem, QMessageBox
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt

from .models import Theme

if TYPE_CHECKING:
    from .labeler import PDFLabeler


class ThemeManagerMixin:
    """테마 관리 기능을 제공하는 Mixin 클래스

    PDFLabeler에서 상속받아 사용합니다.
    self는 PDFLabeler 인스턴스를 참조합니다.
    """

    def get_theme_by_id(self: 'PDFLabeler', theme_id: str) -> Optional[Theme]:
        """ID로 테마 찾기"""
        for theme in self.themes:
            if theme.id == theme_id:
                return theme
        return None

    def _generate_theme_id(self: 'PDFLabeler') -> str:
        """새 테마 ID 생성"""
        self._theme_counter += 1
        return f"theme_{self._theme_counter}"

    def _natural_sort_key(self: 'PDFLabeler', text: str):
        """자연 정렬 키 (숫자를 숫자로 처리: 1, 2, 10 순)"""
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

    def _update_theme_list(self: 'PDFLabeler'):
        """테마 목록 UI 업데이트 (자연 정렬)"""
        self.theme_list.blockSignals(True)  # 시그널 임시 차단
        self.theme_list.clear()
        # 자연 정렬 (숫자 우선: 1, 2, 10 순, 삭제된 테마는 맨 아래)
        active_themes = sorted([t for t in self.themes if not t.deleted], key=lambda t: self._natural_sort_key(t.name))
        deleted_themes = sorted([t for t in self.themes if t.deleted], key=lambda t: self._natural_sort_key(t.name))
        sorted_themes = active_themes + deleted_themes
        for theme in sorted_themes:
            item = QListWidgetItem(theme.name)
            item.setData(Qt.UserRole, theme.id)
            item.setFlags(item.flags() | Qt.ItemIsEditable)  # 편집 가능
            if theme.deleted:
                # 삭제된 테마: 취소선 + 회색
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
                item.setForeground(QColor("#999999"))
            # 삭제되지 않은 테마는 기본 색상 (검정)
            self.theme_list.addItem(item)

        # 맨 아래에 항상 빈 입력 항목 추가
        new_item = QListWidgetItem("")
        new_item.setFlags(new_item.flags() | Qt.ItemIsEditable)
        new_item.setData(Qt.UserRole, "__new__")
        new_item.setForeground(QColor("#aaaaaa"))
        self.theme_list.addItem(new_item)

        self.theme_list.blockSignals(False)

    def _update_theme_combo(self: 'PDFLabeler'):
        """테마 콤보박스 업데이트 (삭제되지 않은 테마만)"""
        self.theme_combo.clear()
        self.theme_combo.addItem("(없음)", None)
        for theme in self.themes:
            if not theme.deleted:
                self.theme_combo.addItem(f"● {theme.name}", theme.id)

    def _toggle_theme_deleted(self: 'PDFLabeler'):
        """선택된 테마 삭제 토글 (삭제 표시/복원)"""
        current = self.theme_list.currentItem()
        if not current:
            QMessageBox.information(self, "안내", "삭제할 테마를 선택해주세요.")
            return

        theme_id = current.data(Qt.UserRole)
        theme = self.get_theme_by_id(theme_id)
        if not theme:
            return

        if theme.deleted:
            # 복원
            theme.deleted = False
            self.status_label.setText(f"테마 복원: {theme.name}")
        else:
            # 삭제 표시 - 해당 테마의 박스들은 미지정으로 변경
            theme.deleted = True
            # 이 테마에 속한 박스들의 원래 테마 ID를 저장하고 미지정으로 변경
            for page_idx, boxes in self.boxes.items():
                for box in boxes:
                    if box.theme_id == theme_id:
                        # 원래 테마 ID 저장 (복원 시 사용)
                        if not hasattr(box, '_original_theme_id'):
                            box._original_theme_id = None
                        box._original_theme_id = theme_id
                        box.theme_id = None
            self.status_label.setText(f"테마 삭제: {theme.name} (박스들은 미지정으로 이동)")

        self._update_theme_list()
        self._update_theme_combo()
        self._update_box_list()
        self.canvas.update()
        self._schedule_auto_save()

    def _add_theme(self: 'PDFLabeler'):
        """테마 추가 - 인라인 편집으로 시작"""
        new_item = QListWidgetItem("")
        new_item.setFlags(new_item.flags() | Qt.ItemIsEditable)
        new_item.setData(Qt.UserRole, None)  # 아직 ID 없음
        self.theme_list.addItem(new_item)
        self.theme_list.setCurrentItem(new_item)
        self.theme_list.editItem(new_item)

    def _edit_theme(self: 'PDFLabeler'):
        """선택된 테마 편집 - 인라인 편집 시작"""
        current = self.theme_list.currentItem()
        if current:
            self.theme_list.editItem(current)

    def _delete_theme(self: 'PDFLabeler'):
        """선택된 테마 삭제"""
        current = self.theme_list.currentItem()
        if not current:
            return

        theme_id = current.data(Qt.UserRole)
        theme = self.get_theme_by_id(theme_id)
        if not theme:
            return

        # 이 테마를 사용하는 박스가 있는지 확인
        using_count = sum(1 for _, box in self._sorted_boxes if box.theme_id == theme_id)
        if using_count > 0:
            reply = QMessageBox.question(
                self, "테마 삭제",
                f"이 테마를 사용하는 {using_count}개의 문항이 있습니다.\n삭제하면 연결이 해제됩니다. 계속하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

            # 연결 해제
            for _, box in self._sorted_boxes:
                if box.theme_id == theme_id:
                    box.theme_id = None

        self.themes.remove(theme)
        self._update_theme_list()
        self._update_theme_combo()
        self._update_box_list()
        self.canvas.update()
        self._schedule_auto_save()

    def _on_theme_select(self: 'PDFLabeler', item):
        """테마 목록에서 선택"""
        theme_id = item.data(Qt.UserRole)
        # 테마 변경 시 해설 연결 인덱스 리셋
        self._next_solution_link_idx = 0
        # 콤보박스에서 해당 테마 선택
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme_id:
                self.theme_combo.setCurrentIndex(i)
                break

    def _on_theme_double_click(self: 'PDFLabeler', item):
        """테마 목록 더블클릭 - 삭제된 테마는 복구, 아니면 인라인 편집"""
        if not item:
            return

        theme_id = item.data(Qt.UserRole)
        if theme_id:
            theme = self.get_theme_by_id(theme_id)
            if theme and theme.deleted:
                # 삭제된 테마 복구
                theme.deleted = False
                self._update_theme_list()
                self._update_theme_combo()
                self._update_box_list()
                self.canvas.update()
                self._schedule_auto_save()
                self.status_label.setText(f"테마 복구: {theme.name}")
                return

        # 일반 테마는 편집 모드
        self.theme_list.editItem(item)

    def _on_theme_item_changed(self: 'PDFLabeler', item):
        """테마 항목 편집 완료"""
        if not item:
            return
        theme_id = item.data(Qt.UserRole)
        new_name = item.text().strip()

        if theme_id and theme_id != "__new__":
            # 기존 테마 이름 수정
            theme = self.get_theme_by_id(theme_id)
            if theme and new_name:
                theme.name = new_name
                self._update_theme_combo()
                self._update_box_list()
                self.canvas.update()
                self._schedule_auto_save()
            elif not new_name:
                # 빈 이름이면 원래 이름으로 복원
                self._update_theme_list()
        else:
            # 새 테마 추가 완료 (theme_id가 None 또는 "__new__")
            if new_name:
                # 중복 체크
                for theme in self.themes:
                    if theme.name == new_name and not theme.deleted:
                        self.status_label.setText(f"이미 존재하는 테마: {new_name}")
                        self._update_theme_list()
                        return
                # 삭제된 동일 이름 테마가 있으면 복원
                for theme in self.themes:
                    if theme.name == new_name and theme.deleted:
                        theme.deleted = False
                        # 모든 테마 접고 새 테마만 펼치기
                        self.box_list._collapsed_themes = set(t.id for t in self.themes if not t.deleted and t.id != theme.id)
                        self.box_list._collapsed_themes.add("__none__")
                        self._update_theme_list()
                        self._update_theme_combo()
                        self._update_box_list()
                        self.status_label.setText(f"테마 복원: {new_name}")
                        self._schedule_auto_save()
                        return
                # 새 테마 생성
                colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#34495e"]
                color = colors[len(self.themes) % len(colors)]
                theme = Theme(
                    id=self._generate_theme_id(),
                    name=new_name,
                    color=color
                )
                self.themes.append(theme)
                # 모든 테마 접고 새 테마만 펼치기
                self.box_list._collapsed_themes = set(t.id for t in self.themes if not t.deleted and t.id != theme.id)
                self.box_list._collapsed_themes.add("__none__")
                self._update_theme_list()
                self._update_theme_combo()
                self._update_box_list()
                self._schedule_auto_save()
            else:
                # 빈 이름이면 항목 제거
                self._update_theme_list()

    def _on_box_dropped_to_theme(self: 'PDFLabeler', theme_id: str):
        """박스가 테마에 드롭됨"""
        # 현재 선택된 박스의 인덱스 가져오기
        list_idx = self.box_list.currentRow()
        if list_idx < 0 or list_idx >= len(self._box_index_map):
            return

        map_entry = self._box_index_map[list_idx]
        if map_entry is None:  # 헤더는 무시
            return

        page_idx, box = map_entry

        # 테마 할당
        old_theme_id = box.theme_id
        box.theme_id = theme_id

        # UI 업데이트
        self._update_box_list()
        if old_theme_id != theme_id:
            self._update_thumbnail_boxes(page_idx)
        self.canvas.update()
        self._schedule_auto_save()

        # 테마 콤보박스도 업데이트 (선택된 박스의 테마 반영)
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme_id:
                self.theme_combo.setCurrentIndex(i)
                break

        self.status_label.setText(f"박스가 테마에 할당됨")

    def _on_theme_selected_from_popup(self: 'PDFLabeler', list_rows: list, theme_id):
        """팝업 메뉴에서 테마 선택됨 (멀티 선택 지원)"""
        if not list_rows:
            return

        updated_pages = set()
        count = 0

        for list_row in list_rows:
            if list_row < 0 or list_row >= len(self._box_index_map):
                continue

            map_entry = self._box_index_map[list_row]
            if map_entry is None:  # 헤더는 무시
                continue

            page_idx, box = map_entry

            # 테마 할당
            if box.theme_id != theme_id:
                box.theme_id = theme_id
                updated_pages.add(page_idx)
                count += 1

        if count > 0:
            # UI 업데이트
            self._update_box_list()
            for page_idx in updated_pages:
                self._update_thumbnail_boxes(page_idx)
            self.canvas.update()
            self._schedule_auto_save()

            # 테마 이름 가져오기
            if theme_id:
                theme = self.get_theme_by_id(theme_id)
                theme_name = theme.name if theme else "알 수 없음"
            else:
                theme_name = "(없음)"
            self.status_label.setText(f"{count}개 박스 테마 변경: {theme_name}")

    def _on_theme_changed_by_drag(self: 'PDFLabeler', box_items: list, theme_id):
        """드래그앤드롭으로 테마 변경"""
        if not box_items:
            return

        self._save_state_for_undo()  # Undo용 상태 저장
        updated_pages = set()
        count = 0

        for page_idx, box in box_items:
            if box.theme_id != theme_id:
                box.theme_id = theme_id
                updated_pages.add(page_idx)
                count += 1

        if count > 0:
            # 테마 변경 후 정렬 다시 수행
            self._sorted_boxes.sort(key=lambda x: self._get_box_sort_key(x[0], x[1]))
            # 변경된 테마 펼침 상태로 만들기
            if theme_id:
                self.box_list._collapsed_themes.discard(theme_id)
            self._update_box_list()
            for page_idx in updated_pages:
                self._update_thumbnail_boxes(page_idx)
            self.canvas.update()
            self._schedule_auto_save()

            if theme_id:
                theme = self.get_theme_by_id(theme_id)
                theme_name = theme.name if theme else "알 수 없음"
            else:
                theme_name = "(없음)"
            self.status_label.setText(f"{count}개 박스 테마 이동: {theme_name}")
