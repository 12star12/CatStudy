"""``ui/record_dialog.py`` 测试（offscreen，不依赖数据库）。

覆盖：默认值、回填、取值映射（0 分钟 -> NULL）、校验规则、
保存/取消按钮行为。

关键点：所有用例都直接调用方法，**不调用 ``exec()``**——
模态循环会阻塞测试进程。

运行：
    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from core.study_records import StudyRecord  # noqa: E402
from ui.record_dialog import (  # noqa: E402
    MAX_DURATION_MINUTES,
    SUBJECT_PRESETS,
    RecordDialog,
)

_app: QApplication | None = None


def setUpModule() -> None:
    global _app
    _app = QApplication.instance() or QApplication([])


def make_record(**kwargs) -> StudyRecord:
    data = dict(
        id=7,
        study_date="2026-10-20",
        subject="数学",
        duration_minutes=45,
        content="导数",
        created_at="2026-10-20 09:00:00",
        updated_at="2026-10-20 09:30:00",
    )
    data.update(kwargs)
    return StudyRecord(**data)


class DialogDefaultsTest(unittest.TestCase):
    def test_new_dialog_starts_empty(self) -> None:
        dlg = RecordDialog(default_date=date(2026, 10, 31))
        try:
            self.assertEqual(dlg.windowTitle(), "新增学习记录")
            self.assertEqual(dlg.subject_combo.currentText(), "")
            self.assertEqual(dlg.duration_spin.value(), 0)
            self.assertEqual(dlg.content_edit.toPlainText(), "")
            self.assertEqual(dlg.date_edit.date().toString("yyyy-MM-dd"), "2026-10-31")
        finally:
            dlg.close()

    def test_duration_zero_shows_placeholder_text(self) -> None:
        dlg = RecordDialog()
        try:
            self.assertEqual(dlg.duration_spin.specialValueText(), "未填写")
            self.assertEqual(dlg.duration_spin.minimum(), 0)
            self.assertEqual(dlg.duration_spin.maximum(), MAX_DURATION_MINUTES)
        finally:
            dlg.close()

    def test_subject_combo_is_editable_with_presets(self) -> None:
        dlg = RecordDialog()
        try:
            self.assertTrue(dlg.subject_combo.isEditable())
            items = tuple(dlg.subject_combo.itemText(i) for i in range(dlg.subject_combo.count()))
            self.assertEqual(items, SUBJECT_PRESETS)
        finally:
            dlg.close()

    def test_error_label_hidden_initially(self) -> None:
        """用 isHidden() 而非 isVisible()：父窗口未 show 时 isVisible 恒为 False。"""
        dlg = RecordDialog()
        try:
            self.assertTrue(dlg.error_label.isHidden())
        finally:
            dlg.close()


class DialogValuesTest(unittest.TestCase):
    def test_values_from_empty_form(self) -> None:
        dlg = RecordDialog(default_date=date(2026, 10, 31))
        try:
            dlg.subject_combo.setCurrentText("英语")
            self.assertEqual(
                dlg.values(),
                {
                    "study_date": "2026-10-31",
                    "subject": "英语",
                    "duration_minutes": None,     # 0 -> NULL
                    "content": "",
                },
            )
        finally:
            dlg.close()

    def test_values_with_all_fields(self) -> None:
        dlg = RecordDialog()
        try:
            dlg.date_edit.setDate(dlg.date_edit.date().fromString("2026-03-05", "yyyy-MM-dd"))
            dlg.subject_combo.setCurrentText("  物理  ")
            dlg.duration_spin.setValue(90)
            dlg.content_edit.setPlainText("  受力分析  \n第二行  ")
            values = dlg.values()
            self.assertEqual(values["study_date"], "2026-03-05")
            self.assertEqual(values["subject"], "物理")          # 去首尾空格
            self.assertEqual(values["duration_minutes"], 90)
            self.assertEqual(values["content"], "受力分析  \n第二行")
        finally:
            dlg.close()

    def test_duration_none_roundtrip(self) -> None:
        dlg = RecordDialog(record=make_record(duration_minutes=None))
        try:
            self.assertEqual(dlg.duration_spin.value(), 0)
            self.assertIsNone(dlg.values()["duration_minutes"])
        finally:
            dlg.close()


class DialogPrefillTest(unittest.TestCase):
    def test_edit_mode_title(self) -> None:
        dlg = RecordDialog(record=make_record())
        try:
            self.assertEqual(dlg.windowTitle(), "编辑学习记录")
        finally:
            dlg.close()

    def test_prefill_from_record(self) -> None:
        dlg = RecordDialog(record=make_record())
        try:
            self.assertEqual(dlg.date_edit.date().toString("yyyy-MM-dd"), "2026-10-20")
            self.assertEqual(dlg.subject_combo.currentText(), "数学")
            self.assertEqual(dlg.duration_spin.value(), 45)
            self.assertEqual(dlg.content_edit.toPlainText(), "导数")
        finally:
            dlg.close()

    def test_prefill_unknown_subject_kept(self) -> None:
        """自定义科目不在预置列表里，也必须原样回填。"""
        dlg = RecordDialog(record=make_record(subject="雅思"))
        try:
            self.assertEqual(dlg.subject_combo.currentText(), "雅思")
        finally:
            dlg.close()

    def test_edit_values_reflect_changes(self) -> None:
        dlg = RecordDialog(record=make_record())
        try:
            dlg.subject_combo.setCurrentText("化学")
            dlg.duration_spin.setValue(30)
            values = dlg.values()
            self.assertEqual(values["subject"], "化学")
            self.assertEqual(values["duration_minutes"], 30)
        finally:
            dlg.close()


class DialogValidationTest(unittest.TestCase):
    def test_empty_subject_rejected(self) -> None:
        dlg = RecordDialog()
        try:
            dlg.subject_combo.setCurrentText("")
            self.assertEqual(dlg.validate(), "请填写科目")
        finally:
            dlg.close()

    def test_whitespace_subject_rejected(self) -> None:
        dlg = RecordDialog()
        try:
            dlg.subject_combo.setCurrentText("    ")
            self.assertEqual(dlg.validate(), "请填写科目")
        finally:
            dlg.close()

    def test_valid_form_passes(self) -> None:
        dlg = RecordDialog()
        try:
            dlg.subject_combo.setCurrentText("数学")
            self.assertIsNone(dlg.validate())
        finally:
            dlg.close()

    def test_save_with_invalid_shows_error_and_keeps_open(self) -> None:
        dlg = RecordDialog()
        try:
            dlg.subject_combo.setCurrentText("")
            dlg.save_button.click()
            self.assertEqual(dlg.result(), 0)          # 未 accept
            self.assertFalse(dlg.error_label.isHidden())
            self.assertEqual(dlg.error_label.text(), "请填写科目")
        finally:
            dlg.close()

    def test_save_with_valid_accepts_and_hides_error(self) -> None:
        dlg = RecordDialog()
        try:
            dlg.subject_combo.setCurrentText("数学")
            dlg.save_button.click()
            self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
            self.assertTrue(dlg.error_label.isHidden())
        finally:
            dlg.close()

    def test_error_cleared_after_fixing(self) -> None:
        dlg = RecordDialog()
        try:
            dlg.save_button.click()
            self.assertFalse(dlg.error_label.isHidden())
            dlg.subject_combo.setCurrentText("英语")
            dlg.save_button.click()
            self.assertTrue(dlg.error_label.isHidden())
        finally:
            dlg.close()

    def test_cancel_does_not_validate(self) -> None:
        dlg = RecordDialog()
        try:
            dlg.subject_combo.setCurrentText("")
            dlg.cancel_button.click()
            self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
