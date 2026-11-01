"""记一笔支出的对话框。

和学习记录的弹窗同样的约定：只收集与校验，不碰仓储层；校验失败就在表单底部
写一行红字，不弹模态框（省一次点击，也便于测试）。
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

from core.expenses import CATEGORY_PRESETS, DEFAULT_CATEGORY, Expense
from ui.formatting import format_money_plain, parse_money
from ui.theme import Palette


class ExpenseDialog(QDialog):
    """新增 / 编辑一笔支出。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        expense: Expense | None = None,
        default_date: date | None = None,
        known_categories: tuple[str, ...] = (),
    ) -> None:
        super().__init__(parent)
        self._expense = expense
        self._is_edit = expense is not None
        self._values: dict | None = None

        self.setWindowTitle("编辑支出" if self._is_edit else "记一笔")
        self.setModal(True)
        self.setMinimumWidth(380)

        self._build_ui(default_date, known_categories)
        self._fill(expense)

    # ---------- 构建 ----------

    def _build_ui(self, default_date: date | None, known: tuple[str, ...]) -> None:
        self.amount_edit = QLineEdit(self)
        self.amount_edit.setPlaceholderText("0.00")
        self.amount_edit.setClearButtonEnabled(True)

        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        target = default_date or date.today()
        self.date_edit.setDate(QDate(target.year, target.month, target.day))

        self.category_combo = QComboBox(self)
        self.category_combo.setEditable(True)
        # 先放用过的分类，再补预置项，避免常用分类沉到列表底部
        seen: list[str] = []
        for name in (*known, *CATEGORY_PRESETS):
            if name not in seen:
                seen.append(name)
        self.category_combo.addItems(seen)
        self.category_combo.setCurrentText(DEFAULT_CATEGORY)

        self.note_edit = QLineEdit(self)
        self.note_edit.setPlaceholderText("买了什么（可留空）")

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("金额", self.amount_edit)
        form.addRow("日期", self.date_edit)
        form.addRow("分类", self.category_combo)
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
        layout.addLayout(form)
        layout.addLayout(buttons)

    def _fill(self, expense: Expense | None) -> None:
        if expense is None:
            self.amount_edit.setFocus()
            return
        self.amount_edit.setText(format_money_plain(expense.amount_cents))
        day = date.fromisoformat(expense.expense_date)
        self.date_edit.setDate(QDate(day.year, day.month, day.day))
        self.category_combo.setCurrentText(expense.category)
        self.note_edit.setText(expense.note)

    # ---------- 取值 ----------

    def _on_accept(self) -> None:
        try:
            self._values = self._collect()
        except ValueError as exc:
            self.error_label.setText(str(exc))
            self.error_label.show()
            return
        self.accept()

    def _collect(self) -> dict:
        amount_cents = parse_money(self.amount_edit.text())
        category = self.category_combo.currentText().strip() or DEFAULT_CATEGORY
        qdate = self.date_edit.date()
        return {
            "expense_date": date(qdate.year(), qdate.month(), qdate.day()).isoformat(),
            "amount_cents": amount_cents,
            "category": category,
            "note": self.note_edit.text().strip(),
        }

    def values(self) -> dict:
        """校验通过后的字段字典；未通过时调用方拿不到（对话框未 accepted）。"""
        if self._values is None:
            self._values = self._collect()
        return self._values
