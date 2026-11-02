"""界面文案与格式化（纯函数）。

刻意不依赖 Qt，也不依赖任何控件：这样规则可以被直接单测，
不会散落在各个窗口类里，也不会出现"同一时长在两处显示不一致"。

调用方：``ui/study_view.py``、``ui/record_dialog.py``。
"""

from __future__ import annotations

import ast
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


# 算式长度上限：正常记账不会超过这个，超了基本是误粘贴了一大段文本
MAX_EXPRESSION_LENGTH: int = 120

# 全角符号统一成半角，中文输入法下很容易打出这些
_FULLWIDTH_MAP = {
    "＋": "+", "－": "-", "＊": "*", "／": "/",
    "×": "*", "÷": "/", "（": "(", "）": ")",
}


def _evaluate_expression(text: str) -> Decimal:
    """计算四则运算表达式，返回 Decimal。

    **不用 ``eval``**：金额输入框的内容来自用户，``eval`` 等于把任意代码执行
    交给界面。这里用 ``ast`` 解析后自己遍历，只放行数字、``+ - * /``、括号
    和一元正负号，其余一律拒绝。

    支持 ``6.9+2.49``、``3*4``、``(12+8)/2`` 这类输入——记账时常把几笔零钱
    加在一起，逼用户先自己按计算器很反人类。
    """
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ValueError("金额算式太长")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"金额格式不对: {text!r}") from exc

    def walk(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"金额格式不对: {text!r}")
            return Decimal(str(value))
        if isinstance(node, ast.UnaryOp):
            operand = walk(node.operand)
            if isinstance(node.op, ast.UAdd):
                return operand
            if isinstance(node.op, ast.USub):
                return -operand
            raise ValueError(f"金额格式不对: {text!r}")
        if isinstance(node, ast.BinOp):
            left = walk(node.left)
            right = walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("除数不能为 0")
                return left / right
        raise ValueError(f"金额格式不对: {text!r}")

    return walk(tree)


def parse_money(text: str, *, allow_zero: bool = False) -> int:
    """把用户输入的金额解析成整数分。

    容忍 ``12``、``12.5``、``￥12.50``、``12.505``（多余位数四舍五入到分），
    但拒绝空串、负数、非数字。抛 ``ValueError`` 由调用方就地提示。

    ``allow_zero=True`` 用于账户余额：一个刚建好、还没填数的账户余额就是 0，
    而记账的金额为 0 是没有意义的，所以默认仍然拒绝 0。
    """
    if not isinstance(text, str):
        raise TypeError("金额输入必须是字符串")
    cleaned = text.strip().replace("￥", "").replace("¥", "").replace(",", "")
    cleaned = "".join(_FULLWIDTH_MAP.get(ch, ch) for ch in cleaned)
    if not cleaned:
        raise ValueError("金额不能为空")
    value = _evaluate_expression(cleaned)
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError("金额必须大于 0" if not allow_zero else "金额不能为负数")
    if value > Decimal("9999999"):
        raise ValueError("金额过大")
    # 四舍五入到分，避免 0.005 这类输入被截断
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# 结余评语
# ---------------------------------------------------------------------------
# 这段文案有三个优先级，从上到下：
#
# 1. **先让人愿意继续记账**。结余为负时说"这个月花得比赚得多"，等于给刚记完
#    一笔支出的人一记闷棍——记账软件变成记账警察，用户下次就不想打开它。
#    所以这里不评价"你花多了"，只说"还差多少"，把注意力放在数字上而不是人身上。
# 2. **再引导创收**。"省一笔或多赚一笔"把两条路并列摆出来，而不是只说省。
#    只教省钱，用户会觉得自己永远在被限制；给出"多赚"这条路，才有增量意识。
# 3. **记录本身要被肯定**。只要记了，就给一句正反馈——哪怕结余很薄。
#
# 另外，收入为 0 是**最常见**的"负结余"成因（很多人只记花钱不记进账），
# 这时优先提示"收入还没记"，而不是一口咬定花超了。

BALANCE_PRAISE_STRONG: float = 0.5   # 结余率 ≥ 50%：存下一半以上
BALANCE_PRAISE_OK: float = 0.2       # 结余率 ≥ 20%：攒得住


def balance_ratio(income_cents: int, expense_cents: int) -> float:
    """结余占收入的比例（0.0~1.0 之外也可能为负）。

    收入为 0 时无法计算比例，返回 0.0——调用方应先判断收入是否为空，
    而不是拿这个值去下结论。
    """
    if income_cents <= 0:
        return 0.0
    return (income_cents - expense_cents) / income_cents


def format_balance_hint(income_cents: int, expense_cents: int) -> str:
    """给本月结余配一句话。全部为 0 时返回空串（界面另有空状态提示）。"""
    if income_cents == 0 and expense_cents == 0:
        return ""

    # 缺了一半数据时，先说"缺"，别急着算结余
    if income_cents == 0:
        return "收入还没记，补上更清楚"
    if expense_cents == 0:
        return "只记了收入，花销也别漏"

    net = income_cents - expense_cents
    if net < 0:
        # 不写"花得比赚得多"：同一件事，这样说像判决，上面的说法像提醒。
        # "多赚"排在"少花"前面：只教省钱，等于告诉用户他永远在被限制；
        # 把增量这条路先摆出来，才有可能让"创收"变成一个念头。
        return f"还差 {format_money(-net)}，多赚一笔，或少花一笔"
    if net == 0:
        return "正好打平，记得很准"

    ratio = balance_ratio(income_cents, expense_cents)
    if ratio >= BALANCE_PRAISE_STRONG:
        return "存下一半以上，很稳"
    if ratio >= BALANCE_PRAISE_OK:
        return "有结余，攒得住"
    return "结余不多，稳住就好"


# ---------------------------------------------------------------------------
# 收入区的小字
# ---------------------------------------------------------------------------
# 这段只有一个目的：让"进账"成为一件可以累积、值得再记一笔的事。
#
# 三条硬规矩：
#
# 1. **不写目标、不写还差多少。** 一旦有"离 ¥5000 还差 ¥4200"，用户就开始
#    算账，而算账的尽头是把"我想多赚"换成"我还欠多少"——那是负担，不是动力。
# 2. **不按月清零的只有"今年累计"。** 月度收入会被支出抵消（挣 800、花 1150，
#    眼里只剩 −350），"今年累计进账"不会。它只增不减，才谈得上积累感。
# 3. **没进账时不催。** 只留一句低门槛的入口（"多少都算"），因为把"没收入"
#    写成待办，等于提醒用户他失败了一次。
def format_income_meta(entries: int, sources: int, year_cents: int) -> str:
    """收入下方那行小字。

    - 本月无进账、今年也没有：``有进账就记一笔，多少都算``
    - 本月无进账、今年有过：``这个月还没进账 · 今年累计 ¥6,800.00``
    - 有进账：``本月 2 笔 · 2 个来源 · 今年累计 ¥6,800.00``
      （来源只有 1 个时不显示，免得每月都一样的一句变成噪音）
    """
    if entries <= 0:
        if year_cents > 0:
            return f"这个月还没进账 · 今年累计 {format_money(year_cents)}"
        return "有进账就记一笔，多少都算"

    parts = [f"本月 {entries} 笔"]
    if sources >= 2:
        parts.append(f"{sources} 个来源")
    if year_cents > 0:
        parts.append(f"今年累计 {format_money(year_cents)}")
    return " · ".join(parts)
