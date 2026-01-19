"""이미지 캔버스 모듈 - PDF 위에 박스 그리기"""

from PyQt5.QtWidgets import QLabel
from PyQt5.QtGui import QPainter, QPen, QColor
from PyQt5.QtCore import Qt, QPoint, QRect

from .models import BOX_TYPE_QUESTION, BOX_TYPE_SOLUTION


class ImageCanvas(QLabel):
    """이미지 표시 및 박스 그리기 캔버스

    박스 그리기 방식: 두 번 클릭 (첫 클릭 = 시작점, 두번째 클릭 = 끝점)
    """

    DELETE_BTN_SIZE = 18
    MIN_BOX_SIZE = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent_window = parent
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

        # 박스 그리기 상태
        self._first_corner = None  # 첫 번째 클릭 위치 (QPoint or None)
        self._current_mouse = QPoint()  # 현재 마우스 위치

        # 멀티 해설 모드 (Shift 키)
        self._multi_solution_mode = False
        self._multi_solution_boxes = []  # 멀티 모드에서 그린 해설 박스들

        # 컬럼 가이드
        self.column_guides = []
        self.show_guides = True

    @property
    def parent_window(self):
        """부모 윈도우 안전하게 반환"""
        try:
            if self._parent_window and not self._parent_window.isHidden():
                return self._parent_window
        except RuntimeError:
            pass
        return None

    def is_drawing(self):
        """박스 그리기 중인지 확인"""
        return self._first_corner is not None

    def cancel_drawing(self):
        """박스 그리기 취소"""
        self._first_corner = None
        self._current_mouse = QPoint()
        self.update()
        if self.parent_window:
            self.parent_window.status_label.setText("박스 그리기 취소됨")

    def _get_delete_btn_rect(self, box, scale):
        """삭제 버튼의 사각형 영역 반환"""
        x2 = int(box.x2 * scale)
        y1 = int(box.y1 * scale)
        btn_size = self.DELETE_BTN_SIZE
        return QRect(x2 - btn_size - 2, y1 + 2, btn_size, btn_size)

    def _find_delete_btn_at(self, pos):
        """위치에 있는 삭제 버튼의 박스 인덱스 반환"""
        parent = self.parent_window
        if not parent:
            return None

        boxes = parent.get_current_boxes()
        scale = parent.scale

        # 역순으로 검색 (위에 있는 박스 우선)
        for i in range(len(boxes) - 1, -1, -1):
            btn_rect = self._get_delete_btn_rect(boxes[i], scale)
            # 히트 영역 확장 (클릭하기 쉽게)
            expanded = btn_rect.adjusted(-4, -4, 4, 4)
            if expanded.contains(pos):
                return i
        return None

    def _find_box_at(self, pos):
        """위치에 있는 박스 인덱스 반환 (삭제 버튼 영역 제외)"""
        parent = self.parent_window
        if not parent:
            return None

        boxes = parent.get_current_boxes()
        scale = parent.scale

        for i in range(len(boxes) - 1, -1, -1):
            box = boxes[i]
            x1, y1 = int(box.x1 * scale), int(box.y1 * scale)
            x2, y2 = int(box.x2 * scale), int(box.y2 * scale)
            box_rect = QRect(x1, y1, x2 - x1, y2 - y1)

            if box_rect.contains(pos):
                # 삭제 버튼 영역이면 박스 선택 안함
                btn_rect = self._get_delete_btn_rect(box, scale)
                if btn_rect.adjusted(-4, -4, 4, 4).contains(pos):
                    return None
                return i
        return None

    def mousePressEvent(self, event):
        if not self.pixmap():
            return

        pos = event.pos()

        if event.button() == Qt.LeftButton:
            # 1. 삭제 버튼 클릭 확인
            delete_idx = self._find_delete_btn_at(pos)
            if delete_idx is not None:
                if self.parent_window:
                    self.parent_window.delete_box_on_canvas(delete_idx)
                self._first_corner = None
                self.update()
                return

            # 2. 기존 박스 클릭 확인
            box_idx = self._find_box_at(pos)
            if box_idx is not None:
                if self.parent_window:
                    self.parent_window.select_box_on_canvas(box_idx)
                self._first_corner = None
                self.update()
                return

            # 3. 빈 영역 클릭 = 박스 그리기
            # Shift 키 상태 확인 (멀티 해설 모드)
            shift_pressed = event.modifiers() & Qt.ShiftModifier

            if self._first_corner is None:
                # 첫 번째 클릭: 시작점 설정
                self._first_corner = pos
                self._current_mouse = pos

                # Shift 키로 멀티 모드 시작
                if shift_pressed and self.parent_window and self.parent_window.solution_mode_checkbox.isChecked():
                    if not self._multi_solution_mode:
                        self._multi_solution_mode = True
                        self._multi_solution_boxes = []
                        self.parent_window.status_label.setText("멀티 해설 모드: 여러 박스 그리기 (Shift 떼면 완료)")

                self.update()
                if self.parent_window:
                    if self._multi_solution_mode:
                        count = len(self._multi_solution_boxes)
                        self.parent_window.status_label.setText(f"멀티 해설 모드 ({count}개) - 두 번째 클릭으로 박스 완성")
                    else:
                        self.parent_window.status_label.setText("두 번째 클릭으로 박스 완성 (ESC/우클릭: 취소)")
            else:
                # 두 번째 클릭: 박스 생성
                self._complete_box(pos, shift_pressed)

        elif event.button() == Qt.RightButton:
            if self._first_corner is not None:
                # 그리기 중이면 취소
                self.cancel_drawing()
            else:
                # 박스 위에서 우클릭하면 삭제
                box_idx = self._find_box_at(pos)
                if box_idx is not None and self.parent_window:
                    self.parent_window.delete_box_on_canvas(box_idx)

    def _complete_box(self, end_point, shift_pressed=False):
        """박스 그리기 완료"""
        start = self._first_corner

        # 상태 초기화 (먼저!)
        self._first_corner = None
        self._current_mouse = QPoint()

        # 화면 갱신 (녹색 프리뷰 제거)
        self.update()

        # 크기 확인
        width = abs(end_point.x() - start.x())
        height = abs(end_point.y() - start.y())

        if width >= self.MIN_BOX_SIZE and height >= self.MIN_BOX_SIZE:
            if self.parent_window:
                # 멀티 해설 모드인 경우
                if self._multi_solution_mode:
                    box = self.parent_window.add_box(start, end_point, skip_dialog=True)
                    if box:
                        self._multi_solution_boxes.append(box)
                    count = len(self._multi_solution_boxes)
                    self.parent_window.status_label.setText(f"멀티 해설 모드 ({count}개 추가됨) - Shift 떼면 문항 연결")
                else:
                    self.parent_window.add_box(start, end_point)
                    self.parent_window.status_label.setText("박스가 추가되었습니다")
        else:
            if self.parent_window:
                self.parent_window.status_label.setText(
                    f"박스가 너무 작습니다 ({self.MIN_BOX_SIZE}px 이상 필요)"
                )

    def mouseMoveEvent(self, event):
        pos = event.pos()

        if self._first_corner is not None:
            # 그리기 중: 프리뷰 업데이트
            self._current_mouse = pos
            self.update()
        else:
            # 커서 변경
            if self._find_delete_btn_at(pos) is not None:
                self.setCursor(Qt.PointingHandCursor)
            elif self._find_box_at(pos) is not None:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        # 클릭 모드에서는 릴리즈 무시
        pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self._first_corner is not None:
                self.cancel_drawing()
                return
            # 멀티 모드 취소
            if self._multi_solution_mode:
                self._multi_solution_mode = False
                self._multi_solution_boxes = []
                if self.parent_window:
                    self.parent_window.status_label.setText("멀티 해설 모드 취소됨")
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Shift 키를 떼면 멀티 해설 모드 종료"""
        if event.key() == Qt.Key_Shift:
            if self._multi_solution_mode and self._multi_solution_boxes:
                boxes = self._multi_solution_boxes.copy()
                self._multi_solution_mode = False
                self._multi_solution_boxes = []
                # 부모에게 다이얼로그 표시 요청
                if self.parent_window:
                    self.parent_window._show_solution_link_dialog(boxes)
            elif self._multi_solution_mode:
                # 박스 없이 Shift 떼면 모드만 종료
                self._multi_solution_mode = False
                if self.parent_window:
                    self.parent_window.status_label.setText("멀티 해설 모드 종료 (박스 없음)")
        super().keyReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)

        if not self.pixmap():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        try:
            self._draw_column_guides(painter)
            self._draw_boxes(painter)
            self._draw_preview(painter)
        except Exception:
            pass
        finally:
            painter.end()

    def _draw_column_guides(self, painter):
        """컬럼 가이드 그리기"""
        if not self.show_guides or not self.column_guides:
            return

        parent = self.parent_window
        if not parent:
            return

        scale = parent.scale
        height = self.pixmap().height()

        guide_pen = QPen(QColor(100, 100, 255, 80), 1, Qt.DashLine)
        painter.setPen(guide_pen)

        for x1, x2 in self.column_guides:
            sx1, sx2 = int(x1 * scale), int(x2 * scale)
            painter.drawLine(sx1, 0, sx1, height)
            painter.drawLine(sx2, 0, sx2, height)
            painter.fillRect(sx1, 0, sx2 - sx1, height, QColor(100, 100, 255, 15))

    def _draw_boxes(self, painter):
        """기존 박스들 그리기"""
        parent = self.parent_window
        if not parent:
            return

        boxes = parent.get_current_boxes()
        selected_idx = parent.current_box_id
        scale = parent.scale

        # 박스 번호 계산
        box_labels = self._compute_box_labels(parent)

        for i, box in enumerate(boxes):
            x1, y1 = int(box.x1 * scale), int(box.y1 * scale)
            x2, y2 = int(box.x2 * scale), int(box.y2 * scale)

            # 선택된 박스는 빨간색, 아니면 파란색
            is_selected = (i == selected_idx)
            color = QColor(255, 0, 0) if is_selected else QColor(0, 0, 255)

            # 박스 테두리
            pen = QPen(color, 2)
            if box.box_type == BOX_TYPE_SOLUTION:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            # 라벨
            self._draw_box_label(painter, box, x1, y1, color, box_labels, parent)

            # 삭제 버튼
            self._draw_delete_button(painter, x2, y1)

    def _compute_box_labels(self, parent):
        """박스별 테마 내 순번 계산"""
        box_labels = {}
        theme_counts = {}

        for page_idx, b in parent._sorted_boxes:
            theme_id = b.theme_id or "__none__"
            if theme_id not in theme_counts:
                theme_counts[theme_id] = 0
            theme_counts[theme_id] += 1
            box_labels[id(b)] = theme_counts[theme_id]

        return box_labels

    def _draw_box_label(self, painter, box, x, y, color, box_labels, parent):
        """박스 라벨 그리기 (전체박스목록과 동일한 형식)"""
        box_num = box_labels.get(id(box), 1)
        is_question = box.box_type == BOX_TYPE_QUESTION

        theme_name = "미지정"
        if box.theme_id:
            theme = parent.get_theme_by_id(box.theme_id)
            if theme:
                theme_name = theme.name

        if is_question:
            # 문제: 📝 테마명-01
            label = f"📝 {theme_name}-{box_num:02d}"
        else:
            # 해설: 📖 테마명-01 해설
            if box.linked_box_id:
                # 연결된 해설 - 연결된 문제 번호 찾기
                linked_q_num = self._find_linked_question_num(box, parent)
                if linked_q_num:
                    label = f"📖 {theme_name}-{linked_q_num:02d} 해설"
                else:
                    label = f"📖 {theme_name}-{box_num:02d} 해설"
            else:
                label = f"📖 {theme_name}-{box_num:02d} 해설 (미연결)"

        pen = QPen(color, 1)
        pen.setStyle(Qt.SolidLine)
        painter.setPen(pen)
        painter.drawText(x, y - 5, label)

    def _find_linked_question_num(self, solution_box, parent):
        """해설이 연결된 문제의 순번 찾기"""
        if not solution_box.linked_box_id or not parent:
            return None

        # 같은 테마의 문제들 수집
        questions = []
        for page_idx, page_boxes in parent.boxes.items():
            for box in page_boxes:
                if box.box_type == BOX_TYPE_QUESTION and box.theme_id == solution_box.theme_id:
                    questions.append((page_idx, box))

        # 정렬
        questions.sort(key=lambda x: parent._get_box_sort_key(x[0], x[1]))

        # 연결된 문제의 순번 찾기
        for idx, (page_idx, box) in enumerate(questions, 1):
            if box.box_id == solution_box.linked_box_id:
                return idx
        return None

    def _draw_delete_button(self, painter, x2, y1):
        """삭제 버튼 그리기"""
        btn_size = self.DELETE_BTN_SIZE
        btn_x = x2 - btn_size - 2
        btn_y = y1 + 2

        # 빨간 원
        painter.setBrush(QColor(220, 53, 69))
        painter.setPen(QPen(QColor(220, 53, 69), 1))
        painter.drawEllipse(btn_x, btn_y, btn_size, btn_size)

        # 흰색 X
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        margin = 5
        painter.drawLine(btn_x + margin, btn_y + margin,
                         btn_x + btn_size - margin, btn_y + btn_size - margin)
        painter.drawLine(btn_x + btn_size - margin, btn_y + margin,
                         btn_x + margin, btn_y + btn_size - margin)

        painter.setBrush(Qt.NoBrush)

    def _draw_preview(self, painter):
        """그리기 중인 박스 프리뷰"""
        if self._first_corner is None:
            return

        pen = QPen(QColor(0, 200, 0), 2, Qt.DashLine)
        painter.setPen(pen)

        rect = QRect(self._first_corner, self._current_mouse).normalized()
        painter.drawRect(rect)

        # 첫 번째 클릭 위치 표시 (작은 원)
        painter.setBrush(QColor(0, 200, 0))
        painter.drawEllipse(self._first_corner, 4, 4)
        painter.setBrush(Qt.NoBrush)
