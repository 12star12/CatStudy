"""``ui/formatting.py`` 纯函数测试（不启动 Qt）。

这些规则决定界面上"看到什么字"，属于最容易出错又最容易测的部分，
所以单独成文件、独立于控件测试。

运行：
    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.study_records import StudyRecord  # noqa: E402
from ui.formatting import (  # noqa: E402
    EMPTY_DURATION,
    WEEKDAY_NAMES,
    flatten_content,
    format_day_title,
    format_duration,
    format_minutes,
    format_month_title,
    format_summary,
    to_date,
    total_minutes,
)


def make_record(duration: int | None, subject: str = "数学", **kwargs) -> StudyRecord:
    """构造一条测试用记录（不需要数据库）。"""
    data = dict(
        id=kwargs.pop("id", 1),
        study_date=kwargs.pop("study_date", "2026-10-31"),
        subject=subject,
        duration_minutes=duration,
        content=kwargs.pop("content", ""),
        created_at="2026-10-31 10:00:00",
        updated_at="2026-10-31 10:00:00",
    )
    data.update(kwargs)
    return StudyRecord(**data)


class FormatMinutesTest(unittest.TestCase):
    def test_below_one_hour(self) -> None:
        self.assertEqual(format_minutes(0), "0 分钟")
        self.assertEqual(format_minutes(1), "1 分钟")
        self.assertEqual(format_minutes(45), "45 分钟")
        self.assertEqual(format_minutes(59), "59 分钟")

    def test_exact_hours(self) -> None:
        self.assertEqual(format_minutes(60), "1 小时")
        self.assertEqual(format_minutes(120), "2 小时")
        self.assertEqual(format_minutes(600), "10 小时")

    def test_hours_with_remainder(self) -> None:
        self.assertEqual(format_minutes(61), "1 小时 1 分")
        self.assertEqual(format_minutes(90), "1 小时 30 分")
        self.assertEqual(format_minutes(125), "2 小时 5 分")

    def test_negative_rejected(self) -> None:
        with self.assertRaises(ValueError):
            format_minutes(-1)


class FormatDurationTest(unittest.TestCase):
    def test_none_and_zero_show_placeholder(self) -> None:
        self.assertEqual(EMPTY_DURATION, "—")
        self.assertEqual(format_duration(None), EMPTY_DURATION)
        self.assertEqual(format_duration(0), EMPTY_DURATION)

    def test_positive_values(self) -> None:
        self.assertEqual(format_duration(30), "30 分钟")
        self.assertEqual(format_duration(60), "1 小时")
        self.assertEqual(format_duration(105), "1 小时 45 分")


class DateTitleTest(unittest.TestCase):
    def test_day_title_with_date_object(self) -> None:
        self.assertEqual(format_day_title(date(2026, 10, 31)), "10月31日 周六")

    def test_day_title_with_iso_string(self) -> None:
        self.assertEqual(format_day_title("2026-10-31"), "10月31日 周六")

    def test_day_title_with_datetime(self) -> None:
        self.assertEqual(format_day_title(datetime(2026, 10, 31, 23, 30)), "10月31日 周六")

    def test_all_weekday_names(self) -> None:
        monday = date(2026, 10, 26)          # 2026-10-31 是周六，回推 5 天
        self.assertEqual(monday.weekday(), 0)
        for i, name in enumerate(WEEKDAY_NAMES):
            day = monday + timedelta(days=i)
            self.assertTrue(
                format_day_title(day).endswith(name), f"{day} 应为{name}"
            )

    def test_sunday_is_last(self) -> None:
        self.assertEqual(format_day_title(date(2026, 11, 1)), "11月1日 周日")

    def test_month_title(self) -> None:
        self.assertEqual(format_month_title(2026, 10), "2026年10月")
        self.assertEqual(format_month_title(2026, 1), "2026年1月")
        self.assertEqual(format_month_title(2026, 12), "2026年12月")


class ToDateTest(unittest.TestCase):
    def test_accepts_three_input_kinds(self) -> None:
        d = date(2026, 10, 31)
        self.assertEqual(to_date(d), d)
        self.assertEqual(to_date(datetime(2026, 10, 31, 9, 0)), d)
        self.assertEqual(to_date("2026-10-31"), d)
        self.assertEqual(to_date("  2026-10-31  "), d)

    def test_invalid_string_raises(self) -> None:
        with self.assertRaises(ValueError):
            to_date("2026/10/31")

    def test_wrong_type_raises(self) -> None:
        with self.assertRaises(TypeError):
            to_date(20261031)


class SummaryTest(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(format_summary([]), "暂无记录")
        self.assertEqual(total_minutes([]), 0)

    def test_all_durations_missing(self) -> None:
        records = [make_record(None), make_record(None, subject="英语")]
        self.assertEqual(format_summary(records), "2 条 · 未记录时长")
        self.assertEqual(total_minutes(records), 0)

    def test_mixed(self) -> None:
        records = [
            make_record(45),
            make_record(30, subject="英语"),
            make_record(None, subject="物理"),
        ]
        self.assertEqual(format_summary(records), "3 条 · 共 1 小时 15 分")

    def test_single_record(self) -> None:
        self.assertEqual(format_summary([make_record(30)]), "1 条 · 共 30 分钟")

    def test_summary_accepts_any_iterable(self) -> None:
        records = (make_record(60) for _ in range(2))
        self.assertEqual(format_summary(records), "2 条 · 共 2 小时")


class FlattenContentTest(unittest.TestCase):
    def test_single_line_unchanged(self) -> None:
        self.assertEqual(flatten_content("导数与极值"), "导数与极值")

    def test_multiline_collapsed(self) -> None:
        self.assertEqual(
            flatten_content("第一行\n第二行\n\n第三行"), "第一行 第二行 第三行"
        )

    def test_leading_trailing_whitespace_stripped(self) -> None:
        self.assertEqual(flatten_content("  内容  "), "内容")

    def test_empty(self) -> None:
        self.assertEqual(flatten_content(""), "")
        self.assertEqual(flatten_content("   \n  "), "")

    def test_truncation_with_ellipsis(self) -> None:
        text = "一二三四五六七八九十"
        self.assertEqual(flatten_content(text, limit=5), "一二三四五…")
        self.assertEqual(flatten_content(text, limit=100), text)

    def test_truncation_strips_trailing_space(self) -> None:
        self.assertEqual(flatten_content("ab cd ef", limit=3), "ab…")


if __name__ == "__main__":
    unittest.main(verbosity=2)
