"""资产 / 负债账户的新增与编辑对话框。

和学习记录、支出两个弹窗同一套约定：只收集与校验，不碰仓储层；校验失败
在表单底部写一行红字，不弹模态框。

额外一点：**切换"资产/负债"时类别候选跟着换**。资产有"银行卡、投资"，
负债有"信用卡、房贷"，混在一起会让下拉框变成一长串无关选项。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.accounts import (
    ASSET,
    CATEGORY_PRESETS,
    KIND_LABELS,
    LIABILITY,
    Account,
)
from ui.formatting import format_money_plain, parse_money
from ui.theme import Palette


class AccountDialog(QDialog):
    """新增 / 编辑一个账户。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        account: Account | None = None,
        known_categories: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._account = account
        self._is_edit = account is not None
        # {kind: (实际用过的类别...)}；切换类型时只取对应那一份
        self._known: dict[str, tuple[str, ...]] = dict(known_categories or {})
        self._values: dict | None = None

        self.setWindowTitle("编辑账户" if self._is_edit else "新增账户")
        self.setModal(True)
        self.setMinimumWidth(400)

        self._build_ui()
        self._fill(account)

    # ---------- 构建 ----------

    def _build_ui(self) -> None:
        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("例如：招商银行卡、花呗、房贷")
        self.name_edit.setClearButtonEnabled(True)

        self.kind_combo = QComboBox(self)
        for kind in (ASSET, LIABILITY):
            self.kind_combo.addItem(KIND_LABELS[kind], kind)

        self.balance_edit = QLineEdit(self)
        self.balance_edit.setPlaceholderText("0.00")

        self.category_combo = QComboBox(self)
        self.category_combo.setEditable(True)
        self.category_combo.setCurrentText("")
        self.category_combo.lineEdit().setPlaceholderText("可不填")

        self.note_edit = QLineEdit(self)
        self.note_edit.setPlaceholderText("备注（可不填）")

        self.hint_label = QLabel("", self)
        self.hint_label.setObjectName("emptyHint")
        self.hint_label.setWordWrap(True)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow("名称", self.name_edit)
        form.addRow("类型", self.kind_combo)
        form.addRow("金额", self.balance_edit)
        form.addRow("类别", self.category_combo)
        form.addRow("备注", self.note_edit)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet(f"color: {Palette.DANGER};")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存", self)
        save.setObjectName("primaryButton")
        save.setDefault(True)
        save.clicked.connect(self._on_accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.error_label, 1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.hint_label)
        layout.addLayout(buttons)

        self.kind_combo.currentIndexChanged.connect(self._refresh_categories)
        self._refresh_categories()

    def _refresh_categories(self) -> None:
        """按当前类型重建类别候选，同时更新金额的说明文案。"""
        kind = self.current_kind()
        presets = CATEGORY_PRESETS.get(kind, ())
        seen: list[str] = []
        for name in (*self._known.get(kind, ()), *presets):
            if name and name not in seen:
                seen.append(name)

        current = self.category_combo.currentText()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItems(seen)
        self.category_combo.setCurrentText(current)
        self.category_combo.blockSignals(False)

        if kind == LIABILITY:
            self.hint_label.setText("填欠款金额，按正数记。净资产 = 资产合计 − 负债合计。")
        else:
            self.hint_label.setText("填这个账户现在实际有多少，不是买入价。")

    # ---------- 数据 ----------

    def current_kind(self) -> str:
        data = self.kind_combo.currentData()
        return str(data) if data else ASSET

    def _fill(self, account: Account | None) -> None:
        if account is None:
            self.name_edit.setFocus()
            return
        self.name_edit.setText(account.name)
        index = self.kind_combo.findData(account.kind)
        if index >= 0:
            self.kind_combo.setCurrentIndex(index)
        self.balance_edit.setText(format_money_plain(account.balance_cents))
        self._refresh_categories()
        self.category_combo.setCurrentText(account.category)
        self.note_edit.setText(account.note)
        self.name_edit.setCursorPosition(0)

    def _collect(self) -> dict:
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("请填写账户名称")
        balance = parse_money(self.balance_edit.text() or "0", allow_zero=True)
        return {
            "name": name,
            "kind": self.current_kind(),
            "balance_cents": balance,
            "category": self.category_combo.currentText().strip(),
            "note": self.note_edit.text().strip(),
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
        """校验通过后的字段字典，键名对应 ``AccountRepository`` 的参数。"""
        if self._values is None:
            self._values = self._collect()
        return self._values
