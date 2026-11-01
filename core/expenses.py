"""收支流水（发生额）的仓储层。

设计要点：

- **金额单位是"分"（整数）**。账本里最忌讳浮点误差：``0.1 + 0.2`` 会得到
  ``0.30000000000000004``，累加几十笔之后总额就对不上了。存储与计算全部用
  整数分，只在显示时格式化成 ``¥12.50``。
- **金额恒为正，方向由 ``kind`` 决定**（``expense`` / ``income``）。存负数的话，
  "本月支出合计"、"结余"、"分类占比"每个地方都要判断符号，错一次就全错。
- **``account_id`` 为 NULL 表示这条流水不联动资产负债表**。用户可以选择
  "只记一笔账，余额我自己对"（记账时最常见），也可以选择挂到某个账户上，
  写入的同时调整余额。两种用法共存在同一张表里，靠这一个字段区分。
- **分类是自由文本，不建分类表**。常见分类给一份预置清单做下拉，用户也可以
  直接输新分类；需要"有哪些分类"时从数据里聚合，不会出现空标签。
- 日期校验复用学习记录那套 ``date(...) IS date(...)`` 的真实日历校验。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from core.accounts import ASSET, AccountRepository
from core.database import DatabaseManager
from core.study_records import normalize_date

# 支出分类预置项：只用于下拉候选，不是白名单
CATEGORY_PRESETS: tuple[str, ...] = (
    "吃饭", "交通", "学习", "购物", "娱乐", "其他",
)

# 收入分类预置项。单独一份，避免"工资"出现在支出下拉里、"奶茶"出现在收入里
INCOME_CATEGORY_PRESETS: tuple[str, ...] = (
    "工资", "兼职", "奖学金", "投资收益", "红包", "其他",
)

DEFAULT_CATEGORY: str = "其他"

# 流水方向
FLOW_EXPENSE: str = "expense"
FLOW_INCOME: str = "income"
FLOW_KINDS: tuple[str, str] = (FLOW_EXPENSE, FLOW_INCOME)
FLOW_LABELS: dict[str, str] = {FLOW_EXPENSE: "支出", FLOW_INCOME: "收入"}

_COLUMNS = (
    "id, expense_date, amount_cents, category, note, kind, account_id, "
    "created_at, updated_at"
)

_UNSET: Any = object()


def presets_for(kind: str) -> tuple[str, ...]:
    """某一方向的分类候选。"""
    return INCOME_CATEGORY_PRESETS if kind == FLOW_INCOME else CATEGORY_PRESETS


def flow_delta(flow_kind: str, account_kind: str, amount_cents: int) -> int:
    """一笔收支对账户余额的影响（带符号）。

    四种组合，符合直觉：

    ==========  ==============  ================================
    流水方向    账户类型        余额变化
    ==========  ==============  ================================
    支出        资产            −金额（钱少了）
    支出        负债            +金额（刷信用卡，欠款变多）
    收入        资产            +金额（钱多了）
    收入        负债            −金额（还信用卡，欠款变少）
    ==========  ==============  ================================
    """
    if flow_kind == FLOW_INCOME:
        return amount_cents if account_kind == ASSET else -amount_cents
    return -amount_cents if account_kind == ASSET else amount_cents


@dataclass(frozen=True)
class Expense:
    """一条流水（支出或收入）。"""

    id: int
    expense_date: str          # ISO 'YYYY-MM-DD'
    amount_cents: int          # 恒为正，方向见 kind
    category: str
    note: str
    created_at: str
    updated_at: str
    kind: str = FLOW_EXPENSE   # 'expense' / 'income'
    account_id: int | None = None  # None = 不联动资产负债表

    @property
    def is_income(self) -> bool:
        return self.kind == FLOW_INCOME

    @property
    def kind_label(self) -> str:
        return FLOW_LABELS.get(self.kind, self.kind)

    @property
    def signed_cents(self) -> int:
        """带符号的金额：收入为正、支出为负，用于求和。"""
        return self.amount_cents if self.is_income else -self.amount_cents

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
            kind=str(row["kind"]),
            account_id=None if row["account_id"] is None else int(row["account_id"]),
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


def _check_kind(value: str) -> str:
    if value not in FLOW_KINDS:
        raise ValueError(f"未知的流水方向: {value!r}，可选 {list(FLOW_KINDS)}")
    return value


class ExpenseRepository:
    """``expenses`` 表的增删改查、月度汇总与账户联动。"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        # 联动要改账户余额并刷新快照，这里复用 AccountRepository，
        # 避免把"余额怎么调、快照怎么存"的规则复制一份
        self._accounts = AccountRepository(db)

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
        kind: str = FLOW_EXPENSE,
        account_id: int | None = None,
    ) -> int:
        """新增一条流水，返回 id。

        ``account_id`` 不为 None 时，同一次操作里调整该账户余额，
        并刷新当天净资产快照。
        """
        amount = _check_amount(amount_cents)
        flow = _check_kind(kind)
        account = self._resolve_account(account_id)

        now = _now()
        cursor = self._conn.execute(
            "INSERT INTO expenses (expense_date, amount_cents, category, note, "
            "kind, account_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                normalize_date(expense_date),
                amount,
                _check_category(category),
                note,
                flow,
                account,
                now,
                now,
            ),
        )
        delta = self._delta_for(flow, account, amount)
        self._apply_delta(account, delta, now)
        self._conn.commit()

        if delta:
            self._accounts.refresh_snapshot()
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

    def list_by_month(
        self, year: int, month: int, kind: str | None = None
    ) -> list[Expense]:
        """某月的流水，按日期倒序（最近的在上面）。

        ``kind`` 为 None 时收支都返回；给定 ``expense`` / ``income`` 时只返回那一种。
        """
        if kind is not None:
            _check_kind(kind)
        start, end = _month_range(year, month)
        sql = (
            f"SELECT {_COLUMNS} FROM expenses "
            "WHERE expense_date BETWEEN ? AND ? "
        )
        params: list[Any] = [start.isoformat(), end.isoformat()]
        if kind is not None:
            sql += "AND kind = ? "
            params.append(kind)
        sql += "ORDER BY expense_date DESC, created_at DESC, id DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [Expense.from_row(r) for r in rows]

    def month_total_cents(self, year: int, month: int) -> int:
        """某月**支出**合计（分）。历史方法，语义保持不变。"""
        start, end = _month_range(year, month)
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM expenses "
            "WHERE expense_date BETWEEN ? AND ? AND kind = ?",
            (start.isoformat(), end.isoformat(), FLOW_EXPENSE),
        ).fetchone()
        return int(row["total"])

    def month_income_cents(self, year: int, month: int) -> int:
        """某月**收入**合计（分）。"""
        start, end = _month_range(year, month)
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM expenses "
            "WHERE expense_date BETWEEN ? AND ? AND kind = ?",
            (start.isoformat(), end.isoformat(), FLOW_INCOME),
        ).fetchone()
        return int(row["total"])

    def month_net_cents(self, year: int, month: int) -> int:
        """某月结余（分）= 收入 − 支出，可为负。"""
        return self.month_income_cents(year, month) - self.month_total_cents(
            year, month
        )

    def category_totals(
        self, year: int, month: int, kind: str = FLOW_EXPENSE
    ) -> list[tuple[str, int]]:
        """某月某一方向按分类汇总，金额从大到小。"""
        flow = _check_kind(kind)
        start, end = _month_range(year, month)
        rows = self._conn.execute(
            "SELECT category, SUM(amount_cents) AS total FROM expenses "
            "WHERE expense_date BETWEEN ? AND ? AND kind = ? "
            "GROUP BY category ORDER BY total DESC, category ASC",
            (start.isoformat(), end.isoformat(), flow),
        ).fetchall()
        return [(str(r["category"]), int(r["total"])) for r in rows]

    def list_categories(self, kind: str = FLOW_EXPENSE) -> list[str]:
        """某一方向出现过的分类（按笔数从多到少），用于左侧标签页。"""
        flow = _check_kind(kind)
        rows = self._conn.execute(
            "SELECT category, COUNT(*) AS n FROM expenses WHERE kind = ? "
            "GROUP BY category ORDER BY n DESC, category ASC",
            (flow,),
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
        kind: str | Any = _UNSET,
        account_id: int | None | Any = _UNSET,
    ) -> bool:
        """按字段更新，返回是否命中。

        若改动了金额 / 方向 / 关联账户，会**先撤销旧记录对账户的影响，再施加新的**。
        例如"这笔 30 块从支付宝改到银行卡"，等价于给支付宝 +30、给银行卡 −30。
        """
        old = self.get(expense_id)
        if old is None:
            return False

        assignments: list[str] = []
        params: list[Any] = []

        new_date = old.expense_date
        new_amount = old.amount_cents
        new_kind = old.kind
        new_account = old.account_id

        if expense_date is not _UNSET:
            new_date = normalize_date(expense_date)
            assignments.append("expense_date = ?")
            params.append(new_date)
        if amount_cents is not _UNSET:
            new_amount = _check_amount(amount_cents)
            assignments.append("amount_cents = ?")
            params.append(new_amount)
        if category is not _UNSET:
            assignments.append("category = ?")
            params.append(_check_category(category))
        if note is not _UNSET:
            assignments.append("note = ?")
            params.append(note)
        if kind is not _UNSET:
            new_kind = _check_kind(kind)
            assignments.append("kind = ?")
            params.append(new_kind)
        if account_id is not _UNSET:
            new_account = self._resolve_account(account_id)
            assignments.append("account_id = ?")
            params.append(new_account)

        if not assignments:
            return True

        now = _now()
        assignments.append("updated_at = ?")
        params.append(now)
        params.append(expense_id)

        cursor = self._conn.execute(
            f"UPDATE expenses SET {', '.join(assignments)} WHERE id = ?", params
        )

        link_changed = (old.amount_cents, old.kind, old.account_id) != (
            new_amount,
            new_kind,
            new_account,
        )
        if link_changed:
            old_delta = self._delta_for(
                old.kind, old.account_id, old.amount_cents
            )
            self._apply_delta(old.account_id, -old_delta, now)
            new_delta = self._delta_for(new_kind, new_account, new_amount)
            self._apply_delta(new_account, new_delta, now)

        self._conn.commit()
        if link_changed:
            self._accounts.refresh_snapshot()
        return cursor.rowcount > 0

    # ---------- 删除 ----------

    def delete(self, expense_id: int) -> bool:
        """删除流水；若它联动过账户，会把那笔影响退回去。"""
        old = self.get(expense_id)
        if old is None:
            return False

        delta = self._delta_for(old.kind, old.account_id, old.amount_cents)
        cursor = self._conn.execute(
            "DELETE FROM expenses WHERE id = ?", (expense_id,)
        )
        if delta:
            self._apply_delta(old.account_id, -delta, _now())
        self._conn.commit()

        if delta:
            self._accounts.refresh_snapshot()
        return cursor.rowcount > 0

    # ---------- 账户联动（内部） ----------

    def _resolve_account(self, account_id: int | None) -> int | None:
        """校验账户存在，返回原值；None 原样返回。"""
        if account_id is None:
            return None
        if isinstance(account_id, bool) or not isinstance(account_id, int):
            raise TypeError(f"account_id 必须是整数或 None，收到 {type(account_id).__name__}")
        row = self._conn.execute(
            "SELECT 1 FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"账户不存在: {account_id}")
        return account_id

    def _delta_for(
        self, flow_kind: str, account_id: int | None, amount_cents: int
    ) -> int:
        """这笔流水会让账户变化多少；账户不存在或未关联时返回 0。"""
        if account_id is None:
            return 0
        row = self._conn.execute(
            "SELECT kind FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if row is None:
            return 0
        return flow_delta(flow_kind, str(row["kind"]), amount_cents)

    def _apply_delta(self, account_id: int | None, delta: int, now: str) -> None:
        """直接改余额（不 commit，由调用方统一提交）。"""
        if account_id is None or delta == 0:
            return
        self._conn.execute(
            "UPDATE accounts SET balance_cents = balance_cents + ?, updated_at = ? "
            "WHERE id = ?",
            (delta, now, account_id),
        )


def _month_range(year: int, month: int) -> tuple[date, date]:
    """返回某月的首末日期；月份非法时抛 ValueError。"""
    if not 1 <= month <= 12:
        raise ValueError(f"月份必须在 1..12: {month}")
    first = date(year, month, 1)
    # 下个月 1 号减一天，天然处理闰年与月末
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    return first, last
