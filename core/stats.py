"""专注统计的区间与占比计算（纯逻辑，不依赖 Qt 与数据库）。

统计页要回答的问题只有一句：**这段时间里，时间花在哪些科目上，各占多少。**
所以这里只做两件事：

1. :func:`period_bounds` —— 把"今天/本周/本月/今年/全部"翻译成一个闭区间；
2. :func:`group_slices` —— 把过长的科目列表收敛成最多 8 块（末位合并为"其他"），
   否则 14 个科目会画出 14 条比头发还细的扇形，谁也读不出来。

日期计算放在核心层而不是界面层，因为它有边界条件（周一、月末、闰年），
需要能脱离 GUI 单独测试。
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

PERIOD_DAY: str = "day"
PERIOD_WEEK: str = "week"
PERIOD_MONTH: str = "month"
PERIOD_YEAR: str = "year"
PERIOD_ALL: str = "all"

# 页签顺序：由短到长，最后一项是"全部"——它跨过了前面所有区间
PERIODS: tuple[tuple[str, str], ...] = (
    (PERIOD_DAY, "今天"),
    (PERIOD_WEEK, "本周"),
    (PERIOD_MONTH, "本月"),
    (PERIOD_YEAR, "今年"),
    (PERIOD_ALL, "全部"),
)

# 扇区上限。超过就合并尾部为"其他"：8 块以内颜色能区分，
# 再多就只能靠图例逐条对色，反而更难读。
MAX_SLICES: int = 8

# 合并后的那一块叫什么（图例里也用它判断要不要用中性色）
OTHERS_LABEL: str = "其他"


def period_bounds(period: str, today: date) -> tuple[date | None, date | None]:
    """把统计区间翻译成闭区间 ``(start, end)``；"全部"返回 ``(None, None)``。

    区间一律取**自然边界**（周一到周日、整月、整年），不截断到今天：
    截断会让"本周"在周一显示成一天，用户会以为上周的数据丢了。
    未来的日期本来就没有记录，不影响结果。
    """
    if period == PERIOD_DAY:
        return today, today
    if period == PERIOD_WEEK:
        monday = today - timedelta(days=today.weekday())
        return monday, monday + timedelta(days=6)
    if period == PERIOD_MONTH:
        first = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        return first, today.replace(day=last_day)
    if period == PERIOD_YEAR:
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if period == PERIOD_ALL:
        return None, None
    raise ValueError(f"未知的统计区间: {period}")


def group_slices(
    totals: list[tuple[str, int]],
    limit: int = MAX_SLICES,
) -> list[tuple[str, int]]:
    """按时长降序整理扇区，超过 ``limit`` 时把尾部合并成"其他"。

    ``limit`` 至少为 2：1 块饼没有意义，0 块则连"其他"都放不下。
    """
    if limit < 2:
        raise ValueError(f"扇区上限至少为 2: {limit}")
    items = [(str(name), int(minutes)) for name, minutes in totals if int(minutes) > 0]
    # 同长时按名排序，保证两次刷新顺序一致（否则颜色会跳）
    items.sort(key=lambda pair: (-pair[1], pair[0]))
    if len(items) <= limit:
        return items
    head = items[: limit - 1]
    rest_total = sum(minutes for _, minutes in items[limit - 1 :])
    return head + [(OTHERS_LABEL, rest_total)]


def total_minutes(totals: list[tuple[str, int]]) -> int:
    """总时长；负数（不该出现）按 0 计，避免占比出现负值。"""
    return sum(max(0, int(minutes)) for _, minutes in totals)


def share(minutes: int, total: int) -> float:
    """占比（0~1）。总时长为 0 时返回 0，而不是除零。"""
    if total <= 0:
        return 0.0
    return max(0.0, int(minutes)) / total


def format_share(minutes: int, total: int) -> str:
    """占比文案：整数百分比；非零但不足 1% 时写 ``<1%``，不写成 ``0%``。"""
    ratio = share(minutes, total) * 100.0
    if ratio <= 0.0:
        return "0%"
    if ratio < 1.0:
        return "<1%"
    return f"{ratio:.0f}%"
