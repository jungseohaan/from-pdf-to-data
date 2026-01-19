"""커스텀 위젯 모듈"""

import sys
import time
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import (
    QAbstractItemView, QListWidget, QMenu, QScrollArea
)
from PyQt5.QtGui import QColor, QDrag, QWheelEvent
from PyQt5.QtCore import Qt, QMimeData, pyqtSignal

from .models import BOX_TYPE_QUESTION, BOX_TYPE_SOLUTION


def get_poppler_path() -> Optional[str]:
    """PyInstaller 번들 또는 시스템에서 poppler 경로를 찾습니다."""
    if getattr(sys, 'frozen', False):
        bundle_dir = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(sys.executable).parent
        if sys.platform == 'darwin':
            resources_dir = bundle_dir.parent / 'Resources'
            if (resources_dir / 'pdftoppm').exists():
                return str(resources_dir)
        if (bundle_dir / 'pdftoppm').exists():
            return str(bundle_dir)
    return None


class ScrollAreaWithPageNav(QScrollArea):
    """스크롤 경계에서 페이지 이동을 지원하는 커스텀 스크롤 영역"""

    page_next = pyqtSignal()
    page_prev = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.at_bottom_count = 0
        self.at_top_count = 0
        self.scroll_threshold = 5
        self._last_scroll_time = 0
        self._scroll_timeout = 500

    def wheelEvent(self, event: QWheelEvent):
        """휠 이벤트 처리 - 경계에서 추가 스크롤 시 페이지 이동"""
        current_time = int(time.time() * 1000)

        if current_time - self._last_scroll_time > self._scroll_timeout:
            self.at_bottom_count = 0
            self.at_top_count = 0
        self._last_scroll_time = current_time

        scrollbar = self.verticalScrollBar()
        delta = event.angleDelta().y()

        at_top = scrollbar.value() == scrollbar.minimum()
        at_bottom = scrollbar.value() == scrollbar.maximum()

        if delta < 0:
            if at_bottom:
                self.at_bottom_count += 1
                self.at_top_count = 0
                if self.at_bottom_count >= self.scroll_threshold:
                    self.page_next.emit()
                    self.at_bottom_count = 0
                    scrollbar.setValue(scrollbar.minimum())
                    event.accept()
                    return
            else:
                self.at_bottom_count = 0

        elif delta > 0:
            if at_top:
                self.at_top_count += 1
                self.at_bottom_count = 0
                if self.at_top_count >= self.scroll_threshold:
                    self.page_prev.emit()
                    self.at_top_count = 0
                    scrollbar.setValue(scrollbar.maximum())
                    event.accept()
                    return
            else:
                self.at_top_count = 0

        super().wheelEvent(event)


class ThemeListWidget(QListWidget):
    """드롭을 지원하는 테마 목록 위젯"""

    box_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            item = self.itemAt(event.pos())
            if item and item.data(Qt.UserRole):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasText():
            item = self.itemAt(event.pos())
            if item:
                theme_id = item.data(Qt.UserRole)
                if theme_id:
                    self.box_dropped.emit(theme_id)
                    event.acceptProposedAction()
                    return
        event.ignore()


class BoxListWidget(QListWidget):
    """멀티 선택과 드래그를 지원하는 박스 목록 위젯"""

    theme_changed = pyqtSignal(list, object)
    theme_selected = pyqtSignal(list, object)
    type_changed = pyqtSignal(list, str)
    solution_linked = pyqtSignal(list, str)
    boxes_deleted = pyqtSignal(list)  # 삭제할 박스 리스트 [(page_idx, box), ...]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._parent_window = None
        self._collapsed_themes = set()
        self._dragging = False
        self._drag_start_pos = None
        self._highlighted_row = -1
        self._original_bg = None

    def set_parent_window(self, parent_window):
        self._parent_window = parent_window

    def _get_box_index_map(self):
        if self._parent_window and hasattr(self._parent_window, '_box_index_map'):
            return self._parent_window._box_index_map
        return []

    def _is_header_row(self, row):
        box_map = self._get_box_index_map()
        if 0 <= row < len(box_map):
            return box_map[row] is None
        return False

    def _get_selected_boxes(self):
        result = []
        box_map = self._get_box_index_map()
        for item in self.selectedItems():
            row = self.row(item)
            if 0 <= row < len(box_map) and box_map[row] is not None:
                result.append(box_map[row])
        return result

    def _get_theme_id_from_header(self, item):
        if not self._parent_window:
            return None
        header_text = item.text()
        if "(미지정)" in header_text:
            return None
        for theme in self._parent_window.themes:
            if theme.name in header_text:
                return theme.id
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if self._drag_start_pos is None:
            return

        if (event.pos() - self._drag_start_pos).manhattanLength() < 10:
            return

        selected_boxes = self._get_selected_boxes()
        if not selected_boxes:
            return

        self._dragging = True

        drag = QDrag(self)
        mime_data = QMimeData()

        box_ids = []
        for page_idx, box in selected_boxes:
            if box.box_id:
                box_ids.append(f"{page_idx}:{box.box_id}")

        mime_data.setData("application/x-boxlist", ",".join(box_ids).encode('utf-8'))
        drag.setMimeData(mime_data)

        drag.exec_(Qt.MoveAction)
        self._dragging = False

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if not item or not self._parent_window:
            super().mouseDoubleClickEvent(event)
            return

        row = self.row(item)

        if self._is_header_row(row):
            self._toggle_theme(item)
        else:
            selected_rows = [self.row(i) for i in self.selectedItems()
                           if not self._is_header_row(self.row(i))]
            if selected_rows:
                self._show_theme_popup(event.globalPos(), selected_rows)

    def _toggle_theme(self, header_item):
        if not self._parent_window:
            return

        header_text = header_item.text()
        theme_id = None

        if "(미지정)" in header_text:
            theme_id = "__none__"
        else:
            for theme in self._parent_window.themes:
                if theme.name in header_text:
                    theme_id = theme.id
                    break

        if theme_id:
            if theme_id in self._collapsed_themes:
                self._collapsed_themes.remove(theme_id)
            else:
                self._collapsed_themes.add(theme_id)
            self._parent_window._update_box_list()

    def _show_theme_popup(self, global_pos, rows):
        if not self._parent_window:
            return

        menu = QMenu(self)

        none_action = menu.addAction("(없음)")
        none_action.setData(None)
        menu.addSeparator()

        for theme in self._parent_window.themes:
            if not theme.deleted:
                action = menu.addAction(theme.name)
                action.setData(theme.id)

        action = menu.exec_(global_pos)
        if action:
            self.theme_selected.emit(rows, action.data())

    def _show_context_menu(self, pos):
        if not self._parent_window:
            return

        selected_boxes = self._get_selected_boxes()
        if not selected_boxes:
            return

        menu = QMenu(self)

        type_menu = menu.addMenu("타입 변경")
        question_action = type_menu.addAction("📝 문제")
        question_action.setData(BOX_TYPE_QUESTION)
        solution_action = type_menu.addAction("📖 해설")
        solution_action.setData(BOX_TYPE_SOLUTION)

        theme_menu = menu.addMenu("테마 변경")
        none_action = theme_menu.addAction("(없음)")
        none_action.setData(("theme", None))
        theme_menu.addSeparator()
        for theme in self._parent_window.themes:
            if not theme.deleted:
                action = theme_menu.addAction(theme.name)
                action.setData(("theme", theme.id))

        if len(selected_boxes) == 1:
            page_idx, box = selected_boxes[0]
            if box.box_type == BOX_TYPE_SOLUTION:
                menu.addSeparator()
                link_menu = menu.addMenu("문제 연결")

                unlink_action = link_menu.addAction("(연결 해제)")
                unlink_action.setData(("link", None))
                link_menu.addSeparator()

                questions = self._parent_window.get_questions_for_linking(box)
                for q_page_idx, q_box in questions:
                    label = f"p{q_page_idx + 1}"
                    if q_box.number:
                        label += f" #{q_box.number}"
                    if box.linked_box_id == q_box.box_id:
                        label = "✓ " + label
                    action = link_menu.addAction(label)
                    action.setData(("link", q_box.box_id))

        # 삭제 메뉴
        menu.addSeparator()
        count = len(selected_boxes)
        delete_action = menu.addAction(f"🗑️ 삭제 ({count}개)" if count > 1 else "🗑️ 삭제")
        delete_action.setData(("delete", selected_boxes))

        action = menu.exec_(self.mapToGlobal(pos))
        if action:
            data = action.data()
            if data in (BOX_TYPE_QUESTION, BOX_TYPE_SOLUTION):
                self.type_changed.emit(selected_boxes, data)
            elif isinstance(data, tuple) and data[0] == "theme":
                self.theme_changed.emit(selected_boxes, data[1])
            elif isinstance(data, tuple) and data[0] == "link":
                page_idx, box = selected_boxes[0]
                box.linked_box_id = data[1]
                self._parent_window._update_box_list()
                self._parent_window.canvas.update()
                self._parent_window._schedule_auto_save()
                if data[1]:
                    self._parent_window.status_label.setText("문제 연결됨")
                else:
                    self._parent_window.status_label.setText("문제 연결 해제됨")
            elif isinstance(data, tuple) and data[0] == "delete":
                self.boxes_deleted.emit(data[1])

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-boxlist"):
            self._highlighted_row = -1
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not event.mimeData().hasFormat("application/x-boxlist"):
            event.ignore()
            return

        if hasattr(self, '_highlighted_row') and self._highlighted_row >= 0:
            old_item = self.item(self._highlighted_row)
            if old_item and hasattr(self, '_original_bg'):
                old_item.setBackground(self._original_bg)
            self._highlighted_row = -1

        item = self.itemAt(event.pos())
        if item:
            row = self.row(item)
            box_map = self._get_box_index_map()

            if self._is_header_row(row):
                self._original_bg = item.background()
                self._highlighted_row = row
                item.setBackground(QColor("#90EE90"))
                event.acceptProposedAction()
                return

            if 0 <= row < len(box_map) and box_map[row] is not None:
                _, target_box = box_map[row]
                if target_box.box_type == "question":
                    dragged_boxes = self._get_selected_boxes()
                    all_solutions = dragged_boxes and all(b.box_type == "solution" for _, b in dragged_boxes)
                    if all_solutions:
                        self._original_bg = item.background()
                        self._highlighted_row = row
                        item.setBackground(QColor("#87CEEB"))
                        event.acceptProposedAction()
                        return

        event.ignore()

    def dragLeaveEvent(self, event):
        if hasattr(self, '_highlighted_row') and self._highlighted_row >= 0:
            old_item = self.item(self._highlighted_row)
            if old_item and hasattr(self, '_original_bg'):
                old_item.setBackground(self._original_bg)
            self._highlighted_row = -1
        event.accept()

    def _get_theme_id_for_row(self, row):
        box_map = self._get_box_index_map()
        if row < 0 or row >= len(box_map):
            return None

        if box_map[row] is None:
            item = self.item(row)
            return self._get_theme_id_from_header(item) if item else None

        for i in range(row, -1, -1):
            if box_map[i] is None:
                item = self.item(i)
                return self._get_theme_id_from_header(item) if item else None

        return None

    def dropEvent(self, event):
        if hasattr(self, '_highlighted_row') and self._highlighted_row >= 0:
            old_item = self.item(self._highlighted_row)
            if old_item and hasattr(self, '_original_bg'):
                old_item.setBackground(self._original_bg)
            self._highlighted_row = -1

        if not event.mimeData().hasFormat("application/x-boxlist"):
            event.ignore()
            return

        if not self._parent_window:
            event.ignore()
            return

        item = self.itemAt(event.pos())
        if not item:
            event.ignore()
            return

        row = self.row(item)

        data = event.mimeData().data("application/x-boxlist").data().decode('utf-8')
        box_items = []

        for item_str in data.split(","):
            if ":" not in item_str:
                continue
            page_str, box_id = item_str.split(":", 1)
            try:
                page_idx = int(page_str)
                box = self._parent_window.get_box_by_id(box_id)
                if box:
                    box_items.append((page_idx, box))
            except ValueError:
                continue

        if not box_items:
            event.ignore()
            return

        box_map = self._get_box_index_map()
        target_entry = box_map[row] if 0 <= row < len(box_map) else None

        if target_entry is not None:
            target_page_idx, target_box = target_entry
            if target_box.box_type == "question":
                all_solutions = all(b.box_type == "solution" for _, b in box_items)
                if all_solutions:
                    self.solution_linked.emit(box_items, target_box.box_id)
                    event.acceptProposedAction()
                    return

        target_theme_id = self._get_theme_id_for_row(row)
        self.theme_changed.emit(box_items, target_theme_id)
        event.acceptProposedAction()
