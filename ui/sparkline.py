"""净资产走势的小折线（sparkline）。

为什么自己画而不是引图表库：这里只需要"一条线 + 一点填充"，引入
matplotlib / pyqtgraph 会让依赖多几十 MB、启动慢一截，而且它们的默认样式
（白底、网格、图例）与笔记本风冲突，改起来比自己画更费事。

约定：

- 只接受"旧 → 新"顺序的数值（``AccountRepository.list_snapshots`` 就是这么返回的）；
- 数据不足两点时不去猜趋势，画一条基线并说明；
- 净值跨越 0 时画一条零线，负资产一眼能看出来。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ui.theme import Palette

# 控件推荐高度；父容器给更大的高度也不会变形（按实际高度绘制）
PREFERRED_HEIGHT: int = 58

PADDING_TOP: int = 6
PADDING_BOTTOM: int = 6
# 左右留白：末端圆点如果正好压在边框上会显得像被裁掉
PADDING_SIDE: int = 6

# 纵向留白比例：不留余量时最高点会贴顶、最低点会贴底，波动看起来比实际剧烈。
# 0.25 意味着"数据只占纵向的 2/3"，折线填满卡片时也不会像过山车
RANGE_MARGIN_RATIO: float = 0.25


class Sparkline(QWidget):
    """一条表示趋势的折线。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: list[int] = []
        self.setMinimumHeight(PREFERRED_HEIGHT)
        # 纵向也允许伸展：卡片下方常有剩余空间，让它吃掉比留一块空白好看
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    # ---------- 数据 ----------

    def set_values(self, values: list[int]) -> None:
        """设置数值序列（旧 → 新，单位：分）。"""
        self._values = [int(v) for v in values]
        self.update()

    @property
    def values(self) -> list[int]:
        return list(self._values)

    def has_enough_data(self) -> bool:
        return len(self._values) >= 2

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect())
        if rect.width() <= 4 or rect.height() <= 4:
            painter.end()
            return

        if not self.has_enough_data():
            self._paint_placeholder(painter, rect)
            painter.end()
            return

        plot = rect.adjusted(
            PADDING_SIDE, PADDING_TOP, -PADDING_SIDE, -PADDING_BOTTOM
        )
        low = float(min(self._values))
        high = float(max(self._values))
        if high == low:
            # 所有快照金额相同：给一点纵向余量，否则线会贴在一条边上
            high += 1.0
            low -= 1.0
        margin = (high - low) * RANGE_MARGIN_RATIO
        low -= margin
        high += margin
        span = high - low

        def y_of(value: int) -> float:
            ratio = (value - low) / span
            return plot.bottom() - ratio * plot.height()

        step = plot.width() / (len(self._values) - 1)
        points = [
            QPointF(plot.left() + index * step, y_of(value))
            for index, value in enumerate(self._values)
        ]

        # 零线：有负债且资产不足时，净值会掉到 0 以下，这条线让"负"变得直观
        if low < 0 < high:
            pen = QPen(QColor(Palette.RULE), 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            zero_y = y_of(0)
            painter.drawLine(QPointF(plot.left(), zero_y), QPointF(plot.right(), zero_y))

        # 折线下方的淡色填充
        area = QPainterPath(QPointF(points[0].x(), plot.bottom()))
        for point in points:
            area.lineTo(point)
        area.lineTo(QPointF(points[-1].x(), plot.bottom()))
        area.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        fill = QColor(Palette.ROSE_SOFT)
        fill.setAlpha(110)
        painter.setBrush(fill)
        painter.drawPath(area)

        # 折线
        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)
        pen = QPen(QColor(Palette.ROSE), 2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(line)

        # 末端点：标出"现在"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Palette.ROSE))
        painter.drawEllipse(points[-1], 3.0, 3.0)

        painter.end()

    def _paint_placeholder(self, painter: QPainter, rect: QRectF) -> None:
        """数据不足时的占位：一条基线 + 一句说明。"""
        middle = rect.center().y()
        pen = QPen(QColor(Palette.RULE), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(
            QPointF(rect.left() + PADDING_SIDE, middle),
            QPointF(rect.right() - PADDING_SIDE, middle),
        )

        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor(Palette.INK_MUTED))
        text = "改动余额后开始记录走势" if not self._values else "再记录一天就能看到走势"
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
