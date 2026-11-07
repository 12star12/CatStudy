"""专注统计页：一段时间里，时间花在哪些科目上。

布局是"一图一表"：左边环形图给出结构（各科目占比），右边图例给出数字
（时长 + 百分比），顶上五个区间胶囊，底下一条口径说明。

三条取舍：

1. **区间用自然边界**（今天 / 本周 / 本月 / 今年 / 全部），不做"自定义日期
   范围"。这个页要回答的是"我最近的时间花在哪"，不是查账；多一个日期选择器
   就多一层操作，而且真正需要细查时会去学习记录页看日历。
2. **占比按时长，不按次数**。次数会把"25 分钟"和"90 分钟"算成一样重，
   而专注统计关心的恰恰是时间。
3. **没有目标、没有达标线**。只显示结构，不评判结构（不标红"数学占比过低"）。
   猫不索取，统计页也不训人。
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.stats import (
    PERIOD_WEEK,
    PERIODS,
    format_share,
    group_slices,
    period_bounds,
    total_minutes,
)
from core.study_records import StudyRecordRepository
from ui.formatting import format_minutes
from ui.pie_chart import DonutChart, color_for

# 图例里科目名最多显示几个字；完整名字进 tooltip
LEGEND_NAME_LIMIT: int = 8


class StatsView(QWidget):
    """专注统计页（环形图 + 图例 + 区间切换）。"""

    def __init__(
        self,
        repository: StudyRecordRepository,
        parent: QWidget | None = None,
        today_provider=date.today,
    ) -> None:
        super().__init__(parent)
        self._repo = repository
        self._today = today_provider
        self._period: str = PERIOD_WEEK
        self._period_buttons: dict[str, QPushButton] = {}
        self._legend_rows: list[QWidget] = []

        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        root.addLayout(self._build_header())
        root.addWidget(self._build_card(), 1)

        self.hint_label = QLabel("", self)
        self.hint_label.setObjectName("statsHint")
        root.addWidget(self.hint_label)

    def _build_header(self) -> QHBoxLayout:
        title = QLabel("专注统计", self)
        title.setObjectName("statsTitle")

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(title)
        row.addStretch(1)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for period, label in PERIODS:
            button = QPushButton(label, self)
            button.setObjectName("periodButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, value=period: self.set_period(value)
            )
            group.addButton(button)
            self._period_buttons[period] = button
            row.addWidget(button)
        self._period_buttons[self._period].setChecked(True)
        return row

    def _build_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("statsCard")

        box = QHBoxLayout(card)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(18)

        self.chart = DonutChart(card)
        self.chart.setFixedSize(250, 250)
        box.addWidget(self.chart, 0, Qt.AlignmentFlag.AlignVCenter)

        box.addWidget(self._build_legend(card), 1)
        return card

    def _build_legend(self, parent: QWidget) -> QWidget:
        host = QWidget(parent)
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        caption = QLabel("科目占比", host)
        caption.setObjectName("statsCaption")
        outer.addWidget(caption)

        # 图例可能长于可视区（8 块 + 名字），放进滚动区避免把卡片撑高
        self._legend_layout = QVBoxLayout()
        self._legend_layout.setContentsMargins(0, 0, 0, 0)
        self._legend_layout.setSpacing(4)

        rows_host = QWidget(host)
        rows_host.setObjectName("legendHost")
        rows_host.setLayout(self._legend_layout)

        scroll = QScrollArea(host)
        scroll.setObjectName("legendScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(rows_host)
        outer.addWidget(scroll, 1)

        self.empty_label = QLabel("这段时间还没有记录", host)
        self.empty_label.setObjectName("statsEmpty")
        self.empty_label.hide()
        outer.addWidget(self.empty_label)
        return host

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    @property
    def period(self) -> str:
        return self._period

    def set_period(self, period: str) -> None:
        """切换区间并刷新；按钮选中态同步（也供测试直接调用）。"""
        self._period = period
        button = self._period_buttons.get(period)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self.refresh()

    @property
    def legend_count(self) -> int:
        """当前图例行数（测试用）。"""
        return len(self._legend_rows)

    def refresh(self) -> None:
        """按当前区间重查一次数据并重绘。"""
        start, end = period_bounds(self._period, self._today())
        totals = self._repo.subject_totals(start, end)
        slices = group_slices(totals)
        self.chart.set_slices(slices)
        self._rebuild_legend(slices)
        self._update_hint(start, end, slices)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        """每次切到本页都重查：记录是在别的页面里改的。"""
        super().showEvent(event)
        self.refresh()

    # ------------------------------------------------------------------
    # 图例与说明
    # ------------------------------------------------------------------

    def _rebuild_legend(self, slices: list[tuple[str, int]]) -> None:
        # 逐项取出（含上次加的弹簧），否则刷新几次之后底部会堆一串空白
        while self._legend_layout.count():
            item = self._legend_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._legend_rows.clear()

        total = total_minutes(slices)
        self.empty_label.setVisible(not slices)
        if not slices:
            return

        for index, (label, minutes) in enumerate(slices):
            self._legend_layout.addWidget(self._make_legend_row(index, label, minutes, total))
        self._legend_layout.addStretch(1)

    def _make_legend_row(
        self,
        index: int,
        label: str,
        minutes: int,
        total: int,
    ) -> QWidget:
        row = QWidget(self)
        row.setObjectName("legendRow")

        box = QHBoxLayout(row)
        box.setContentsMargins(2, 3, 2, 3)
        box.setSpacing(8)

        swatch = QLabel(row)
        swatch.setObjectName("legendSwatch")
        swatch.setFixedSize(10, 10)
        swatch.setStyleSheet(
            f"background-color: {color_for(index, label).name()}; border-radius: 3px;"
        )

        name = QLabel(self._elide(label), row)
        name.setObjectName("legendName")
        name.setToolTip(label)
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        value = QLabel(f"{format_minutes(minutes)} · {format_share(minutes, total)}", row)
        value.setObjectName("legendValue")
        value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        box.addWidget(swatch)
        box.addWidget(name, 1)
        box.addWidget(value)
        self._legend_rows.append(row)
        return row

    @staticmethod
    def _elide(label: str) -> str:
        if len(label) <= LEGEND_NAME_LIMIT:
            return label
        return label[: LEGEND_NAME_LIMIT - 1] + "…"

    def _update_hint(
        self,
        start,
        end,
        slices: list[tuple[str, int]],
    ) -> None:
        if not slices:
            self.hint_label.setText(
                "这段时间没有带时长的记录。开一个番茄钟，或手动补一条记录。"
            )
            return
        count = self._repo.record_count_in_range(start, end)
        total = total_minutes(slices)
        self.hint_label.setText(
            f"{count} 条记录 · 合计 {format_minutes(total)} · 占比按时长计算"
        )
