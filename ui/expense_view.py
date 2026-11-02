"""流水视图：左类型/分类筛选 + 中间当月流水 + 右侧月度收支汇总。

与学习记录、资产界面同构（三栏、同样的纸质配色），用户不用重新学一套交互。
职责边界同样严格：不出现任何 SQL，读写都走 ``ExpenseRepository``。

这一版的三处变化：

1. **收支分开**：表格里收入用 ``+¥`` 与墨绿、支出用 ``−¥`` 与深棕，一眼能分；
   左栏多了「支出 / 收入」筛选，和分类筛选叠加生效。
2. **账户列**：联动过账户的流水会显示账户名；不联动的显示「—」。
3. **右栏改为"结余"视角**：大数字是本月结余（收入 − 支出），下面拆出收入与支出，
   这样"这个月到底有没有多赚"一眼可见——这也是用户要的"创收意识"。
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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

from core.accounts import AccountRepository
from core.expenses import (
    FLOW_EXPENSE,
    FLOW_INCOME,
    FLOW_LABELS,
    Expense,
    ExpenseRepository,
)
from ui.expense_dialog import ExpenseDialog
from ui.formatting import format_balance_hint, format_income_meta, format_money
from ui.theme import Palette

TABLE_HEADERS: tuple[str, ...] = ("日期", "分类", "金额", "账户", "备注")

CATEGORY_TAB_ALL: str = "全部"

RAIL_WIDTH: int = 116
CARD_WIDTH: int = 250

# 备注列最多显示的字符数，超出用省略号（完整内容在悬浮提示里）
NOTE_PREVIEW_LIMIT: int = 20

# 列宽：日期 / 分类 / 金额 / 账户 固定，备注吃掉剩余。
# 分类列要放下「支出 · 吃饭」这种 6~7 个字，78px 会截断，实测 108 刚好
COLUMN_WIDTHS: tuple[int, ...] = (100, 108, 104, 96)


class _NoFocusRectDelegate(QStyledItemDelegate):
    """去掉单元格的虚线焦点框（与另外两张表一致）。"""

    def paint(self, painter, option, index) -> None:  # noqa: ANN001 (Qt 回调签名)
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class ExpenseView(QWidget):
    """收支流水主视图。"""

    def __init__(
        self,
        repository: ExpenseRepository,
        parent: QWidget | None = None,
        account_repository: AccountRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repository
        # 账户仓储只用来给"账户"下拉填选项与显示名字；没有也能用（只有"不关联"）
        self._accounts_repo = account_repository
        self._rows: list[Expense] = []
        self._category_filter: str | None = None
        self._kind_filter: str | None = None
        self._category_buttons: dict[str, QPushButton] = {}
        self._account_names: dict[int, str] = {}
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
        root.addWidget(self._build_filter_rail())
        root.addWidget(self._build_list_panel(), 1)
        root.addWidget(self._build_summary_card())

    def _build_filter_rail(self) -> QWidget:
        rail = QFrame(self)
        rail.setObjectName("subjectRail")
        rail.setFixedWidth(RAIL_WIDTH)

        box = QVBoxLayout(rail)
        box.setContentsMargins(0, 6, 6, 0)
        box.setSpacing(8)

        kind_title = QLabel("类型", rail)
        kind_title.setObjectName("railTitle")
        box.addWidget(kind_title)

        self._kind_layout = QVBoxLayout()
        self._kind_layout.setSpacing(8)
        box.addLayout(self._kind_layout)

        category_title = QLabel("分类", rail)
        category_title.setObjectName("railTitle")
        box.addWidget(category_title)

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
        for index, width in enumerate(COLUMN_WIDTHS):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(index, width)
        header.setSectionResizeMode(
            len(TABLE_HEADERS) - 1, QHeaderView.ResizeMode.Stretch
        )
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

        self.empty_hint = QLabel(
            "这个月还没有记账，点「＋ 记一笔」开始。收入可以记成「收入」方向", panel
        )
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
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

        caption = QLabel("本月结余", card)
        caption.setObjectName("statLabel")
        self.balance_label = QLabel("¥0.00", card)
        self.balance_label.setStyleSheet(
            f"color: {Palette.INK_STRONG}; font-size: 26px; font-weight: 600;"
        )

        self.balance_hint = QLabel("", card)
        # 这行是"这个月怎么样"的评语，属于要读的内容：
        # 不能用 emptyHint 那种极淡的灰（那是空状态占位），要按正文次级色给
        self.balance_hint.setStyleSheet(
            f"color: {Palette.INK_MUTED}; font-size: 12px;"
        )
        self.balance_hint.setWordWrap(True)

        divider = QFrame(card)
        divider.setObjectName("divider")
        divider.setFixedHeight(1)

        self.income_label = QLabel("¥0.00", card)
        self.income_label.setObjectName("statValue")
        self.expense_label = QLabel("¥0.00", card)
        self.expense_label.setObjectName("statValue")

        income_caption = QLabel("收入", card)
        income_caption.setObjectName("statLabel")
        expense_caption = QLabel("支出", card)
        expense_caption.setObjectName("statLabel")

        income_row = QHBoxLayout()
        income_row.setSpacing(6)
        income_row.addWidget(income_caption)
        income_row.addStretch(1)
        income_row.addWidget(self.income_label)

        expense_row = QHBoxLayout()
        expense_row.setSpacing(6)
        expense_row.addWidget(expense_caption)
        expense_row.addStretch(1)
        expense_row.addWidget(self.expense_label)

        # 收入下面这行小字，是"创收"唯一的常驻入口：
        # 不设目标、不催，只把"这个月记了几笔进账、今年累计多少"摆出来。
        # 放在收入一侧而不是结余下面，是因为结余会被支出抵消，
        # 而进账的笔数与年度累计不会——只有不会倒退的数才谈得上积累。
        self.income_meta = QLabel("", card)
        self.income_meta.setStyleSheet(
            f"color: {Palette.INK_MUTED}; font-size: 11px;"
        )
        self.income_meta.setWordWrap(True)

        divider2 = QFrame(card)
        divider2.setObjectName("divider")
        divider2.setFixedHeight(1)

        detail_caption = QLabel("分类明细", card)
        detail_caption.setObjectName("railTitle")

        self.detail_label = QLabel("", card)
        self.detail_label.setObjectName("statValue")
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        box.addWidget(caption)
        box.addWidget(self.balance_label)
        box.addWidget(self.balance_hint)
        box.addWidget(divider)
        box.addLayout(income_row)
        box.addWidget(self.income_meta)
        box.addLayout(expense_row)
        box.addWidget(divider2)
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
    # 筛选
    # ------------------------------------------------------------------

    def _rebuild_kind_tabs(self) -> None:
        """左栏上半：全部 / 支出 / 收入。"""
        while self._kind_layout.count():
            item = self._kind_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for label, value in (
            ("全部", None),
            (FLOW_LABELS[FLOW_EXPENSE], FLOW_EXPENSE),
            (FLOW_LABELS[FLOW_INCOME], FLOW_INCOME),
        ):
            button = QPushButton(label, self)
            button.setObjectName("subjectTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(self._kind_filter == value)
            button.clicked.connect(
                lambda _checked=False, kind=value: self.set_kind_filter(kind)
            )
            self._kind_layout.addWidget(button)

    def set_kind_filter(self, kind: str | None) -> None:
        """只看支出 / 只看收入 / 全部。"""
        self._kind_filter = kind if kind in (FLOW_EXPENSE, FLOW_INCOME) else None
        self.refresh()

    def current_kind_filter(self) -> str | None:
        return self._kind_filter

    def _rebuild_category_tabs(self) -> None:
        """左栏下半：分类标签。候选随收支筛选变化。"""
        kind = self._kind_filter or FLOW_EXPENSE
        categories = self._repo.list_categories(kind)
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
        """重建筛选标签、重填表格、重算汇总。写操作后统一调用。"""
        self._refresh_account_names()
        self._rebuild_kind_tabs()
        self._rebuild_category_tabs()

        records = self._repo.list_by_month(self._year, self._month, self._kind_filter)
        if self._category_filter is not None:
            records = [r for r in records if r.category == self._category_filter]
        self._rows = records

        self.month_label.setText(f"{self._year} 年 {self._month} 月")
        self._fill_table(records)
        self._update_summary()
        self._update_actions()

    def _refresh_account_names(self) -> None:
        """缓存 id → 名称，表格里显示账户名而不是 id。"""
        self._account_names = {}
        if self._accounts_repo is None:
            return
        for account in self._accounts_repo.list_all():
            self._account_names[account.id] = account.name

    def _fill_table(self, rows: list[Expense]) -> None:
        self.table.setRowCount(len(rows))
        for index, expense in enumerate(rows):
            date_item = QTableWidgetItem(expense.expense_date)
            date_item.setData(Qt.ItemDataRole.UserRole, expense.id)

            # 分类前加方向标记，一眼能区分"吃饭"和"工资"
            label = FLOW_LABELS.get(expense.kind, "")
            category_item = QTableWidgetItem(f"{label} · {expense.category}")
            category_item.setToolTip(f"{label} · {expense.category}")

            # format_money 对负数自带 '-'，收入再补一个 '+'，两种方向一眼可分
            amount_text = format_money(expense.signed_cents)
            if expense.is_income:
                amount_text = "+" + amount_text
            amount_item = QTableWidgetItem(amount_text)
            amount_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            amount_item.setForeground(
                QColor(Palette.INCOME if expense.is_income else Palette.INK_STRONG)
            )

            account_item = QTableWidgetItem(
                self._account_names.get(expense.account_id, "—")
                if expense.account_id is not None
                else "—"
            )
            if expense.account_id is not None and expense.account_id not in self._account_names:
                account_item.setToolTip("关联的账户已被删除")

            note_item = QTableWidgetItem(
                expense.note
                if len(expense.note) <= NOTE_PREVIEW_LIMIT
                else expense.note[:NOTE_PREVIEW_LIMIT] + "…"
            )
            if expense.note:
                note_item.setToolTip(expense.note)

            self.table.setItem(index, 0, date_item)
            self.table.setItem(index, 1, category_item)
            self.table.setItem(index, 2, amount_item)
            self.table.setItem(index, 3, account_item)
            self.table.setItem(index, 4, note_item)

        self.empty_hint.setVisible(not rows)
        self.summary_label.setText(f"共 {len(rows)} 笔")

    def _update_summary(self) -> None:
        """右栏永远是本月全量，不受左侧筛选影响。"""
        income = self._repo.month_income_cents(self._year, self._month)
        expense = self._repo.month_total_cents(self._year, self._month)
        net = income - expense

        self.balance_label.setText(format_money(net))
        # 结余为负不标红：月初还没发工资、这个月刚交完房租，都会是负数，
        # 这属于常态而不是错误。给红色等于给"记账"这个动作贴处罚标签，
        # 记一次被警告一次，人就不想记了。方向交给下面那句评语去讲。
        self.balance_label.setStyleSheet(
            f"color: {Palette.INK_STRONG}; font-size: 26px; font-weight: 600;"
        )
        self.balance_hint.setText(
            format_balance_hint(income, expense) or "还没有流水"
        )

        self.income_label.setText(format_money(income))
        self.expense_label.setText(format_money(expense))
        self.income_label.setStyleSheet(f"color: {Palette.INCOME};")
        self.expense_label.setStyleSheet(f"color: {Palette.INK};")

        income_rows = self._repo.category_totals(
            self._year, self._month, FLOW_INCOME
        )
        self.income_meta.setText(
            format_income_meta(
                entries=self._repo.month_income_entries(self._year, self._month),
                sources=len(income_rows),
                year_cents=self._repo.year_income_cents(self._year),
            )
        )

        expense_rows = self._repo.category_totals(
            self._year, self._month, FLOW_EXPENSE
        )
        lines: list[str] = [
            f"{category}  {format_money(amount)}" for category, amount in expense_rows[:4]
        ]
        for category, amount in income_rows[:3]:
            lines.append(f"＋{category}  {format_money(amount)}")
        self.detail_label.setText("\n".join(lines) if lines else "—")

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
        accounts: tuple[tuple[int, str, str], ...] = ()
        if self._accounts_repo is not None:
            accounts = tuple(
                (a.id, a.name, a.kind) for a in self._accounts_repo.list_all()
            )

        dialog = ExpenseDialog(
            self,
            expense=expense,
            # 新记一笔默认"今天"，不是"当前查看月份的第一天"：
            # 记账这个动作几乎总是发生在当天，翻着看三个月前的账再点记一笔，
            # 日期却落在那个月一号，是最容易被忽略、也最难事后发现的数据错误。
            # 编辑时用传进来的那笔自己的日期，不受这里影响。
            default_date=date.today(),
            known_categories={
                FLOW_EXPENSE: tuple(self._repo.list_categories(FLOW_EXPENSE)),
                FLOW_INCOME: tuple(self._repo.list_categories(FLOW_INCOME)),
            },
            accounts=accounts,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.values()
        return None

    def _confirm_delete(self, expense: Expense) -> bool:
        amount_text = format_money(expense.signed_cents)
        if expense.is_income:
            amount_text = "+" + amount_text
        linked = ""
        if expense.account_id is not None:
            name = self._account_names.get(expense.account_id)
            if name:
                linked = f"\n它的影响会从「{name}」上撤回。"
        answer = QMessageBox.question(
            self,
            "删除流水",
            f"确定删除 {expense.expense_date} 的 "
            f"{amount_text}（{expense.category}）吗？"
            f"{linked}\n此操作无法撤销。",
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
