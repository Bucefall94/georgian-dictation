from __future__ import annotations

import ctypes as ct
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget


class ListeningOverlay(QWidget):
    COLORS = {
        "listening": QColor("#55D6BE"),
        "loading": QColor("#8CA7FF"),
        "processing": QColor("#8CA7FF"),
        "transcribing": QColor("#8CA7FF"),
        "ai_processing": QColor("#B88CFF"),
        "typing": QColor("#F5C76A"),
        "success": QColor("#68DB8B"),
        "error": QColor("#FF6B78"),
    }

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(310, 76)
        self.state = "listening"
        self.label = "გისმენთ"
        self._levels = [0.05] * 10
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_state(self, state: str, label: str = "") -> None:
        self.state = state
        self.label = label or {
            "listening": "გისმენთ",
            "loading": "მოდელი იტვირთება…",
            "processing": "ვამუშავებ…",
            "transcribing": "Transcribing",
            "ai_processing": "AI Processing",
            "typing": "ვწერ…",
            "success": "მზადაა",
            "error": "შეცდომა",
        }.get(state, state)
        self._hide_timer.stop()
        self._position()
        self.show()
        self.raise_()
        self._apply_no_activate()
        if state in ("processing", "loading", "transcribing", "ai_processing"):
            self._timer.start(30)
        else:
            self._timer.stop()
        if state == "success":
            self._hide_timer.start(700)
        elif state == "error":
            self._hide_timer.start(2200)
        self.update()

    def set_level(self, level: float) -> None:
        if self.state != "listening":
            return
        value = max(0.02, min(1.0, float(level)))
        self._levels.pop(0)
        self._levels.append(value)
        self.update()

    def _tick(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def _position(self) -> None:
        app = QApplication.instance()
        screen = app.screenAt(QCursor.pos()) if app else None
        if not screen and app:
            screen = app.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 42)

    def _apply_no_activate(self) -> None:
        if not self.winId():
            return
        user32 = ct.WinDLL("user32", use_last_error=True)
        GWL_EXSTYLE = -20
        WS_EX_TRANSPARENT = 0x20
        WS_EX_TOOLWINDOW = 0x80
        WS_EX_NOACTIVATE = 0x08000000
        hwnd = int(self.winId())
        get_style = user32.GetWindowLongPtrW
        get_style.argtypes = [ct.c_void_p, ct.c_int]
        get_style.restype = ct.c_ssize_t
        set_style = user32.SetWindowLongPtrW
        set_style.argtypes = [ct.c_void_p, ct.c_int, ct.c_ssize_t]
        set_style.restype = ct.c_ssize_t
        style = get_style(hwnd, GWL_EXSTYLE)
        set_style(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shadow = QRectF(4, 6, self.width() - 8, self.height() - 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawRoundedRect(shadow.translated(0, 3), 20, 20)
        painter.setBrush(QColor("#171A20"))
        painter.setPen(QPen(QColor("#303640"), 1))
        painter.drawRoundedRect(shadow, 20, 20)

        color = self.COLORS.get(self.state, QColor("#55D6BE"))
        self._draw_microphone(painter, QPointF(35, 37), color)
        if self.state == "listening":
            self._draw_levels(painter, color)
        elif self.state in ("loading", "processing", "transcribing"):
            self._draw_spinner(painter, color)
        elif self.state == "ai_processing":
            self._draw_ai_processing(painter, color)
        elif self.state == "success":
            self._draw_check(painter, color)
        elif self.state == "error":
            self._draw_error(painter, color)

        painter.setPen(QColor("#F4F6F8"))
        font = QFont()
        font.setPointSize(10)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(153, 18, 135, 38), Qt.AlignVCenter | Qt.AlignLeft, self.label)

    @staticmethod
    def _draw_microphone(p: QPainter, center: QPointF, color: QColor) -> None:
        p.setPen(QPen(color, 2.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(center.x() - 5, center.y() - 12, 10, 18), 5, 5)
        path = QPainterPath()
        path.moveTo(center.x() - 10, center.y())
        path.cubicTo(center.x() - 10, center.y() + 10, center.x() + 10, center.y() + 10, center.x() + 10, center.y())
        p.drawPath(path)
        p.drawLine(QPointF(center.x(), center.y() + 9), QPointF(center.x(), center.y() + 14))
        p.drawLine(QPointF(center.x() - 6, center.y() + 14), QPointF(center.x() + 6, center.y() + 14))

    def _draw_levels(self, p: QPainter, color: QColor) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for i, level in enumerate(self._levels):
            shaped = min(1.0, level * (0.7 + ((i * 7) % 5) * 0.12))
            height = 5 + shaped * 31
            x = 66 + i * 8
            p.drawRoundedRect(QRectF(x, 37 - height / 2, 4, height), 2, 2)

    def _draw_spinner(self, p: QPainter, color: QColor) -> None:
        rect = QRectF(93, 24, 26, 26)
        pen = QPen(color, 3, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, int((-self._angle) * 16), int(245 * 16))

    def _draw_ai_processing(self, p: QPainter, color: QColor) -> None:
        pulse = 1.0 + 0.12 * math.sin(math.radians(self._angle * 2))
        p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        cx, cy = 103.0, 37.0
        radius = 12.0 * pulse
        for rotation in (0, 45):
            angle = math.radians(rotation)
            dx, dy = math.cos(angle) * radius, math.sin(angle) * radius
            p.drawLine(QPointF(cx - dx, cy - dy), QPointF(cx + dx, cy + dy))
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 3.2, 3.2)

    @staticmethod
    def _draw_check(p: QPainter, color: QColor) -> None:
        p.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(88, 37), QPointF(98, 46))
        p.drawLine(QPointF(98, 46), QPointF(119, 25))

    @staticmethod
    def _draw_error(p: QPainter, color: QColor) -> None:
        p.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(91, 27), QPointF(115, 51))
        p.drawLine(QPointF(115, 27), QPointF(91, 51))
