"""学习记录视图：左科目页签 + 中记录列表 + 右日历卡片。

版面参考了笔记本风格的参考图：左侧螺旋装订旁挂一排科目页签，中间是
"纸上的一条条记录"，右侧是独立的日历卡片。三栏职责互不重叠：

- **左栏（科目标签）**：由数据库里出现过的科目动态生成，点一下只看该科；
  不写死清单，新记了一个科目就自动多一个标签；
- **中栏（记录列表）**：选中日期当天的记录，双击行可编辑；
- **右栏（日历卡片）**：月份导航 + 月历 + 今日合计 / 连续打卡。

职责边界不变：
- **不出现任何 SQL**，全部读写都走 ``StudyRecordRepository``；
- 不做模态框以外的事情：新增/编辑的弹窗、删除确认都封装成
  可替换的方法（``_ask_record`` / ``_confirm_delete``），
  这样界面逻辑可以被单测覆盖，而不会卡在模态事件循环里。

数据加载分两级，避免每次点日期都全表扫描：
- 切换月份时用 ``list_by_date_range`` 一次取回整月，只用来给月历打标记；
- 点某一天时用 ``list_by_date`` 取当天记录，用来填表格。
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtGui import QColor, QPalette, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QSizePolicy,
    QCalendarWidget,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.study_records import StudyRecord, StudyRecordRepository
from ui.formatting import (
    flatten_content,
    format_day_title,
    format_duration,
    format_month_title,
    format_summary,
)
from ui.record_dialog import RecordDialog
from ui.theme import Palette

# 表格列定义：科目 / 时长 / 学习内容
TABLE_HEADERS: tuple[str, ...] = ("科目", "时长", "学习内容")

# 「学习内容」列在表格里最多显示多少字，超出以省略号收尾（完整内容见悬浮提示）
CONTENT_PREVIEW_LIMIT: int = 60

# 科目标签里"不过滤"的那一项
SUBJECT_TAB_ALL: str = "全部"

# 左栏与右栏的固定宽度：中间列表吃掉剩余空间，窗口拉宽时不会把日历挤变形
RAIL_WIDTH: int = 116
CARD_WIDTH: int = 288


class _NoFocusRectDelegate(QStyledItemDelegate):
    """去掉单元格外面的虚线焦点框。

    表格是只读的（双击才改），但 Qt 仍会在当前单元格上画一个焦点框，
    看着像"这里可以输入"，容易误导。选中态本身已经由整行高亮表达，
    所以直接把焦点框状态抹掉即可，键盘导航不受影响。
    """

    def paint(self, painter, option, index) -> None:  # noqa: ANN001 (Qt 回调签名)
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class StudyRecordView(QWidget):
    """学习记录主视图。"""

    def __init__(
        self,
        repository: StudyRecordRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repository

        # 当前显示日的记录，供"按选中行取记录"使用
        self._records: list[StudyRecord] = []
        # 已套用自定义格式的日期，换月时用于逐条清除
        self._decorated_dates: set[date] = set()
        # 程序化改日期时抑制 selectionChanged 触发的重复刷新
        self._suppress_selection: bool = False
        # 当前科目筛选；None 表示"全部"
        self._subject_filter: str | None = None
        # 科目名 -> 页签按钮，用于同步选中态
        self._subject_buttons: dict[str, QPushButton] = {}

        self._build_ui()
        self._connect_signals()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(14)
        root.addWidget(self._build_subject_rail())
        root.addWidget(self._build_record_panel(), 1)
        root.addWidget(self._build_calendar_card())

    def _build_subject_rail(self) -> QWidget:
        """左栏：科目标签页。按钮在 ``_rebuild_subject_tabs`` 里动态生成。"""
        rail = QFrame(self)
        rail.setObjectName("subjectRail")
        rail.setFixedWidth(RAIL_WIDTH)

        box = QVBoxLayout(rail)
        box.setContentsMargins(0, 6, 6, 0)
        box.setSpacing(8)

        title = QLabel("科目", rail)
        title.setObjectName("railTitle")
        box.addWidget(title)

        self._subject_layout = QVBoxLayout()
        self._subject_layout.setSpacing(8)
        box.addLayout(self._subject_layout)
        box.addStretch(1)
        return rail

    def _build_record_panel(self) -> QWidget:
        """中栏：当天记录列表（纸面 + 一条条记录）。"""
        panel = QFrame(self)
        panel.setObjectName("paperPanel")

        box = QVBoxLayout(panel)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)

        self.day_title = QLabel("", panel)
        self.day_title.setObjectName("dayTitleLabel")

        self.summary_label = QLabel("", panel)
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(self.day_title)
        header.addStretch(1)
        header.addWidget(self.summary_label)

        self.table = QTableWidget(0, len(TABLE_HEADERS), panel)
        self.table.setObjectName("recordTable")
        self.table.setHorizontalHeaderLabels(list(TABLE_HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setItemDelegate(_NoFocusRectDelegate(self.table))

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 96)
        # 表头必须直接设样式：全局 QSS 里的 `QHeaderView::section` 优先级更高，
        # 用 id 选择器写 `QTableWidget#recordTable QHeaderView` 实测盖不住它，
        # 结果是一条突兀的浅色横带。直接给这个 header 挂样式最稳。
        header_view.setStyleSheet(
            "QHeaderView::section {"
            f" background-color: {Palette.PAPER_DEEP};"
            " border: none;"
            f" border-bottom: 1px solid {Palette.RULE};"
            f" color: {Palette.INK_MUTED};"
            " padding: 4px 8px;"
            "}"
        )
        header_view.viewport().setAutoFillBackground(False)

        # 空状态提示：没有任何记录时顶替空白表格，告诉用户下一步做什么
        self.empty_hint = QLabel(
            "这一天还没有记录，点「新增记录」，或让猫开一个番茄钟", panel
        )
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.hide()

        self.add_button = QPushButton("＋ 新增记录", panel)
        self.add_button.setObjectName("primaryButton")
        self.edit_button = QPushButton("编辑", panel)
        self.delete_button = QPushButton("删除", panel)
        self.delete_button.setObjectName("dangerButton")

        hint = QLabel("双击一行即可编辑", panel)
        hint.setObjectName("emptyHint")

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        actions.addWidget(hint)

        box.addLayout(header)
        box.addWidget(self.table, 1)
        box.addWidget(self.empty_hint)
        box.addLayout(actions)
        return panel

    def _build_calendar_card(self) -> QWidget:
        """右栏：日历卡片（月份导航 + 月历 + 今日/连续打卡）。"""
        card = QFrame(self)
        card.setObjectName("calendarCard")
        card.setFixedWidth(CARD_WIDTH)

        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)

        self.prev_button = QPushButton("‹", card)
        self.prev_button.setObjectName("cardNavButton")
        self.prev_button.setToolTip("上个月")

        self.next_button = QPushButton("›", card)
        self.next_button.setObjectName("cardNavButton")
        self.next_button.setToolTip("下个月")

        self.month_label = QLabel("", card)
        self.month_label.setObjectName("monthLabel")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        nav = QHBoxLayout()
        nav.setSpacing(4)
        nav.addWidget(self.prev_button)
        nav.addWidget(self.month_label, 1)
        nav.addWidget(self.next_button)

        self.calendar = QCalendarWidget(card)
        self.calendar.setObjectName("calendar")
        # 用自绘的导航栏替代日历自带的那一条，避免出现两套切换按钮
        self.calendar.setNavigationBarVisible(False)
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        # 星期行改用自绘：日历内置表头的底色由 Qt 自己画（系统灰 #E9E7E3），
        # QSS 与调色板都改不动，跟暖色纸面格格不入。关掉它，自己排一行标签，
        # 宽度在每个列的坐标上对齐（见 _align_weekday_row）。
        self.calendar.setHorizontalHeaderFormat(
            QCalendarWidget.HorizontalHeaderFormat.NoHorizontalHeader
        )
        self.calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        # 纵向按内容高度：给 stretch 会让行距被撑得很稀，写死高度又会在月末
        # 只剩 5 行时留一截空白，交给 sizeHint 最稳
        # 高度取中间值：QCalendarWidget 的 sizeHint 只有 120px，6 行日期会挤在一起；
        # 撑满整张卡片又会把行距拉得很稀。实测 200px 时一行约 29px，最舒服。
        self.calendar.setFixedHeight(200)
        self._apply_weekday_formats()

        self._weekday_row = QWidget(card)
        self._weekday_layout = QHBoxLayout(self._weekday_row)
        self._weekday_layout.setContentsMargins(0, 0, 0, 0)
        self._weekday_layout.setSpacing(0)
        for name in ("一", "二", "三", "四", "五", "六", "日"):
            label = QLabel(name, self._weekday_row)
            label.setObjectName("weekdayLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._weekday_layout.addWidget(label, 1)

        divider = QFrame(card)
        divider.setObjectName("divider")
        divider.setFixedHeight(1)

        today_caption = QLabel("今日", card)
        today_caption.setObjectName("statLabel")
        self.today_stat = QLabel("—", card)
        self.today_stat.setObjectName("statValue")

        streak_caption = QLabel("连续打卡", card)
        streak_caption.setObjectName("statLabel")
        self.streak_stat = QLabel("—", card)
        self.streak_stat.setObjectName("statValue")

        today_block = QVBoxLayout()
        today_block.setSpacing(2)
        today_block.addWidget(today_caption)
        today_block.addWidget(self.today_stat)

        streak_block = QVBoxLayout()
        streak_block.setSpacing(2)
        streak_block.addWidget(streak_caption)
        streak_block.addWidget(self.streak_stat)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        stats.addLayout(today_block)
        stats.addStretch(1)
        stats.addLayout(streak_block)

        self.today_button = QPushButton("回到今天", card)
        self.today_button.setObjectName("linkButton")
        self.today_button.setToolTip("跳转到今天")

        box.addLayout(nav)
        box.addWidget(self._weekday_row)
        box.addWidget(self.calendar)
        box.addStretch(1)
        box.addWidget(divider)
        box.addLayout(stats)
        box.addWidget(self.today_button)
        return card

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        super().showEvent(event)
        # 列宽要等布局算完才准，因此对齐放在显示之后做
        self._align_weekday_row()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        super().resizeEvent(event)
        self._align_weekday_row()

    def _align_weekday_row(self) -> None:
        """让自绘的星期行与日历网格逐列对齐。

        日历内部视图相对日历本身有若干像素的边距，直接把标签行铺满卡片会整体
        偏几像素；这里读出视图的真实位置，转成标签行的左右边距。
        """
        view = self.calendar.findChild(QAbstractItemView)
        if view is None:
            return
        offset = view.mapTo(self.calendar, QPoint(0, 0)).x()
        right = max(self.calendar.width() - offset - view.width(), 0)
        self._weekday_layout.setContentsMargins(offset, 0, right, 0)

    def _connect_signals(self) -> None:
        self.prev_button.clicked.connect(self.show_previous_month)
        self.next_button.clicked.connect(self.show_next_month)
        self.today_button.clicked.connect(self.go_to_today)
        self.calendar.selectionChanged.connect(self._on_selection_changed)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(lambda _index: self.edit_record())
        self.add_button.clicked.connect(self.add_record)
        self.edit_button.clicked.connect(self.edit_record)
        self.delete_button.clicked.connect(self.delete_record)

    # ------------------------------------------------------------------
    # 科目标签页
    # ------------------------------------------------------------------

    def _rebuild_subject_tabs(self) -> None:
        """按数据库里出现过的科目重建左栏标签。

        每次都整体重建而不是增量对比：科目数量很少（通常几个），重建更简单
        可靠，也不会在"删掉某科最后一条记录"后留下一个点不出内容的空标签。
        """
        subjects = self._repo.list_subjects()
        if self._subject_filter is not None and self._subject_filter not in subjects:
            # 该科目的记录已经全被删掉了，筛选自动回落到「全部」
            self._subject_filter = None

        while self._subject_layout.count():
            item = self._subject_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._subject_buttons = {}
        for name in [SUBJECT_TAB_ALL, *subjects]:
            button = QPushButton(name, self)
            button.setObjectName("subjectTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(self._is_subject_active(name))
            button.clicked.connect(
                lambda _checked=False, subject=name: self.set_subject_filter(subject)
            )
            self._subject_layout.addWidget(button)
            self._subject_buttons[name] = button

    def _is_subject_active(self, name: str) -> bool:
        if name == SUBJECT_TAB_ALL:
            return self._subject_filter is None
        return self._subject_filter == name

    def set_subject_filter(self, subject: str | None) -> None:
        """切换科目筛选；``None`` 或「全部」表示不过滤。"""
        self._subject_filter = None if subject in (None, SUBJECT_TAB_ALL) else subject
        self.refresh()

    def current_subject_filter(self) -> str | None:
        """当前科目筛选；None 表示全部。"""
        return self._subject_filter

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def _update_stats(self) -> None:
        """右栏底部的"今日合计 / 连续打卡"。"""
        minutes = sum(r.duration_minutes or 0 for r in self._repo.list_by_date(date.today()))
        self.today_stat.setText(f"{minutes} 分钟")
        self.streak_stat.setText(f"{self._streak_days()} 天")

    def _streak_days(self) -> int:
        """连续打卡天数。

        从今天往前数；今天还没学则从昨天起数——否则每天凌晨打开窗口都会看到
        "0 天"，把昨天及以前的连续记录白白断掉。
        """
        studied = {date.fromisoformat(d) for d in self._repo.list_dates()}
        cursor = date.today()
        if cursor not in studied:
            cursor -= timedelta(days=1)
        days = 0
        while cursor in studied:
            days += 1
            cursor -= timedelta(days=1)
        return days

    # ------------------------------------------------------------------
    # 日期与月份
    # ------------------------------------------------------------------

    def selected_date(self) -> date:
        """月历上当前选中的日期。"""
        qdate = self.calendar.selectedDate()
        return date(qdate.year(), qdate.month(), qdate.day())

    def visible_month(self) -> tuple[int, int]:
        """月历当前显示的年份与月份。"""
        return self.calendar.yearShown(), self.calendar.monthShown()

    def set_selected_date(self, day: date) -> None:
        """跳到指定日期（跨月时会自动切换到对应月份）。"""
        self._suppress_selection = True
        try:
            self.calendar.setSelectedDate(QDate(day.year, day.month, day.day))
        finally:
            self._suppress_selection = False
        self.refresh()

    def show_previous_month(self) -> None:
        self._shift_month(-1)

    def show_next_month(self) -> None:
        self._shift_month(1)

    def go_to_today(self) -> None:
        self.set_selected_date(date.today())

    def _shift_month(self, delta: int) -> None:
        """切换月份，并把选中日挪到该月的同一天（超出月末则取月末）。"""
        year, month = self.visible_month()
        index = year * 12 + (month - 1) + delta
        new_year, new_month = divmod(index, 12)
        new_month += 1

        day = min(self.selected_date().day, monthrange(new_year, new_month)[1])
        self.set_selected_date(date(new_year, new_month, day))
        # 日历显示月份由 setSelectedDate 跟随；再显式展示一次，
        # 保证"当前选中日恰好在新月份里"时也不会出现标题与网格不一致
        self.calendar.setCurrentPage(new_year, new_month)

    def _on_selection_changed(self) -> None:
        if self._suppress_selection:
            return
        self.refresh()

    # ------------------------------------------------------------------
    # 数据加载
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """重新加载科目标签、整月标记、当天记录与统计。写操作后统一调用。"""
        self._rebuild_subject_tabs()
        self._load_month_marks()
        self._reload_current_day()
        self._update_stats()

    def _load_month_marks(self) -> None:
        """按月取一次数据，给有记录的日期打标记，并把相邻月份日期淡化。"""
        year, month = self.visible_month()
        self.month_label.setText(format_month_title(year, month))

        last_day = monthrange(year, month)[1]
        first = date(year, month, 1)
        last = date(year, month, last_day)

        records = self._repo.list_by_date_range(first, last)
        days_with_records = {date.fromisoformat(r.study_date) for r in records}

        # 月历网格会补齐到整周，因此一定会显示相邻月份的日期。
        # Qt 并不会自动把它们画淡（实测与本月同色），这里显式加一层淡化，
        # 否则用户分不清哪些格子属于当前月份。
        grid_start = first - timedelta(days=first.weekday())
        grid_end = last + timedelta(days=6 - last.weekday())
        outside = [
            grid_start + timedelta(days=i)
            for i in range((grid_end - grid_start).days + 1)
        ]
        outside = [d for d in outside if (d.year, d.month) != (year, month)]

        self._clear_date_formats()

        dim = QTextCharFormat()
        dim.setForeground(QColor(Palette.TEXT_DISABLED))
        for day in outside:
            self._apply_date_format(day, dim)

        # 先淡化再打标记：有记录的日期一定属于当月，不会被淡化覆盖
        for day in days_with_records:
            self._apply_date_format(day, self._mark_format())
        self._marked_dates = days_with_records

    def _apply_date_format(self, day: date, fmt: QTextCharFormat) -> None:
        self.calendar.setDateTextFormat(QDate(day.year, day.month, day.day), fmt)
        self._decorated_dates.add(day)

    def _clear_date_formats(self) -> None:
        """清掉上一轮套用的格式，否则换月后旧月份会残留高亮/淡化。"""
        if not self._decorated_dates:
            return
        empty = QTextCharFormat()
        for day in self._decorated_dates:
            self.calendar.setDateTextFormat(
                QDate(day.year, day.month, day.day), empty
            )
        self._decorated_dates.clear()

    def _apply_weekday_formats(self) -> None:
        """按星期几设置日期文字颜色。

        必须显式设置，不能靠样式表的 ``color``：QSS 的 color 会覆盖
        ``setDateTextFormat`` 的逐日期前景色，导致相邻月份的淡化失效。
        周末沿用「红字」这一习惯，但取调色板里的砖红，避免默认大红色
        和整窗暖色调打架。
        """
        normal = QTextCharFormat()
        normal.setForeground(QColor(Palette.INK))
        weekend = QTextCharFormat()
        weekend.setForeground(QColor(Palette.ROSE))

        for weekday in (
            Qt.DayOfWeek.Monday,
            Qt.DayOfWeek.Tuesday,
            Qt.DayOfWeek.Wednesday,
            Qt.DayOfWeek.Thursday,
            Qt.DayOfWeek.Friday,
        ):
            self.calendar.setWeekdayTextFormat(weekday, normal)
        for weekday in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.calendar.setWeekdayTextFormat(weekday, weekend)

    @staticmethod
    def _mark_format() -> QTextCharFormat:
        """有记录的日期：淡玫红块 + 深字加粗。

        参考图用的是"日期外面套一个圆圈"，那需要自定义绘制代理；
        底色块在观感上等价，实现成本低得多，也不会随缩放糊掉。
        """
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(Palette.ROSE_SOFT))
        fmt.setForeground(QColor(Palette.INK_STRONG))
        fmt.setFontWeight(600)
        return fmt

    def _reload_current_day(self) -> None:
        day = self.selected_date()
        records = self._repo.list_by_date(day)
        if self._subject_filter is not None:
            records = [r for r in records if r.subject == self._subject_filter]
        self._records = records

        self.day_title.setText(format_day_title(day))
        self.summary_label.setText(format_summary(records))

        selected_id = self.selected_record_id()
        self._fill_table(self._records)
        if selected_id is not None:
            self._select_row_by_id(selected_id)
        self._update_actions()

    def _fill_table(self, records: list[StudyRecord]) -> None:
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            subject_item = QTableWidgetItem(record.subject)
            # 记录 id 挂在第一列上，用于"选中行 -> 记录"的反查
            subject_item.setData(Qt.ItemDataRole.UserRole, record.id)
            subject_item.setToolTip(record.subject)

            duration_item = QTableWidgetItem(format_duration(record.duration_minutes))
            duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            content_item = QTableWidgetItem(
                flatten_content(record.content, CONTENT_PREVIEW_LIMIT)
            )
            if record.content:
                content_item.setToolTip(record.content)

            self.table.setItem(row, 0, subject_item)
            self.table.setItem(row, 1, duration_item)
            self.table.setItem(row, 2, content_item)
        # 没有记录时把空状态提示露出来，避免一片空白让人以为窗口坏了
        self.empty_hint.setVisible(not records)

    # ------------------------------------------------------------------
    # 选中行
    # ------------------------------------------------------------------

    def selected_record_id(self) -> int | None:
        """当前选中行对应的记录 id；没有选中返回 None。"""
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def selected_record(self) -> StudyRecord | None:
        record_id = self.selected_record_id()
        if record_id is None:
            return None
        for record in self._records:
            if record.id == record_id:
                return record
        return None

    def _select_row_by_id(self, record_id: int) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == record_id:
                self.table.selectRow(row)
                return

    def _update_actions(self) -> None:
        has_selection = self.selected_record_id() is not None
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # 新增 / 编辑 / 删除
    # ------------------------------------------------------------------
    # 下面两个方法刻意做成可替换的：正常运行时弹真实对话框，
    # 测试里直接替换掉，避免模态事件循环把测试卡死。

    def _ask_record(self, record: StudyRecord | None) -> dict | None:
        """弹表单，返回字段字典；用户取消时返回 None。"""
        dialog = RecordDialog(self, record=record, default_date=self.selected_date())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.values()
        return None

    def _confirm_delete(self, subject: str) -> bool:
        """删除前的二次确认，默认选中「否」防误触。"""
        answer = QMessageBox.question(
            self,
            "删除记录",
            f"确定要删除「{subject}」这条学习记录吗？此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def add_record(self) -> None:
        values = self._ask_record(None)
        if values is None:
            return
        new_id = self._repo.add(**values)
        self._after_write(values["study_date"], new_id)

    def edit_record(self) -> None:
        record = self.selected_record()
        if record is None:
            return
        values = self._ask_record(record)
        if values is None:
            return
        self._repo.update(
            record.id,
            study_date=values["study_date"],
            subject=values["subject"],
            duration_minutes=values["duration_minutes"],
            content=values["content"],
        )
        self._after_write(values["study_date"], record.id)

    def delete_record(self) -> None:
        record = self.selected_record()
        if record is None:
            return
        if not self._confirm_delete(record.subject):
            return
        self._repo.delete(record.id)
        # 记录没了就不该再保持选中，直接按当前日重载
        self.refresh()

    def _after_write(self, study_date: str, record_id: int) -> None:
        """写操作后校准显示位置并刷新，顺便保持刚处理的记录被选中。"""
        target = date.fromisoformat(study_date)
        if target != self.selected_date():
            # 用户把记录挪到了别的日期：跟过去，否则用户会以为记录丢了
            self._suppress_selection = True
            try:
                self.calendar.setSelectedDate(
                    QDate(target.year, target.month, target.day)
                )
            finally:
                self._suppress_selection = False
        self.refresh()
        self._select_row_by_id(record_id)
        self._update_actions()
