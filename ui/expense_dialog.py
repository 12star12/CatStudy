"""记一笔（支出或收入）的对话框。

和学习记录的弹窗同样的约定：只收集与校验，不碰仓储层；校验失败就在表单底部
写一行红字，不弹模态框。

这一版多了三个东西：

1. **收支方向**：顶部两个互斥按钮。支出和收入的分类候选不同（不会让你在收入里
   选"奶茶"），所以切换方向时要重建下拉。
2. **账户联动**：可以选一个账户，也可以选「不关联」。选了会在表单底部提示
   这笔会怎么影响余额（"从『招行卡』扣除 ¥9.39"），避免"记完账发现余额被改了"
   这种不明不白的体验。
3. **金额支持算式**：``6.9+2.49`` 直接算成 9.39，不用先去按计算器。
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.expenses import (
    DEFAULT_CATEGORY,
    FLOW_EXPENSE,
    FLOW_INCOME,
    FLOW_LABELS,
    Expense,
    presets_for,
)
from ui.formatting import format_money, format_money_plain, parse_money
from ui.theme import Palette

# 账户下拉里"不关联"那一项的数据值
NO_ACCOUNT: int = -1

HINT_UNLINKED: str = "不关联账户：只记一笔账，资产/负债表的余额保持不变。"


class ExpenseDialog(QDialog):
    """新增 / 编辑一条流水。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        expense: Expense | None = None,
        default_date: date | None = None,
        known_categories: dict[str, tuple[str, ...]] | None = None,
        accounts: tuple[tuple[int, str, str], ...] = (),
    ) -> None:
        """``accounts`` 是 ``(id, 名称, 类型)`` 三元组，类型取 ``asset`` / ``liability``。"""
        super().__init__(parent)
        self._expense = expense
        self._is_edit = expense is not None
        self._known = dict(known_categories or {})
        self._accounts = accounts
        self._values: dict | None = None

        self.setWindowTitle("编辑流水" if self._is_edit else "记一笔")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._build_ui(default_date)
        self._fill(expense)

    # ---------- 构建 ----------

    def _build_ui(self, default_date: date | None) -> None:
        # ---- 收支方向 ----
        self.expense_button = QPushButton(FLOW_LABELS[FLOW_EXPENSE], self)
        self.income_button = QPushButton(FLOW_LABELS[FLOW_INCOME], self)
        for button in (self.expense_button, self.income_button):
            button.setObjectName("viewTab")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expense_button.setChecked(True)
        self.expense_button.clicked.connect(
            lambda: self.set_kind(FLOW_EXPENSE)
        )
        self.income_button.clicked.connect(lambda: self.set_kind(FLOW_INCOME))

        kind_row = QHBoxLayout()
        kind_row.setSpacing(8)
        kind_row.addWidget(self.expense_button)
        kind_row.addWidget(self.income_button)
        kind_row.addStretch(1)

        # ---- 表单字段 ----
        self.amount_edit = QLineEdit(self)
        self.amount_edit.setPlaceholderText("0.00，可直接写 6.9+2.49")
        self.amount_edit.setClearButtonEnabled(True)

        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        target = default_date or date.today()
        self.date_edit.setDate(QDate(target.year, target.month, target.day))

        self.category_combo = QComboBox(self)
        self.category_combo.setEditable(True)
        self.category_combo.setCurrentText(DEFAULT_CATEGORY)

        self.account_combo = QComboBox(self)
        self.account_combo.addItem("不关联账户", NO_ACCOUNT)
        for account_id, name, kind in self._accounts:
            label = f"{name}（{'资产' if kind == 'asset' else '负债'}）"
            self.account_combo.addItem(label, account_id)

        self.note_edit = QLineEdit(self)
        self.note_edit.setPlaceholderText("买了什么 / 哪来的（可留空）")

        self.hint_label = QLabel(HINT_UNLINKED, self)
        # 这行是"这笔会怎么改余额"的说明，属于需要读的内容，
        # 不能像空状态提示那样淡——给正文墨色 + 小一号字
        self.hint_label.setStyleSheet(
            f"color: {Palette.INK}; font-size: 12px;"
        )
        self.hint_label.setWordWrap(True)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("金额", self.amount_edit)
        form.addRow("日期", self.date_edit)
        form.addRow("分类", self.category_combo)
        form.addRow("账户", self.account_combo)
        form.addRow("备注", self.note_edit)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet(f"color: {Palette.DANGER};")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存", self)
        save.setObjectName("primaryButton")
        save.clicked.connect(self._on_accept)
        save.setDefault(True)

        buttons = QHBoxLayout()
        buttons.addWidget(self.error_label, 1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(kind_row)
        layout.addLayout(form)
        layout.addWidget(self.hint_label)
        layout.addLayout(buttons)

        self.account_combo.currentIndexChanged.connect(self._refresh_hint)
        self.amount_edit.textChanged.connect(self._refresh_hint)
        self._refresh_categories()

    # ---------- 方向 ----------

    def current_kind(self) -> str:
        return FLOW_INCOME if self.income_button.isChecked() else FLOW_EXPENSE

    def set_kind(self, kind: str) -> None:
        """切换收支方向：同步按钮选中态、重建分类候选、刷新提示。"""
        is_income = kind == FLOW_INCOME
        self.expense_button.setChecked(not is_income)
        self.income_button.setChecked(is_income)
        self._refresh_categories()
        self._refresh_hint()

    def _refresh_categories(self) -> None:
        kind = self.current_kind()
        seen: list[str] = []
        for name in (*self._known.get(kind, ()), *presets_for(kind)):
            if name and name not in seen:
                seen.append(name)

        current = self.category_combo.currentText()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItems(seen)
        # 切换方向时保留用户已输入的分类，即使它不在候选里
        self.category_combo.setCurrentText(current or DEFAULT_CATEGORY)
        self.category_combo.blockSignals(False)

    # ---------- 联动提示 ----------

    def selected_account(self) -> tuple[int, str, str] | None:
        """当前选中的账户 ``(id, 名称, 类型)``；未关联返回 None。"""
        data = self.account_combo.currentData()
        if data is None or int(data) == NO_ACCOUNT:
            return None
        for account in self._accounts:
            if account[0] == int(data):
                return account
        return None

    def _refresh_hint(self) -> None:
        """把"这笔会怎么改变余额"用人话写出来。"""
        account = self.selected_account()
        if account is None:
            self.hint_label.setText(HINT_UNLINKED)
            return

        account_id, name, account_kind = account
        del account_id  # 仅用于匹配，提示里不需要
        try:
            amount = parse_money(self.amount_edit.text() or "0")
        except ValueError:
            amount_text = "这笔金额"
        else:
            amount_text = format_money(amount)

        is_income = self.current_kind() == FLOW_INCOME
        if account_kind == "asset":
            action = "存入" if is_income else "扣除"
            self.hint_label.setText(f"{action}「{name}」{amount_text}，净资产随之变化。")
        else:
            action = "减少" if is_income else "增加"
            self.hint_label.setText(f"「{name}」的欠款{action} {amount_text}，净资产随之变化。")

    # ---------- 数据 ----------

    def _fill(self, expense: Expense | None) -> None:
        if expense is None:
            self.amount_edit.setFocus()
            return
        self.set_kind(expense.kind)
        self.amount_edit.setText(format_money_plain(expense.amount_cents))
        day = date.fromisoformat(expense.expense_date)
        self.date_edit.setDate(QDate(day.year, day.month, day.day))
        self.category_combo.setCurrentText(expense.category)
        if expense.account_id is not None:
            index = self.account_combo.findData(expense.account_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.note_edit.setText(expense.note)
        self._refresh_hint()

    def _collect(self) -> dict:
        amount_cents = parse_money(self.amount_edit.text())
        category = self.category_combo.currentText().strip() or DEFAULT_CATEGORY
        qdate = self.date_edit.date()
        account = self.selected_account()
        return {
            "expense_date": date(
                qdate.year(), qdate.month(), qdate.day()
            ).isoformat(),
            "amount_cents": amount_cents,
            "category": category,
            "note": self.note_edit.text().strip(),
            "kind": self.current_kind(),
            "account_id": None if account is None else account[0],
        }

    def _on_accept(self) -> None:
        try:
            self._values = self._collect()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.error_label.hide()
        self.accept()

    def values(self) -> dict:
        """校验通过后的字段字典；未通过时调用方拿不到（对话框未 accepted）。"""
        if self._values is None:
            self._values = self._collect()
        return self._values
