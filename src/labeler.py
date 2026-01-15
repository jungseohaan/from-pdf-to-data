"""PDF 문항 수작업 박싱 및 레이블링 도구 (PyQt5)"""

import json
import sys
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass, asdict
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QListWidget, QFileDialog,
    QMessageBox, QScrollArea, QGroupBox, QSplitter,
    QMenuBar, QMenu, QAction, QComboBox, QInputDialog, QColorDialog,
    QListWidgetItem, QAbstractItemView, QWidgetAction
)
from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QImage, QWheelEvent, QIcon, QDrag
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QSettings, QTimer, QMimeData

from PIL import Image
from pdf2image import convert_from_path


@dataclass
class Theme:
    """테마/단원 정보"""
    id: str
    name: str
    color: str = "#3498db"  # 기본 파란색
    deleted: bool = False  # 삭제 표시 (실제 삭제 아님)

    def to_dict(self) -> dict:
        return asdict(self)


# 박스 유형 상수
BOX_TYPE_QUESTION = "question"  # 문제
BOX_TYPE_SOLUTION = "solution"  # 풀이


@dataclass
class QuestionBox:
    """문항 박스 정보"""
    x1: int
    y1: int
    x2: int
    y2: int
    number: Optional[int] = None
    theme_id: Optional[str] = None  # 테마 ID로 연결
    page: int = 1
    box_type: str = BOX_TYPE_QUESTION  # 문제 또는 풀이
    linked_box_id: Optional[str] = None  # 연결된 박스 ID (풀이→문제)
    box_id: Optional[str] = None  # 고유 ID

    def to_dict(self) -> dict:
        return asdict(self)


class ScrollAreaWithPageNav(QScrollArea):
    """스크롤 경계에서 페이지 이동을 지원하는 커스텀 스크롤 영역"""

    page_next = pyqtSignal()
    page_prev = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.at_bottom_count = 0
        self.at_top_count = 0
        self.scroll_threshold = 5  # 5번 연속 스크롤 시 페이지 이동 (민감도 낮춤)
        self._last_scroll_time = 0
        self._scroll_timeout = 500  # 500ms 내에 스크롤해야 카운트 유지

    def wheelEvent(self, event: QWheelEvent):
        """휠 이벤트 처리 - 경계에서 추가 스크롤 시 페이지 이동"""
        import time
        current_time = int(time.time() * 1000)

        # 시간 초과 시 카운트 리셋
        if current_time - self._last_scroll_time > self._scroll_timeout:
            self.at_bottom_count = 0
            self.at_top_count = 0
        self._last_scroll_time = current_time

        scrollbar = self.verticalScrollBar()
        delta = event.angleDelta().y()

        at_top = scrollbar.value() == scrollbar.minimum()
        at_bottom = scrollbar.value() == scrollbar.maximum()

        # 아래로 스크롤 (delta < 0)
        if delta < 0:
            if at_bottom:
                self.at_bottom_count += 1
                self.at_top_count = 0
                if self.at_bottom_count >= self.scroll_threshold:
                    self.page_next.emit()
                    self.at_bottom_count = 0
                    # 다음 페이지로 이동 후 맨 위로
                    scrollbar.setValue(scrollbar.minimum())
                    event.accept()
                    return
            else:
                self.at_bottom_count = 0

        # 위로 스크롤 (delta > 0)
        elif delta > 0:
            if at_top:
                self.at_top_count += 1
                self.at_bottom_count = 0
                if self.at_top_count >= self.scroll_threshold:
                    self.page_prev.emit()
                    self.at_top_count = 0
                    # 이전 페이지로 이동 후 맨 아래로
                    scrollbar.setValue(scrollbar.maximum())
                    event.accept()
                    return
            else:
                self.at_top_count = 0

        # 기본 스크롤 동작
        super().wheelEvent(event)


class ThemeListWidget(QListWidget):
    """드롭을 지원하는 테마 목록 위젯"""

    box_dropped = pyqtSignal(str)  # theme_id를 전달

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        """드래그 진입 시"""
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """드래그 이동 중 - 테마 항목 위에서만 허용"""
        if event.mimeData().hasText():
            item = self.itemAt(event.pos())
            if item and item.data(Qt.UserRole):  # 테마 ID가 있는 항목만
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event):
        """드롭 시 - 테마에 박스 할당"""
        if event.mimeData().hasText():
            item = self.itemAt(event.pos())
            if item:
                theme_id = item.data(Qt.UserRole)
                if theme_id:
                    # 드롭된 박스 인덱스 전달
                    self.box_dropped.emit(theme_id)
                    event.acceptProposedAction()
                    return
        event.ignore()


class BoxListWidget(QListWidget):
    """멀티 선택과 드래그를 지원하는 박스 목록 위젯"""

    # 테마 변경 시그널: (box_items: list of (page_idx, box), theme_id)
    theme_changed = pyqtSignal(list, object)
    # 테마 선택 시그널 (더블클릭 팝업용): (list_rows, theme_id)
    theme_selected = pyqtSignal(list, object)
    # 타입 변경 시그널: (box_items: list of (page_idx, box), box_type)
    type_changed = pyqtSignal(list, str)
    # 해설 연결 시그널: (solution_items: list of (page_idx, box), question_box_id)
    solution_linked = pyqtSignal(list, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAcceptDrops(True)  # 드롭 허용
        self.viewport().setAcceptDrops(True)  # viewport도 드롭 허용
        self.setContextMenuPolicy(Qt.CustomContextMenu)  # 우클릭 메뉴
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._parent_window = None
        self._collapsed_themes = set()
        self._dragging = False
        self._drag_start_pos = None
        self._highlighted_row = -1
        self._original_bg = None

    def set_parent_window(self, parent_window):
        """부모 윈도우 설정"""
        self._parent_window = parent_window

    def _get_box_index_map(self):
        """안전하게 _box_index_map 가져오기"""
        if self._parent_window and hasattr(self._parent_window, '_box_index_map'):
            return self._parent_window._box_index_map
        return []

    def _is_header_row(self, row):
        """해당 행이 테마 헤더인지 확인"""
        box_map = self._get_box_index_map()
        if 0 <= row < len(box_map):
            return box_map[row] is None
        return False

    def _get_selected_boxes(self):
        """선택된 박스들 반환 (헤더 제외) - (page_idx, box) 튜플 리스트"""
        result = []
        box_map = self._get_box_index_map()
        for item in self.selectedItems():
            row = self.row(item)
            if 0 <= row < len(box_map) and box_map[row] is not None:
                result.append(box_map[row])
        return result

    def _get_theme_id_from_header(self, item):
        """헤더 아이템에서 테마 ID 추출"""
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
        """마우스 누름 - 드래그 시작점 기록 (Shift 멀티 선택 지원)"""
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.pos()
            self._dragging = False
        # 기본 동작 수행 (Shift/Ctrl 멀티 선택 포함)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """마우스 이동 - 드래그 시작"""
        if not (event.buttons() & Qt.LeftButton):
            return
        if self._drag_start_pos is None:
            return

        # 최소 드래그 거리
        if (event.pos() - self._drag_start_pos).manhattanLength() < 10:
            return

        # 선택된 박스가 있어야 드래그 가능
        selected_boxes = self._get_selected_boxes()
        if not selected_boxes:
            return

        self._dragging = True

        # QDrag 생성
        drag = QDrag(self)
        mime_data = QMimeData()

        # 박스 정보를 직렬화 (page_idx, box_id)
        box_ids = []
        for page_idx, box in selected_boxes:
            if box.box_id:
                box_ids.append(f"{page_idx}:{box.box_id}")

        mime_data.setData("application/x-boxlist", ",".join(box_ids).encode('utf-8'))
        drag.setMimeData(mime_data)

        # 드래그 실행
        drag.exec_(Qt.MoveAction)
        self._dragging = False

    def mouseReleaseEvent(self, event):
        """마우스 릴리즈"""
        self._drag_start_pos = None
        self._dragging = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        """더블클릭: 헤더면 접기/펼치기, 박스면 테마 선택 팝업"""
        item = self.itemAt(event.pos())
        if not item or not self._parent_window:
            super().mouseDoubleClickEvent(event)
            return

        row = self.row(item)

        if self._is_header_row(row):
            # 테마 헤더 클릭 - 접기/펼치기
            self._toggle_theme(item)
        else:
            # 박스 클릭 - 테마 선택 팝업
            selected_rows = [self.row(i) for i in self.selectedItems()
                           if not self._is_header_row(self.row(i))]
            if selected_rows:
                self._show_theme_popup(event.globalPos(), selected_rows)

    def _toggle_theme(self, header_item):
        """테마 접기/펼치기"""
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
        """테마 선택 팝업"""
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
        """우클릭 컨텍스트 메뉴"""
        if not self._parent_window:
            return

        # 선택된 박스들
        selected_boxes = self._get_selected_boxes()
        if not selected_boxes:
            return

        menu = QMenu(self)

        # 타입 변경 서브메뉴
        type_menu = menu.addMenu("타입 변경")
        question_action = type_menu.addAction("📝 문제")
        question_action.setData(BOX_TYPE_QUESTION)
        solution_action = type_menu.addAction("📖 해설")
        solution_action.setData(BOX_TYPE_SOLUTION)

        # 테마 변경 서브메뉴
        theme_menu = menu.addMenu("테마 변경")
        none_action = theme_menu.addAction("(없음)")
        none_action.setData(("theme", None))
        theme_menu.addSeparator()
        for theme in self._parent_window.themes:
            if not theme.deleted:
                action = theme_menu.addAction(theme.name)
                action.setData(("theme", theme.id))

        # 해설인 경우 문제 연결 메뉴 추가
        # 선택된 박스가 하나이고 해설 타입인 경우
        if len(selected_boxes) == 1:
            page_idx, box = selected_boxes[0]
            if box.box_type == BOX_TYPE_SOLUTION:
                menu.addSeparator()
                link_menu = menu.addMenu("문제 연결")

                # 연결 해제 옵션
                unlink_action = link_menu.addAction("(연결 해제)")
                unlink_action.setData(("link", None))
                link_menu.addSeparator()

                # 문제 목록 (같은 테마 내의 문제들)
                questions = self._parent_window.get_questions_for_linking(box)
                for q_page_idx, q_box in questions:
                    label = f"p{q_page_idx + 1}"
                    if q_box.number:
                        label += f" #{q_box.number}"
                    # 현재 연결된 문제 표시
                    if box.linked_box_id == q_box.box_id:
                        label = "✓ " + label
                    action = link_menu.addAction(label)
                    action.setData(("link", q_box.box_id))

        # 메뉴 실행
        action = menu.exec_(self.mapToGlobal(pos))
        if action:
            data = action.data()
            if data in (BOX_TYPE_QUESTION, BOX_TYPE_SOLUTION):
                # 타입 변경
                self.type_changed.emit(selected_boxes, data)
            elif isinstance(data, tuple) and data[0] == "theme":
                # 테마 변경
                self.theme_changed.emit(selected_boxes, data[1])
            elif isinstance(data, tuple) and data[0] == "link":
                # 문제 연결
                page_idx, box = selected_boxes[0]
                box.linked_box_id = data[1]
                self._parent_window._update_box_list()
                self._parent_window.canvas.update()
                self._parent_window._schedule_auto_save()
                if data[1]:
                    self._parent_window.status_label.setText("문제 연결됨")
                else:
                    self._parent_window.status_label.setText("문제 연결 해제됨")

    def dragEnterEvent(self, event):
        """드래그 진입"""
        if event.mimeData().hasFormat("application/x-boxlist"):
            self._highlighted_row = -1
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """드래그 이동 - 테마 헤더 또는 문제 박스 위에서 허용, 하이라이트 표시"""
        if not event.mimeData().hasFormat("application/x-boxlist"):
            event.ignore()
            return

        # 이전 하이라이트 제거
        if hasattr(self, '_highlighted_row') and self._highlighted_row >= 0:
            old_item = self.item(self._highlighted_row)
            if old_item and hasattr(self, '_original_bg'):
                old_item.setBackground(self._original_bg)
            self._highlighted_row = -1

        item = self.itemAt(event.pos())
        if item:
            row = self.row(item)
            box_map = self._get_box_index_map()

            # 테마 헤더 위에서 드롭 허용
            if self._is_header_row(row):
                self._original_bg = item.background()
                self._highlighted_row = row
                item.setBackground(QColor("#90EE90"))  # 연한 초록색
                event.acceptProposedAction()
                return

            # 문제 박스 위에서 해설 드롭 허용
            if 0 <= row < len(box_map) and box_map[row] is not None:
                _, target_box = box_map[row]
                if target_box.box_type == "question":
                    # 드래그 중인 항목이 해설인지 확인
                    dragged_boxes = self._get_selected_boxes()
                    all_solutions = dragged_boxes and all(b.box_type == "solution" for _, b in dragged_boxes)
                    if all_solutions:
                        self._original_bg = item.background()
                        self._highlighted_row = row
                        item.setBackground(QColor("#87CEEB"))  # 연한 파란색 (해설→문제 연결)
                        event.acceptProposedAction()
                        return

        event.ignore()

    def dragLeaveEvent(self, event):
        """드래그 영역 벗어남 - 하이라이트 제거"""
        if hasattr(self, '_highlighted_row') and self._highlighted_row >= 0:
            old_item = self.item(self._highlighted_row)
            if old_item and hasattr(self, '_original_bg'):
                old_item.setBackground(self._original_bg)
            self._highlighted_row = -1
        event.accept()

    def _get_theme_id_for_row(self, row):
        """해당 행이 속한 테마 ID를 반환 (헤더 또는 박스 항목 모두 처리)"""
        box_map = self._get_box_index_map()
        if row < 0 or row >= len(box_map):
            return None

        # 헤더인 경우 직접 테마 ID 반환
        if box_map[row] is None:
            item = self.item(row)
            return self._get_theme_id_from_header(item) if item else None

        # 박스인 경우 위로 올라가며 헤더 찾기
        for i in range(row, -1, -1):
            if box_map[i] is None:  # 헤더 찾음
                item = self.item(i)
                return self._get_theme_id_from_header(item) if item else None

        return None

    def dropEvent(self, event):
        """드롭 - 테마 헤더/항목에 박스 할당 또는 해설을 문제에 연결"""
        # 하이라이트 제거
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

        # 드래그된 박스들 파싱
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

        # 드롭 대상이 박스 항목인지 확인
        box_map = self._get_box_index_map()
        target_entry = box_map[row] if 0 <= row < len(box_map) else None

        # 드롭 대상이 문제 박스이고, 드래그 항목이 모두 해설인 경우 → 연결
        if target_entry is not None:
            target_page_idx, target_box = target_entry
            # 드롭 대상이 문제 타입인지 확인
            if target_box.box_type == "question":
                # 드래그된 항목이 모두 해설인지 확인
                all_solutions = all(b.box_type == "solution" for _, b in box_items)
                if all_solutions:
                    # 해설을 문제에 연결
                    self.solution_linked.emit(box_items, target_box.box_id)
                    event.acceptProposedAction()
                    return

        # 기존 로직: 테마 변경
        target_theme_id = self._get_theme_id_for_row(row)
        self.theme_changed.emit(box_items, target_theme_id)
        event.acceptProposedAction()


class ImageCanvas(QLabel):
    """이미지 표시 및 박스 그리기 캔버스"""

    DELETE_BTN_SIZE = 16  # 삭제 버튼 크기

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent_window = parent  # 약한 참조 대신 직접 참조
        self.drawing = False
        self.start_point = QPoint()
        self.current_point = QPoint()
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    @property
    def parent_window(self):
        """부모 윈도우 안전하게 접근"""
        try:
            if self._parent_window and not self._parent_window.isHidden():
                return self._parent_window
        except RuntimeError:
            pass
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.pixmap():
            # 먼저 삭제 버튼 클릭 확인
            delete_btn_idx = self._get_delete_btn_at_pos(event.pos())
            if delete_btn_idx is not None and self.parent_window:
                self.parent_window.delete_box_on_canvas(delete_btn_idx)
                return

            # 클릭한 위치에 박스가 있는지 확인
            clicked_box_idx = self._get_box_at_pos(event.pos())
            if clicked_box_idx is not None:
                # 박스 선택
                if self.parent_window:
                    self.parent_window.select_box_on_canvas(clicked_box_idx)
            else:
                # 새 박스 그리기 시작
                self.drawing = True
                self.start_point = event.pos()
                self.current_point = event.pos()
        elif event.button() == Qt.RightButton and self.pixmap():
            # 오른쪽 클릭: 박스 삭제
            clicked_box_idx = self._get_box_at_pos(event.pos())
            if clicked_box_idx is not None and self.parent_window:
                self.parent_window.delete_box_on_canvas(clicked_box_idx)

    def _get_delete_btn_at_pos(self, pos):
        """클릭 위치에 있는 삭제 버튼의 박스 인덱스 반환"""
        if not self.parent_window:
            return None

        boxes = self.parent_window.get_current_boxes()
        scale = self.parent_window.scale
        btn_size = self.DELETE_BTN_SIZE

        # 역순으로 검색 (위에 그려진 박스 우선)
        for i in range(len(boxes) - 1, -1, -1):
            box = boxes[i]
            x2 = int(box.x2 * scale)
            y1 = int(box.y1 * scale)

            # 삭제 버튼 영역 (박스 오른쪽 상단)
            btn_x = x2 - btn_size - 2
            btn_y = y1 + 2

            if btn_x <= pos.x() <= btn_x + btn_size and btn_y <= pos.y() <= btn_y + btn_size:
                return i
        return None

    def _get_box_at_pos(self, pos):
        """클릭 위치에 있는 박스 인덱스 반환"""
        if not self.parent_window:
            return None

        boxes = self.parent_window.get_current_boxes()
        scale = self.parent_window.scale

        # 역순으로 검색 (위에 그려진 박스 우선)
        for i in range(len(boxes) - 1, -1, -1):
            box = boxes[i]
            x1 = int(box.x1 * scale)
            y1 = int(box.y1 * scale)
            x2 = int(box.x2 * scale)
            y2 = int(box.y2 * scale)

            if x1 <= pos.x() <= x2 and y1 <= pos.y() <= y2:
                return i
        return None

    def mouseMoveEvent(self, event):
        if self.drawing:
            self.current_point = event.pos()
            self.update()
        else:
            # 삭제 버튼 위에서 커서 변경
            if self._get_delete_btn_at_pos(event.pos()) is not None:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.drawing:
            self.drawing = False
            end_point = event.pos()

            # 최소 크기 체크
            if abs(end_point.x() - self.start_point.x()) > 20 and \
               abs(end_point.y() - self.start_point.y()) > 20:
                if self.parent_window:
                    self.parent_window.add_box(self.start_point, end_point)

            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        if not self.pixmap():
            return

        painter = QPainter(self)

        try:
            # 기존 박스 그리기
            parent = self.parent_window
            if parent:
                boxes = parent.get_current_boxes()
                selected_idx = parent.current_box_id
                scale = parent.scale
                current_page = parent.current_page_idx

                # 테마 내 전체 순번 계산 (페이지 상관없이)
                box_labels = {}
                theme_counts = {}
                for page_idx, b in parent._sorted_boxes:
                    theme_id = b.theme_id or "__none__"
                    if theme_id not in theme_counts:
                        theme_counts[theme_id] = 0
                    theme_counts[theme_id] += 1
                    box_labels[id(b)] = theme_counts[theme_id]

                for i, box in enumerate(boxes):
                    x1 = int(box.x1 * scale)
                    y1 = int(box.y1 * scale)
                    x2 = int(box.x2 * scale)
                    y2 = int(box.y2 * scale)

                    # 테마 색상 또는 기본 색상
                    if i == selected_idx:
                        color = QColor(255, 0, 0)  # 선택된 박스: 빨강
                    else:
                        color = QColor(0, 0, 255)  # 기본: 파랑

                    # 유형에 따른 선 스타일: 문제=실선, 풀이=점선
                    pen = QPen(color, 2)
                    if box.box_type == BOX_TYPE_SOLUTION:
                        pen.setStyle(Qt.DashLine)
                    painter.setPen(pen)
                    painter.drawRect(x1, y1, x2 - x1, y2 - y1)

                    # 레이블 (테마명-순번 형식)
                    box_num = box_labels.get(id(box), i + 1)
                    type_icon = "📝" if box.box_type == BOX_TYPE_QUESTION else "📖"
                    theme_name = "미지정"
                    if box.theme_id:
                        theme = parent.get_theme_by_id(box.theme_id)
                        if theme:
                            theme_name = theme.name
                    label = f"{type_icon} {theme_name}-{box_num:02d}"
                    if box.number:
                        label += f" #{box.number}"
                    # 풀이 선 스타일 복원하고 텍스트 그리기 (박스 바로 위)
                    pen.setStyle(Qt.SolidLine)
                    painter.setPen(pen)
                    painter.drawText(x1, y1 - 5, label)

                    # 삭제 버튼 (박스 오른쪽 상단에 X 버튼)
                    btn_size = self.DELETE_BTN_SIZE
                    btn_x = x2 - btn_size - 2
                    btn_y = y1 + 2

                    # 버튼 배경 (빨간색 원)
                    painter.setBrush(QColor(220, 53, 69))  # 빨간색
                    painter.setPen(QPen(QColor(220, 53, 69), 1))
                    painter.drawEllipse(btn_x, btn_y, btn_size, btn_size)

                    # X 표시 (흰색)
                    painter.setPen(QPen(QColor(255, 255, 255), 2))
                    margin = 4
                    painter.drawLine(btn_x + margin, btn_y + margin,
                                     btn_x + btn_size - margin, btn_y + btn_size - margin)
                    painter.drawLine(btn_x + btn_size - margin, btn_y + margin,
                                     btn_x + margin, btn_y + btn_size - margin)

                    # 브러시 초기화
                    painter.setBrush(Qt.NoBrush)

            # 드래그 중인 박스
            if self.drawing:
                pen = QPen(QColor(0, 255, 0), 2, Qt.DashLine)
                painter.setPen(pen)
                rect = QRect(self.start_point, self.current_point).normalized()
                painter.drawRect(rect)
        except Exception:
            pass  # paintEvent에서 예외 발생 시 무시

        painter.end()


class PDFLabeler(QMainWindow):
    """PDF 문항 레이블링 GUI 애플리케이션"""

    MAX_RECENT_FILES = 10  # 최근 파일 최대 개수

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 문항 레이블러 v0.9")

        # 설정 (최근 파일, 창 위치/크기 저장용)
        self.settings = QSettings("PDFLabeler", "PDFLabeler")

        # 저장된 창 위치/크기 복원
        self._restore_window_geometry()

        # 상태 변수
        self.pdf_path: Optional[Path] = None
        self.pages: List[Image.Image] = []
        self.current_page_idx = 0
        self.boxes: Dict[int, List[QuestionBox]] = {}
        self.current_box_id: Optional[int] = None
        self.scale = 1.0
        self._box_index_map: List[tuple] = []  # (page_idx, box_idx) 매핑
        self._sorted_boxes: List[tuple] = []  # 정렬된 (page_idx, box) 목록
        self._auto_save_pending = False  # 자동 저장 대기 플래그
        self.themes: List[Theme] = []  # 테마 목록
        self._theme_counter = 0  # 테마 ID 생성용
        self._box_counter = 0  # 박스 ID 생성용
        self._current_theme_id: Optional[str] = None  # 현재 선택된 테마 (새 박스에 자동 적용)
        self._undo_state: Optional[dict] = None  # 1단계 Undo용 이전 상태

        # 자동 저장 타이머 (변경 후 2초 뒤 저장)
        self._auto_save_timer = QTimer()
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.timeout.connect(self._do_auto_save)

        self._setup_ui()
        self._setup_menu()

        # 최근 파일이 있으면 자동 로드, 없으면 환영 메시지
        recent_files = self._get_recent_files()
        if recent_files and Path(recent_files[0]).exists():
            self._load_pdf(recent_files[0])
        else:
            self._show_welcome_message()

    def _setup_menu(self):
        """메뉴바 구성"""
        menubar = self.menuBar()

        # 파일 메뉴
        file_menu = menubar.addMenu("파일")

        open_action = QAction("PDF 열기", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_pdf)
        file_menu.addAction(open_action)

        # 최근 항목 서브메뉴
        self.recent_menu = file_menu.addMenu("최근 항목")
        self._update_recent_menu()

        file_menu.addSeparator()

        export_action = QAction("이미지 내보내기", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self._export_images)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        quit_action = QAction("종료", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # 편집 메뉴
        edit_menu = menubar.addMenu("편집")

        undo_action = QAction("실행 취소", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self._undo)
        edit_menu.addAction(undo_action)

    def _update_recent_menu(self):
        """최근 항목 메뉴 업데이트"""
        self.recent_menu.clear()
        recent = self._get_recent_files()

        if not recent:
            no_recent = QAction("(없음)", self)
            no_recent.setEnabled(False)
            self.recent_menu.addAction(no_recent)
            return

        for file_path in recent:
            path = Path(file_path)
            if path.exists():
                action = QAction(path.name, self)
                action.setToolTip(str(path))
                action.triggered.connect(lambda checked, p=file_path: self._load_pdf(p))
                self.recent_menu.addAction(action)

        self.recent_menu.addSeparator()
        clear_action = QAction("최근 항목 지우기", self)
        clear_action.triggered.connect(self._clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def _clear_recent_files(self):
        """최근 파일 목록 지우기"""
        self.settings.setValue("recent_files", [])
        self._update_recent_menu()

    def _restore_window_geometry(self):
        """저장된 창 위치/크기 복원"""
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.setGeometry(100, 100, 1400, 900)

    def _save_window_geometry(self):
        """창 위치/크기 저장"""
        self.settings.setValue("window_geometry", self.saveGeometry())

    def closeEvent(self, event):
        """창 닫힐 때 위치/크기 저장"""
        self._save_window_geometry()
        # 자동 저장 대기 중이면 즉시 저장
        if self._auto_save_pending:
            self._auto_save_timer.stop()
            self._do_auto_save()
        event.accept()

    def _show_welcome_message(self):
        """프로그램 소개 메시지 표시"""
        welcome_text = """
<div style="padding: 40px; font-family: sans-serif; max-width: 600px;">
<h1 style="text-align: center;">📄 PDF 문항 레이블러</h1>
<p style="font-size: 14px; text-align: center; opacity: 0.7;">PDF 문서에서 문항을 박싱하고 레이블링하는 도구입니다.</p>

<h3 style="margin-top: 30px;">✨ 주요 기능</h3>
<ul style="line-height: 1.8;">
<li><a href="action:open_pdf" style="color: #4a90d9; text-decoration: none;"><b>PDF 열기</b></a> - PDF 파일을 불러와 페이지별로 탐색</li>
<li><b>박스 그리기</b> - 마우스 드래그로 문항 영역 선택</li>
<li><b>레이블링</b> - 문항 번호와 테마/주제 입력</li>
<li><b>순서 조정</b> - 박스 목록에서 순서 변경 가능</li>
<li><b>자동 저장</b> - 작업 내용이 .works 폴더에 자동 저장</li>
<li><b>이미지 내보내기</b> - 고해상도(300 DPI) 이미지 추출</li>
</ul>

<h3 style="margin-top: 30px;">⌨️ 단축키</h3>
<ul style="line-height: 1.8;">
<li><b>← / →</b> - 이전/다음 페이지</li>
<li><b>Delete</b> - 선택된 박스 삭제</li>
<li><b>+ / -</b> - 확대/축소</li>
<li><b>스크롤</b> - 페이지 끝에서 추가 스크롤 시 페이지 이동</li>
</ul>

<p style="margin-top: 40px; font-size: 12px; text-align: center; opacity: 0.7;">
👉 <a href="action:open_pdf" style="color: #4a90d9;"><b>PDF 열기</b></a>를 클릭하거나<br>
우측 패널에서 최근 항목을 선택하세요.
</p>

<p style="margin-top: 30px; font-size: 12px; text-align: center; opacity: 0.7;">
📖 <a href="action:show_manual" style="color: #4a90d9;">사용자 매뉴얼 보기</a>
</p>

<p style="margin-top: 30px; font-size: 11px; text-align: center; opacity: 0.5;">
© 2026 MilliSquare
</p>
</div>
"""
        from PyQt5.QtWidgets import QTextBrowser, QFrame

        # 컨테이너 위젯 생성 (수직 중앙 정렬용)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setAlignment(Qt.AlignCenter)

        # 텍스트 브라우저
        self.welcome_label = QTextBrowser()
        self.welcome_label.setReadOnly(True)
        self.welcome_label.setOpenLinks(False)  # 링크 자동 열기 비활성화
        self.welcome_label.anchorClicked.connect(self._on_welcome_link_clicked)
        self.welcome_label.setHtml(welcome_text)
        self.welcome_label.setStyleSheet("border: none;")
        self.welcome_label.setFixedSize(650, 550)
        self.welcome_label.setFrameShape(QFrame.NoFrame)

        layout.addWidget(self.welcome_label)
        self.scroll_area.setWidget(container)

    def _on_welcome_link_clicked(self, url):
        """Welcome 메시지 링크 클릭 처리"""
        if url.toString() == "action:open_pdf":
            self._open_pdf()
        elif url.toString() == "action:show_manual":
            self._show_manual()
        elif url.toString() == "action:back_to_welcome":
            self._show_welcome_message()

    def _show_manual(self):
        """사용자 매뉴얼 표시"""
        manual_text = """
<div style="padding: 30px; font-family: sans-serif; max-width: 700px;">
<h1 style="text-align: center;">📖 사용자 매뉴얼</h1>

<h2 style="margin-top: 25px; border-bottom: 1px solid gray; padding-bottom: 5px;">설치 및 실행</h2>
<ol style="line-height: 1.8;">
<li><code>PDF문항레이블러.zip</code> 압축 해제</li>
<li><code>PDF문항레이블러.app</code> 더블클릭하여 실행</li>
<li>첫 실행 시 "확인되지 않은 개발자" 경고: 우클릭 → 열기</li>
</ol>

<h2 style="margin-top: 25px; border-bottom: 1px solid gray; padding-bottom: 5px;">테마(단원) 관리</h2>
<ul style="line-height: 1.8;">
<li>왼쪽 <b>테마 목록</b>에서 테마 추가/삭제</li>
<li><b>+</b> 버튼: 새 테마 추가 (입력 후 Enter)</li>
<li><b>-</b> 버튼: 선택된 테마 삭제</li>
<li>테마 클릭 시 해당 테마가 선택됨 (새 박스에 자동 적용)</li>
</ul>

<h2 style="margin-top: 25px; border-bottom: 1px solid gray; padding-bottom: 5px;">박싱 작업</h2>
<h3>문제/해설 박스 생성</h3>
<ol style="line-height: 1.8;">
<li>테마를 먼저 선택</li>
<li><b>해설 입력</b> 체크박스:
    <ul>
    <li>체크 해제: 문제 박스 생성</li>
    <li>체크: 해설 박스 생성</li>
    </ul>
</li>
<li>PDF 위에서 드래그하여 영역 선택</li>
</ol>

<h3>박스 삭제</h3>
<ul style="line-height: 1.8;">
<li>PDF에서: 박스 위 우클릭</li>
<li>목록에서: 선택 후 <code>Delete</code> 키</li>
</ul>

<h3>박스 테마 변경</h3>
<ul style="line-height: 1.8;">
<li>전체 박스 목록에서 박스를 드래그하여 다른 테마 헤더에 드롭</li>
</ul>

<h2 style="margin-top: 25px; border-bottom: 1px solid gray; padding-bottom: 5px;">해설 연결</h2>
<p style="line-height: 1.8;">해설 박스를 문제에 연결하는 방법:</p>
<ol style="line-height: 1.8;">
<li>전체 박스 목록에서 <b>해설 항목</b>을 선택</li>
<li><b>문제 항목</b> 위로 드래그&드롭</li>
<li>연결되면 해설이 문제 아래에 들여쓰기로 표시됨</li>
</ol>
<pre style="padding: 10px; border-radius: 5px; font-size: 12px; opacity: 0.8;">
▼ 수열의 극한 (2)
    📝 수열의 극한-01
        └ 📖 수열의 극한-01-01 해설
    📝 수열의 극한-02
</pre>

<h2 style="margin-top: 25px; border-bottom: 1px solid gray; padding-bottom: 5px;">단축키</h2>
<table style="width: 100%; border-collapse: collapse;">
<tr><th style="padding: 8px; text-align: left; border-bottom: 1px solid gray;">단축키</th><th style="padding: 8px; text-align: left; border-bottom: 1px solid gray;">기능</th></tr>
<tr><td style="padding: 8px;"><code>Cmd+O</code></td><td style="padding: 8px;">PDF 열기</td></tr>
<tr><td style="padding: 8px;"><code>Cmd+E</code></td><td style="padding: 8px;">이미지 내보내기</td></tr>
<tr><td style="padding: 8px;"><code>Cmd+Z</code></td><td style="padding: 8px;">실행 취소 (1단계)</td></tr>
<tr><td style="padding: 8px;"><code>Delete</code></td><td style="padding: 8px;">선택된 박스 삭제</td></tr>
<tr><td style="padding: 8px;"><code>← / →</code></td><td style="padding: 8px;">이전/다음 페이지</td></tr>
<tr><td style="padding: 8px;"><code>Shift+클릭</code></td><td style="padding: 8px;">다중 선택</td></tr>
</table>

<h2 style="margin-top: 25px; border-bottom: 1px solid gray; padding-bottom: 5px;">저장 및 내보내기</h2>
<h3>자동 저장</h3>
<ul style="line-height: 1.8;">
<li>모든 작업은 자동으로 저장됨 (<code>.json</code> 파일)</li>
<li>PDF와 같은 폴더에 <code>PDF파일명_labels.json</code>으로 저장</li>
</ul>

<h3>이미지 내보내기</h3>
<ul style="line-height: 1.8;">
<li><b>메뉴</b>: 파일 → 이미지 내보내기 (<code>Cmd+E</code>)</li>
<li>각 박스가 개별 이미지로 저장됨</li>
</ul>

<p style="margin-top: 40px; font-size: 12px; text-align: center; opacity: 0.7;">
<a href="action:back_to_welcome" style="color: #4a90d9;">← 처음으로 돌아가기</a>
</p>
</div>
"""
        self.welcome_label.setHtml(manual_text)
        self.welcome_label.setFixedSize(750, 800)

    def _get_works_dir(self) -> Optional[Path]:
        """PDF 파일 위치의 .works 폴더 경로 반환"""
        if not self.pdf_path:
            return None
        return self.pdf_path.parent / ".works"

    def _get_auto_save_path(self) -> Optional[Path]:
        """자동 저장 파일 경로 반환"""
        works_dir = self._get_works_dir()
        if not works_dir:
            return None
        return works_dir / f"{self.pdf_path.stem}.json"

    def _get_backup_path(self) -> Optional[Path]:
        """백업 파일 경로 반환"""
        works_dir = self._get_works_dir()
        if not works_dir:
            return None
        return works_dir / f"{self.pdf_path.stem}.backup.json"

    def _schedule_auto_save(self):
        """자동 저장 예약 (변경 후 2초 뒤 저장)"""
        if not self.pdf_path:
            return
        self._auto_save_pending = True
        self._auto_save_timer.start(2000)  # 2초 후 저장

    def _do_auto_save(self):
        """실제 자동 저장 수행 (두 벌 백업)"""
        if not self.pdf_path or not self._auto_save_pending:
            return

        works_dir = self._get_works_dir()
        if not works_dir:
            return

        # .works 폴더 생성
        try:
            works_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.status_label.setText(f"자동 저장 실패: {e}")
            return

        save_path = self._get_auto_save_path()
        backup_path = self._get_backup_path()

        # 저장할 데이터 준비
        all_boxes = []
        for page_idx, box in self._sorted_boxes:
            box_dict = box.to_dict()
            box_dict['_sort_order'] = self._sorted_boxes.index((page_idx, box))
            all_boxes.append(box_dict)

        # 테마 데이터 준비
        themes_data = [theme.to_dict() for theme in self.themes]

        data = {
            "source_pdf": self.pdf_path.name,
            "saved_at": datetime.now().isoformat(),
            "themes": themes_data,
            "total_boxes": len(all_boxes),
            "boxes": all_boxes
        }

        json_str = json.dumps(data, ensure_ascii=False, indent=2)

        try:
            # 1단계: 기존 파일이 있으면 백업으로 복사
            if save_path.exists():
                import shutil
                shutil.copy2(save_path, backup_path)

            # 2단계: 새 파일 저장
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(json_str)

            self._auto_save_pending = False
            self.status_label.setText(f"자동 저장됨 ({len(all_boxes)}개 박스)")

        except Exception as e:
            # 저장 실패 시 백업에서 복구 시도
            self.status_label.setText(f"자동 저장 실패: {e}")
            if backup_path and backup_path.exists():
                try:
                    import shutil
                    shutil.copy2(backup_path, save_path)
                except:
                    pass

    def _load_auto_saved_data(self):
        """자동 저장된 데이터 로드"""
        save_path = self._get_auto_save_path()
        backup_path = self._get_backup_path()

        # 메인 파일 시도
        data = None
        loaded_from = None

        if save_path and save_path.exists():
            try:
                with open(save_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                loaded_from = save_path
            except:
                pass

        # 메인 파일 실패 시 백업 시도
        if data is None and backup_path and backup_path.exists():
            try:
                with open(backup_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                loaded_from = backup_path
            except:
                pass

        if data is None:
            return False

        # 테마 로드
        self.themes = []
        self._theme_counter = 0
        for theme_data in data.get("themes", []):
            theme = Theme(
                id=theme_data["id"],
                name=theme_data["name"],
                color=theme_data.get("color", "#3498db")
            )
            self.themes.append(theme)
            # 테마 카운터 업데이트 (ID 충돌 방지)
            if theme.id.startswith("theme_"):
                try:
                    num = int(theme.id.split("_")[1])
                    self._theme_counter = max(self._theme_counter, num)
                except ValueError:
                    pass
        self._update_theme_list()
        self._update_theme_combo()

        # 박스 데이터 로드
        self.boxes = {i: [] for i in range(len(self.pages))}
        self._sorted_boxes = []

        # _sort_order로 정렬하여 로드
        boxes_data = data.get("boxes", [])
        boxes_data.sort(key=lambda x: x.get('_sort_order', 0))

        for box_data in boxes_data:
            page_idx = box_data.get("page", 1) - 1
            if 0 <= page_idx < len(self.pages):
                box = QuestionBox(
                    x1=box_data["x1"],
                    y1=box_data["y1"],
                    x2=box_data["x2"],
                    y2=box_data["y2"],
                    number=box_data.get("number"),
                    theme_id=box_data.get("theme_id"),
                    page=box_data.get("page", 1),
                    box_type=box_data.get("box_type", BOX_TYPE_QUESTION),
                    linked_box_id=box_data.get("linked_box_id"),
                    box_id=box_data.get("box_id")
                )
                # box_id가 없으면 생성
                if not box.box_id:
                    box.box_id = self._generate_box_id()
                else:
                    # box_counter 업데이트 (ID 충돌 방지)
                    if box.box_id.startswith("box_"):
                        try:
                            num = int(box.box_id.split("_")[1])
                            self._box_counter = max(self._box_counter, num)
                        except ValueError:
                            pass
                self.boxes[page_idx].append(box)
                self._sorted_boxes.append((page_idx, box))

        # 썸네일에 박스 표시
        self._update_thumbnail_boxes()

        self.status_label.setText(f"자동 저장 데이터 로드됨 ({len(self._sorted_boxes)}개 박스, {len(self.themes)}개 테마)")
        return True

    def _setup_ui(self):
        """UI 구성"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)

        # 스플리터
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # 좌측: 썸네일 패널 (토글 버튼 포함)
        self.thumbnail_panel = QWidget()
        self.thumbnail_panel.setMinimumWidth(80)
        self.thumbnail_panel.setMaximumWidth(300)
        thumbnail_layout = QVBoxLayout(self.thumbnail_panel)
        thumbnail_layout.setContentsMargins(2, 2, 2, 2)

        # 사이드바 토글 버튼
        self.sidebar_toggle_btn = QPushButton("◀")
        self.sidebar_toggle_btn.setFixedHeight(24)
        self.sidebar_toggle_btn.setToolTip("사이드바 숨기기")
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        thumbnail_layout.addWidget(self.sidebar_toggle_btn)

        thumbnail_label = QLabel("페이지")
        thumbnail_label.setAlignment(Qt.AlignCenter)
        thumbnail_layout.addWidget(thumbnail_label)

        self.thumbnail_scroll = QScrollArea()
        self.thumbnail_scroll.setWidgetResizable(True)
        self.thumbnail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.thumbnail_container = QWidget()
        self.thumbnail_list_layout = QVBoxLayout(self.thumbnail_container)
        self.thumbnail_list_layout.setSpacing(5)
        self.thumbnail_list_layout.setAlignment(Qt.AlignTop)
        self.thumbnail_scroll.setWidget(self.thumbnail_container)

        thumbnail_layout.addWidget(self.thumbnail_scroll)
        splitter.addWidget(self.thumbnail_panel)

        # 스플리터 크기 변경 시 썸네일 재렌더링 (디바운싱)
        self._main_splitter = splitter
        splitter.splitterMoved.connect(self._on_splitter_moved)
        self._last_thumbnail_width = 0
        self._thumbnail_resize_timer = QTimer()
        self._thumbnail_resize_timer.setSingleShot(True)
        self._thumbnail_resize_timer.timeout.connect(self._delayed_thumbnail_resize)

        # 처음에는 썸네일 패널 숨기기
        self.thumbnail_panel.hide()
        self._sidebar_visible = True  # 사이드바 표시 상태

        # 사이드바 보이기 버튼 (숨겨졌을 때 표시)
        self.sidebar_show_btn = QPushButton("▶")
        self.sidebar_show_btn.setFixedWidth(20)
        self.sidebar_show_btn.setToolTip("사이드바 보이기")
        self.sidebar_show_btn.clicked.connect(self._toggle_sidebar)
        self.sidebar_show_btn.hide()
        main_layout.insertWidget(0, self.sidebar_show_btn)

        # 중앙: 이미지 캔버스 + 상단 줌 바
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        # 상단 줌 툴바 (얇은 패널)
        zoom_bar = QWidget()
        zoom_bar.setFixedHeight(35)
        zoom_bar.setStyleSheet("border-bottom: 1px solid palette(mid);")
        zoom_bar_layout = QHBoxLayout(zoom_bar)
        zoom_bar_layout.setContentsMargins(10, 2, 10, 2)

        zoom_bar_layout.addStretch()

        btn_zoom_out = QPushButton("−")
        btn_zoom_out.setFixedSize(28, 28)
        btn_zoom_out.setToolTip("축소")
        btn_zoom_out.clicked.connect(self._zoom_out)
        zoom_bar_layout.addWidget(btn_zoom_out)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(50)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        zoom_bar_layout.addWidget(self.zoom_label)

        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedSize(28, 28)
        btn_zoom_in.setToolTip("확대")
        btn_zoom_in.clicked.connect(self._zoom_in)
        zoom_bar_layout.addWidget(btn_zoom_in)

        btn_fit = QPushButton("맞춤")
        btn_fit.setFixedSize(45, 28)
        btn_fit.setToolTip("화면 폭에 맞춤")
        btn_fit.clicked.connect(self._fit_to_window)
        zoom_bar_layout.addWidget(btn_fit)

        zoom_bar_layout.addStretch()

        center_layout.addWidget(zoom_bar)

        # 이미지 캔버스
        self.scroll_area = ScrollAreaWithPageNav()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.page_next.connect(lambda: self._next_page(scroll_to_top=True))
        self.scroll_area.page_prev.connect(lambda: self._prev_page(scroll_to_bottom=True))
        self.canvas = ImageCanvas(self)
        self.canvas.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll_area.setWidget(self.canvas)
        center_layout.addWidget(self.scroll_area)

        splitter.addWidget(center_widget)

        # 우측: 컨트롤 패널
        control_panel = QWidget()
        control_panel.setMaximumWidth(300)
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(0, 0, 0, 0)

        # 우측 패널 레이아웃
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(10)

        # 교재 이름 표시
        self.textbook_label = QLabel("교재: (없음)")
        self.textbook_label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 5px; background-color: palette(midlight); border-radius: 3px;")
        self.textbook_label.setWordWrap(True)
        right_layout.addWidget(self.textbook_label)

        # 테마 헤더 (레이블 + 추가/삭제 버튼)
        theme_header = QHBoxLayout()
        theme_header.setContentsMargins(0, 0, 0, 0)
        theme_label = QLabel("테마")
        theme_label.setStyleSheet("font-weight: bold; padding: 3px;")
        theme_header.addWidget(theme_label)
        theme_header.addStretch()
        self.theme_delete_btn = QPushButton("-")
        self.theme_delete_btn.setFixedSize(24, 24)
        self.theme_delete_btn.setToolTip("선택된 테마 삭제/복원")
        self.theme_delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #da190b; }
        """)
        self.theme_delete_btn.clicked.connect(self._toggle_theme_deleted)
        theme_header.addWidget(self.theme_delete_btn)
        right_layout.addLayout(theme_header)

        # 테마 목록 (스크롤 가능)
        self.theme_list = ThemeListWidget()
        self.theme_list.setMinimumHeight(80)
        self.theme_list.setMaximumHeight(200)  # 최대 높이 제한, 넘으면 스크롤
        self.theme_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.theme_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 테마 순서는 self.themes 리스트 순서를 따름 (자동 정렬 비활성화)
        self.theme_list.itemClicked.connect(self._on_theme_select)
        self.theme_list.itemDoubleClicked.connect(self._on_theme_double_click)
        self.theme_list.itemChanged.connect(self._on_theme_item_changed)
        self.theme_list.box_dropped.connect(self._on_box_dropped_to_theme)
        self.theme_list.viewport().installEventFilter(self)  # 빈 영역 더블클릭 감지
        right_layout.addWidget(self.theme_list)

        # 더미 콤보박스들 (내부 로직용 - 숨김)
        self.type_combo = QComboBox()
        self.type_combo.addItem("📝 문제", BOX_TYPE_QUESTION)
        self.type_combo.addItem("📖 풀이", BOX_TYPE_SOLUTION)
        self.type_combo.hide()

        self.number_input = QLineEdit()
        self.number_input.hide()

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("(없음)", None)
        self.theme_combo.hide()

        self.link_label = QLabel()
        self.link_label.hide()
        self.link_combo = QComboBox()
        self.link_combo.hide()

        # 숨김 상태 라벨 (내부용)
        self.status_label = QLabel("")
        self.status_label.hide()
        self.page_label = QLabel("")
        self.page_label.hide()

        # 전체 박스 목록 헤더 (레이블 + 해설 입력 체크박스 + 전체 접기 버튼)
        box_list_header = QHBoxLayout()
        box_list_header.setContentsMargins(0, 0, 0, 0)
        self.box_list_label = QLabel("전체 박스 목록 (0)")
        self.box_list_label.setStyleSheet("font-weight: bold; padding: 3px;")
        box_list_header.addWidget(self.box_list_label)
        box_list_header.addStretch()
        from PyQt5.QtWidgets import QCheckBox
        self.solution_mode_checkbox = QCheckBox("해설 입력")
        self.solution_mode_checkbox.setChecked(True)
        self.solution_mode_checkbox.setToolTip("체크 시 새 박스가 해설 타입으로 생성됩니다")
        box_list_header.addWidget(self.solution_mode_checkbox)
        self.collapse_all_btn = QPushButton("전체 접기")
        self.collapse_all_btn.setFixedWidth(70)
        self.collapse_all_btn.clicked.connect(self._collapse_all_themes)
        box_list_header.addWidget(self.collapse_all_btn)
        right_layout.addLayout(box_list_header)

        self.box_list = BoxListWidget()
        self.box_list.set_parent_window(self)
        self.box_list.itemClicked.connect(self._on_box_select)
        self.box_list.theme_selected.connect(self._on_theme_selected_from_popup)
        self.box_list.theme_changed.connect(self._on_theme_changed_by_drag)
        self.box_list.type_changed.connect(self._on_type_changed_by_context)
        self.box_list.solution_linked.connect(self._on_solution_linked)
        right_layout.addWidget(self.box_list)

        control_layout.addLayout(right_layout)

        splitter.addWidget(control_panel)
        splitter.setSizes([100, 800, 300])

    def _toggle_sidebar(self):
        """사이드바 토글"""
        if self._sidebar_visible:
            # 숨기기
            self.thumbnail_panel.hide()
            self.sidebar_show_btn.show()
            self._sidebar_visible = False
        else:
            # 보이기
            if self.pdf_path:  # PDF가 열려있을 때만
                self.thumbnail_panel.show()
            self.sidebar_show_btn.hide()
            self._sidebar_visible = True

    def keyPressEvent(self, event):
        """키보드 이벤트"""
        if event.key() == Qt.Key_Left:
            self._prev_page()
        elif event.key() == Qt.Key_Right:
            self._next_page()
        elif event.key() == Qt.Key_Delete:
            self._delete_selected_box()
        elif event.key() == Qt.Key_Plus:
            self._zoom_in()
        elif event.key() == Qt.Key_Minus:
            self._zoom_out()

    def eventFilter(self, obj, event):
        """이벤트 필터 - 테마 목록 빈 영역 더블클릭 감지"""
        from PyQt5.QtCore import QEvent
        if obj == self.theme_list.viewport() and event.type() == QEvent.MouseButtonDblClick:
            item = self.theme_list.itemAt(event.pos())
            if item is None:
                # 빈 영역 더블클릭 → 새 항목 추가 후 인라인 편집
                new_item = QListWidgetItem("")
                new_item.setFlags(new_item.flags() | Qt.ItemIsEditable)
                new_item.setData(Qt.UserRole, None)  # 아직 ID 없음
                self.theme_list.addItem(new_item)
                self.theme_list.setCurrentItem(new_item)
                self.theme_list.editItem(new_item)
                return True
            # 항목 위 더블클릭은 itemDoubleClicked 시그널에서 처리
            return False
        return super().eventFilter(obj, event)

    # ===== 테마 관리 =====
    def get_theme_by_id(self, theme_id: str) -> Optional[Theme]:
        """ID로 테마 찾기"""
        for theme in self.themes:
            if theme.id == theme_id:
                return theme
        return None

    def _generate_theme_id(self) -> str:
        """새 테마 ID 생성"""
        self._theme_counter += 1
        return f"theme_{self._theme_counter}"

    def _update_theme_list(self):
        """테마 목록 UI 업데이트 (이름순 정렬)"""
        self.theme_list.blockSignals(True)  # 시그널 임시 차단
        self.theme_list.clear()
        # 이름순 정렬 (삭제된 테마는 맨 아래)
        active_themes = sorted([t for t in self.themes if not t.deleted], key=lambda t: t.name)
        deleted_themes = sorted([t for t in self.themes if t.deleted], key=lambda t: t.name)
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

    def _update_theme_combo(self):
        """테마 콤보박스 업데이트 (삭제되지 않은 테마만)"""
        self.theme_combo.clear()
        self.theme_combo.addItem("(없음)", None)
        for theme in self.themes:
            if not theme.deleted:
                self.theme_combo.addItem(f"● {theme.name}", theme.id)

    def _toggle_theme_deleted(self):
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

    def _add_theme(self):
        """테마 추가 - 인라인 편집으로 시작"""
        new_item = QListWidgetItem("")
        new_item.setFlags(new_item.flags() | Qt.ItemIsEditable)
        new_item.setData(Qt.UserRole, None)  # 아직 ID 없음
        self.theme_list.addItem(new_item)
        self.theme_list.setCurrentItem(new_item)
        self.theme_list.editItem(new_item)

    def _edit_theme(self):
        """선택된 테마 편집 - 인라인 편집 시작"""
        current = self.theme_list.currentItem()
        if current:
            self.theme_list.editItem(current)

    def _delete_theme(self):
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

    def _on_theme_select(self, item):
        """테마 목록에서 선택"""
        theme_id = item.data(Qt.UserRole)
        # 콤보박스에서 해당 테마 선택
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == theme_id:
                self.theme_combo.setCurrentIndex(i)
                break

    def _on_theme_double_click(self, item):
        """테마 목록 더블클릭 - 인라인 편집 시작"""
        if item:
            self.theme_list.editItem(item)

    def _on_theme_item_changed(self, item):
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
                self._update_theme_list()
                self._update_theme_combo()
                self._schedule_auto_save()
            else:
                # 빈 이름이면 항목 제거
                self._update_theme_list()

    def _on_box_dropped_to_theme(self, theme_id: str):
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

    def _on_theme_selected_from_popup(self, list_rows: list, theme_id):
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

    def _on_theme_changed_by_drag(self, box_items: list, theme_id):
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
            self.status_label.setText(f"{count}개 박스 테마 변경: {theme_name}")

    def _on_type_changed_by_context(self, box_items: list, box_type: str):
        """우클릭 메뉴로 박스 타입 변경"""
        if not box_items:
            return

        self._save_state_for_undo()  # Undo용 상태 저장
        updated_pages = set()
        count = 0

        for page_idx, box in box_items:
            if box.box_type != box_type:
                box.box_type = box_type
                # 문제로 변경시 연결 해제
                if box_type == BOX_TYPE_QUESTION:
                    box.linked_box_id = None
                updated_pages.add(page_idx)
                count += 1

        if count > 0:
            self._update_box_list()
            for page_idx in updated_pages:
                self._update_thumbnail_boxes(page_idx)
            self.canvas.update()
            self._schedule_auto_save()

            type_name = "문제" if box_type == BOX_TYPE_QUESTION else "해설"
            self.status_label.setText(f"{count}개 박스 타입 변경: {type_name}")

    def _on_solution_linked(self, solution_items: list, question_box_id: str):
        """해설을 문제에 드래그&드롭으로 연결"""
        if not solution_items or not question_box_id:
            return

        self._save_state_for_undo()  # Undo용 상태 저장
        count = 0
        for page_idx, solution_box in solution_items:
            if solution_box.box_type == BOX_TYPE_SOLUTION:
                solution_box.linked_box_id = question_box_id
                count += 1

        if count > 0:
            self._update_box_list()
            self.canvas.update()
            self._schedule_auto_save()
            self.status_label.setText(f"{count}개 해설이 문제에 연결됨")

    # ===== Undo 기능 =====
    def _save_state_for_undo(self):
        """현재 상태를 Undo용으로 저장"""
        import copy
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

    def _undo(self):
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

    # ===== 박스 유형 및 연결 관리 =====
    def _generate_box_id(self) -> str:
        """새 박스 ID 생성"""
        self._box_counter += 1
        return f"box_{self._box_counter}"

    def get_box_by_id(self, box_id: str) -> Optional[QuestionBox]:
        """ID로 박스 찾기"""
        for page_idx, boxes in self.boxes.items():
            for box in boxes:
                if box.box_id == box_id:
                    return box
        return None

    def get_questions_for_linking(self, solution_box: QuestionBox) -> list:
        """해설과 연결할 수 있는 문제 목록 반환"""
        result = []
        for page_idx, boxes in self.boxes.items():
            for box in boxes:
                # 문제 타입만, 같은 테마
                if box.box_type == BOX_TYPE_QUESTION and box.theme_id == solution_box.theme_id:
                    result.append((page_idx, box))
        # 페이지, 번호 순 정렬
        result.sort(key=lambda x: (x[0], x[1].number or 0))
        return result

    def _on_type_changed(self, index):
        """유형 콤보박스 변경 시"""
        box_type = self.type_combo.currentData()
        if box_type == BOX_TYPE_SOLUTION:
            # 풀이 선택 시 연결 콤보박스 표시
            self.link_label.show()
            self.link_combo.show()
            self._update_link_combo()
        else:
            # 문제 선택 시 연결 콤보박스 숨김
            self.link_label.hide()
            self.link_combo.hide()

    def _update_link_combo(self):
        """문제 연결 콤보박스 업데이트 (문제 유형만 표시)"""
        self.link_combo.clear()
        self.link_combo.addItem("(없음)", None)

        for page_idx, box in self._sorted_boxes:
            if box.box_type == BOX_TYPE_QUESTION:
                # 문제만 표시
                label = f"{page_idx + 1:02d}p"
                if box.number:
                    label += f" #{box.number}"
                if box.theme_id:
                    theme = self.get_theme_by_id(box.theme_id)
                    if theme:
                        label += f" [{theme.name}]"
                self.link_combo.addItem(label, box.box_id)

    def _get_linked_solutions(self, question_box_id: str) -> List[QuestionBox]:
        """특정 문제에 연결된 풀이들 반환"""
        solutions = []
        for page_idx, boxes in self.boxes.items():
            for box in boxes:
                if box.linked_box_id == question_box_id:
                    solutions.append(box)
        return solutions

    def _get_recent_files(self) -> List[str]:
        """최근 파일 목록 가져오기"""
        recent = self.settings.value("recent_files", [])
        if isinstance(recent, str):
            recent = [recent] if recent else []
        return recent or []

    def _add_to_recent_files(self, file_path: str):
        """최근 파일 목록에 추가"""
        recent = self._get_recent_files()

        # 이미 있으면 제거 (맨 앞으로 이동시키기 위해)
        if file_path in recent:
            recent.remove(file_path)

        # 맨 앞에 추가
        recent.insert(0, file_path)

        # 최대 개수 유지
        recent = recent[:self.MAX_RECENT_FILES]

        self.settings.setValue("recent_files", recent)
        self._update_recent_menu()

    def get_current_boxes(self) -> List[QuestionBox]:
        """현재 페이지의 박스 목록"""
        return self.boxes.get(self.current_page_idx, [])

    def select_box_on_canvas(self, box_idx: int):
        """캔버스에서 박스 선택"""
        boxes = self.get_current_boxes()
        if 0 <= box_idx < len(boxes):
            self.current_box_id = box_idx
            box = boxes[box_idx]

            # 레이블 입력 필드 업데이트
            self.number_input.setText(str(box.number) if box.number else "")

            # 테마 콤보박스 업데이트
            idx = 0
            for i in range(self.theme_combo.count()):
                if self.theme_combo.itemData(i) == box.theme_id:
                    idx = i
                    break
            self.theme_combo.setCurrentIndex(idx)

            # 유형 콤보박스 업데이트
            type_idx = 0
            for i in range(self.type_combo.count()):
                if self.type_combo.itemData(i) == box.box_type:
                    type_idx = i
                    break
            self.type_combo.setCurrentIndex(type_idx)

            # 연결 콤보박스 업데이트 (풀이인 경우)
            if box.box_type == BOX_TYPE_SOLUTION:
                self.link_label.show()
                self.link_combo.show()
                self._update_link_combo()
                # 현재 연결된 문제 선택
                link_idx = 0
                for i in range(self.link_combo.count()):
                    if self.link_combo.itemData(i) == box.linked_box_id:
                        link_idx = i
                        break
                self.link_combo.setCurrentIndex(link_idx)
            else:
                self.link_label.hide()
                self.link_combo.hide()

            # 전체 목록에서 해당 박스 선택
            for list_idx, entry in enumerate(self._box_index_map):
                if entry is None:  # 헤더는 건너뛰기
                    continue
                page_idx_entry, b = entry
                if page_idx_entry == self.current_page_idx and b is box:
                    self.box_list.setCurrentRow(list_idx)
                    break

            self.canvas.update()

    def delete_box_on_canvas(self, box_idx: int):
        """캔버스에서 박스 삭제 (오른쪽 클릭)"""
        self._save_state_for_undo()  # Undo용 상태 저장
        boxes = self.get_current_boxes()
        if 0 <= box_idx < len(boxes):
            box = boxes[box_idx]

            # boxes 딕셔너리에서 삭제
            self.boxes[self.current_page_idx].remove(box)

            # 정렬 목록에서도 삭제
            if (self.current_page_idx, box) in self._sorted_boxes:
                self._sorted_boxes.remove((self.current_page_idx, box))

            self.current_box_id = None
            self._update_box_list()
            self._update_thumbnail_boxes(self.current_page_idx)  # 썸네일 업데이트
            self.canvas.update()
            self._schedule_auto_save()

    def add_box(self, start: QPoint, end: QPoint):
        """박스 추가"""
        self._save_state_for_undo()  # Undo용 상태 저장
        x1 = int(min(start.x(), end.x()) / self.scale)
        y1 = int(min(start.y(), end.y()) / self.scale)
        x2 = int(max(start.x(), end.x()) / self.scale)
        y2 = int(max(start.y(), end.y()) / self.scale)

        # 해설 입력 모드 체크 시 해설 타입으로 생성
        box_type = BOX_TYPE_SOLUTION if self.solution_mode_checkbox.isChecked() else BOX_TYPE_QUESTION

        box = QuestionBox(
            x1=x1, y1=y1, x2=x2, y2=y2,
            page=self.current_page_idx + 1,
            box_id=self._generate_box_id(),
            theme_id=self._current_theme_id,  # 현재 테마 자동 적용
            box_type=box_type
        )

        if self.current_page_idx not in self.boxes:
            self.boxes[self.current_page_idx] = []

        self.boxes[self.current_page_idx].append(box)
        self.current_box_id = len(self.boxes[self.current_page_idx]) - 1

        # 정렬 목록에 추가하고 재정렬
        self._sorted_boxes.append((self.current_page_idx, box))
        self._sorted_boxes.sort(key=lambda x: self._get_box_sort_key(x[0], x[1]))

        # 현재 테마가 있으면 펼침 상태로 만들기
        if self._current_theme_id:
            self.box_list._collapsed_themes.discard(self._current_theme_id)

        self._update_box_list()
        self._update_thumbnail_boxes(self.current_page_idx)  # 썸네일 업데이트
        self._schedule_auto_save()  # 자동 저장

        # 전체 목록에서 방금 추가한 박스의 인덱스 찾기
        for list_idx, entry in enumerate(self._box_index_map):
            if entry is None:  # 헤더는 건너뛰기
                continue
            page_idx, b = entry
            if page_idx == self.current_page_idx and b is box:
                self.box_list.setCurrentRow(list_idx)
                break

        self.canvas.update()

    def _open_pdf(self):
        """PDF 파일 열기 다이얼로그"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "PDF 파일 선택", "", "PDF files (*.pdf);;All files (*.*)"
        )
        if file_path:
            self._load_pdf(file_path)

    def _load_pdf(self, file_path: str):
        """PDF 파일 로드"""
        self.pdf_path = Path(file_path)
        self.status_label.setText("PDF 로딩 중...")
        QApplication.processEvents()

        try:
            self.pages = convert_from_path(str(self.pdf_path), dpi=150)
            self.current_page_idx = 0
            self.boxes = {i: [] for i in range(len(self.pages))}
            self._sorted_boxes = []  # 정렬 목록 초기화

            # 캔버스를 새로 생성하고 스크롤 영역에 설정 (welcome 메시지 대체)
            self.canvas = ImageCanvas(self)
            self.canvas.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            self.scroll_area.setWidget(self.canvas)

            # 썸네일 패널 표시 (사이드바 상태에 따라)
            if self._sidebar_visible:
                self.thumbnail_panel.show()
                self.sidebar_show_btn.hide()
            else:
                self.sidebar_show_btn.show()

            # 썸네일 생성 (패널이 표시된 후 폭을 정확히 가져오기 위해 약간 지연)
            QTimer.singleShot(100, self._create_thumbnails)

            # 교재 이름 표시
            self.textbook_label.setText(f"📚 {self.pdf_path.stem}")

            # 자동 저장된 데이터가 있으면 로드
            if self._load_auto_saved_data():
                pass  # 이미 status_label 업데이트됨
            else:
                self.status_label.setText(f"로드 완료: {self.pdf_path.name}")

            # 모든 테마를 접힌 상태로 초기화 (삭제된 테마 제외)
            self.box_list._collapsed_themes = set(t.id for t in self.themes if not t.deleted)
            self.box_list._collapsed_themes.add("__none__")  # 미지정 테마도 접기

            # 기본 보기: 화면 폭에 맞춤
            self._fit_to_window()

            # 최근 파일에 추가
            self._add_to_recent_files(str(self.pdf_path.resolve()))

        except Exception as e:
            QMessageBox.critical(self, "오류", f"PDF 로드 실패: {e}")
            self.status_label.setText("PDF 로드 실패")

    def _on_splitter_moved(self, pos, index):
        """스플리터 크기 변경 시 디바운싱으로 썸네일 재렌더링 예약"""
        if not hasattr(self, 'pages') or not self.pages:
            return

        # 1초 후 재렌더링 예약 (기존 타이머 취소 후 재시작)
        self._thumbnail_resize_timer.stop()
        self._thumbnail_resize_timer.start(1000)  # 1초

    def _delayed_thumbnail_resize(self):
        """디바운싱된 썸네일 재렌더링"""
        if not hasattr(self, 'pages') or not self.pages:
            return

        panel_width = self.thumbnail_panel.width()

        # 폭이 크게 변했을 때만 재렌더링
        if abs(panel_width - self._last_thumbnail_width) > 20:
            self._create_thumbnails()
            # 현재 작업 중인 페이지 박스도 다시 표시
            self._update_thumbnail_boxes()
            # 레이아웃 완료 후 현재 페이지로 스크롤 동기화 (지연 필요)
            QTimer.singleShot(50, self._update_thumbnail_highlight)

    def _create_thumbnails(self):
        """페이지 썸네일 생성 - 패널 폭에 맞춰 동적 렌더링"""
        # 기존 썸네일 제거
        while self.thumbnail_list_layout.count():
            item = self.thumbnail_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.thumbnail_buttons = []
        self.thumbnail_base_pixmaps = []  # 원본 썸네일 저장

        # 패널 폭에 맞춰 썸네일 크기 계산 (여백 고려)
        panel_width = self.thumbnail_panel.width()
        thumb_width = max(60, panel_width - 30)  # 최소 60px, 여백 30px
        self._last_thumbnail_width = panel_width

        for idx, page in enumerate(self.pages):
            # 썸네일 크기 (패널 폭 기준)
            aspect_ratio = page.height / page.width
            thumb_height = int(thumb_width * aspect_ratio)

            # PIL -> QPixmap
            thumb_img = page.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
            data = thumb_img.convert("RGB").tobytes("raw", "RGB")
            qimage = QImage(data, thumb_img.width, thumb_img.height, thumb_img.width * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimage)

            self.thumbnail_base_pixmaps.append((pixmap, page.width, page.height))

            # 버튼으로 썸네일 생성
            btn = QPushButton()
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(pixmap.size())
            btn.setFixedSize(thumb_width + 10, thumb_height + 20)
            btn.setToolTip(f"페이지 {idx + 1}")
            btn.setStyleSheet("QPushButton { text-align: center; padding: 2px; }")
            btn.setText(f"{idx + 1}")

            # 클릭 시 해당 페이지로 이동
            btn.clicked.connect(lambda checked, i=idx: self._go_to_page(i))

            self.thumbnail_list_layout.addWidget(btn)
            self.thumbnail_buttons.append(btn)

        # 현재 페이지 강조 (레이아웃 완료 후 스크롤을 위해 지연)
        QTimer.singleShot(50, self._update_thumbnail_highlight)

    def _update_thumbnail_boxes(self, page_idx: Optional[int] = None):
        """썸네일에 박스 표시 업데이트"""
        if not hasattr(self, 'thumbnail_buttons') or not hasattr(self, 'thumbnail_base_pixmaps'):
            return

        # 특정 페이지만 또는 전체 업데이트
        if page_idx is not None:
            indices = [page_idx]
        else:
            indices = range(len(self.thumbnail_buttons))

        for idx in indices:
            if idx >= len(self.thumbnail_buttons) or idx >= len(self.thumbnail_base_pixmaps):
                continue

            base_pixmap, orig_width, orig_height = self.thumbnail_base_pixmaps[idx]
            boxes = self.boxes.get(idx, [])

            # 박스가 없으면 원본 사용
            if not boxes:
                self.thumbnail_buttons[idx].setIcon(QIcon(base_pixmap))
                self.thumbnail_buttons[idx].setIconSize(base_pixmap.size())
                continue

            # 박스가 있으면 복사본에 그리기
            pixmap = base_pixmap.copy()
            painter = QPainter(pixmap)

            # 스케일 계산
            scale_x = pixmap.width() / orig_width
            scale_y = pixmap.height() / orig_height

            for box in boxes:
                # 테마 색상
                color = QColor(0, 0, 255)  # 기본: 파랑
                pen = QPen(color, 1)
                painter.setPen(pen)

                x1 = int(box.x1 * scale_x)
                y1 = int(box.y1 * scale_y)
                x2 = int(box.x2 * scale_x)
                y2 = int(box.y2 * scale_y)
                painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            painter.end()
            self.thumbnail_buttons[idx].setIcon(QIcon(pixmap))
            self.thumbnail_buttons[idx].setIconSize(pixmap.size())

    def _update_thumbnail_highlight(self):
        """현재 페이지 썸네일 강조 및 스크롤"""
        if not hasattr(self, 'thumbnail_buttons'):
            return

        for idx, btn in enumerate(self.thumbnail_buttons):
            if idx == self.current_page_idx:
                btn.setStyleSheet("QPushButton { background-color: #4a90d9; color: white; font-weight: bold; }")
                # 현재 페이지 썸네일이 보이도록 스크롤
                self.thumbnail_scroll.ensureWidgetVisible(btn)
            else:
                btn.setStyleSheet("QPushButton { background-color: none; }")

    def _go_to_page(self, page_idx: int):
        """특정 페이지로 이동"""
        if 0 <= page_idx < len(self.pages):
            self.current_page_idx = page_idx
            self.current_box_id = None
            self._display_page()
            self._update_thumbnail_highlight()

    def _display_page(self):
        """현재 페이지 표시"""
        if not self.pages:
            return

        page = self.pages[self.current_page_idx]

        # PIL -> QPixmap 변환
        new_width = int(page.width * self.scale)
        new_height = int(page.height * self.scale)
        resized = page.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # PIL Image -> QImage -> QPixmap
        data = resized.convert("RGB").tobytes("raw", "RGB")
        qimage = QImage(data, resized.width, resized.height, resized.width * 3, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimage)

        self.canvas.setPixmap(pixmap)
        self.canvas.setFixedSize(pixmap.size())

        self.page_label.setText(f"페이지: {self.current_page_idx + 1} / {len(self.pages)}")
        self._update_box_list()

    def _get_box_sort_key(self, page_idx: int, box: QuestionBox) -> tuple:
        """박스 정렬 키: 페이지 → 좌/우 컬럼 → Y 좌표"""
        # 페이지 중앙을 기준으로 좌/우 컬럼 판단
        if self.pages:
            page_width = self.pages[page_idx].width if page_idx < len(self.pages) else 1000
        else:
            page_width = 1000
        mid_x = page_width / 2

        # 박스 중앙 X 좌표로 좌/우 판단
        box_center_x = (box.x1 + box.x2) / 2
        column = 0 if box_center_x < mid_x else 1  # 0: 왼쪽, 1: 오른쪽

        return (page_idx, column, box.y1)

    def _rebuild_sorted_boxes(self):
        """정렬된 박스 목록 재구성"""
        # 모든 박스를 (page_idx, box) 튜플로 수집
        all_boxes = []
        for page_idx, boxes in self.boxes.items():
            for box in boxes:
                all_boxes.append((page_idx, box))

        # 위치 기준으로 정렬
        self._sorted_boxes = sorted(all_boxes, key=lambda x: self._get_box_sort_key(x[0], x[1]))

    def _collapse_all_themes(self):
        """모든 테마를 접힌 상태로 만들기"""
        self.box_list._collapsed_themes = set(t.id for t in self.themes if not t.deleted)
        self.box_list._collapsed_themes.add("__none__")  # 미지정 테마도 접기
        self._update_box_list()

    def _update_box_list(self):
        """전체 박스 목록 업데이트 (테마별 그룹화)"""
        # 선택된 박스들 저장 (box 객체로 저장)
        selected_boxes = set()
        for item in self.box_list.selectedItems():
            row = self.box_list.row(item)
            if row >= 0 and row < len(self._box_index_map):
                entry = self._box_index_map[row]
                if entry is not None:
                    selected_boxes.add(id(entry[1]))  # box 객체의 id

        self.box_list.clear()
        self._box_index_map = []  # list_idx -> (page_idx, box) 또는 None(헤더)

        # 정렬된 목록이 없거나 박스 수가 다르면 재구성
        total_boxes = sum(len(boxes) for boxes in self.boxes.values())

        # 박스 목록 라벨 업데이트
        self.box_list_label.setText(f"전체 박스 목록 ({total_boxes})")
        if len(self._sorted_boxes) != total_boxes:
            self._rebuild_sorted_boxes()

        # 테마별로 박스 분류
        theme_boxes: Dict[Optional[str], List[tuple]] = {}  # theme_id -> [(page_idx, box), ...]
        for page_idx, box in self._sorted_boxes:
            theme_id = box.theme_id
            if theme_id not in theme_boxes:
                theme_boxes[theme_id] = []
            theme_boxes[theme_id].append((page_idx, box))

        # 페이지별 박스 카운터 (전체 기준)
        page_box_counts: Dict[int, int] = {}
        for page_idx, box in self._sorted_boxes:
            if page_idx not in page_box_counts:
                page_box_counts[page_idx] = 0
            page_box_counts[page_idx] += 1

        # 테마 순서대로 표시 (이름순 정렬 → 미지정, 삭제된 테마 제외)
        # 빈 테마도 표시하기 위해 모든 테마를 순회
        sorted_themes = sorted([t for t in self.themes if not t.deleted], key=lambda t: t.name)
        theme_order = [t.id for t in sorted_themes] + [None]

        # 접힌 테마 정보 가져오기
        collapsed_themes = self.box_list._collapsed_themes

        for theme_id in theme_order:
            boxes_in_theme = theme_boxes.get(theme_id, [])
            theme = self.get_theme_by_id(theme_id) if theme_id else None

            # 미지정(None)은 박스가 있을 때만 표시
            if theme_id is None and not boxes_in_theme:
                continue

            # 접힌 상태 확인
            collapse_key = theme_id if theme_id else "__none__"
            is_collapsed = collapse_key in collapsed_themes
            arrow = "▶" if is_collapsed else "▼"

            # 현재 선택된 테마인지 확인
            is_current_theme = (theme_id == self._current_theme_id)

            # 테마 헤더 추가
            marker = "★ " if is_current_theme else ""
            if theme:
                header_text = f"{arrow} {marker}{theme.name} ({len(boxes_in_theme)})"
            else:
                header_text = f"{arrow} {marker}(미지정) ({len(boxes_in_theme)})"
            header_item = QListWidgetItem(header_text)
            # 현재 테마면 배경색 강조
            if is_current_theme:
                header_item.setBackground(QColor("#d0e8ff"))
            font = header_item.font()
            font.setBold(True)
            header_item.setFont(font)

            # 테마 ID 저장 (클릭 시 사용)
            header_item.setData(Qt.UserRole, theme_id)

            self.box_list.addItem(header_item)
            self._box_index_map.append(None)  # 헤더는 None

            # 접힌 상태면 박스 항목 건너뛰기
            if is_collapsed:
                continue

            # 해당 테마의 박스들을 문제/해설로 분류
            display_theme = theme.name if theme else "미지정"
            questions = [(p, b) for p, b in boxes_in_theme if b.box_type == BOX_TYPE_QUESTION]
            solutions = [(p, b) for p, b in boxes_in_theme if b.box_type == BOX_TYPE_SOLUTION]

            # 문제에 연결된 해설 매핑 생성
            linked_solutions: Dict[str, List[tuple]] = {}  # question_box_id -> [(page_idx, solution_box), ...]
            unlinked_solutions = []
            for p, s in solutions:
                if s.linked_box_id:
                    if s.linked_box_id not in linked_solutions:
                        linked_solutions[s.linked_box_id] = []
                    linked_solutions[s.linked_box_id].append((p, s))
                else:
                    unlinked_solutions.append((p, s))

            # 문제를 순서대로 표시하고, 각 문제 아래에 연결된 해설 표시
            question_index = 0
            for page_idx, box in questions:
                question_index += 1

                # 문제 표시
                label = f"    📝 {display_theme}-{question_index:02d}"
                if box.number:
                    label += f" #{box.number}"

                item = QListWidgetItem(label)
                if page_idx == self.current_page_idx:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)

                self.box_list.addItem(item)
                self._box_index_map.append((page_idx, box))
                if id(box) in selected_boxes:
                    item.setSelected(True)

                # 이 문제에 연결된 해설들 표시 (들여쓰기)
                if box.box_id in linked_solutions:
                    sol_index = 0
                    for sol_page_idx, sol_box in linked_solutions[box.box_id]:
                        sol_index += 1
                        # 테마명-문제순번-해설순번 해설 형식
                        sol_label = f"        └ 📖 {display_theme}-{question_index:02d}-{sol_index:02d} 해설"

                        sol_item = QListWidgetItem(sol_label)
                        sol_item.setForeground(QColor("#666666"))
                        if sol_page_idx == self.current_page_idx:
                            font = sol_item.font()
                            font.setBold(True)
                            sol_item.setFont(font)

                        self.box_list.addItem(sol_item)
                        self._box_index_map.append((sol_page_idx, sol_box))
                        if id(sol_box) in selected_boxes:
                            sol_item.setSelected(True)

            # 미연결 해설 표시 (테마명-순번 해설 형식)
            solution_index = 0
            for page_idx, box in unlinked_solutions:
                solution_index += 1
                label = f"    📖 {display_theme}-{solution_index:02d} 해설 (미연결)"

                item = QListWidgetItem(label)
                item.setForeground(QColor("#cc6600"))  # 주황색으로 미연결 표시
                if page_idx == self.current_page_idx:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)

                self.box_list.addItem(item)
                self._box_index_map.append((page_idx, box))
                if id(box) in selected_boxes:
                    item.setSelected(True)

    def _on_box_select(self, item):
        """박스 선택 - 해당 페이지로 이동 또는 테마 헤더 클릭 시 현재 테마 설정"""
        # Shift/Ctrl 키가 눌린 상태면 멀티 선택 중이므로 페이지 이동 등 추가 동작 안함
        modifiers = QApplication.keyboardModifiers()
        if modifiers & (Qt.ShiftModifier | Qt.ControlModifier):
            return

        list_idx = self.box_list.row(item)
        if list_idx < 0 or list_idx >= len(self._box_index_map):
            return

        # 헤더 클릭 시 해당 테마를 현재 테마로 설정
        map_entry = self._box_index_map[list_idx]
        if map_entry is None:
            # 헤더에서 테마 ID 추출
            theme_id = item.data(Qt.UserRole)
            self._current_theme_id = theme_id
            # UI에 현재 테마 표시
            self._update_current_theme_display()
            # 박스 목록 갱신 (선택된 테마 강조 업데이트)
            self._update_box_list()
            return

        page_idx, box = map_entry

        # 다른 페이지면 이동
        if page_idx != self.current_page_idx:
            self.current_page_idx = page_idx
            self._display_page()
            self._update_thumbnail_highlight()

        # 현재 페이지에서 이 박스의 인덱스 찾기
        boxes = self.boxes.get(self.current_page_idx, [])
        try:
            self.current_box_id = boxes.index(box)
        except ValueError:
            self.current_box_id = None

        self.canvas.update()

        # 레이블 입력 필드 업데이트
        self.number_input.setText(str(box.number) if box.number else "")

        # 테마 콤보박스 업데이트
        idx = 0
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == box.theme_id:
                idx = i
                break
        self.theme_combo.setCurrentIndex(idx)

        # 유형 콤보박스 업데이트
        type_idx = 0
        for i in range(self.type_combo.count()):
            if self.type_combo.itemData(i) == box.box_type:
                type_idx = i
                break
        self.type_combo.setCurrentIndex(type_idx)

        # 연결 콤보박스 업데이트 (풀이인 경우)
        if box.box_type == BOX_TYPE_SOLUTION:
            self.link_label.show()
            self.link_combo.show()
            self._update_link_combo()
            link_idx = 0
            for i in range(self.link_combo.count()):
                if self.link_combo.itemData(i) == box.linked_box_id:
                    link_idx = i
                    break
            self.link_combo.setCurrentIndex(link_idx)
        else:
            self.link_label.hide()
            self.link_combo.hide()

        # 목록에서 현재 선택 항목 다시 선택 (페이지 이동 후에도 유지)
        self.box_list.setCurrentRow(list_idx)

    def _update_current_theme_display(self):
        """현재 테마 표시 업데이트"""
        if self._current_theme_id:
            theme = self.get_theme_by_id(self._current_theme_id)
            theme_name = theme.name if theme else "미지정"
        else:
            theme_name = "미지정"

        book_name = self.pdf_path.stem if self.pdf_path else "(없음)"
        self.textbook_label.setText(f"📚 {book_name}\n🏷️ 현재 테마: {theme_name}")

    def _apply_label(self):
        """레이블 적용"""
        if self.current_box_id is None:
            return

        boxes = self.boxes.get(self.current_page_idx, [])
        if not (0 <= self.current_box_id < len(boxes)):
            return

        box = boxes[self.current_box_id]

        num_text = self.number_input.text().strip()
        box.number = int(num_text) if num_text.isdigit() else None
        old_theme_id = box.theme_id
        box.theme_id = self.theme_combo.currentData()  # 테마 ID

        # 유형 및 연결 정보 저장
        old_box_type = box.box_type
        box.box_type = self.type_combo.currentData()

        # 풀이인 경우만 연결 정보 저장
        if box.box_type == BOX_TYPE_SOLUTION:
            box.linked_box_id = self.link_combo.currentData()
        else:
            box.linked_box_id = None  # 문제는 연결 정보 없음

        self._update_box_list()
        # 테마나 유형이 바뀌면 썸네일도 업데이트
        if old_theme_id != box.theme_id or old_box_type != box.box_type:
            self._update_thumbnail_boxes(self.current_page_idx)
        self.canvas.update()
        self._schedule_auto_save()  # 자동 저장

    def _delete_selected_box(self):
        """선택된 박스 삭제"""
        list_idx = self.box_list.currentRow()
        if list_idx < 0 or list_idx >= len(self._box_index_map):
            return

        map_entry = self._box_index_map[list_idx]
        if map_entry is None:  # 헤더 클릭 시 무시
            return

        self._save_state_for_undo()  # Undo용 상태 저장

        page_idx, box = map_entry

        # boxes 딕셔너리에서 삭제
        if page_idx in self.boxes and box in self.boxes[page_idx]:
            self.boxes[page_idx].remove(box)

        # 정렬 목록에서도 삭제
        if (page_idx, box) in self._sorted_boxes:
            self._sorted_boxes.remove((page_idx, box))

        self.current_box_id = None
        self._update_box_list()
        self._update_thumbnail_boxes(page_idx)  # 썸네일 업데이트
        self.canvas.update()
        self._schedule_auto_save()  # 자동 저장

    def _prev_page(self, scroll_to_bottom: bool = False):
        """이전 페이지"""
        if self.current_page_idx > 0:
            self.current_page_idx -= 1
            self.current_box_id = None
            self._display_page()
            self._update_thumbnail_highlight()
            if scroll_to_bottom:
                # 이전 페이지로 이동 후 맨 아래로 스크롤
                self.scroll_area.verticalScrollBar().setValue(
                    self.scroll_area.verticalScrollBar().maximum()
                )

    def _next_page(self, scroll_to_top: bool = False):
        """다음 페이지"""
        if self.current_page_idx < len(self.pages) - 1:
            self.current_page_idx += 1
            self.current_box_id = None
            self._display_page()
            self._update_thumbnail_highlight()
            if scroll_to_top:
                # 다음 페이지로 이동 후 맨 위로 스크롤
                self.scroll_area.verticalScrollBar().setValue(
                    self.scroll_area.verticalScrollBar().minimum()
                )

    def _zoom_in(self):
        """확대"""
        self.scale = min(3.0, self.scale + 0.1)
        self.zoom_label.setText(f"{int(self.scale * 100)}%")
        self._display_page()

    def _zoom_out(self):
        """축소"""
        self.scale = max(0.2, self.scale - 0.1)
        self.zoom_label.setText(f"{int(self.scale * 100)}%")
        self._display_page()

    def _fit_to_window(self):
        """폭 맞춤 - PDF 폭을 작업 화면 폭에 맞춤"""
        if not self.pages:
            return

        page = self.pages[self.current_page_idx]
        # 스크롤 영역 폭 기준 (스크롤바 여유 포함)
        available_width = self.scroll_area.viewport().width() - 20

        self.scale = available_width / page.width

        self.zoom_label.setText(f"{int(self.scale * 100)}%")
        self._display_page()

    def _save_labels(self):
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

    def _load_labels(self):
        """레이블 불러오기"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "레이블 불러오기", "", "JSON files (*.json)"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 테마 로드 (있는 경우)
            if "themes" in data:
                self.themes = []
                self._theme_counter = 0
                for theme_data in data.get("themes", []):
                    theme = Theme(
                        id=theme_data["id"],
                        name=theme_data["name"],
                        color=theme_data.get("color", "#3498db")
                    )
                    self.themes.append(theme)
                    if theme.id.startswith("theme_"):
                        try:
                            num = int(theme.id.split("_")[1])
                            self._theme_counter = max(self._theme_counter, num)
                        except ValueError:
                            pass
                self._update_theme_list()
                self._update_theme_combo()

            self.boxes = {i: [] for i in range(len(self.pages))}
            self._box_counter = 0
            for box_data in data.get("boxes", []):
                page_idx = box_data.get("page", 1) - 1
                if 0 <= page_idx < len(self.pages):
                    box = QuestionBox(
                        x1=box_data["x1"],
                        y1=box_data["y1"],
                        x2=box_data["x2"],
                        y2=box_data["y2"],
                        number=box_data.get("number"),
                        theme_id=box_data.get("theme_id"),
                        page=box_data.get("page", 1),
                        box_type=box_data.get("box_type", BOX_TYPE_QUESTION),
                        linked_box_id=box_data.get("linked_box_id"),
                        box_id=box_data.get("box_id")
                    )
                    # box_id가 없으면 생성
                    if not box.box_id:
                        box.box_id = self._generate_box_id()
                    else:
                        if box.box_id.startswith("box_"):
                            try:
                                num = int(box.box_id.split("_")[1])
                                self._box_counter = max(self._box_counter, num)
                            except ValueError:
                                pass
                    self.boxes[page_idx].append(box)

            # 정렬 목록 재구성
            self._rebuild_sorted_boxes()

            self._display_page()
            self.status_label.setText(f"불러오기 완료: {len(data.get('boxes', []))}개 박스")

        except Exception as e:
            QMessageBox.critical(self, "오류", f"불러오기 실패: {e}")

    def _export_images(self):
        """박스 영역 이미지 내보내기

        - 교재별 폴더 생성 (PDF 파일명 기준)
        - 파일명: 테마명-순번.png (테마 내 순차 번호)
        - 300 DPI, PNG 무손실 형식
        """
        if not self.pdf_path:
            QMessageBox.warning(self, "경고", "PDF 파일이 열려있지 않습니다.")
            return

        # PDF 파일이 있는 폴더를 기본 위치로 설정
        default_dir = str(self.pdf_path.parent) if self.pdf_path else ""
        output_dir = QFileDialog.getExistingDirectory(self, "이미지 저장 폴더 선택", default_dir)
        if not output_dir:
            return

        output_path = Path(output_dir)

        # 교재명 폴더 생성 (PDF 파일명에서 확장자 제거)
        book_name = self.pdf_path.stem
        book_dir = output_path / book_name
        book_dir.mkdir(parents=True, exist_ok=True)

        self.status_label.setText("고해상도 이미지 생성 중...")
        QApplication.processEvents()

        hires_pages = convert_from_path(str(self.pdf_path), dpi=300)
        scale_factor = 300 / 150

        exported = []

        # 테마별 박스를 페이지 순서대로 수집
        theme_boxes: Dict[str, List[Tuple[int, 'BoundingBox']]] = {}
        for page_idx, boxes in self.boxes.items():
            for box in boxes:
                theme_name = "미분류"
                if box.theme_id:
                    theme = self.get_theme_by_id(box.theme_id)
                    if theme:
                        theme_name = theme.name
                if theme_name not in theme_boxes:
                    theme_boxes[theme_name] = []
                theme_boxes[theme_name].append((page_idx, box))

        # 각 테마 내에서 페이지 순서로 정렬
        for theme_name in theme_boxes:
            theme_boxes[theme_name].sort(key=lambda x: (x[0], x[1].y1, x[1].x1))

        # 테마별 순차 인덱스
        theme_counter: Dict[str, int] = {}

        for page_idx, boxes in self.boxes.items():
            if page_idx >= len(hires_pages):
                continue

            page = hires_pages[page_idx]
            page_num = page_idx + 1  # 1-based 페이지 번호

            for box in boxes:
                x1 = int(box.x1 * scale_factor)
                y1 = int(box.y1 * scale_factor)
                x2 = int(box.x2 * scale_factor)
                y2 = int(box.y2 * scale_factor)

                cropped = page.crop((x1, y1, x2, y2))

                # 테마명 가져오기 (없으면 "미분류")
                theme_name = "미분류"
                theme_info = None
                if box.theme_id:
                    theme = self.get_theme_by_id(box.theme_id)
                    if theme:
                        theme_name = theme.name
                        theme_info = {"id": theme.id, "name": theme.name}

                # 테마 내 순차 인덱스 계산 (페이지 상관없이)
                if theme_name not in theme_counter:
                    theme_counter[theme_name] = 0
                theme_counter[theme_name] += 1
                box_index = theme_counter[theme_name]

                # 파일명: 테마명-순번.png (페이지 번호 제거)
                filename = f"{theme_name}-{box_index:02d}.png"

                # PNG 무손실 저장 (300 DPI 메타데이터 포함)
                cropped.save(
                    book_dir / filename,
                    "PNG",
                    dpi=(300, 300)
                )

                exported.append({
                    "filename": filename,
                    "theme": theme_info,
                    "page": page_num,
                    "index": box_index,
                    "bbox": {"x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2},
                    "box_type": box.box_type
                })

        metadata = {
            "source_pdf": self.pdf_path.name,
            "book_name": book_name,
            "exported_at": datetime.now().isoformat(),
            "total_images": len(exported),
            "dpi": 300,
            "format": "PNG (lossless)",
            "images": exported
        }

        with open(book_dir / "metadata.json", 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        self.status_label.setText(f"내보내기 완료: {len(exported)}개")
        QMessageBox.information(
            self, "완료",
            f"{len(exported)}개 이미지가 내보내기 되었습니다.\n\n"
            f"폴더: {book_dir}\n"
            f"형식: PNG 300 DPI (무손실)"
        )


def main():
    import traceback
    from PyQt5.QtNetwork import QLocalServer, QLocalSocket

    # 전역 예외 핸들러 설정
    def exception_hook(exctype, value, tb):
        print("=" * 50)
        print("예외 발생!")
        print("=" * 50)
        traceback.print_exception(exctype, value, tb)
        print("=" * 50)
        sys.__excepthook__(exctype, value, tb)

    sys.excepthook = exception_hook

    # macOS 메뉴바 앱 이름 설정 (QApplication 생성 전에 설정)
    if sys.platform == "darwin":
        try:
            from Foundation import NSBundle
            bundle = NSBundle.mainBundle()
            info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
            if info:
                info["CFBundleName"] = "문항 레이블러"
        except ImportError:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("문항 레이블러")
    app.setApplicationDisplayName("문항 레이블러")
    app.setOrganizationName("MilliSquare")

    # 싱글톤: 이미 실행 중인 인스턴스 확인
    socket = QLocalSocket()
    socket.connectToServer("PDFLabeler_SingleInstance")
    if socket.waitForConnected(500):
        # 이미 실행 중이면 기존 창 활성화 요청 후 종료
        socket.close()
        print("앱이 이미 실행 중입니다.")
        sys.exit(0)

    # 서버 생성 (다른 인스턴스 감지용)
    server = QLocalServer()
    server.removeServer("PDFLabeler_SingleInstance")  # 이전 서버 정리
    server.listen("PDFLabeler_SingleInstance")

    window = PDFLabeler()
    window.show()

    # 다른 인스턴스에서 연결 시 창 활성화
    def activate_window():
        window.raise_()
        window.activateWindow()

    server.newConnection.connect(activate_window)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
