"""资产 / 负债功能测试。

覆盖四层：
1. 仓储：增删改查、货币校验、排序、分类聚合；
2. 汇总：净资产计算（含负净资产）、负债比例；
3. 快照：自动生成、同一天覆盖、跨天累积、升序返回；
4. 视图：三栏构建、类型筛选、汇总不受筛选影响、增删改（弹窗可替换）；
5. 窗口：三页签（学习记录 / 资产 / 流水）的切换与按钮同步。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.accounts import (
    ASSET,
    LIABILITY,
    AccountRepository,
    NetWorth,
)
from core.database import SCHEMA_VERSION, DatabaseManager
from core.expenses import ExpenseRepository
from core.study_records import StudyRecordRepository
from ui.assets_view import AssetsView
from ui.main_window import MainWindow
from ui.sparkline import Sparkline

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    _APP = QApplication.instance() or QApplication([])


class _RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = AccountRepository(self.db)


class AccountRepositoryTests(_RepoCase):
    def test_add_and_get(self) -> None:
        account_id = self.repo.add("招商银行卡", ASSET, 800000, "银行卡", "工资卡")
        account = self.repo.get(account_id)
        self.assertIsNotNone(account)
        assert account is not None
        self.assertEqual(account.name, "招商银行卡")
        self.assertEqual(account.kind, ASSET)
        self.assertEqual(account.balance_cents, 800000)
        self.assertEqual(account.category, "银行卡")
        self.assertFalse(account.is_liability)
        self.assertEqual(account.kind_label, "资产")

    def test_default_kind_is_asset(self) -> None:
        account = self.repo.get(self.repo.add("现金"))
        assert account is not None
        self.assertEqual(account.kind, ASSET)
        self.assertEqual(account.balance_cents, 0, "新账户可以先不填金额")

    def test_negative_balance_allowed(self) -> None:
        """v6 起允许负余额：流水联动扣款可能把账户扣成负数（透支）。

        拒绝反而更烦人——用户只是想记一笔账，余额对不对是另一件事。
        """
        account_id = self.repo.add("招行卡", ASSET, 1000)
        self.assertTrue(self.repo.adjust_balance(account_id, -2500))
        account = self.repo.get(account_id)
        assert account is not None
        self.assertEqual(account.balance_cents, -1500)

    def test_reject_bad_input(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.add("", ASSET, 100)
        with self.assertRaises(ValueError):
            self.repo.add("卡", "unknown", 100)
        with self.assertRaises(TypeError):
            self.repo.add("卡", ASSET, 100.5)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            self.repo.add("卡", ASSET, True)  # type: ignore[arg-type]

    def test_list_orders_assets_first(self) -> None:
        self.repo.add("花呗", LIABILITY, 1000)
        self.repo.add("现金", ASSET, 2000)
        self.repo.add("房贷", LIABILITY, 300000)
        names = [a.name for a in self.repo.list_all()]
        self.assertEqual(names[:1], ["现金"], "资产排在负债前面")
        self.assertEqual(set(names[1:]), {"花呗", "房贷"})

    def test_list_by_kind(self) -> None:
        self.repo.add("现金", ASSET, 2000)
        self.repo.add("花呗", LIABILITY, 1000)
        self.assertEqual([a.name for a in self.repo.list_all(ASSET)], ["现金"])
        self.assertEqual([a.name for a in self.repo.list_all(LIABILITY)], ["花呗"])

    def test_update_partial_fields(self) -> None:
        account_id = self.repo.add("现金", ASSET, 2000, "现金")
        self.assertTrue(self.repo.update(account_id, balance_cents=3500))
        account = self.repo.get(account_id)
        assert account is not None
        self.assertEqual(account.balance_cents, 3500)
        self.assertEqual(account.name, "现金", "没传的字段保持原值")
        self.assertEqual(account.category, "现金")

        self.repo.update(account_id, kind=LIABILITY, name="信用卡")
        account = self.repo.get(account_id)
        assert account is not None
        self.assertTrue(account.is_liability)

    def test_update_missing_returns_false(self) -> None:
        self.assertFalse(self.repo.update(9999, balance_cents=1))

    def test_delete(self) -> None:
        account_id = self.repo.add("现金", ASSET, 2000)
        self.assertTrue(self.repo.delete(account_id))
        self.assertIsNone(self.repo.get(account_id))
        self.assertFalse(self.repo.delete(account_id))

    def test_list_categories_skips_empty(self) -> None:
        self.repo.add("A", ASSET, 1, "银行卡")
        self.repo.add("B", ASSET, 1, "银行卡")
        self.repo.add("C", ASSET, 1, "投资")
        self.repo.add("D", ASSET, 1, "")
        self.assertEqual(self.repo.list_categories(ASSET), ["银行卡", "投资"])
        self.assertEqual(self.repo.list_categories(LIABILITY), [])


class NetWorthTests(_RepoCase):
    def test_empty_totals(self) -> None:
        totals = self.repo.totals()
        self.assertEqual(totals.assets_cents, 0)
        self.assertEqual(totals.liabilities_cents, 0)
        self.assertEqual(totals.net_cents, 0)
        self.assertEqual(totals.liability_ratio, 0.0)

    def test_totals_and_ratio(self) -> None:
        self.repo.add("卡", ASSET, 800000)
        self.repo.add("现金", ASSET, 25000)
        self.repo.add("花呗", LIABILITY, 120000)
        totals = self.repo.totals()
        self.assertEqual(totals.assets_cents, 825000)
        self.assertEqual(totals.liabilities_cents, 120000)
        self.assertEqual(totals.net_cents, 705000)
        self.assertAlmostEqual(totals.liability_ratio, 120000 / 825000, places=6)

    def test_negative_net_worth_is_allowed(self) -> None:
        self.repo.add("现金", ASSET, 10000)
        self.repo.add("房贷", LIABILITY, 500000)
        self.assertEqual(self.repo.totals().net_cents, -490000)

    def test_ratio_caps_at_one(self) -> None:
        net = NetWorth(assets_cents=100, liabilities_cents=500)
        self.assertEqual(net.liability_ratio, 1.0)

    def test_ratio_without_assets(self) -> None:
        self.assertEqual(NetWorth(0, 500).liability_ratio, 1.0)
        self.assertEqual(NetWorth(0, 0).liability_ratio, 0.0)


class SnapshotTests(_RepoCase):
    def _drop_today(self) -> None:
        """删掉"今天"的快照。

        任何写操作都会顺手刷新当天快照（这是产品行为），而断言历史序列时
        不希望多出一条随真实日期变化的记录，所以测历史前先把它清掉。
        """
        self.db.connection.execute(
            "DELETE FROM net_worth_snapshots WHERE snapshot_date = ?",
            (date.today().isoformat(),),
        )
        self.db.connection.commit()

    def test_snapshot_created_on_add(self) -> None:
        self.repo.add("现金", ASSET, 5000)
        latest = self.repo.latest_snapshot()
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.net_cents, 5000)
        self.assertEqual(len(self.repo.list_snapshots()), 1)

    def test_same_day_overwrites(self) -> None:
        account_id = self.repo.add("现金", ASSET, 5000)
        self.repo.update(account_id, balance_cents=9000)
        self.repo.refresh_snapshot()
        snapshots = self.repo.list_snapshots()
        self.assertEqual(len(snapshots), 1, "同一天只保留一条快照")
        self.assertEqual(snapshots[0].net_cents, 9000)

    def test_multi_day_history(self) -> None:
        account_id = self.repo.add("现金", ASSET, 5000)
        self.repo.refresh_snapshot("2026-10-29")
        self.repo.update(account_id, balance_cents=8000)
        self.repo.refresh_snapshot("2026-10-30")
        self.repo.update(account_id, balance_cents=3000)
        self.repo.refresh_snapshot("2026-10-31")
        self._drop_today()

        snapshots = self.repo.list_snapshots()
        self.assertEqual(
            [s.snapshot_date for s in snapshots], ["2026-10-29", "2026-10-30", "2026-10-31"]
        )
        self.assertEqual([s.net_cents for s in snapshots], [5000, 8000, 3000])

    def test_limit_keeps_ascending_order(self) -> None:
        account_id = self.repo.add("现金", ASSET, 0)
        for day, value in (("2026-10-01", 100), ("2026-10-02", 200), ("2026-10-03", 300)):
            self.repo.update(account_id, balance_cents=value)
            self.repo.refresh_snapshot(day)
        self._drop_today()

        recent = self.repo.list_snapshots(2)
        self.assertEqual([s.snapshot_date for s in recent], ["2026-10-02", "2026-10-03"])
        self.assertEqual(self.repo.list_snapshots(0), [])

    def test_snapshot_records_both_sides(self) -> None:
        self.repo.add("卡", ASSET, 100000)
        self.repo.add("花呗", LIABILITY, 30000)
        latest = self.repo.latest_snapshot()
        assert latest is not None
        self.assertEqual(latest.total_assets_cents, 100000)
        self.assertEqual(latest.total_liabilities_cents, 30000)
        self.assertEqual(latest.net_cents, 70000)


class MigrationTests(unittest.TestCase):
    """迁移用例自己管理临时目录。

    不能用 ``with TemporaryDirectory()``：Windows 上 SQLite 连接没关时
    目录删不掉（WinError 32）。先注册目录清理、再注册 close，
    addCleanup 是后进先出，正好保证"先关库、再删目录"。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "m.db"

    def test_fresh_database_is_current_version(self) -> None:
        db = DatabaseManager(self.path)
        db.connect()
        self.addCleanup(db.close)
        self.assertEqual(db.schema_version(), SCHEMA_VERSION)
        # 硬编码一次：万一有人只改常量忘了写迁移，这里会立刻暴露
        self.assertEqual(SCHEMA_VERSION, 7)
        self.assertTrue(db.table_exists("accounts"))
        self.assertTrue(db.table_exists("net_worth_snapshots"))

    def test_upgrade_from_v3_creates_tables(self) -> None:
        db = DatabaseManager(self.path)
        db.connect()
        db.connection.execute("DROP TABLE accounts")
        db.connection.execute("DROP TABLE net_worth_snapshots")
        db.connection.execute(
            "UPDATE app_meta SET value = '3' WHERE key = 'schema_version'"
        )
        db.connection.commit()
        db.close()

        db2 = DatabaseManager(self.path)
        db2.connect()
        self.addCleanup(db2.close)
        self.assertEqual(db2.schema_version(), SCHEMA_VERSION)
        self.assertTrue(db2.table_exists("accounts"))
        self.assertTrue(db2.table_exists("net_worth_snapshots"))
        # 迁移后账户表可正常写入
        repo = AccountRepository(db2)
        self.assertEqual(repo.add("现金", ASSET, 100), 1)


class SparklineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spark = Sparkline()

    def test_empty_values(self) -> None:
        self.spark.set_values([])
        self.assertFalse(self.spark.has_enough_data())
        self.assertEqual(self.spark.values, [])

    def test_single_value_needs_two_points(self) -> None:
        self.spark.set_values([100])
        self.assertFalse(self.spark.has_enough_data())

    def test_values_are_copied(self) -> None:
        source = [1, 2, 3]
        self.spark.set_values(source)
        source.append(4)
        self.assertEqual(self.spark.values, [1, 2, 3])
        self.assertTrue(self.spark.has_enough_data())

    def test_render_does_not_crash(self) -> None:
        """空数据、单点、多点、全相等等极端情况都要能画出来。"""
        for values in ([], [100], [100, 100, 100], [-500, 0, 800], [500, -300]):
            self.spark.set_values(values)
            self.spark.resize(180, 58)
            self.assertFalse(self.spark.grab().isNull())


class AssetsViewTests(_RepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.view = AssetsView(self.repo)
        self.addCleanup(self.view.deleteLater)
        self.view.resize(900, 600)

    def test_empty_state(self) -> None:
        self.assertEqual(self.view.table.rowCount(), 0)
        self.assertTrue(self.view.empty_hint.isVisibleTo(self.view))
        self.assertEqual(self.view.net_label.text(), "¥0.00")

    def test_rows_and_totals(self) -> None:
        self.repo.add("招商银行卡", ASSET, 800000, "银行卡")
        self.repo.add("花呗", LIABILITY, 120000, "花呗")
        self.view.refresh()
        self.assertEqual(self.view.table.rowCount(), 2)
        self.assertEqual(self.view.assets_label.text(), "¥8,000.00")
        self.assertEqual(self.view.liabilities_label.text(), "¥1,200.00")
        self.assertEqual(self.view.net_label.text(), "¥6,800.00")
        self.assertIn("负债占资产", self.view.ratio_label.text())

    def test_negative_net_worth_is_highlighted(self) -> None:
        self.repo.add("花呗", LIABILITY, 500000)
        self.view.refresh()
        self.assertTrue(self.view.net_label.text().startswith("-"))
        self.assertEqual(self.view.net_hint.text(), "负债大于资产")

    def test_filter_does_not_change_summary(self) -> None:
        """筛到「只看负债」时，净资产必须还是整体的净资产。"""
        self.repo.add("卡", ASSET, 100000)
        self.repo.add("花呗", LIABILITY, 30000)
        self.view.refresh()
        before = self.view.net_label.text()

        self.view.set_kind_filter(LIABILITY)
        self.assertEqual(self.view.table.rowCount(), 1)
        self.assertEqual(self.view.net_label.text(), before)
        self.assertEqual(self.view.current_kind_filter(), LIABILITY)

        self.view.set_kind_filter(None)
        self.assertEqual(self.view.table.rowCount(), 2)

    def test_add_via_replaced_dialog(self) -> None:
        self.view._ask_account = lambda account: {  # type: ignore[assignment]
            "name": "新卡",
            "kind": ASSET,
            "balance_cents": 250000,
            "category": "银行卡",
            "note": "",
        }
        self.view.add_account()
        self.assertEqual(self.repo.count(), 1)
        self.assertEqual(self.view.table.rowCount(), 1)
        self.assertEqual(self.view.selected_account().name, "新卡")

    def test_edit_via_replaced_dialog(self) -> None:
        account_id = self.repo.add("旧名", ASSET, 1000)
        self.view.refresh()
        self.view.table.selectRow(0)

        self.view._ask_account = lambda account: {  # type: ignore[assignment]
            "name": "新名",
            "kind": ASSET,
            "balance_cents": 5000,
            "category": "现金",
            "note": "改过",
        }
        self.view.edit_account()

        account = self.repo.get(account_id)
        assert account is not None
        self.assertEqual(account.name, "新名")
        self.assertEqual(account.balance_cents, 5000)

    def test_delete_via_replaced_confirm(self) -> None:
        self.repo.add("要删的", ASSET, 1000)
        self.view.refresh()
        self.view.table.selectRow(0)
        self.view._confirm_delete = lambda account: True  # type: ignore[assignment]
        self.view.delete_account()
        self.assertEqual(self.repo.count(), 0)
        self.assertEqual(self.view.table.rowCount(), 0)

    def test_delete_cancelled_keeps_row(self) -> None:
        self.repo.add("保留", ASSET, 1000)
        self.view.refresh()
        self.view.table.selectRow(0)
        self.view._confirm_delete = lambda account: False  # type: ignore[assignment]
        self.view.delete_account()
        self.assertEqual(self.repo.count(), 1)

    def test_actions_disabled_without_selection(self) -> None:
        self.repo.add("卡", ASSET, 1000)
        self.view.refresh()
        self.view.table.clearSelection()
        self.view.table.setCurrentCell(-1, -1)
        self.assertFalse(self.view.edit_button.isEnabled())
        self.assertFalse(self.view.delete_button.isEnabled())


class ThreeTabTests(_RepoCase):
    def _window(self, **kwargs) -> MainWindow:
        window = MainWindow(StudyRecordRepository(self.db), **kwargs)
        self.addCleanup(window.deleteLater)
        return window

    def test_all_three_pages(self) -> None:
        window = self._window(
            expense_repository=ExpenseRepository(self.db),
            account_repository=self.repo,
        )
        # 统计页只依赖学习记录，因此总在最后多一页
        self.assertEqual(window.stack.count(), 4)
        self.assertEqual(window.stack.currentIndex(), 0)
        self.assertIsNotNone(window.assets_view)
        self.assertIsNotNone(window.expense_view)
        labels = [b.text() for b, _ in window._tabs]
        self.assertEqual(labels, ["学习记录", "资产", "流水", "统计"])

    def test_switch_to_assets(self) -> None:
        window = self._window(
            expense_repository=ExpenseRepository(self.db),
            account_repository=self.repo,
        )
        window.show_page(1)
        self.assertEqual(window.current_page(), window.assets_view)
        self.assertTrue(window.assets_tab.isChecked())
        self.assertFalse(window.study_tab.isChecked())
        self.assertFalse(window.expense_tab.isChecked())

    def test_switch_to_ledger(self) -> None:
        window = self._window(
            expense_repository=ExpenseRepository(self.db),
            account_repository=self.repo,
        )
        window.show_page(2)
        self.assertEqual(window.current_page(), window.expense_view)
        self.assertTrue(window.expense_tab.isChecked())

    def test_only_study_and_stats_when_no_repositories(self) -> None:
        window = self._window()
        self.assertEqual(window.stack.count(), 2)  # 学习记录 + 统计
        window.show_page(2)  # 越界忽略
        self.assertEqual(window.stack.currentIndex(), 0)

    def test_assets_page_independent_of_ledger(self) -> None:
        """只传账户仓储时，资产页就是第 2 页（不依赖流水是否存在）。"""
        window = self._window(account_repository=self.repo)
        self.assertEqual(window.stack.count(), 3)  # 学习记录 + 资产 + 统计
        window.show_page(1)
        self.assertEqual(window.current_page(), window.assets_view)
        self.assertIsNone(window.expense_tab)

    def test_refresh_reloads_all_pages(self) -> None:
        window = self._window(
            expense_repository=ExpenseRepository(self.db),
            account_repository=self.repo,
        )
        self.repo.add("后加的卡", ASSET, 12345)
        window.refresh()
        assert window.assets_view is not None
        self.assertEqual(window.assets_view.table.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
