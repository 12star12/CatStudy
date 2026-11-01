"""日记功能的测试：仓储、自动保存、日期切换、与主窗口的接线。"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.database import DatabaseManager, SCHEMA_VERSION
from core.journal import MAX_CONTENT_LENGTH, JournalRepository
from core.study_records import StudyRecordRepository
from ui.journal_view import AUTOSAVE_MS, SUMMARY_LIMIT, JournalView
from ui.main_window import MainWindow

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class _RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = JournalRepository(self.db)


class JournalRepositoryTests(_RepoCase):
    def test_empty_by_default(self) -> None:
        self.assertIsNone(self.repo.get("2026-11-01"))
        self.assertEqual(self.repo.count(), 0)
        self.assertEqual(self.repo.list_recent(), [])

    def test_save_and_read_back(self) -> None:
        entry = self.repo.save("2026-11-01", "第一行\n第二行")
        assert entry is not None
        self.assertEqual(entry.entry_date, "2026-11-01")
        self.assertEqual(self.repo.get("2026-11-01").content, "第一行\n第二行")

    def test_save_accepts_date_object(self) -> None:
        self.repo.save(date(2026, 11, 1), "x")
        self.assertIsNotNone(self.repo.get("2026-11-01"))

    def test_overwrite_keeps_single_row(self) -> None:
        first = self.repo.save("2026-11-01", "初稿")
        second = self.repo.save("2026-11-01", "改过")
        assert first is not None and second is not None
        self.assertEqual(first.id, second.id, "同一天应覆盖而不是新增")
        self.assertEqual(self.repo.count(), 1)
        self.assertEqual(self.repo.get("2026-11-01").content, "改过")

    def test_empty_content_deletes_entry(self) -> None:
        """清空正文后列表里不该留一条空白日记。"""
        self.repo.save("2026-11-01", "写了一堆")
        self.assertIsNone(self.repo.save("2026-11-01", "   \n\t "))
        self.assertEqual(self.repo.count(), 0)

    def test_delete(self) -> None:
        self.repo.save("2026-11-01", "x")
        self.assertTrue(self.repo.delete("2026-11-01"))
        self.assertFalse(self.repo.delete("2026-11-01"), "重复删除返回 False")

    def test_list_recent_is_desc(self) -> None:
        for day in ("2026-10-30", "2026-11-02", "2026-10-31"):
            self.repo.save(day, day)
        self.assertEqual(
            [e.entry_date for e in self.repo.list_recent()],
            ["2026-11-02", "2026-10-31", "2026-10-30"],
        )

    def test_list_recent_limit_takes_newest(self) -> None:
        for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
            self.repo.save(day, day)
        self.assertEqual(
            [e.entry_date for e in self.repo.list_recent(2)],
            ["2026-10-03", "2026-10-02"],
        )

    def test_list_recent_rejects_negative_limit(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.list_recent(-1)

    def test_list_by_month_boundaries(self) -> None:
        self.repo.save("2026-10-31", "上月")
        self.repo.save("2026-11-01", "本月首日")
        self.repo.save("2026-11-30", "本月末日")
        self.repo.save("2026-12-01", "下月")
        self.assertEqual(
            [e.entry_date for e in self.repo.list_by_month(2026, 11)],
            ["2026-11-30", "2026-11-01"],
        )

    def test_list_by_month_december(self) -> None:
        """12 月的上界要跨年，写成 month+1 会抛异常。"""
        self.repo.save("2026-12-31", "跨年前一天")
        self.assertEqual(len(self.repo.list_by_month(2026, 12)), 1)

    def test_list_by_month_rejects_bad_month(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.list_by_month(2026, 13)

    def test_dates_and_first_date(self) -> None:
        self.repo.save("2026-11-01", "a")
        self.repo.save("2026-10-05", "b")
        self.assertEqual(self.repo.dates(), {"2026-11-01", "2026-10-05"})
        self.assertEqual(self.repo.first_date(), "2026-10-05")

    def test_invalid_date_rejected(self) -> None:
        for bad in ("2026-02-30", "2026-13-01", "2026/11/01"):
            with self.assertRaises(ValueError, msg=bad):
                self.repo.save(bad, "x")

    def test_content_type_checked(self) -> None:
        with self.assertRaises(TypeError):
            self.repo.save("2026-11-01", 123)  # type: ignore[arg-type]

    def test_content_length_checked(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.save("2026-11-01", "x" * (MAX_CONTENT_LENGTH + 1))

    def test_word_count_ignores_blanks(self) -> None:
        entry = self.repo.save("2026-11-01", "  今天很好  \n")
        assert entry is not None
        self.assertEqual(entry.word_count, 4)

    def test_summary_flattens_newlines(self) -> None:
        entry = self.repo.save("2026-11-01", "第一行\n第二行")
        assert entry is not None
        self.assertEqual(entry.summary, "第一行 第二行")


class JournalMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "m.db"

    def test_fresh_database_has_journal(self) -> None:
        db = DatabaseManager(self.path)
        db.connect()
        self.addCleanup(db.close)
        self.assertEqual(db.schema_version(), SCHEMA_VERSION)
        self.assertTrue(db.table_exists("journal_entries"))

    def test_upgrade_from_v6_creates_table(self) -> None:
        """老库升上来要能直接用，原有学习记录不受影响。"""
        db = DatabaseManager(self.path)
        db.connect()
        StudyRecordRepository(db).add("2026-11-01", "数学", "旧记录", 30)
        db.connection.execute("DROP TABLE journal_entries")
        db.connection.execute("UPDATE app_meta SET value = '6' WHERE key = 'schema_version'")
        db.connection.commit()
        db.close()

        db2 = DatabaseManager(self.path)
        db2.connect()
        self.addCleanup(db2.close)
        self.assertEqual(db2.schema_version(), SCHEMA_VERSION)
        self.assertTrue(db2.table_exists("journal_entries"))
        self.assertEqual(StudyRecordRepository(db2).count(), 1, "老数据不能丢")
        self.assertEqual(len(JournalRepository(db2).list_recent()), 0)


class JournalViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "v.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = JournalRepository(self.db)
        self.study = StudyRecordRepository(self.db)
        self.view = JournalView(self.repo, study_repository=self.study)
        self.addCleanup(self.view.deleteLater)

    def test_starts_on_today(self) -> None:
        self.assertEqual(self.view.selected_date(), date.today())
        self.assertEqual(self.view.editor.toPlainText(), "")

    def test_typing_marks_dirty_and_starts_timer(self) -> None:
        self.view.editor.setPlainText("今天学了导数")
        self.assertTrue(self.view.has_unsaved_changes())
        self.assertTrue(self.view._save_timer.isActive())
        self.assertEqual(self.view._save_timer.interval(), AUTOSAVE_MS)

    def test_save_writes_to_repository(self) -> None:
        self.view.editor.setPlainText("写下一点东西")
        self.view.save_now()
        self.assertFalse(self.view.has_unsaved_changes())
        entry = self.repo.get(date.today())
        self.assertIsNotNone(entry)
        self.assertEqual(entry.content, "写下一点东西")

    def test_loading_does_not_mark_dirty(self) -> None:
        """把已有正文填进编辑器时不能算"用户改了"。"""
        self.repo.save(date.today(), "已有的内容")
        self.view.refresh()
        self.assertEqual(self.view.editor.toPlainText(), "已有的内容")
        self.assertFalse(self.view.has_unsaved_changes())

    def test_switch_day_saves_first(self) -> None:
        self.view.editor.setPlainText("今天的")
        self.view.set_selected_date(date.today() - timedelta(days=1))
        # 旧日期应该已经落库，编辑器换成新日期的内容（空）
        self.assertEqual(self.repo.get(date.today()).content, "今天的")
        self.assertEqual(self.view.editor.toPlainText(), "")

    def test_shift_day_and_back(self) -> None:
        self.view.shift_day(-1)
        self.assertEqual(self.view.selected_date(), date.today() - timedelta(days=1))
        self.view.shift_day(1)
        self.assertEqual(self.view.selected_date(), date.today())

    def test_list_shows_entries_desc(self) -> None:
        self.repo.save(date.today(), "今天的")
        self.repo.save(date.today() - timedelta(days=2), "前天的")
        self.view.refresh()
        self.assertEqual(self.view.list.count(), 2)
        self.assertIn("今天的", self.view.list.item(0).text())

    def test_list_truncates_long_summary(self) -> None:
        self.repo.save(date.today(), "字" * (SUMMARY_LIMIT + 30))
        self.view.refresh()
        text = self.view.list.item(0).text()
        self.assertIn("…", text)
        self.assertLess(len(text.split("\n")[1]), SUMMARY_LIMIT + 5)

    def test_clearing_text_removes_from_list(self) -> None:
        self.view.editor.setPlainText("先写一句")
        self.view.save_now()
        self.assertEqual(self.view.list.count(), 1)
        self.view.editor.setPlainText("   ")
        self.view.save_now()
        self.assertEqual(self.view.list.count(), 0)
        self.assertEqual(self.repo.count(), 0)

    def test_status_shows_saved_marker(self) -> None:
        self.view.editor.setPlainText("四个汉字")
        self.view.save_now()
        self.assertIn("已保存", self.view.status_label.text())

    def test_study_summary_reads_records(self) -> None:
        self.study.add(date.today(), "数学", "错题", 50)
        self.study.add(date.today(), "英语", "单词", 25)
        self.view.refresh()
        self.assertIn("75 分钟", self.view.study_label.text())

    def test_study_summary_hidden_without_repository(self) -> None:
        bare = JournalView(self.repo)
        self.addCleanup(bare.deleteLater)
        self.assertEqual(bare.study_label.text(), "")

    def test_hide_saves_pending_text(self) -> None:
        """切页签/关窗口前必须落库，否则写了半天白写。"""
        self.view.show()
        self.view.editor.setPlainText("没来得及保存")
        self.view.hide()
        self.assertEqual(self.repo.get(date.today()).content, "没来得及保存")

    def test_today_button_disabled_on_today(self) -> None:
        self.assertFalse(self.view.today_button.isEnabled())
        self.view.shift_day(-1)
        self.assertTrue(self.view.today_button.isEnabled())


class JournalWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "w.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.study = StudyRecordRepository(self.db)
        self.journal = JournalRepository(self.db)

    def _window(self, **kwargs) -> MainWindow:
        window = MainWindow(self.study, **kwargs)
        self.addCleanup(window.deleteLater)
        return window

    def test_journal_tab_follows_study(self) -> None:
        window = self._window(journal_repository=self.journal)
        labels = [b.text() for b, _ in window._tabs]
        self.assertEqual(labels, ["学习记录", "日记"])
        self.assertIs(window.stack.widget(1), window.journal_view)

    def test_tab_order_with_all_repositories(self) -> None:
        from core.accounts import AccountRepository
        from core.expenses import ExpenseRepository

        window = self._window(
            expense_repository=ExpenseRepository(self.db),
            account_repository=AccountRepository(self.db),
            journal_repository=self.journal,
        )
        labels = [b.text() for b, _ in window._tabs]
        self.assertEqual(labels, ["学习记录", "日记", "资产", "流水"])

    def test_no_journal_page_without_repository(self) -> None:
        window = self._window()
        self.assertIsNone(window.journal_view)
        self.assertEqual(window.stack.count(), 1)

    def test_switch_to_journal(self) -> None:
        window = self._window(journal_repository=self.journal)
        window.show_page(1)
        self.assertIs(window.current_page(), window.journal_view)
        self.assertTrue(window.journal_tab.isChecked())
        self.assertFalse(window.study_tab.isChecked())


if __name__ == "__main__":
    unittest.main()
