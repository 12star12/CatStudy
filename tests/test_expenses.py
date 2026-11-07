"""记账功能的测试：金额解析、仓储增删改查、账本视图与页签切换。"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

from core.accounts import ASSET, LIABILITY, AccountRepository
from core.database import DatabaseManager
from core.expenses import (
    FLOW_EXPENSE,
    FLOW_INCOME,
    ExpenseRepository,
    flow_delta,
    presets_for,
)
from core.study_records import StudyRecordRepository
from ui import expense_view as expense_view_module
from ui.expense_dialog import ExpenseDialog
from ui.expense_view import CATEGORY_TAB_ALL, ExpenseView
from ui.formatting import (
    balance_ratio,
    format_balance_hint,
    format_income_meta,
    format_money,
    format_money_plain,
    parse_money,
)
from ui.main_window import MainWindow
from ui.theme import Palette

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

    def test_parse_arithmetic(self):
        self.assertEqual(parse_money("6.9+2.49"), 939)
        self.assertEqual(parse_money("3*4"), 1200)
        self.assertEqual(parse_money("(12+8)/2"), 1000)
        self.assertEqual(parse_money("10-2.5"), 750)
        # 中文输入法下的全角符号也要能算
        self.assertEqual(parse_money("6.9＋2.49"), 939)
        self.assertEqual(parse_money("10－2"), 800)

    def test_parse_rejects_unsafe_expression(self):
        # 只允许四则运算，幂/函数/属性访问一律拒绝
        for text in ("2**10", "abs(-1)", "1 if 1 else 2", "__import__('os')"):
            with self.assertRaises(ValueError, msg=text):
                parse_money(text)

    def test_parse_rejects_division_by_zero(self):
        with self.assertRaises(ValueError):
            parse_money("1/0")

    def test_format_rejects_float(self):
        with self.assertRaises(TypeError):
            format_money(12.5)


class BalanceHintTests(unittest.TestCase):
    """结余评语：先保住记账意愿，再引导创收。"""

    def test_empty_month_has_no_comment(self):
        self.assertEqual(format_balance_hint(0, 0), "")

    def test_missing_income_blames_data_not_user(self):
        hint = format_balance_hint(0, 1839)
        self.assertIn("收入", hint)

    def test_missing_expense(self):
        self.assertIn("花销", format_balance_hint(800000, 0))

    def test_negative_balance_states_gap_without_judging(self):
        hint = format_balance_hint(1000, 2839)
        self.assertIn("还差", hint)
        self.assertIn("¥18.39", hint)
        # 省钱和多赚两条路都要给：只说省，用户会觉得永远在被限制
        self.assertIn("多赚", hint)
        self.assertIn("少花", hint)
        # 而且"多赚"要排在"少花"前面：先给增量，再给节制
        self.assertLess(hint.index("多赚"), hint.index("少花"))

    def test_break_even(self):
        self.assertIn("打平", format_balance_hint(5000, 5000))

    def test_praise_scales_with_ratio(self):
        self.assertIn("一半以上", format_balance_hint(10000, 4000))  # 60%
        self.assertIn("有结余", format_balance_hint(10000, 7000))    # 30%
        self.assertIn("结余不多", format_balance_hint(10000, 9500))  # 5%

    def test_no_hint_is_blaming(self):
        """所有分支都不得出现指责性措辞。"""
        banned = ("花得比赚得多", "超支", "警告", "太多了", "省着点")
        cases = (
            (0, 0), (0, 100), (100, 0), (100, 200), (100, 100),
            (1000, 100), (1000, 900), (1000, 999), (1000, 1001),
        )
        for income, expense in cases:
            hint = format_balance_hint(income, expense)
            for word in banned:
                self.assertNotIn(word, hint, f"{income}/{expense} -> {hint}")

    def test_ratio_edges(self):
        self.assertEqual(balance_ratio(0, 100), 0.0, "收入为 0 时不能除零")
        self.assertEqual(balance_ratio(100, 100), 0.0)
        self.assertAlmostEqual(balance_ratio(100, 30), 0.7)
        self.assertAlmostEqual(balance_ratio(100, 200), -1.0)


class IncomeMetaTests(unittest.TestCase):
    """收入小字：只陈述积累，不设目标。"""

    def test_first_time_invites_low_threshold(self):
        hint = format_income_meta(0, 0, 0)
        self.assertIn("多少都算", hint)

    def test_quiet_month_keeps_year_total(self):
        """本月没进账但今年有过：不催，只把不清零的那个数留着。"""
        hint = format_income_meta(0, 0, 680000)
        self.assertIn("今年累计", hint)
        self.assertIn("¥6,800.00", hint)
        self.assertNotIn("还差", hint)

    def test_counts_entries_and_sources(self):
        hint = format_income_meta(2, 2, 680000)
        self.assertIn("本月 2 笔", hint)
        self.assertIn("2 个来源", hint)
        self.assertIn("今年累计", hint)

    def test_single_source_is_not_shown(self):
        """来源只有一个时不显示，否则每个月都是一模一样的一句噪音。"""
        self.assertNotIn("来源", format_income_meta(1, 1, 50000))

    def test_no_target_language(self):
        banned = ("还差", "目标", "完成度", "%", "加油")
        for entries, sources, year in ((0, 0, 0), (0, 0, 900), (3, 2, 900)):
            hint = format_income_meta(entries, sources, year)
            for word in banned:
                self.assertNotIn(word, hint, f"{entries}/{sources}/{year} -> {hint}")


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

    def test_year_income_spans_months_but_not_years(self):
        self.repo.add("2026-01-05", 500000, "工资", kind=FLOW_INCOME)
        self.repo.add("2026-11-02", 80000, "稿费", kind=FLOW_INCOME)
        self.repo.add("2026-11-03", 3000, "吃饭")  # 支出不该混进来
        self.repo.add("2025-12-31", 999999, "工资", kind=FLOW_INCOME)  # 去年
        self.assertEqual(self.repo.year_income_cents(2026), 580000)

    def test_month_income_entries_counts_rows_not_money(self):
        self.repo.add("2026-11-02", 300, "稿费", kind=FLOW_INCOME)
        self.repo.add("2026-11-03", 900000, "工资", kind=FLOW_INCOME)
        self.repo.add("2026-11-04", 1250, "吃饭")
        self.assertEqual(self.repo.month_income_entries(2026, 11), 2)
        self.assertEqual(self.repo.month_income_entries(2026, 12), 0)

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
        # 右卡大数字现在是「本月结余」= 收入 − 支出
        self.assertEqual(self.view.balance_label.text(), "¥0.00")

    def test_rows_and_summary(self):
        self.repo.add("2026-11-01", 1250, "吃饭", "午饭")
        self.repo.add("2026-11-03", 350, "交通")
        self.view.refresh()
        self.assertEqual(self.view.table.rowCount(), 2)
        self.assertTrue(self.view.empty_hint.isHidden())
        self.assertEqual(self.view.balance_label.text(), "-¥16.00")  # 只有支出，结余为负
        self.assertEqual(self.view.expense_label.text(), "¥16.00")
        self.assertEqual(self.view.income_label.text(), "¥0.00")
        # 日期倒序，第一行是 11-03 的 3.50；支出带负号以便和收入区分
        self.assertEqual(self.view.table.item(0, 2).text(), "-¥3.50")
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

    def test_negative_balance_is_not_painted_as_error(self):
        """结余为负是常态（月初没发工资），不该用报错的红色。"""
        self.repo.add("2026-11-01", 1250, "吃饭")
        self.view.refresh()
        self.assertNotIn(Palette.DANGER, self.view.balance_label.styleSheet())
        self.assertIn(Palette.INK_STRONG, self.view.balance_label.styleSheet())

    def test_hint_invites_recording_income(self):
        """只记支出时，提示的是"收入没记"，不是"你花超了"。"""
        self.repo.add("2026-11-01", 1250, "吃饭")
        self.view.refresh()
        self.assertIn("收入", self.view.balance_hint.text())

    def test_hint_praises_when_saving(self):
        self.repo.add("2026-11-01", 1250, "吃饭")
        self.repo.add("2026-11-02", 800000, "工资", kind=FLOW_INCOME)
        self.view.refresh()
        self.assertIn("存下", self.view.balance_hint.text())

    def test_income_meta_counts_sources(self):
        self.repo.add("2026-11-02", 80000, "稿费", kind=FLOW_INCOME)
        self.repo.add("2026-11-03", 500000, "工资", kind=FLOW_INCOME)
        self.view.refresh()
        text = self.view.income_meta.text()
        self.assertIn("本月 2 笔", text)
        self.assertIn("2 个来源", text)
        self.assertIn("¥5,800.00", text)  # 今年累计

    def test_income_meta_does_not_drop_when_spending(self):
        """支出再多，进账那行的年度累计也不变——这是它区别于结余的地方。"""
        self.repo.add("2026-11-02", 80000, "稿费", kind=FLOW_INCOME)
        self.view.refresh()
        before = self.view.income_meta.text()
        self.repo.add("2026-11-03", 900000, "吃饭")
        self.view.refresh()
        self.assertIn("¥800.00", self.view.income_meta.text())
        self.assertEqual(before, self.view.income_meta.text())

    def test_income_meta_guides_first_entry(self):
        self.view.refresh()
        self.assertIn("多少都算", self.view.income_meta.text())

    def test_new_expense_defaults_to_today(self):
        """记一笔的默认日期是当天，不是当前浏览月份的一号。"""
        self.view._year, self.view._month = 2025, 3
        captured: dict = {}

        class _StubDialog:
            def __init__(self, parent, **kwargs):
                captured.update(kwargs)

            def exec(self):
                return QDialog.DialogCode.Rejected

        original = expense_view_module.ExpenseDialog
        expense_view_module.ExpenseDialog = _StubDialog
        try:
            self.view.add_expense()
        finally:
            expense_view_module.ExpenseDialog = original
        self.assertEqual(captured["default_date"], date.today())


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
        self.assertEqual(self.window.stack.count(), 3)  # + 统计页
        self.assertEqual(self.window.stack.currentIndex(), 0)

    def test_switch_to_ledger(self):
        self.window.show_page(1)
        self.assertEqual(self.window.stack.currentIndex(), 1)
        self.assertTrue(self.window.expense_tab.isChecked())
        self.assertFalse(self.window.study_tab.isChecked())

    def test_switch_without_ledger_keeps_single_study_page(self):
        plain = MainWindow(StudyRecordRepository(self.db))
        self.addCleanup(plain.deleteLater)
        self.assertEqual(plain.stack.count(), 2)  # 学习记录 + 统计
        self.assertIsNone(plain.expense_tab)
        plain.show_page(5)  # 越界请求应被忽略
        self.assertEqual(plain.stack.currentIndex(), 0)


class FlowKindTests(unittest.TestCase):
    """收支方向：汇总、分类、符号。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = ExpenseRepository(self.db)

    def test_default_is_expense(self):
        expense = self.repo.get(self.repo.add("2026-11-01", 100))
        self.assertEqual(expense.kind, FLOW_EXPENSE)
        self.assertFalse(expense.is_income)
        self.assertEqual(expense.signed_cents, -100)

    def test_income_signed_cents(self):
        expense = self.repo.get(
            self.repo.add("2026-11-01", 8000, "兼职", kind=FLOW_INCOME)
        )
        self.assertTrue(expense.is_income)
        self.assertEqual(expense.signed_cents, 8000)

    def test_totals_separate_by_kind(self):
        self.repo.add("2026-11-01", 1250, "吃饭")
        self.repo.add("2026-11-02", 8000, "兼职", kind=FLOW_INCOME)
        self.repo.add("2026-11-03", 500, "工资", kind=FLOW_INCOME)
        self.assertEqual(self.repo.month_total_cents(2026, 11), 1250)
        self.assertEqual(self.repo.month_income_cents(2026, 11), 8500)
        self.assertEqual(self.repo.month_net_cents(2026, 11), 7250)

    def test_net_can_be_negative(self):
        self.repo.add("2026-11-01", 9000, "吃饭")
        self.assertEqual(self.repo.month_net_cents(2026, 11), -9000)

    def test_list_by_month_filters_kind(self):
        self.repo.add("2026-11-01", 100, "吃饭")
        self.repo.add("2026-11-02", 200, "兼职", kind=FLOW_INCOME)
        self.assertEqual(len(self.repo.list_by_month(2026, 11)), 2)
        self.assertEqual(
            [e.category for e in self.repo.list_by_month(2026, 11, FLOW_INCOME)],
            ["兼职"],
        )
        self.assertEqual(
            [e.category for e in self.repo.list_by_month(2026, 11, FLOW_EXPENSE)],
            ["吃饭"],
        )

    def test_category_totals_by_kind(self):
        self.repo.add("2026-11-01", 100, "吃饭")
        self.repo.add("2026-11-02", 300, "兼职", kind=FLOW_INCOME)
        self.assertEqual(self.repo.category_totals(2026, 11), [("吃饭", 100)])
        self.assertEqual(
            self.repo.category_totals(2026, 11, FLOW_INCOME), [("兼职", 300)]
        )

    def test_list_categories_by_kind(self):
        self.repo.add("2026-11-01", 100, "吃饭")
        self.repo.add("2026-11-02", 300, "兼职", kind=FLOW_INCOME)
        self.assertEqual(self.repo.list_categories(), ["吃饭"])
        self.assertEqual(self.repo.list_categories(FLOW_INCOME), ["兼职"])

    def test_presets_differ_by_kind(self):
        self.assertIn("吃饭", presets_for(FLOW_EXPENSE))
        self.assertNotIn("吃饭", presets_for(FLOW_INCOME))
        self.assertIn("工资", presets_for(FLOW_INCOME))

    def test_rejects_bad_kind(self):
        with self.assertRaises(ValueError):
            self.repo.add("2026-11-01", 100, kind="transfer")


class AccountLinkTests(unittest.TestCase):
    """流水与账户余额联动。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.accounts = AccountRepository(self.db)
        self.repo = ExpenseRepository(self.db)
        self.card = self.accounts.add("招行卡", ASSET, 100000, "银行卡")
        self.credit = self.accounts.add("花呗", LIABILITY, 50000, "花呗")

    def _balance(self, account_id):
        account = self.accounts.get(account_id)
        assert account is not None
        return account.balance_cents

    def test_flow_delta_matrix(self):
        self.assertEqual(flow_delta(FLOW_EXPENSE, ASSET, 100), -100)
        self.assertEqual(flow_delta(FLOW_EXPENSE, LIABILITY, 100), 100)
        self.assertEqual(flow_delta(FLOW_INCOME, ASSET, 100), 100)
        self.assertEqual(flow_delta(FLOW_INCOME, LIABILITY, 100), -100)

    def test_expense_from_asset_reduces_balance(self):
        self.repo.add("2026-11-01", 3000, "吃饭", account_id=self.card)
        self.assertEqual(self._balance(self.card), 97000)

    def test_income_to_asset_increases_balance(self):
        self.repo.add(
            "2026-11-01", 8000, "兼职", kind=FLOW_INCOME, account_id=self.card
        )
        self.assertEqual(self._balance(self.card), 108000)

    def test_expense_on_liability_increases_debt(self):
        self.repo.add("2026-11-01", 2000, "购物", account_id=self.credit)
        self.assertEqual(self._balance(self.credit), 52000)

    def test_income_on_liability_reduces_debt(self):
        self.repo.add(
            "2026-11-01", 20000, "其他", kind=FLOW_INCOME, account_id=self.credit
        )
        self.assertEqual(self._balance(self.credit), 30000)

    def test_unlinked_keeps_balance(self):
        self.repo.add("2026-11-01", 3000, "吃饭")
        self.assertEqual(self._balance(self.card), 100000)
        self.assertEqual(self._balance(self.credit), 50000)

    def test_overdraft_allowed(self):
        """余额不足时照常记账，账户变成负数——比拒绝记账更不烦人。"""
        self.repo.add("2026-11-01", 150000, "买房", account_id=self.card)
        self.assertEqual(self._balance(self.card), -50000)

    def test_unknown_account_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.add("2026-11-01", 100, account_id=9999)
        self.assertEqual(self.repo.count(), 0, "校验失败不应留下流水")

    def test_edit_amount_reapplies_difference(self):
        expense_id = self.repo.add("2026-11-01", 3000, "吃饭", account_id=self.card)
        self.repo.update(expense_id, amount_cents=5000)
        self.assertEqual(self._balance(self.card), 95000)

    def test_edit_moves_between_accounts(self):
        expense_id = self.repo.add("2026-11-01", 3000, "吃饭", account_id=self.card)
        self.repo.update(expense_id, account_id=self.credit)
        self.assertEqual(self._balance(self.card), 100000, "旧账户要退回")
        self.assertEqual(self._balance(self.credit), 53000, "新账户要扣掉")

    def test_edit_to_unlinked_refunds(self):
        expense_id = self.repo.add("2026-11-01", 3000, "吃饭", account_id=self.card)
        self.repo.update(expense_id, account_id=None)
        self.assertEqual(self._balance(self.card), 100000)
        self.assertIsNone(self.repo.get(expense_id).account_id)

    def test_delete_reverts_effect(self):
        expense_id = self.repo.add("2026-11-01", 3000, "吃饭", account_id=self.card)
        self.repo.delete(expense_id)
        self.assertEqual(self._balance(self.card), 100000)

    def test_deleting_account_keeps_rows(self):
        self.repo.add("2026-11-01", 3000, "吃饭", account_id=self.card)
        self.accounts.delete(self.card)
        self.assertEqual(self.repo.count(), 1, "流水不该跟着账户消失")
        self.assertIsNone(self.repo.get(1).account_id, "外键应被置 NULL")

    def test_snapshot_refreshed_after_flow(self):
        self.repo.add("2026-11-01", 3000, "吃饭", account_id=self.card)
        latest = self.accounts.latest_snapshot()
        assert latest is not None
        # 资产 97000 + 负债 50000 → 净资产 47000
        self.assertEqual(latest.net_cents, 47000)


class ExpenseDialogTests(unittest.TestCase):
    """对话框：方向切换、账户下拉、算式金额。"""

    ACCOUNTS = ((1, "招行卡", ASSET), (2, "花呗", LIABILITY))

    def _dialog(self, **kwargs):
        kwargs.setdefault("accounts", self.ACCOUNTS)
        dialog = ExpenseDialog(**kwargs)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_default_kind_is_expense(self):
        dialog = self._dialog()
        self.assertEqual(dialog.current_kind(), FLOW_EXPENSE)
        self.assertTrue(dialog.expense_button.isChecked())

    def test_switch_kind_changes_presets(self):
        dialog = self._dialog()
        dialog.set_kind(FLOW_INCOME)
        self.assertEqual(dialog.current_kind(), FLOW_INCOME)
        self.assertTrue(dialog.income_button.isChecked())
        self.assertFalse(dialog.expense_button.isChecked())
        items = [
            dialog.category_combo.itemText(i)
            for i in range(dialog.category_combo.count())
        ]
        self.assertIn("工资", items)
        self.assertNotIn("吃饭", items)

    def test_formula_amount_is_evaluated(self):
        dialog = self._dialog()
        dialog.amount_edit.setText("6.9+2.49")
        dialog.category_combo.setCurrentText("吃饭")
        self.assertEqual(dialog.values()["amount_cents"], 939)

    def test_invalid_amount_blocks_accept(self):
        dialog = self._dialog()
        dialog.amount_edit.setText("abc")
        dialog._on_accept()
        self.assertTrue(dialog.error_label.isVisible() or dialog.error_label.text())
        self.assertNotEqual(dialog.result(), QDialog.Accepted)

    def test_account_combo_lists_accounts(self):
        dialog = self._dialog()
        self.assertEqual(dialog.account_combo.count(), 3)  # 不关联 + 两个账户
        self.assertIsNone(dialog.selected_account())
        dialog.account_combo.setCurrentIndex(1)
        self.assertEqual(dialog.selected_account()[1], "招行卡")

    def test_values_include_kind_and_account(self):
        dialog = self._dialog()
        dialog.amount_edit.setText("30")
        dialog.set_kind(FLOW_INCOME)
        dialog.account_combo.setCurrentIndex(2)  # 花呗
        values = dialog.values()
        self.assertEqual(values["kind"], FLOW_INCOME)
        self.assertEqual(values["account_id"], 2)

    def test_hint_mentions_selected_account(self):
        dialog = self._dialog()
        dialog.amount_edit.setText("9.39")
        dialog.account_combo.setCurrentIndex(1)
        self.assertIn("招行卡", dialog.hint_label.text())
        self.assertIn("9.39", dialog.hint_label.text())


if __name__ == "__main__":
    unittest.main()
