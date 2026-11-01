"""记账功能的测试：金额解析、仓储增删改查、账本视图与页签切换。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.database import DatabaseManager
from core.expenses import ExpenseRepository
from core.study_records import StudyRecordRepository
from ui.expense_view import CATEGORY_TAB_ALL, ExpenseView
from ui.formatting import format_money, format_money_plain, parse_money
from ui.main_window import MainWindow

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class MoneyFormatTests(unittest.TestCase):
    def test_format_money(self):
        self.assertEqual(format_money(0), "¥0.00")
        self.assertEqual(format_money(5), "¥0.05")
        self.assertEqual(format_money(1250), "¥12.50")
        self.assertEqual(format_money(123456789), "¥1,234,567.89")

    def test_plain_money_is_copyable(self):
        self.assertEqual(format_money_plain(1250), "12.50")
        self.assertEqual(format_money_plain(0), "0.00")

    def test_parse_accepts_common_inputs(self):
        self.assertEqual(parse_money("12"), 1200)
        self.assertEqual(parse_money("12.5"), 1250)
        self.assertEqual(parse_money(" ￥12.50 "), 1250)
        self.assertEqual(parse_money("1,200"), 120000)

    def test_parse_rounds_to_cent(self):
        self.assertEqual(parse_money("12.505"), 1251)
        self.assertEqual(parse_money("0.004"), 0)  # 四舍五入到 0 分

    def test_parse_rejects_bad_input(self):
        for text in ("", "   ", "abc", "-5", "0"):
            with self.assertRaises(ValueError, msg=text):
                parse_money(text)

    def test_format_rejects_float(self):
        with self.assertRaises(TypeError):
            format_money(12.5)


class ExpenseRepositoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = ExpenseRepository(self.db)

    def test_add_and_read_back(self):
        record_id = self.repo.add("2026-11-01", 1250, "吃饭", "午饭")
        expense = self.repo.get(record_id)
        self.assertEqual(expense.amount_cents, 1250)
        self.assertEqual(expense.category, "吃饭")
        self.assertEqual(expense.note, "午饭")
        self.assertEqual(expense.expense_date, "2026-11-01")

    def test_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError):
            self.repo.add("2026-11-01", 0)
        with self.assertRaises(ValueError):
            self.repo.add("2026-11-01", -100)

    def test_rejects_impossible_date(self):
        with self.assertRaises(ValueError):
            self.repo.add("2026-02-30", 100)

    def test_month_total_and_category_totals(self):
        self.repo.add("2026-11-01", 1250, "吃饭")
        self.repo.add("2026-11-02", 350, "交通")
        self.repo.add("2026-11-30", 1000, "吃饭")
        self.repo.add("2026-10-31", 9999, "吃饭")  # 上个月，不应计入
        self.assertEqual(self.repo.month_total_cents(2026, 11), 2600)
        self.assertEqual(
            self.repo.category_totals(2026, 11), [("吃饭", 2250), ("交通", 350)]
        )

    def test_list_by_month_is_descending(self):
        self.repo.add("2026-11-01", 100)
        self.repo.add("2026-11-20", 200)
        dates = [e.expense_date for e in self.repo.list_by_month(2026, 11)]
        self.assertEqual(dates, ["2026-11-20", "2026-11-01"])

    def test_list_categories_sorted_by_usage(self):
        self.repo.add("2026-11-01", 100, "吃饭")
        self.repo.add("2026-11-02", 100, "吃饭")
        self.repo.add("2026-11-03", 100, "交通")
        self.assertEqual(self.repo.list_categories(), ["吃饭", "交通"])

    def test_update_and_delete(self):
        record_id = self.repo.add("2026-11-01", 100, "吃饭")
        self.assertTrue(self.repo.update(record_id, amount_cents=250, note="加了个蛋"))
        updated = self.repo.get(record_id)
        self.assertEqual(updated.amount_cents, 250)
        self.assertEqual(updated.note, "加了个蛋")
        self.assertTrue(self.repo.delete(record_id))
        self.assertIsNone(self.repo.get(record_id))

    def test_update_missing_row_returns_false(self):
        self.assertFalse(self.repo.update(999, amount_cents=100))

    def test_month_range_handles_december(self):
        self.repo.add("2026-12-31", 500)
        self.assertEqual(self.repo.month_total_cents(2026, 12), 500)

    def test_invalid_month_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.list_by_month(2026, 13)


class ExpenseViewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = ExpenseRepository(self.db)
        self.view = ExpenseView(self.repo)
        self.addCleanup(self.view.deleteLater)
        # 固定到 2026 年 11 月，避免月初/月末切换导致断言飘
        self.view._year, self.view._month = 2026, 11
        self.view.refresh()

    def test_empty_month_shows_hint(self):
        self.assertFalse(self.view.empty_hint.isHidden())
        self.assertEqual(self.view.total_label.text(), "¥0.00")

    def test_rows_and_summary(self):
        self.repo.add("2026-11-01", 1250, "吃饭", "午饭")
        self.repo.add("2026-11-03", 350, "交通")
        self.view.refresh()
        self.assertEqual(self.view.table.rowCount(), 2)
        self.assertTrue(self.view.empty_hint.isHidden())
        self.assertEqual(self.view.total_label.text(), "¥16.00")
        self.assertEqual(self.view.table.item(0, 2).text(), "¥3.50")
        self.assertIn("吃饭", self.view.detail_label.text())

    def test_category_filter(self):
        self.repo.add("2026-11-01", 1250, "吃饭")
        self.repo.add("2026-11-03", 350, "交通")
        self.view.refresh()
        self.view.set_category_filter("吃饭")
        self.assertEqual(self.view.table.rowCount(), 1)
        self.assertTrue(self.view._category_buttons["吃饭"].isChecked())
        self.view.set_category_filter(CATEGORY_TAB_ALL)
        self.assertEqual(self.view.table.rowCount(), 2)

    def test_add_expense_via_replaced_dialog(self):
        self.view._ask_expense = lambda expense: {
            "expense_date": "2026-11-05",
            "amount_cents": 880,
            "category": "学习",
            "note": "买笔",
        }
        self.view.add_expense()
        self.assertEqual(self.view.table.rowCount(), 1)
        self.assertEqual(self.repo.count(), 1)

    def test_delete_uses_confirmation(self):
        record_id = self.repo.add("2026-11-01", 500, "其他")
        self.view.refresh()
        self.view.table.selectRow(0)
        self.view._confirm_delete = lambda expense: True
        self.view.delete_expense()
        self.assertIsNone(self.repo.get(record_id))

    def test_shift_month_moves_window(self):
        self.view.shift_month(1)
        self.assertEqual((self.view.year, self.view.month), (2026, 12))
        self.view.shift_month(1)
        self.assertEqual((self.view.year, self.view.month), (2027, 1))

    def test_actions_disabled_without_selection(self):
        self.repo.add("2026-11-01", 500, "其他")
        self.view.refresh()
        self.assertFalse(self.view.edit_button.isEnabled())
        self.view.table.selectRow(0)
        self.assertTrue(self.view.edit_button.isEnabled())


class WindowSwitchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.window = MainWindow(
            StudyRecordRepository(self.db), expense_repository=ExpenseRepository(self.db)
        )
        self.addCleanup(self.window.deleteLater)

    def test_both_pages_present(self):
        self.assertIsNotNone(self.window.expense_view)
        self.assertEqual(self.window.stack.count(), 2)
        self.assertEqual(self.window.stack.currentIndex(), 0)

    def test_switch_to_ledger(self):
        self.window.show_page(1)
        self.assertEqual(self.window.stack.currentIndex(), 1)
        self.assertTrue(self.window.expense_tab.isChecked())
        self.assertFalse(self.window.study_tab.isChecked())

    def test_switch_without_ledger_keeps_single_page(self):
        plain = MainWindow(StudyRecordRepository(self.db))
        self.addCleanup(plain.deleteLater)
        self.assertEqual(plain.stack.count(), 1)
        plain.show_page(1)  # 越界请求应被忽略
        self.assertEqual(plain.stack.currentIndex(), 0)


if __name__ == "__main__":
    unittest.main()
