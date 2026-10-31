"""学习记录的新增 / 编辑对话框。

一个对话框承担两种用途：传 ``record=None`` 为新增，传入既有记录为编辑。
对话框**只负责收集与校验输入**，不接触仓储层——保存动作由调用方
（``ui/study_view.py``）拿到 ``values()`` 后执行，保持界面与数据分离。

校验策略：错误就地显示在表单底部，不弹模态提示框。
一是减少用户点击次数，二是模态框会阻塞事件循环、让界面测试无从下手。
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
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.study_records import StudyRecord
from ui.theme import Palette

# 常用科目预置项；下拉框可编辑，允许自由输入
SUBJECT_PRESETS: tuple[str, ...] = (
    "数学", "语文", "英语", "物理", "化学",
    "生物", "历史", "地理", "政治", "其他",
)

# 时长输入上限（分钟），对应 10 小时
MAX_DURATION_MINUTES: int = 600


class RecordDialog(QDialog):
    """新增 / 编辑学习记录的表单。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        record: StudyRecord | None = None,
        default_date: date | None = None,
    ) -> None:
        super().__init__(parent)
        self._record = record
        self._is_edit = record is not None

        self.setWindowTitle("编辑学习记录" if self._is_edit else "新增学习记录")
        self.setModal(True)
        self.setMinimumWidth(420)

        self._build_ui()
        self._fill_defaults(default_date)
        if record is not None:
            self.set_values_from_record(record)

    # ---------- 构建 ----------

    def _build_ui(self) -> None:
        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setDate(QDate.currentDate())

        self.subject_combo = QComboBox(self)
        self.subject_combo.setEditable(True)
        self.subject_combo.addItems(SUBJECT_PRESETS)
        self.subject_combo.setCurrentText("")
        self.subject_combo.lineEdit().setPlaceholderText("例如：数学、雅思、算法")

        self.duration_spin = QSpinBox(self)
        self.duration_spin.setRange(0, MAX_DURATION_MINUTES)
        self.duration_spin.setSingleStep(5)
        # 0 表示"未填写"，入库时存 NULL
        self.duration_spin.setSpecialValueText("未填写")
        self.duration_spin.setValue(0)

        self.content_edit = QPlainTextEdit(self)
        self.content_edit.setPlaceholderText("今天学了什么？（可不填）")
        self.content_edit.setFixedHeight(96)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet(f"color: {Palette.DANGER};")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        self.save_button = QPushButton("保存", self)
        self.save_button.setObjectName("primaryButton")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save_clicked)

        self.cancel_button = QPushButton("取消", self)
        self.cancel_button.clicked.connect(self.reject)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setSpacing(10)
        form.addRow("日期", self.date_edit)
        form.addRow("科目", self.subject_combo)
        form.addRow("学习时长", self.duration_spin)
        form.addRow("学习内容", self.content_edit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        root.addLayout(form)
        root.addWidget(self.error_label)
        root.addLayout(buttons)

    def _fill_defaults(self, default_date: date | None) -> None:
        day = default_date or date.today()
        self.date_edit.setDate(QDate(day.year, day.month, day.day))
        # 初始焦点给科目：既符合填写顺序，也避免日期框首次显示时
        # 整段文字处于全选高亮状态、看起来像被误选
        self.subject_combo.setFocus()

    # ---------- 数据 ----------

    def set_values_from_record(self, record: StudyRecord) -> None:
        """把既有记录回填到表单（编辑模式用）。"""
        qdate = QDate.fromString(record.study_date, "yyyy-MM-dd")
        if qdate.isValid():
            self.date_edit.setDate(qdate)
        self.subject_combo.setCurrentText(record.subject)
        self.duration_spin.setValue(record.duration_minutes or 0)
        self.content_edit.setPlainText(record.content)
        # setCurrentText 会把整段文字选中（显示成蓝底），编辑态打开时
        # 看起来像"已被误选"，这里把光标挪到开头取消选中
        self.subject_combo.lineEdit().setCursorPosition(0)

    def values(self) -> dict:
        """收集表单内容，直接对应 ``StudyRecordRepository`` 的字段名。"""
        subject = self.subject_combo.currentText().strip()
        duration = self.duration_spin.value()
        return {
            "study_date": self.date_edit.date().toString("yyyy-MM-dd"),
            "subject": subject,
            "duration_minutes": None if duration == 0 else duration,
            "content": self.content_edit.toPlainText().strip(),
        }

    # ---------- 校验 ----------

    def validate(self) -> str | None:
        """返回错误文案；``None`` 表示通过。"""
        if not self.subject_combo.currentText().strip():
            return "请填写科目"
        if not self.date_edit.date().isValid():
            return "日期无效"
        duration = self.duration_spin.value()
        if duration < 0:
            return "学习时长不能为负数"
        return None

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.hide()

    # ---------- 动作 ----------

    def _on_save_clicked(self) -> None:
        message = self.validate()
        if message is not None:
            self._show_error(message)
            return
        self._clear_error()
        self.accept()
