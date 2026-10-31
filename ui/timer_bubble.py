"""桌宠下方的计时气泡。

为什么单独开一个窗口，而不是在 ``PetWindow`` 里加一个子标签：
``PetWindow`` 设置了 ``setMask``（取像素轮廓），子控件落在遮罩之外的部分会被
直接裁掉，气泡贴在猫下方就会消失。因此气泡独立成一个无边框置顶窗口，
由 ``PetWindow`` 负责跟随移动。

气泡是纯展示组件：

- ``WindowTransparentForInput`` + ``WA_TransparentForMouseEvents``：点它等于
  点空气，不会挡住拖动猫的手感，也不会抢焦点；
- ``WA_ShowWithoutActivating``：弹出时不打断用户正在进行的输入；
- 只暴露 ``set_text`` / ``show_near`` / ``hide``，不认识计时器与数据库。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

# 背景与文字：半透明暖黑 + 米白，和像素猫的橘白配色不打架
BACKGROUND = QColor(30, 26, 22, 224)
BORDER_IDLE = QColor(255, 255, 255, 46)
BORDER_ACCENT = QColor(255, 176, 84, 190)
TEXT_COLOR = QColor(255, 244, 232)
RADIUS = 9
PADDING_H = 10
PADDING_V = 4


class TimerBubble(QWidget):
    """显示 ``24:59`` 之类读数的浮动气泡。"""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._text = ""
        self._accent = False
        self._font = QFont("Consolas")
        if not QFontMetrics(self._font).horizontalAdvance("00:00"):
            # 极少数环境没有 Consolas，退回等宽族
            self._font = QFont("Courier New")
        self._font.setPixelSize(13)
        self._font.setBold(True)

    # ---------- 内容 ----------

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str, *, accent: bool = False) -> None:
        """更新读数；内容与强调色都没变时不触发重绘。"""
        if text == self._text and accent == self._accent:
            return
        self._text = text
        self._accent = accent
        self._resize_to_text()
        self.update()

    def _resize_to_text(self) -> None:
        metrics = QFontMetrics(self._font)
        width = metrics.horizontalAdvance(self._text or "00:00") + PADDING_H * 2
        height = metrics.height() + PADDING_V * 2
        self.resize(width, height)

    # ---------- 定位 ----------

    def show_near(self, pet: QWidget) -> None:
        """贴在猫的下方居中显示；下方空间不够时改到上方。"""
        geometry: QRect = pet.frameGeometry()
        screen = pet.screen()
        available = screen.availableGeometry() if screen is not None else geometry

        x = geometry.center().x() - self.width() // 2
        y = geometry.bottom() + 2
        if y + self.height() > available.bottom():
            y = geometry.top() - self.height() - 2
        x = max(available.left(), min(x, available.right() - self.width()))

        self.move(x, y)
        if not self.isVisible():
            self.show()

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(BORDER_ACCENT if self._accent else BORDER_IDLE, 1))
        painter.setBrush(BACKGROUND)
        painter.drawRoundedRect(rect, RADIUS, RADIUS)

        painter.setFont(self._font)
        painter.setPen(TEXT_COLOR)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()
