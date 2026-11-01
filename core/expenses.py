"""记账（支出流水）的仓储层。

设计要点：

- **金额单位是"分"（整数）**。账本里最忌讳浮点误差：``0.1 + 0.2`` 会得到
  ``0.30000000000000004``，累加几十笔之后总额就对不上了。存储与计算全部用
  整数分，只在显示时格式化成 ``¥12.50``。
- **分类是自由文本，不建分类表**。常见分类给一份预置清单做下拉，用户也可以
  直接输新分类；需要"有哪些分类"时用 ``list_categories()`` 从数据里聚合，
  这样不会出现"分类表里有、但没有数据"的空标签。
- 日期校验复用学习记录那套 ``date(...) IS date(...)`` 的真实日历校验，
  避免 ``2026-02-30`` 这种能通过格式校验的假日期。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from core.database import DatabaseManager
from core.study_records import normalize_date

# 预置分类：只用于下拉框的候选项，不是白名单
CATEGORY_PRESETS: tuple[str, ...] = (
    "吃饭", "交通", "学习", "购物", "娱乐", "其他",
)

# 未指定分类时的兜底
DEFAULT_CATEGORY: str = "其他"

_COLUMNS = (
    "id, expense_date, amount_cents, category, note, created_at, updated_at"
)

_UNSET: Any = object()


@dataclass(frozen=True)
class Expense:
    """一笔支出。"""

    id: int
    expense_date: str          # ISO 'YYYY-MM-DD'
    amount_cents: int          # 金额，单位：分
    category: str
    note: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Expense":
        return cls(
            id=int(row["id"]),
            expense_date=str(row["expense_date"]),
            amount_cents=int(row["amount_cents"]),
            category=str(row["category"]),
            note=str(row["note"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _check_amount(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"amount_cents 必须是整数，收到 {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"金额必须大于 0 分: {value}")
    return value


def _check_category(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"category 必须是字符串，收到 {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError("category 不能为空")
    return text


class ExpenseRepository:
    """``expenses`` 表的增删改查与月度汇总。"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._db.connection

    # ---------- 新增 ----------

    def add(
        self,
        expense_date: str | date | datetime,
        amount_cents: int,
        category: str = DEFAULT_CATEGORY,
        note: str = "",
    ) -> int:
        """记一笔支出，返回 id。"""
        now = _now()
        cursor = self._conn.execute(
            "INSERT INTO expenses (expense_date, amount_cents, category, note, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                normalize_date(expense_date),
                _check_amount(amount_cents),
                _check_category(category),
                note,
                now,
                now,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    # ---------- 查询 ----------

    def get(self, expense_id: int) -> Expense | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        return Expense.from_row(row) if row else None

    def list_by_date(self, expense_date: str | date | datetime) -> list[Expense]:
        """某天的流水，按创建顺序。"""
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM expenses WHERE expense_date = ? "
            "ORDER BY created_at, id",
            (normalize_date(expense_date),),
        ).fetchall()
        return [Expense.from_row(r) for r in rows]

    def list_by_month(self, year: int, month: int) -> list[Expense]:
        """某月的流水，按日期倒序（最近的在上面）。"""
        start, end = _month_range(year, month)
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM expenses "
            "WHERE expense_date BETWEEN ? AND ? "
            "ORDER BY expense_date DESC, created_at DESC, id DESC",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [Expense.from_row(r) for r in rows]

    def month_total_cents(self, year: int, month: int) -> int:
        """某月支出合计（分）。"""
        start, end = _month_range(year, month)
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM expenses "
            "WHERE expense_date BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return int(row["total"])

    def category_totals(self, year: int, month: int) -> list[tuple[str, int]]:
        """某月各分类合计，金额从大到小。"""
        start, end = _month_range(year, month)
        rows = self._conn.execute(
            "SELECT category, SUM(amount_cents) AS total FROM expenses "
            "WHERE expense_date BETWEEN ? AND ? "
            "GROUP BY category ORDER BY total DESC, category ASC",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        return [(str(r["category"]), int(r["total"])) for r in rows]

    def list_categories(self) -> list[str]:
        """出现过的分类（按笔数从多到少），用于左侧标签页。"""
        rows = self._conn.execute(
            "SELECT category, COUNT(*) AS n FROM expenses "
            "GROUP BY category ORDER BY n DESC, category ASC"
        ).fetchall()
        return [str(r["category"]) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()
        return int(row["n"])

    # ---------- 修改 ----------

    def update(
        self,
        expense_id: int,
        *,
        expense_date: str | date | datetime | Any = _UNSET,
        amount_cents: int | Any = _UNSET,
        category: str | Any = _UNSET,
        note: str | Any = _UNSET,
    ) -> bool:
        """按字段更新，返回是否命中；未传的字段保持原值。"""
        assignments: list[str] = []
        params: list[Any] = []

        if expense_date is not _UNSET:
            assignments.append("expense_date = ?")
            params.append(normalize_date(expense_date))
        if amount_cents is not _UNSET:
            assignments.append("amount_cents = ?")
            params.append(_check_amount(amount_cents))
        if category is not _UNSET:
            assignments.append("category = ?")
            params.append(_check_category(category))
        if note is not _UNSET:
            assignments.append("note = ?")
            params.append(note)

        if not assignments:
            return self.get(expense_id) is not None

        assignments.append("updated_at = ?")
        params.append(_now())
        params.append(expense_id)

        cursor = self._conn.execute(
            f"UPDATE expenses SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ---------- 删除 ----------

    def delete(self, expense_id: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM expenses WHERE id = ?", (expense_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0


def _month_range(year: int, month: int) -> tuple[date, date]:
    """返回某月的首末日期；月份非法时抛 ValueError。"""
    if not 1 <= month <= 12:
        raise ValueError(f"月份必须在 1..12: {month}")
    first = date(year, month, 1)
    # 下个月 1 号减一天，天然处理闰年与月末
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    return first, last
