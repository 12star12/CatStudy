"""第 3 步：学习记录视图与主窗口的界面测试。

两个刻意为之的设计：

1. 所有用例都跑在**临时数据库**上，绝不碰 ``data/catstudy.db``；
2. 模态弹窗通过替换 ``_ask_record`` / ``_confirm_delete`` 绕过，
   否则 ``exec()`` 会阻塞事件循环，测试直接卡死。
"""

from __future__ import annotations

import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication

from core.database import DatabaseManager
from core.study_records import StudyRecordRepository
from ui.formatting import format_month_title
from ui.main_window import MainWindow
from ui.study_view import CONTENT_PREVIEW_LIMIT, StudyRecordView

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class _ViewCase(unittest.TestCase):
    """每个用例一个独立临时库 + 一个视图。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        self.db_path = Path(self._tmp.name) / "test.db"
        self.db = DatabaseManager(self.db_path)
        self.db.connect()
        self.addCleanup(self.db.close)

        self.repo = StudyRecordRepository(self.db)
        self.view = StudyRecordView(self.repo)
        self.addCleanup(self.view.deleteLater)

    # ---------- 辅助 ----------

    def _seed(self, day: str, subject: str, minutes: int | None, content: str = "") -> int:
        return self.repo.add(day, subject, content=content, duration_minutes=minutes)

    def _row_count(self) -> int:
        return self.view.table.rowCount()

    def _cell(self, row: int, col: int) -> str:
        item = self.view.table.item(row, col)
        return item.text() if item is not None else ""

    @staticmethod
    def _has_background(fmt) -> bool:
        return fmt.background().style() != Qt.BrushStyle.NoBrush


class DefaultStateTest(_ViewCase):
    def test_defaults_to_today(self) -> None:
        self.assertEqual(self.view.selected_date(), date.today())

    def test_month_label_matches_visible_month(self) -> None:
        year, month = self.view.visible_month()
        self.assertEqual(self.view.month_label.text(), format_month_title(year, month))

    def test_empty_day_shows_hint(self) -> None:
        self.assertEqual(self._row_count(), 0)
        self.assertEqual(self.view.summary_label.text(), "暂无记录")

    def test_actions_disabled_without_selection(self) -> None:
        self.assertFalse(self.view.edit_button.isEnabled())
        self.assertFalse(self.view.delete_button.isEnabled())
        self.assertTrue(self.view.add_button.isEnabled())

    def test_table_headers(self) -> None:
        headers = [
            self.view.table.horizontalHeaderItem(i).text()
            for i in range(self.view.table.columnCount())
        ]
        self.assertEqual(headers, ["科目", "时长", "学习内容"])


class MonthNavigationTest(_ViewCase):
    def test_next_month(self) -> None:
        self.view.set_selected_date(date(2026, 10, 15))
        self.view.show_next_month()
        self.assertEqual(self.view.visible_month(), (2026, 11))
        self.assertEqual(self.view.selected_date(), date(2026, 11, 15))
        self.assertEqual(self.view.month_label.text(), "2026年11月")

    def test_previous_month_crosses_year(self) -> None:
        self.view.set_selected_date(date(2026, 1, 10))
        self.view.show_previous_month()
        self.assertEqual(self.view.visible_month(), (2025, 12))
        self.assertEqual(self.view.selected_date(), date(2025, 12, 10))

    def test_next_month_clamps_day_to_month_length(self) -> None:
        # 1 月 31 日 -> 2 月没有 31 号，应落到 2 月 28 日
        self.view.set_selected_date(date(2026, 1, 31))
        self.view.show_next_month()
        self.assertEqual(self.view.selected_date(), date(2026, 2, 28))

    def test_leap_year_clamp(self) -> None:
        self.view.set_selected_date(date(2024, 1, 31))
        self.view.show_next_month()
        self.assertEqual(self.view.selected_date(), date(2024, 2, 29))

    def test_go_to_today(self) -> None:
        self.view.set_selected_date(date(2020, 3, 3))
        self.view.go_to_today()
        self.assertEqual(self.view.selected_date(), date.today())


class DateSelectionTest(_ViewCase):
    def test_switching_date_refreshes_rows(self) -> None:
        self._seed("2026-10-05", "数学", 45)
        self._seed("2026-10-05", "英语", 30)
        self._seed("2026-10-06", "物理", None)

        self.view.set_selected_date(date(2026, 10, 5))
        self.assertEqual(self._row_count(), 2)

        self.view.set_selected_date(date(2026, 10, 6))
        self.assertEqual(self._row_count(), 1)
        self.assertEqual(self._cell(0, 0), "物理")

    def test_summary_updates_with_date(self) -> None:
        self._seed("2026-10-05", "数学", 45)
        self._seed("2026-10-05", "英语", 30)
        self.view.set_selected_date(date(2026, 10, 5))
        self.assertEqual(self.view.summary_label.text(), "2 条 · 共 1 小时 15 分")

    def test_day_title_updates(self) -> None:
        self.view.set_selected_date(date(2026, 10, 31))
        self.assertEqual(self.view.day_title.text(), "10月31日 周六")


class TableRenderingTest(_ViewCase):
    def test_empty_duration_shows_dash(self) -> None:
        self._seed("2026-10-05", "数学", None)
        self.view.set_selected_date(date(2026, 10, 5))
        self.assertEqual(self._cell(0, 1), "—")

    def test_duration_formatting(self) -> None:
        self._seed("2026-10-05", "数学", 90)
        self.view.set_selected_date(date(2026, 10, 5))
        self.assertEqual(self._cell(0, 1), "1 小时 30 分")

    def test_multiline_content_is_flattened(self) -> None:
        self._seed("2026-10-05", "数学", 30, "第一节\n第二节\n\n第三节")
        self.view.set_selected_date(date(2026, 10, 5))
        self.assertEqual(self._cell(0, 2), "第一节 第二节 第三节")

    def test_long_content_is_truncated_with_ellipsis(self) -> None:
        long_text = "很长的内容" * 30
        self._seed("2026-10-05", "数学", 30, long_text)
        self.view.set_selected_date(date(2026, 10, 5))
        shown = self._cell(0, 2)
        self.assertTrue(shown.endswith("…"))
        self.assertEqual(len(shown), CONTENT_PREVIEW_LIMIT + 1)
        # 完整内容仍可通过 tooltip 看到，没有被截断丢失
        self.assertEqual(self.view.table.item(0, 2).toolTip(), long_text)


class MonthMarkTest(_ViewCase):
    def test_days_with_records_are_marked(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self._seed("2026-10-20", "英语", 30)
        self.view.set_selected_date(date(2026, 10, 1))

        for day in (5, 20):
            fmt = self.view.calendar.dateTextFormat(QDate(2026, 10, day))
            self.assertTrue(self._has_background(fmt), f"10月{day}日应有标记")

        empty_fmt = self.view.calendar.dateTextFormat(QDate(2026, 10, 6))
        self.assertFalse(self._has_background(empty_fmt), "10月6日不应有标记")

    def test_marks_cleared_when_leaving_month(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self.view.set_selected_date(date(2026, 10, 5))
        self.assertTrue(self._has_background(
            self.view.calendar.dateTextFormat(QDate(2026, 10, 5))
        ))

        self.view.show_next_month()
        # 换月后旧标记应被清掉，否则回到 10 月会看到残留高亮
        self.assertFalse(self._has_background(
            self.view.calendar.dateTextFormat(QDate(2026, 10, 5))
        ))

    def test_marks_refresh_after_add(self) -> None:
        self.view.set_selected_date(date(2026, 11, 12))
        self.view._ask_record = lambda record: {
            "study_date": "2026-11-12",
            "subject": "化学",
            "duration_minutes": 20,
            "content": "",
        }
        self.view.add_record()
        self.assertTrue(self._has_background(
            self.view.calendar.dateTextFormat(QDate(2026, 11, 12))
        ))


class AddRecordTest(_ViewCase):
    def test_add_inserts_and_refreshes(self) -> None:
        self.view.set_selected_date(date(2026, 10, 5))
        self.view._ask_record = lambda record: {
            "study_date": "2026-10-05",
            "subject": "数学",
            "duration_minutes": 45,
            "content": "导数",
        }
        self.view.add_record()

        self.assertEqual(self._row_count(), 1)
        self.assertEqual(self._cell(0, 0), "数学")
        self.assertEqual(self.repo.count("2026-10-05"), 1)
        # 新增后该行应被自动选中，便于紧接着编辑
        self.assertIsNotNone(self.view.selected_record_id())

    def test_add_cancelled_changes_nothing(self) -> None:
        self.view._ask_record = lambda record: None
        self.view.add_record()
        self.assertEqual(self._row_count(), 0)
        self.assertEqual(self.repo.count(), 0)

    def test_add_to_other_date_follows_record(self) -> None:
        self.view.set_selected_date(date(2026, 10, 5))
        self.view._ask_record = lambda record: {
            "study_date": "2026-10-09",
            "subject": "英语",
            "duration_minutes": None,
            "content": "",
        }
        self.view.add_record()

        # 记录被放到了 9 号，界面应跟过去，否则用户会觉得记录消失了
        self.assertEqual(self.view.selected_date(), date(2026, 10, 9))
        self.assertEqual(self._row_count(), 1)

    def test_add_without_duration_stores_null(self) -> None:
        self.view.set_selected_date(date(2026, 10, 5))
        self.view._ask_record = lambda record: {
            "study_date": "2026-10-05",
            "subject": "自习",
            "duration_minutes": None,
            "content": "",
        }
        self.view.add_record()
        records = self.repo.list_by_date("2026-10-05")
        self.assertIsNone(records[0].duration_minutes)
        self.assertEqual(self._cell(0, 1), "—")


class EditRecordTest(_ViewCase):
    def test_edit_updates_db_and_table(self) -> None:
        self._seed("2026-10-05", "数学", 30, "旧内容")
        self.view.set_selected_date(date(2026, 10, 5))
        self.view.table.selectRow(0)

        self.view._ask_record = lambda record: {
            "study_date": "2026-10-05",
            "subject": "高数",
            "duration_minutes": 60,
            "content": "新内容",
        }
        self.view.edit_record()

        self.assertEqual(self._cell(0, 0), "高数")
        self.assertEqual(self._cell(0, 1), "1 小时")
        self.assertEqual(self._cell(0, 2), "新内容")

        saved = self.repo.list_by_date("2026-10-05")[0]
        self.assertEqual(saved.subject, "高数")
        self.assertEqual(saved.duration_minutes, 60)

    def test_edit_without_selection_does_nothing(self) -> None:
        called = []
        self.view._ask_record = lambda record: called.append(record) or {
            "study_date": "2026-10-05",
            "subject": "x",
            "duration_minutes": None,
            "content": "",
        }
        self.view.edit_record()
        self.assertEqual(called, [], "没有选中行时不应弹出表单")

    def test_edit_cancelled_keeps_original(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self.view.set_selected_date(date(2026, 10, 5))
        self.view.table.selectRow(0)
        self.view._ask_record = lambda record: None
        self.view.edit_record()
        self.assertEqual(self.repo.list_by_date("2026-10-05")[0].subject, "数学")

    def test_edit_moving_date_follows_record(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self.view.set_selected_date(date(2026, 10, 5))
        self.view.table.selectRow(0)

        self.view._ask_record = lambda record: {
            "study_date": "2026-10-08",
            "subject": "数学",
            "duration_minutes": 30,
            "content": "",
        }
        self.view.edit_record()

        self.assertEqual(self.view.selected_date(), date(2026, 10, 8))
        self.assertEqual(self.repo.count("2026-10-05"), 0)
        self.assertEqual(self.repo.count("2026-10-08"), 1)


class DeleteRecordTest(_ViewCase):
    def test_delete_after_confirmation(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self.view.set_selected_date(date(2026, 10, 5))
        self.view.table.selectRow(0)

        self.view._confirm_delete = lambda subject: True
        self.view.delete_record()

        self.assertEqual(self._row_count(), 0)
        self.assertEqual(self.repo.count(), 0)

    def test_delete_cancelled_keeps_record(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self.view.set_selected_date(date(2026, 10, 5))
        self.view.table.selectRow(0)

        self.view._confirm_delete = lambda subject: False
        self.view.delete_record()

        self.assertEqual(self._row_count(), 1)
        self.assertEqual(self.repo.count(), 1)

    def test_delete_without_selection_does_nothing(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self.view.set_selected_date(date(2026, 10, 5))
        asked = []
        self.view._confirm_delete = lambda subject: asked.append(subject) or True
        self.view.delete_record()
        self.assertEqual(asked, [], "没有选中行时不应弹出确认框")
        self.assertEqual(self.repo.count(), 1)

    def test_confirm_message_contains_subject(self) -> None:
        """确认框的文案必须带上科目名，避免用户误删。"""
        captured: dict[str, str] = {}

        import ui.study_view as module

        def fake_question(parent, title, text, buttons, default):
            captured["text"] = text
            captured["default"] = default
            # 模拟用户点了「是」；注意不能返回 buttons（那是 Yes|No 的位或）
            return module.QMessageBox.StandardButton.Yes

        original = module.QMessageBox.question
        module.QMessageBox.question = fake_question
        try:
            self.assertTrue(self.view._confirm_delete("线性代数"))
        finally:
            module.QMessageBox.question = original

        self.assertIn("线性代数", captured["text"])


class SelectionTest(_ViewCase):
    def test_selection_enables_action_buttons(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self.view.set_selected_date(date(2026, 10, 5))
        self.view.table.selectRow(0)
        self.assertTrue(self.view.edit_button.isEnabled())
        self.assertTrue(self.view.delete_button.isEnabled())

    def test_selected_record_maps_to_row(self) -> None:
        self._seed("2026-10-05", "数学", 30)
        self._seed("2026-10-05", "英语", 20)
        self.view.set_selected_date(date(2026, 10, 5))
        self.view.table.selectRow(1)
        record = self.view.selected_record()
        self.assertIsNotNone(record)
        self.assertEqual(record.subject, "英语")


class PersistenceTest(_ViewCase):
    def test_records_survive_reopen(self) -> None:
        """模拟重启：关连接、重新开库、重建视图。"""
        self._seed("2026-10-05", "数学", 45, "导数")
        self.view.set_selected_date(date(2026, 10, 5))
        self.assertEqual(self._row_count(), 1)

        self.db.close()

        db2 = DatabaseManager(self.db_path)
        db2.connect()
        self.addCleanup(db2.close)
        view2 = StudyRecordView(StudyRecordRepository(db2))
        self.addCleanup(view2.deleteLater)
        view2.set_selected_date(date(2026, 10, 5))

        self.assertEqual(view2.table.rowCount(), 1)
        self.assertEqual(view2.table.item(0, 0).text(), "数学")

    def test_same_day_multiple_records(self) -> None:
        for subject in ("数学", "英语", "物理"):
            self._seed("2026-10-05", subject, 30)
        self.view.set_selected_date(date(2026, 10, 5))
        self.assertEqual(self._row_count(), 3)


class MainWindowTest(_ViewCase):
    def test_window_properties(self) -> None:
        window = MainWindow(self.repo)
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.windowTitle(), "CatStudy · 学习记录")
        # 中央控件现在是「切换按钮 + 页面栈」的容器，不是单个视图
        self.assertIn(window.view, window.stack.findChildren(type(window.view)))
        self.assertGreaterEqual(window.minimumWidth(), 640)

    def test_show_event_refreshes(self) -> None:
        window = MainWindow(self.repo)
        self.addCleanup(window.deleteLater)
        window.show()
        QApplication.processEvents()

        self._seed(date.today().isoformat(), "数学", 30)
        # 窗口隐藏期间数据变了，再显示时应看到最新内容
        window.hide()
        window.show()
        QApplication.processEvents()

        self.assertEqual(window.view.table.rowCount(), 1)
        window.close()

    def test_window_can_be_closed_and_reopened(self) -> None:
        window = MainWindow(self.repo)
        self.addCleanup(window.deleteLater)
        window.show()
        QApplication.processEvents()
        window.close()
        window.show()
        QApplication.processEvents()
        self.assertTrue(window.isVisible())
        window.close()


class ArchitectureTest(unittest.TestCase):
    """UI 层不得直接写 SQL —— 这条约束在第四阶段更要守住。"""

    def setUp(self) -> None:
        self.ui_dir = Path(__file__).resolve().parent.parent / "ui"

    def test_study_view_has_no_sql(self) -> None:
        source = (self.ui_dir / "study_view.py").read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)
        for keyword in ("SELECT ", "INSERT ", "UPDATE ", "DELETE FROM", "CREATE TABLE"):
            self.assertNotIn(keyword, source.upper().replace("_", ""), keyword)

    def test_main_window_has_no_sql(self) -> None:
        source = (self.ui_dir / "main_window.py").read_text(encoding="utf-8")
        self.assertNotIn("sqlite3", source)

    def test_ui_uses_repository_only(self) -> None:
        source = (self.ui_dir / "study_view.py").read_text(encoding="utf-8")
        self.assertIn("StudyRecordRepository", source)
        # 只允许通过仓储层属性访问数据
        self.assertIsNotNone(re.search(r"self\._repo\.(add|update|delete|list_by_date)", source))
