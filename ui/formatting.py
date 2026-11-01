"""界面文案与格式化（纯函数）。

刻意不依赖 Qt，也不依赖任何控件：这样规则可以被直接单测，
不会散落在各个窗口类里，也不会出现"同一时长在两处显示不一致"。

调用方：``ui/study_view.py``、``ui/record_dialog.py``。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable

from core.study_records import StudyRecord

# 未填写时长时表格中显示的占位符
EMPTY_DURATION: str = "—"

WEEKDAY_NAMES: tuple[str, ...] = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def to_date(value: str | date | datetime) -> date:
    """把 ``date`` / ``datetime`` / ISO 字符串统一转成 ``date``。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value.strip())
    raise TypeError(f"不支持的日期类型: {type(value).__name__}")


def format_minutes(minutes: int) -> str:
    """把分钟数转成人话：``45 -> 45 分钟``、``90 -> 1 小时 30 分``。"""
    if minutes < 0:
        raise ValueError(f"分钟数不能为负: {minutes}")
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} 小时"
    return f"{hours} 小时 {rest} 分"


def format_duration(minutes: int | None) -> str:
    """表格「时长」列。``None`` 与 ``0`` 都视为未填写（0 在录入时即存为 NULL）。"""
    if minutes is None or minutes == 0:
        return EMPTY_DURATION
    return format_minutes(minutes)


def format_day_title(value: str | date | datetime) -> str:
    """当天标题：``2026-10-31 -> 10月31日 周六``。"""
    day = to_date(value)
    return f"{day.month}月{day.day}日 {WEEKDAY_NAMES[day.weekday()]}"


def format_month_title(year: int, month: int) -> str:
    """月份标题：``(2026, 10) -> 2026年10月``。"""
    return f"{year}年{month}月"


def total_minutes(records: Iterable[StudyRecord]) -> int:
    """记录集合的时长合计，未填写的记录不计入。"""
    return sum(r.duration_minutes or 0 for r in records)


def format_summary(records: Iterable[StudyRecord]) -> str:
    """当天汇总文案。

    - 没有记录：``暂无记录``
    - 有记录但都没填时长：``3 条 · 未记录时长``
    - 正常：``3 条 · 共 105 分钟``
    """
    items = list(records)
    if not items:
        return "暂无记录"
    total = total_minutes(items)
    if total == 0:
        return f"{len(items)} 条 · 未记录时长"
    return f"{len(items)} 条 · 共 {format_minutes(total)}"


def flatten_content(content: str, limit: int | None = None) -> str:
    """把多行内容压成单行，供表格单元格显示。

    表格行高固定，多行文本会被截断成不完整的换行，所以在展示层统一压平；
    数据库里仍然保存原始的换行与缩进。
    """
    text = " ".join(part.strip() for part in content.splitlines() if part.strip())
    if limit is not None and len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def format_money(cents: int) -> str:
    """把"分"格式化成 ``¥12.50``；负数（将来做收支时）带负号。"""
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise TypeError(f"金额必须是整数分，收到 {type(cents).__name__}")
    sign = "-" if cents < 0 else ""
    yuan, rest = divmod(abs(cents), 100)
    return f"{sign}¥{yuan:,}.{rest:02d}"


def format_money_plain(cents: int) -> str:
    """不带货币符号的金额，用于输入框回填。"""
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise TypeError(f"金额必须是整数分，收到 {type(cents).__name__}")
    sign = "-" if cents < 0 else ""
    yuan, rest = divmod(abs(cents), 100)
    return f"{sign}{yuan}.{rest:02d}"


def parse_money(text: str) -> int:
    """把用户输入的金额解析成整数分。

    容忍 ``12``、``12.5``、``￥12.50``、``12.505``（多余位数四舍五入到分），
    但拒绝空串、负数、非数字。抛 ``ValueError`` 由调用方就地提示。
    """
    if not isinstance(text, str):
        raise TypeError("金额输入必须是字符串")
    cleaned = text.strip().replace("￥", "").replace("¥", "").replace(",", "")
    if not cleaned:
        raise ValueError("金额不能为空")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"金额格式不对: {text!r}") from exc
    if value <= 0:
        raise ValueError("金额必须大于 0")
    if value > Decimal("9999999"):
        raise ValueError("金额过大")
    # 四舍五入到分，避免 0.005 这类输入被截断
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
