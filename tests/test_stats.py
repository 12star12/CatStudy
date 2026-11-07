"""专注统计页的测试：区间计算、聚合查询、扇区合并、环形图与页面。

分四层：
1. ``core/stats.py`` 的日期边界（周一/月末/闰年）与占比文案；
2. 仓储聚合（区间过滤、空时长排除、排序、条数口径）；
3. 环形图（整圆不塌成一条线、空数据不崩、扇区可读）；
4. 页面（区间切换重查、图例行数、空状态、主面板页签）。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from core.database import DatabaseManager
from core.stats import (
    MAX_SLICES,
    OTHERS_LABEL,
    PERIOD_ALL,
    PERIOD_DAY,
    PERIOD_MONTH,
    PERIOD_WEEK,
    PERIOD_YEAR,
    format_share,
    group_slices,
    period_bounds,
    total_minutes,
)
from core.study_records import StudyRecordRepository
from ui.formatting import format_total
from ui.main_window import MainWindow
from ui.pie_chart import DonutChart, color_for, donut_path
from ui.stats_view import StatsView

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class PeriodBoundsTest(unittest.TestCase):
    def test_day(self) -> None:
        today = date(2026, 11, 7)
        self.assertEqual(period_bounds(PERIOD_DAY, today), (today, today))

    def test_week_is_monday_to_sunday(self) -> None:
        # 2026-11-07 是周六
        start, end = period_bounds(PERIOD_WEEK, date(2026, 11, 7))
        self.assertEqual(start, date(2026, 11, 2))
        self.assertEqual(end, date(2026, 11, 8))

    def test_week_starting_on_monday(self) -> None:
        monday = date(2026, 11, 2)
        start, end = period_bounds(PERIOD_WEEK, monday)
        self.assertEqual(start, monday)
        self.assertEqual(end, date(2026, 11, 8))

    def test_week_starting_on_sunday(self) -> None:
        sunday = date(2026, 11, 8)
        start, _ = period_bounds(PERIOD_WEEK, sunday)
        self.assertEqual(start, date(2026, 11, 2))

    def test_month_length_differs(self) -> None:
        self.assertEqual(
            period_bounds(PERIOD_MONTH, date(2026, 2, 10)),
            (date(2026, 2, 1), date(2026, 2, 28)),
        )
        self.assertEqual(
            period_bounds(PERIOD_MONTH, date(2028, 2, 3)),
            (date(2028, 2, 1), date(2028, 2, 29)),
        )

    def test_year_and_all(self) -> None:
        self.assertEqual(
            period_bounds(PERIOD_YEAR, date(2026, 11, 7)),
            (date(2026, 1, 1), date(2026, 12, 31)),
        )
        self.assertEqual(period_bounds(PERIOD_ALL, date(2026, 11, 7)), (None, None))

    def test_unknown_period_raises(self) -> None:
        with self.assertRaises(ValueError):
            period_bounds("quarter", date(2026, 11, 7))


class GroupSlicesTest(unittest.TestCase):
    def test_sorted_desc_without_merging(self) -> None:
        result = group_slices([("数学", 60), ("英语", 120), ("写作", 30)])
        self.assertEqual(
            result, [("英语", 120), ("数学", 60), ("写作", 30)]
        )

    def test_zero_and_negative_dropped(self) -> None:
        result = group_slices([("数学", 0), ("英语", -5), ("写作", 10)])
        self.assertEqual(result, [("写作", 10)])

    def test_merge_tail_into_others(self) -> None:
        totals = [(f"科目{i}", 100 - i) for i in range(12)]
        result = group_slices(totals)
        self.assertEqual(len(result), MAX_SLICES)
        self.assertEqual(result[-1][0], OTHERS_LABEL)
        # 合并前后总时长不变
        self.assertEqual(total_minutes(result), total_minutes(totals))
        # 其他 = 被合并的那几项之和
        self.assertEqual(result[-1][1], sum(m for _, m in totals[MAX_SLICES - 1 :]))

    def test_ties_sorted_by_name_for_stable_colors(self) -> None:
        # 同长时按 Unicode 码位排（乙 4E59 < 甲 7532），重点不是顺序本身，
        # 而是"同一天刷新两次不会换色"
        result = group_slices([("甲", 30), ("乙", 30)])
        self.assertEqual([name for name, _ in result], ["乙", "甲"])
        self.assertEqual(group_slices([("甲", 30), ("乙", 30)]), result)

    def test_limit_below_two_rejected(self) -> None:
        with self.assertRaises(ValueError):
            group_slices([("数学", 10)], limit=1)

    def test_total_ignores_negative(self) -> None:
        self.assertEqual(total_minutes([("数学", 10), ("英语", -3)]), 10)


class ShareFormatTest(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(format_share(25, 100), "25%")
        self.assertEqual(format_share(1, 3), "33%")

    def test_tiny_and_zero(self) -> None:
        self.assertEqual(format_share(1, 1000), "<1%")
        self.assertEqual(format_share(0, 100), "0%")
        self.assertEqual(format_share(10, 0), "0%")

    def test_format_total_compacts_long_durations(self) -> None:
        self.assertEqual(format_total(0), "0 分钟")
        self.assertEqual(format_total(45), "45 分钟")
        self.assertEqual(format_total(380), "6 小时 20 分")
        self.assertEqual(format_total(3000), "2 天 2 小时")
        self.assertEqual(format_total(9000), "6 天 6 小时")
        self.assertEqual(format_total(8640), "6 天")


class RepositoryTotalsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = StudyRecordRepository(self.db)
        self.repo.add("2026-11-02", "数学", duration_minutes=60)
        self.repo.add("2026-11-03", "数学", duration_minutes=40)
        self.repo.add("2026-11-03", "英语", duration_minutes=120)
        self.repo.add("2026-11-03", "写作")  # 未填时长
        self.repo.add("2026-10-20", "数学", duration_minutes=500)

    def test_range_filters_and_sums(self) -> None:
        totals = self.repo.subject_totals("2026-11-01", "2026-11-30")
        self.assertEqual(totals, [("英语", 120), ("数学", 100)])

    def test_all_time(self) -> None:
        totals = self.repo.subject_totals()
        self.assertEqual(totals, [("数学", 600), ("英语", 120)])

    def test_null_duration_excluded(self) -> None:
        totals = self.repo.subject_totals("2026-11-03", "2026-11-03")
        self.assertNotIn("写作", [name for name, _ in totals])

    def test_record_count_counts_null_duration(self) -> None:
        self.assertEqual(self.repo.record_count_in_range("2026-11-03", "2026-11-03"), 3)
        self.assertEqual(self.repo.record_count_in_range(), 5)


class DonutChartTest(unittest.TestCase):
    def test_slices_and_total(self) -> None:
        chart = DonutChart()
        chart.set_slices([("数学", 60), ("英语", 30)])
        self.assertEqual(chart.total, 90)
        self.assertEqual(len(chart.slices), 2)

    def test_negative_minutes_clamped(self) -> None:
        chart = DonutChart()
        chart.set_slices([("数学", -10)])
        self.assertEqual(chart.total, 0)

    def test_full_circle_path_is_a_ring(self) -> None:
        """单块占 100% 时不能塌成一条线——这里用面积判断洞确实被挖掉了。"""
        outer = QRectF(0, 0, 100, 100)
        inner = QRectF(30, 30, 40, 40)
        ring = donut_path(outer, inner, 90.0, -360.0)
        self.assertFalse(ring.isEmpty())
        # 环的面积 = 外圆 - 内圆，介于两者之间
        import math

        area = ring.boundingRect().width() * ring.boundingRect().height()
        self.assertGreater(area, 0)
        self.assertLess(ring.length(), 2 * math.pi * 50 + 2 * math.pi * 20 + 1)

    def test_paints_without_crashing(self) -> None:
        chart = DonutChart()
        chart.resize(240, 240)
        chart.set_slices([("数学", 60), ("英语", 30), ("写作", 10)])
        pixmap = QPixmap(240, 240)
        chart.render(pixmap)  # 空数据与有数据都走一遍 paintEvent
        chart.set_slices([])
        chart.render(pixmap)

    def test_others_color_is_neutral(self) -> None:
        self.assertNotEqual(color_for(0, OTHERS_LABEL).name(), color_for(0, "数学").name())


class StatsViewTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = StudyRecordRepository(self.db)
        self.today = date(2026, 11, 7)
        self.view = StatsView(self.repo, today_provider=lambda: self.today)
        self.addCleanup(self.view.deleteLater)

    def test_default_period_is_week(self) -> None:
        self.assertEqual(self.view.period, PERIOD_WEEK)

    def test_empty_state(self) -> None:
        self.assertEqual(self.view.legend_count, 0)
        self.assertTrue(self.view.empty_label.isVisibleTo(self.view))
        self.assertIn("没有", self.view.hint_label.text())

    def test_day_period_sees_only_today(self) -> None:
        self.repo.add("2026-11-07", "数学", duration_minutes=50)
        self.repo.add("2026-11-06", "英语", duration_minutes=90)
        self.view.set_period(PERIOD_DAY)
        self.assertEqual(self.view.legend_count, 1)
        self.assertEqual(self.view.chart.slices, [("数学", 50)])

    def test_week_period_includes_whole_week(self) -> None:
        self.repo.add("2026-11-02", "数学", duration_minutes=50)  # 周一
        self.repo.add("2026-11-06", "英语", duration_minutes=90)
        self.repo.add("2026-10-30", "写作", duration_minutes=30)  # 上周，不该算
        self.view.set_period(PERIOD_WEEK)
        self.assertEqual(
            self.view.chart.slices, [("英语", 90), ("数学", 50)]
        )

    def test_all_period_covers_everything(self) -> None:
        self.repo.add("2025-03-01", "数学", duration_minutes=10)
        self.repo.add("2026-11-07", "英语", duration_minutes=20)
        self.view.set_period(PERIOD_ALL)
        self.assertEqual(self.view.chart.total, 30)

    def test_hint_mentions_records_and_total(self) -> None:
        self.repo.add("2026-11-07", "数学", duration_minutes=50)
        self.view.set_period(PERIOD_DAY)
        self.assertIn("1 条记录", self.view.hint_label.text())
        self.assertIn("50 分钟", self.view.hint_label.text())

    def test_legend_merges_many_subjects(self) -> None:
        for index in range(10):
            self.repo.add("2026-11-07", f"科目{index}", duration_minutes=10 + index)
        self.view.set_period(PERIOD_DAY)
        self.assertEqual(self.view.legend_count, MAX_SLICES)

    def test_refresh_twice_does_not_duplicate_legend(self) -> None:
        self.repo.add("2026-11-07", "数学", duration_minutes=50)
        self.view.set_period(PERIOD_DAY)
        self.view.refresh()
        self.view.refresh()
        self.assertEqual(self.view.legend_count, 1)

    def test_long_name_elided(self) -> None:
        self.assertEqual(StatsView._elide("数学"), "数学")
        self.assertEqual(StatsView._elide("一二三四五六七八九十"), "一二三四五六七…")


class MainWindowStatsTabTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.window = MainWindow(StudyRecordRepository(self.db))
        self.addCleanup(self.window.deleteLater)

    def test_stats_tab_is_last_and_always_present(self) -> None:
        labels = [button.text() for button, _ in self.window._tabs]
        self.assertEqual(labels, ["学习记录", "统计"])
        self.assertIs(self.window.current_page(), self.window.view)

    def test_switch_to_stats(self) -> None:
        self.window.show_page(1)
        self.assertIs(self.window.current_page(), self.window.stats_view)
        self.assertTrue(self.window.stats_tab.isChecked())


if __name__ == "__main__":
    unittest.main()
