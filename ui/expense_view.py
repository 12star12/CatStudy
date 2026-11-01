"""账本视图：左分类页签 + 中间当月流水 + 右侧月度汇总。

与学习记录界面同构（三栏、同样的纸质配色），用户不用重新学一套交互。
职责边界同样严格：不出现任何 SQL，读写都走 ``ExpenseRepository``。
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from core.expenses import Expense, ExpenseRepository
from ui.expense_dialog import ExpenseDialog
from ui.formatting import format_money, format_money_plain
from ui.theme import Palette

TABLE_HEADERS: tuple[str, ...] = ("日期", "分类", "金额", "备注")

CATEGORY_TAB_ALL: str = "全部"

RAIL_WIDTH: int = 116
CARD_WIDTH: int = 236

# 备注列最多显示的字符数，超出用省略号（完整内容在悬浮提示里）
NOTE_PREVIEW_LIMIT: int = 24


class _NoFocusRectDelegate(QStyledItemDelegate):
    """去掉单元格的虚线焦点框（与学习记录表格一致）。"""

    def paint(self, painter, option, index) -> None:  # noqa: ANN001 (Qt 回调签名)
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class ExpenseView(QWidget):
    """记账主视图。"""

    def __init__(
        self,
        repository: ExpenseRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repository
        self._rows: list[Expense] = []
        self._category_filter: str | None = None
        self._category_buttons: dict[str, QPushButton] = {}
        # 当前显示的月份，默认本月
        today = date.today()
        self._year: int = today.year
        self._month: int = today.month

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
        root.addWidget(self._build_category_rail())
        root.addWidget(self._build_list_panel(), 1)
        root.addWidget(self._build_summary_card())

    def _build_category_rail(self) -> QWidget:
        rail = QFrame(self)
        rail.setObjectName("subjectRail")
        rail.setFixedWidth(RAIL_WIDTH)

        box = QVBoxLayout(rail)
        box.setContentsMargins(0, 6, 6, 0)
        box.setSpacing(8)

        title = QLabel("分类", rail)
        title.setObjectName("railTitle")
        box.addWidget(title)

        self._category_layout = QVBoxLayout()
        self._category_layout.setSpacing(8)
        box.addLayout(self._category_layout)
        box.addStretch(1)
        return rail

    def _build_list_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("paperPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)

        self.prev_button = QPushButton("‹", panel)
        self.prev_button.setObjectName("cardNavButton")
        self.month_label = QLabel("", panel)
        self.month_label.setObjectName("dayTitleLabel")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_button = QPushButton("›", panel)
        self.next_button.setObjectName("cardNavButton")

        self.summary_label = QLabel("", panel)
        self.summary_label.setObjectName("summaryLabel")

        nav = QHBoxLayout()
        nav.setSpacing(6)
        nav.addWidget(self.prev_button)
        nav.addWidget(self.month_label)
        nav.addWidget(self.next_button)
        nav.addStretch(1)
        nav.addWidget(self.summary_label)

        self.table = QTableWidget(0, len(TABLE_HEADERS), panel)
        # 复用学习记录表的样式（同一套纸质表格外观），因此沿用同名 objectName
        self.table.setObjectName("recordTable")
        self.table.setHorizontalHeaderLabels(list(TABLE_HEADERS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setItemDelegate(_NoFocusRectDelegate(self.table))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 104)
        self.table.setColumnWidth(1, 84)
        self.table.setColumnWidth(2, 96)
        header.setStyleSheet(
            "QHeaderView::section {"
            f" background-color: {Palette.PAPER_DEEP};"
            " border: none;"
            f" border-bottom: 1px solid {Palette.RULE};"
            f" color: {Palette.INK_MUTED};"
            " padding: 4px 8px;"
            "}"
        )
        header.viewport().setAutoFillBackground(False)

        self.empty_hint = QLabel("这个月还没有记账，点「记一笔」开始", panel)
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.hide()

        self.add_button = QPushButton("＋ 记一笔", panel)
        self.add_button.setObjectName("primaryButton")
        self.edit_button = QPushButton("编辑", panel)
        self.delete_button = QPushButton("删除", panel)
        self.delete_button.setObjectName("dangerButton")

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)

        box.addLayout(nav)
        box.addWidget(self.table, 1)
        box.addWidget(self.empty_hint)
        box.addLayout(actions)
        return panel

    def _build_summary_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("calendarCard")
        card.setFixedWidth(CARD_WIDTH)
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 16)
        box.setSpacing(6)

        caption = QLabel("本月支出", card)
        caption.setObjectName("statLabel")
        self.total_label = QLabel("¥0.00", card)
        self.total_label.setStyleSheet(
            f"color: {Palette.INK_STRONG}; font-size: 26px; font-weight: 600;"
        )

        self.count_label = QLabel("", card)
        self.count_label.setObjectName("statValue")
        self.daily_label = QLabel("", card)
        self.daily_label.setObjectName("statLabel")

        divider = QFrame(card)
        divider.setObjectName("divider")
        divider.setFixedHeight(1)

        detail_caption = QLabel("分类明细", card)
        detail_caption.setObjectName("railTitle")

        self.detail_label = QLabel("", card)
        self.detail_label.setObjectName("statValue")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        box.addWidget(caption)
        box.addWidget(self.total_label)
        box.addWidget(self.count_label)
        box.addWidget(self.daily_label)
        box.addWidget(divider)
        box.addWidget(detail_caption)
        box.addWidget(self.detail_label)
        box.addStretch(1)
        return card

    def _connect_signals(self) -> None:
        self.prev_button.clicked.connect(lambda: self.shift_month(-1))
        self.next_button.clicked.connect(lambda: self.shift_month(1))
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(lambda _index: self.edit_expense())
        self.add_button.clicked.connect(self.add_expense)
        self.edit_button.clicked.connect(self.edit_expense)
        self.delete_button.clicked.connect(self.delete_expense)

    # ------------------------------------------------------------------
    # 分类页签
    # ------------------------------------------------------------------

    def _rebuild_category_tabs(self) -> None:
        categories = self._repo.list_categories()
        if self._category_filter is not None and self._category_filter not in categories:
            self._category_filter = None

        while self._category_layout.count():
            item = self._category_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._category_buttons = {}
        for name in [CATEGORY_TAB_ALL, *categories]:
            button = QPushButton(name, self)
            button.setObjectName("subjectTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(self._is_category_active(name))
            button.clicked.connect(
                lambda _checked=False, category=name: self.set_category_filter(category)
            )
            self._category_layout.addWidget(button)
            self._category_buttons[name] = button

    def _is_category_active(self, name: str) -> bool:
        if name == CATEGORY_TAB_ALL:
            return self._category_filter is None
        return self._category_filter == name

    def set_category_filter(self, category: str | None) -> None:
        self._category_filter = None if category in (None, CATEGORY_TAB_ALL) else category
        self.refresh()

    def current_category_filter(self) -> str | None:
        return self._category_filter

    # ------------------------------------------------------------------
    # 月份
    # ------------------------------------------------------------------

    @property
    def year(self) -> int:
        return self._year

    @property
    def month(self) -> int:
        return self._month

    def shift_month(self, delta: int) -> None:
        index = self._year * 12 + (self._month - 1) + delta
        self._year, month_index = divmod(index, 12)
        self._month = month_index + 1
        self.refresh()

    def go_to_current_month(self) -> None:
        today = date.today()
        self._year, self._month = today.year, today.month
        self.refresh()

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._rebuild_category_tabs()

        records = self._repo.list_by_month(self._year, self._month)
        if self._category_filter is not None:
            records = [r for r in records if r.category == self._category_filter]
        self._rows = records

        self.month_label.setText(f"{self._year} 年 {self._month} 月")
        self._fill_table(records)
        self._update_summary()
        self._update_actions()

    def _fill_table(self, rows: list[Expense]) -> None:
        self.table.setRowCount(len(rows))
        for index, expense in enumerate(rows):
            date_item = QTableWidgetItem(expense.expense_date)
            date_item.setData(Qt.ItemDataRole.UserRole, expense.id)
            category_item = QTableWidgetItem(expense.category)
            amount_item = QTableWidgetItem(format_money(expense.amount_cents))
            amount_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            note_item = QTableWidgetItem(
                expense.note if len(expense.note) <= NOTE_PREVIEW_LIMIT
                else expense.note[:NOTE_PREVIEW_LIMIT] + "…"
            )
            if expense.note:
                note_item.setToolTip(expense.note)

            self.table.setItem(index, 0, date_item)
            self.table.setItem(index, 1, category_item)
            self.table.setItem(index, 2, amount_item)
            self.table.setItem(index, 3, note_item)

        self.empty_hint.setVisible(not rows)
        self.summary_label.setText(f"共 {len(rows)} 笔")

    def _update_summary(self) -> None:
        total = self._repo.month_total_cents(self._year, self._month)
        self.total_label.setText(format_money(total))

        rows = self._repo.list_by_month(self._year, self._month)
        self.count_label.setText(f"{len(rows)} 笔")
        if rows:
            days = len({r.expense_date for r in rows})
            self.daily_label.setText(f"日均 {format_money(total // max(days, 1))}")
        else:
            self.daily_label.setText("本月还没有支出")

        totals = self._repo.category_totals(self._year, self._month)
        if not totals:
            self.detail_label.setText("—")
            return
        lines = [
            f"{category}  {format_money(amount)}" for category, amount in totals[:6]
        ]
        self.detail_label.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # 选中行
    # ------------------------------------------------------------------

    def selected_expense(self) -> Expense | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        expense_id = item.data(Qt.ItemDataRole.UserRole)
        for expense in self._rows:
            if expense.id == expense_id:
                return expense
        return None

    def _update_actions(self) -> None:
        has_selection = self.selected_expense() is not None
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # 增删改（弹窗可替换，便于测试）
    # ------------------------------------------------------------------

    def _ask_expense(self, expense: Expense | None) -> dict | None:
        dialog = ExpenseDialog(
            self,
            expense=expense,
            default_date=date(self._year, self._month, 1),
            known_categories=tuple(self._repo.list_categories()),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.values()
        return None

    def _confirm_delete(self, expense: Expense) -> bool:
        answer = QMessageBox.question(
            self,
            "删除记录",
            f"确定删除 {expense.expense_date} 的 {format_money(expense.amount_cents)}"
            f"（{expense.category}）吗？此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def add_expense(self) -> None:
        values = self._ask_expense(None)
        if values is None:
            return
        self._repo.add(**values)
        self._jump_to(values["expense_date"])
        self.refresh()

    def edit_expense(self) -> None:
        expense = self.selected_expense()
        if expense is None:
            return
        values = self._ask_expense(expense)
        if values is None:
            return
        self._repo.update(expense.id, **values)
        self._jump_to(values["expense_date"])
        self.refresh()

    def delete_expense(self) -> None:
        expense = self.selected_expense()
        if expense is None:
            return
        if not self._confirm_delete(expense):
            return
        self._repo.delete(expense.id)
        self.refresh()

    def _jump_to(self, iso_date: str) -> None:
        """把用户改到的日期所在月份显示出来，避免"保存后凭空消失"。"""
        target = date.fromisoformat(iso_date)
        self._year, self._month = target.year, target.month
