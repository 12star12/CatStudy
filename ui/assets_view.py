"""资产 / 负债视图：左类型筛选 + 中账户清单 + 右净资产汇总。

与学习记录、流水三栏同构（同样的宽度节奏、同样的纸质配色），用户不用重新
学一套交互。职责边界同样严格：**不出现任何 SQL**，读写都走
``AccountRepository``。

一个刻意的取舍：**右栏的汇总不受左侧筛选影响**。净资产是"整体"的概念，
筛到"只看负债"时如果净资产也跟着变，用户会以为资产凭空消失了。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
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

from core.accounts import (
    ASSET,
    LIABILITY,
    Account,
    AccountRepository,
)
from ui.account_dialog import AccountDialog
from ui.formatting import format_money
from ui.sparkline import Sparkline
from ui.theme import Palette

TABLE_HEADERS: tuple[str, ...] = ("名称", "类别", "余额", "备注")

FILTER_ALL: str = "全部"
FILTER_ASSET: str = "资产"
FILTER_LIABILITY: str = "负债"

RAIL_WIDTH: int = 116
CARD_WIDTH: int = 264

# 走势只取最近这么多天的快照，太多会把折线压成一团
SPARKLINE_DAYS: int = 30

NOTE_PREVIEW_LIMIT: int = 16


class _NoFocusRectDelegate(QStyledItemDelegate):
    """去掉单元格虚线焦点框（与另外两张表一致）。"""

    def paint(self, painter, option, index) -> None:  # noqa: ANN001 (Qt 回调签名)
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)


class _RatioBar(QWidget):
    """负债占资产比例的细横条。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ratio = 0.0
        self.setFixedHeight(8)

    def set_ratio(self, ratio: float) -> None:
        self._ratio = max(0.0, min(1.0, float(ratio)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        if rect.width() <= 1:
            painter.end()
            return

        radius = rect.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(Palette.RULE))
        painter.drawRoundedRect(rect, radius, radius)

        if self._ratio > 0:
            # 比例极小时也画出一个圆点，让"有负债"这件事可见
            width = max(rect.height(), rect.width() * self._ratio)
            painter.setBrush(QColor(Palette.ROSE))
            painter.drawRoundedRect(
                QRectF(0, 0, width, rect.height()), radius, radius
            )
        painter.end()


class AssetsView(QWidget):
    """资产与负债主视图。"""

    def __init__(
        self,
        repository: AccountRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repository
        self._accounts: list[Account] = []
        self._filter: str | None = None
        self._filter_buttons: dict[str, QPushButton] = {}

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

        title = QLabel("类型", rail)
        title.setObjectName("railTitle")
        box.addWidget(title)

        self._filter_layout = QVBoxLayout()
        self._filter_layout.setSpacing(8)
        box.addLayout(self._filter_layout)
        box.addStretch(1)
        return rail

    def _build_list_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("paperPanel")

        box = QVBoxLayout(panel)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)

        self.title_label = QLabel("资产与负债", panel)
        self.title_label.setObjectName("dayTitleLabel")

        self.summary_label = QLabel("", panel)
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.summary_label)

        self.table = QTableWidget(0, len(TABLE_HEADERS), panel)
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

        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 112)
        self.table.setColumnWidth(2, 124)
        self.table.setColumnWidth(3, 124)
        # 表头颜色必须直接挂在这个 header 上：全局 QSS 的优先级更高，
        # 用 id 选择器写层级选择器实测盖不住（与另外两张表同一个坑）
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

        self.empty_hint = QLabel(
            "还没有账户。点「＋ 新增账户」，把银行卡、余额、花呗这些都加进来",
            panel,
        )
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.hide()

        self.add_button = QPushButton("＋ 新增账户", panel)
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

    def _build_summary_card(self) -> QWidget:
        card = QFrame(self)
        card.setObjectName("calendarCard")
        card.setFixedWidth(CARD_WIDTH)

        box = QVBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(6)

        caption = QLabel("净资产", card)
        caption.setObjectName("statLabel")

        self.net_label = QLabel("¥0.00", card)
        self.net_label.setStyleSheet(
            f"color: {Palette.INK_STRONG}; font-size: 24px; font-weight: 600;"
        )

        self.net_hint = QLabel("", card)
        self.net_hint.setObjectName("emptyHint")

        divider = QFrame(card)
        divider.setObjectName("divider")
        divider.setFixedHeight(1)

        assets_caption = QLabel("总资产", card)
        assets_caption.setObjectName("statLabel")
        self.assets_label = QLabel("¥0.00", card)
        self.assets_label.setObjectName("statValue")

        liabilities_caption = QLabel("总负债", card)
        liabilities_caption.setObjectName("statLabel")
        self.liabilities_label = QLabel("¥0.00", card)
        self.liabilities_label.setObjectName("statValue")

        assets_row = QHBoxLayout()
        assets_row.setSpacing(6)
        assets_row.addWidget(assets_caption)
        assets_row.addStretch(1)
        assets_row.addWidget(self.assets_label)

        liabilities_row = QHBoxLayout()
        liabilities_row.setSpacing(6)
        liabilities_row.addWidget(liabilities_caption)
        liabilities_row.addStretch(1)
        liabilities_row.addWidget(self.liabilities_label)

        self.ratio_label = QLabel("", card)
        self.ratio_label.setObjectName("emptyHint")

        self.ratio_bar = _RatioBar(card)

        trend_caption = QLabel(f"净资产走势 · 近 {SPARKLINE_DAYS} 天", card)
        trend_caption.setObjectName("railTitle")

        self.sparkline = Sparkline(card)

        # 与最早一天相比的变化量：只有折线没有数字时，用户还得自己估
        self.trend_delta = QLabel("", card)
        self.trend_delta.setObjectName("emptyHint")

        box.addWidget(caption)
        box.addWidget(self.net_label)
        box.addWidget(self.net_hint)
        box.addWidget(divider)
        box.addLayout(assets_row)
        box.addLayout(liabilities_row)
        box.addWidget(self.ratio_label)
        box.addWidget(self.ratio_bar)
        box.addSpacing(4)
        box.addWidget(trend_caption)
        # 给 stretch 因子而不是固定高度：卡片下部本来会空一块，
        # 让走势图吃掉它比留白有用（高度由布局决定，绘制按实际尺寸自适应）
        box.addWidget(self.sparkline, 1)
        box.addWidget(self.trend_delta)
        return card

    def _connect_signals(self) -> None:
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(lambda _index: self.edit_account())
        self.add_button.clicked.connect(self.add_account)
        self.edit_button.clicked.connect(self.edit_account)
        self.delete_button.clicked.connect(self.delete_account)

    # ------------------------------------------------------------------
    # 类型筛选
    # ------------------------------------------------------------------

    def _rebuild_filter_tabs(self) -> None:
        while self._filter_layout.count():
            item = self._filter_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._filter_buttons = {}
        for label, value in (
            (FILTER_ALL, None),
            (FILTER_ASSET, ASSET),
            (FILTER_LIABILITY, LIABILITY),
        ):
            button = QPushButton(label, self)
            button.setObjectName("subjectTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setChecked(self._filter == value)
            button.clicked.connect(
                lambda _checked=False, kind=value: self.set_kind_filter(kind)
            )
            self._filter_layout.addWidget(button)
            self._filter_buttons[label] = button

    def set_kind_filter(self, kind: str | None) -> None:
        """切换类型筛选；``None`` 表示全部。"""
        self._filter = kind if kind in (ASSET, LIABILITY) else None
        self.refresh()

    def current_kind_filter(self) -> str | None:
        return self._filter

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """重建筛选标签、重填表格、重算汇总与走势。写操作后统一调用。"""
        self._rebuild_filter_tabs()

        accounts = self._repo.list_all(self._filter)
        self._accounts = accounts
        self._fill_table(accounts)
        self._update_summary()
        self._update_actions()

    def _fill_table(self, accounts: list[Account]) -> None:
        self.table.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            name_item = QTableWidgetItem(account.name)
            # id 挂在第一列，用于"选中行 → 账户"的反查
            name_item.setData(Qt.ItemDataRole.UserRole, account.id)
            name_item.setToolTip(account.name)

            kind_text = account.kind_label
            if account.category:
                kind_text = f"{account.kind_label} · {account.category}"
            kind_item = QTableWidgetItem(kind_text)
            kind_item.setToolTip(kind_text)

            balance_item = QTableWidgetItem(format_money(account.balance_cents))
            balance_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            # 负债用玫红，和资产区分开（颜色只是个提示，不改变数值语义）
            if account.is_liability:
                balance_item.setForeground(QColor(Palette.ROSE))

            note_item = QTableWidgetItem(
                account.note
                if len(account.note) <= NOTE_PREVIEW_LIMIT
                else account.note[:NOTE_PREVIEW_LIMIT] + "…"
            )
            if account.note:
                note_item.setToolTip(account.note)

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, kind_item)
            self.table.setItem(row, 2, balance_item)
            self.table.setItem(row, 3, note_item)

        self.empty_hint.setVisible(not accounts)
        self.summary_label.setText(f"共 {len(accounts)} 个账户")

    def _update_summary(self) -> None:
        totals = self._repo.totals()
        self.net_label.setText(format_money(totals.net_cents))
        self.assets_label.setText(format_money(totals.assets_cents))
        self.liabilities_label.setText(format_money(totals.liabilities_cents))

        if totals.net_cents < 0:
            self.net_label.setStyleSheet(
                f"color: {Palette.DANGER}; font-size: 24px; font-weight: 600;"
            )
            self.net_hint.setText("负债大于资产")
        else:
            self.net_label.setStyleSheet(
                f"color: {Palette.INK_STRONG}; font-size: 24px; font-weight: 600;"
            )
            self.net_hint.setText(
                "" if self._repo.count() else "还没有账户"
            )

        ratio = totals.liability_ratio
        self.ratio_bar.set_ratio(ratio)
        if totals.liabilities_cents == 0:
            self.ratio_label.setText("没有负债")
        else:
            self.ratio_label.setText(f"负债占资产 {ratio * 100:.0f}%")

        snapshots = self._repo.list_snapshots(SPARKLINE_DAYS)
        self.sparkline.set_values([s.net_cents for s in snapshots])
        if len(snapshots) >= 2:
            first, last = snapshots[0], snapshots[-1]
            delta = last.net_cents - first.net_cents
            sign = "+" if delta >= 0 else "−"
            self.trend_delta.setText(
                f"较 {first.snapshot_date[5:]} {sign}{format_money(abs(delta))}"
            )
        else:
            self.trend_delta.setText("")

    # ------------------------------------------------------------------
    # 选中行
    # ------------------------------------------------------------------

    def selected_account(self) -> Account | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        account_id = item.data(Qt.ItemDataRole.UserRole)
        for account in self._accounts:
            if account.id == account_id:
                return account
        return None

    def _update_actions(self) -> None:
        has_selection = self.selected_account() is not None
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    # ------------------------------------------------------------------
    # 增删改（弹窗可替换，便于测试）
    # ------------------------------------------------------------------

    def _ask_account(self, account: Account | None) -> dict | None:
        dialog = AccountDialog(
            self,
            account=account,
            # 两种类型各给一份"实际用过的类别"，对话框切换类型时不会串
            known_categories={
                ASSET: tuple(self._repo.list_categories(ASSET)),
                LIABILITY: tuple(self._repo.list_categories(LIABILITY)),
            },
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.values()
        return None

    def _confirm_delete(self, account: Account) -> bool:
        answer = QMessageBox.question(
            self,
            "删除账户",
            f"确定要删除「{account.name}」（{format_money(account.balance_cents)}）吗？"
            "此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def add_account(self) -> None:
        values = self._ask_account(None)
        if values is None:
            return
        new_id = self._repo.add(**values)
        self.refresh()
        self._select_row_by_id(new_id)

    def edit_account(self) -> None:
        account = self.selected_account()
        if account is None:
            return
        values = self._ask_account(account)
        if values is None:
            return
        self._repo.update(account.id, **values)
        self.refresh()
        self._select_row_by_id(account.id)

    def delete_account(self) -> None:
        account = self.selected_account()
        if account is None:
            return
        if not self._confirm_delete(account):
            return
        self._repo.delete(account.id)
        self.refresh()

    def _select_row_by_id(self, account_id: int) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == account_id:
                self.table.selectRow(row)
                return
