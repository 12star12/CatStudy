"""笔记本风记录窗口的新增部分测试：科目标签页、筛选与统计。

旧版视图的行为测试在 ``test_study_view.py``，这里只覆盖改版后新加的能力，
避免和已有用例重复。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.database import DatabaseManager
from core.study_records import StudyRecordRepository
from ui.study_view import SUBJECT_TAB_ALL, StudyRecordView

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class RepositorySubjectsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = StudyRecordRepository(self.db)

    def test_list_subjects_is_deduped_and_sorted_by_usage(self):
        self.repo.add("2026-10-31", "数学", duration_minutes=10)
        self.repo.add("2026-10-30", "数学", duration_minutes=10)
        self.repo.add("2026-10-31", "英语", duration_minutes=10)
        self.assertEqual(self.repo.list_subjects(), ["数学", "英语"])

    def test_list_subjects_empty_database(self):
        self.assertEqual(self.repo.list_subjects(), [])

    def test_list_dates_is_distinct_and_descending(self):
        self.repo.add("2026-10-29", "数学")
        self.repo.add("2026-10-31", "数学")
        self.repo.add("2026-10-31", "英语")
        self.assertEqual(self.repo.list_dates(), ["2026-10-31", "2026-10-29"])


class SubjectTabTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = StudyRecordRepository(self.db)

        self.view = StudyRecordView(self.repo)
        self.addCleanup(self.view.deleteLater)

    def _rows(self) -> int:
        return self.view.table.rowCount()

    def test_tabs_follow_database_subjects(self):
        self.repo.add(date.today(), "数学", duration_minutes=20)
        self.repo.add(date.today(), "英语", duration_minutes=20)
        self.view.refresh()
        self.assertEqual(
            list(self.view._subject_buttons), [SUBJECT_TAB_ALL, "数学", "英语"]
        )
        # 默认选中「全部」
        self.assertTrue(self.view._subject_buttons[SUBJECT_TAB_ALL].isChecked())

    def test_filter_limits_rows_and_summary(self):
        self.repo.add(date.today(), "数学", duration_minutes=20)
        self.repo.add(date.today(), "英语", duration_minutes=40)
        self.view.refresh()
        self.assertEqual(self._rows(), 2)

        self.view.set_subject_filter("数学")
        self.assertEqual(self.view.current_subject_filter(), "数学")
        self.assertEqual(self._rows(), 1)
        self.assertIn("20 分钟", self.view.summary_label.text())
        self.assertTrue(self.view._subject_buttons["数学"].isChecked())
        self.assertFalse(self.view._subject_buttons[SUBJECT_TAB_ALL].isChecked())

    def test_back_to_all(self):
        self.repo.add(date.today(), "数学", duration_minutes=20)
        self.repo.add(date.today(), "英语", duration_minutes=40)
        self.view.refresh()
        self.view.set_subject_filter("数学")
        self.view.set_subject_filter(SUBJECT_TAB_ALL)
        self.assertIsNone(self.view.current_subject_filter())
        self.assertEqual(self._rows(), 2)

    def test_filter_resets_when_subject_disappears(self):
        record_id = self.repo.add(date.today(), "数学", duration_minutes=20)
        self.view.refresh()
        self.view.set_subject_filter("数学")
        self.repo.delete(record_id)
        self.view.refresh()
        # 该科目已无记录，筛选应自动回到「全部」，避免停在一个空视图上
        self.assertIsNone(self.view.current_subject_filter())

    def test_empty_state_hint_visible_only_without_records(self):
        self.view.refresh()
        self.assertFalse(self.view.empty_hint.isHidden())
        self.repo.add(date.today(), "数学", duration_minutes=20)
        self.view.refresh()
        self.assertTrue(self.view.empty_hint.isHidden())


class StatsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = StudyRecordRepository(self.db)
        self.view = StudyRecordView(self.repo)
        self.addCleanup(self.view.deleteLater)

    def test_today_total_sums_minutes(self):
        self.repo.add(date.today(), "数学", duration_minutes=25)
        self.repo.add(date.today(), "英语", duration_minutes=35)
        self.view.refresh()
        self.assertEqual(self.view.today_stat.text(), "60 分钟")

    def test_streak_counts_consecutive_days(self):
        today = date.today()
        for offset in (0, 1, 2):
            self.repo.add(today - timedelta(days=offset), "数学", duration_minutes=10)
        self.view.refresh()
        self.assertEqual(self.view.streak_stat.text(), "3 天")

    def test_streak_survives_before_studying_today(self):
        # 今天还没学，但昨天学过：连续天数不能显示 0
        today = date.today()
        self.repo.add(today - timedelta(days=1), "数学", duration_minutes=10)
        self.repo.add(today - timedelta(days=2), "数学", duration_minutes=10)
        self.view.refresh()
        self.assertEqual(self.view.streak_stat.text(), "2 天")

    def test_streak_breaks_on_missing_day(self):
        today = date.today()
        self.repo.add(today, "数学", duration_minutes=10)
        self.repo.add(today - timedelta(days=3), "数学", duration_minutes=10)
        self.view.refresh()
        self.assertEqual(self.view.streak_stat.text(), "1 天")


if __name__ == "__main__":
    unittest.main()
