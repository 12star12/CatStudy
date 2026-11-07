"""科目占比环形图。

一个自绘控件，只做一件事：把"哪些科目、各占多少"画成一个环，并在中心写合计。
不引图表库（这个项目除 PySide6 外不装东西），也不做交互（悬停高亮、点击钻取
这些在 8 个扇区、14 个科目的规模上只会让人分心）。

三条取舍：

1. **环形而不是实心饼**：中心那块空白正好放合计时长——这是用户最先想看的
   数字，放在图例里反而要额外扫一眼。
2. **扇区最多 8 块**（在 ``core/stats.py`` 里合并）：14 个科目画成 14 条细线
   谁也读不出来，末位合并成"其他"并给中性灰。
3. **环形用布尔运算挖出来**（``addEllipse`` 相减），不用"先画饼再拿背景色
   盖一个圆"：后者要求洞的颜色与卡片底色完全一致，换主题就穿帮；也不用
   ``CompositionMode_Clear``，那在子控件上会把父窗口画好的纸面一起抹掉。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from core.stats import OTHERS_LABEL, total_minutes
from ui.formatting import format_total
from ui.theme import Palette

# 扇区颜色：以橘系为主，混入绿/玫红/紫/青，保证相邻两块能区分；
# 全部落在暖色范围内，和纸面不打架。
SLICE_COLORS: tuple[str, ...] = (
    "#FBB054",  # 橘
    "#EB7E35",  # 暗橘
    "#8FCF9B",  # 完成绿
    "#F29391",  # 玫红
    "#7FB8C9",  # 灰青
    "#C9A9D6",  # 淡紫
    "#E3B23C",  # 芥末黄
    "#B98A63",  # 焦糖
)
# "其他"用中性灰：它是收纳项，不该抢颜色
OTHERS_COLOR: str = "#C9BDB1"

# 环的厚度（占半径比例）与扇区之间的缝隙（角度）
THICKNESS_RATIO: float = 0.30
GAP_DEGREES: float = 1.2
# 起点在 12 点方向，顺时针排布（与阅读顺序一致）
START_DEGREES: float = 90.0


def color_for(index: int, label: str) -> QColor:
    """第 ``index`` 块的颜色；"其他"固定中性灰。"""
    if label == OTHERS_LABEL:
        return QColor(OTHERS_COLOR)
    return QColor(SLICE_COLORS[index % len(SLICE_COLORS)])


def donut_path(
    outer: QRectF,
    inner: QRectF,
    start: float,
    span: float,
) -> QPainterPath:
    """一块环形扇区：外弧 + 内弧反向 + 两条半径收口。

    ``span`` 为负表示顺时针。整圆（|span| ≥ 360）走布尔相减，
    因为 ``arcTo`` 在 360° 时某些 Qt 版本画不出东西。
    """
    if abs(span) >= 359.9:
        ring = QPainterPath()
        ring.addEllipse(outer)
        hole = QPainterPath()
        hole.addEllipse(inner)
        return ring.subtracted(hole)

    path = QPainterPath()
    path.arcMoveTo(outer, start)
    path.arcTo(outer, start, span)
    path.arcTo(inner, start + span, -span)
    path.closeSubpath()
    return path


class DonutChart(QWidget):
    """科目占比环形图；数据由 :meth:`set_slices` 注入。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slices: list[tuple[str, int]] = []
        self.setMinimumSize(200, 200)

    # ---------- 数据 ----------

    def set_slices(self, slices: list[tuple[str, int]]) -> None:
        self._slices = [(str(name), max(0, int(minutes))) for name, minutes in slices]
        self.update()

    @property
    def slices(self) -> list[tuple[str, int]]:
        return list(self._slices)

    @property
    def total(self) -> int:
        return total_minutes(self._slices)

    # ---------- 绘制 ----------

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名风格)
        return QSize(240, 240)

    def _ring_rects(self) -> tuple[QRectF, QRectF]:
        side = min(self.width(), self.height())
        # 留 8px 余量，避免抗锯齿边缘被窗口裁掉
        diameter = max(0, side - 16)
        thickness = diameter / 2.0 * THICKNESS_RATIO
        outer = QRectF(
            (self.width() - diameter) / 2.0,
            (self.height() - diameter) / 2.0,
            diameter,
            diameter,
        )
        inner_d = diameter - thickness * 2.0
        inner = QRectF(
            outer.x() + thickness,
            outer.y() + thickness,
            inner_d,
            inner_d,
        )
        return outer, inner

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            outer, inner = self._ring_rects()
            total = self.total
            if total <= 0 or not self._slices:
                self._paint_empty(painter, outer, inner)
                return
            angle = START_DEGREES
            for index, (label, minutes) in enumerate(self._slices):
                span = -360.0 * minutes / total
                if abs(span) > GAP_DEGREES * 3:
                    start = angle - GAP_DEGREES / 2.0
                    draw_span = span + GAP_DEGREES
                else:
                    start, draw_span = angle, span
                painter.setBrush(color_for(index, label))
                painter.drawPath(donut_path(outer, inner, start, draw_span))
                angle += span
            self._paint_center(painter, outer)
        finally:
            painter.end()

    def _paint_empty(self, painter: QPainter, outer: QRectF, inner: QRectF) -> None:
        """没有数据时画一圈浅色底环 + 一句提示，而不是空白。"""
        thickness = (outer.width() - inner.width()) / 2.0
        pen = QPen(QColor(Palette.BORDER), thickness)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(
            outer.adjusted(thickness / 2.0, thickness / 2.0, -thickness / 2.0, -thickness / 2.0)
        )

        font = QFont()
        font.setPixelSize(max(13, int(outer.height() * 0.075)))
        painter.setFont(font)
        painter.setPen(QColor(Palette.INK_MUTED))
        painter.drawText(
            outer, Qt.AlignmentFlag.AlignCenter, "这段时间\n还没有记录"
        )

    def _paint_center(self, painter: QPainter, outer: QRectF) -> None:
        total_font = QFont()
        total_font.setBold(True)
        total_font.setPixelSize(max(18, int(outer.height() * 0.13)))
        painter.setFont(total_font)
        painter.setPen(QColor(Palette.INK_STRONG))
        text_rect = QRectF(outer.x(), outer.y() + outer.height() * 0.34,
                           outer.width(), outer.height() * 0.20)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter,
            format_total(self.total),
        )

        sub_font = QFont()
        sub_font.setPixelSize(max(11, int(outer.height() * 0.058)))
        painter.setFont(sub_font)
        painter.setPen(QColor(Palette.INK_MUTED))
        sub_rect = QRectF(outer.x(), outer.y() + outer.height() * 0.53,
                          outer.width(), outer.height() * 0.16)
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignCenter,
            f"{len(self._slices)} 个科目",
        )
