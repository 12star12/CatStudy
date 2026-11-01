"""资产 / 负债账户与净资产快照。

**为什么单独一个模块，而不是复用 ``expenses``**：两者是不同的模型。

- ``expenses`` 是**发生额**："今天花了 30 块"——一件事，有日期、会累积；
- ``accounts`` 是**存量**："这张卡里现在有 8000 块"——某个时点的状态，
  修改即覆盖，不累积。

把存量塞进流水表只能靠"用一条条调整记录去逼近余额"，一旦漏记就永久跑偏，
而且没有对账入口。所以这里是一张独立的账户表。

设计要点：

1. **余额由用户手工维护**（产品决定）。手工改余额本身就承担了"对账"的职责，
   比"每笔自动累加"更抗漏记。
2. **余额永远是非负数**，正负由 ``kind`` 决定：
   ``净资产 = Σ(asset) - Σ(liability)``。允许负债存负数会让这条公式在两处
   取反，极易算错。
3. **金额仍用整数分**，与账本保持一致。
4. **每次写操作后刷新当天快照**（UPSERT，一天一条），用于画净资产走势。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from core.database import DatabaseManager
from core.study_records import normalize_date

# 账户类型
ASSET: str = "asset"
LIABILITY: str = "liability"
KINDS: tuple[str, str] = (ASSET, LIABILITY)

KIND_LABELS: dict[str, str] = {ASSET: "资产", LIABILITY: "负债"}

# 分类候选：只是下拉框的提示项，不是白名单，允许自由输入
CATEGORY_PRESETS: dict[str, tuple[str, ...]] = {
    ASSET: ("现金", "银行卡", "支付余额", "投资", "房产", "其它"),
    LIABILITY: ("信用卡", "花呗", "房贷", "车贷", "借款", "其它"),
}

_COLUMNS = (
    "id, name, kind, balance_cents, category, note, sort_order, created_at, updated_at"
)

_UNSET: Any = object()


@dataclass(frozen=True)
class Account:
    """一个资产或负债账户。"""

    id: int
    name: str
    kind: str                  # 'asset' / 'liability'
    balance_cents: int         # 始终 >= 0，符号由 kind 决定
    category: str
    note: str
    sort_order: int
    created_at: str
    updated_at: str

    @property
    def is_liability(self) -> bool:
        return self.kind == LIABILITY

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Account":
        return cls(
            id=int(row["id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            balance_cents=int(row["balance_cents"]),
            category=str(row["category"]),
            note=str(row["note"]),
            sort_order=int(row["sort_order"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


@dataclass(frozen=True)
class NetWorth:
    """某一时刻的资产负债汇总。"""

    assets_cents: int
    liabilities_cents: int

    @property
    def net_cents(self) -> int:
        """净资产；负债大于资产时为负，这是合法状态。"""
        return self.assets_cents - self.liabilities_cents

    @property
    def liability_ratio(self) -> float:
        """负债占总资产的比例（0.0~1.0）；没有资产但有负债时按 1.0 处理。"""
        if self.assets_cents <= 0:
            return 1.0 if self.liabilities_cents > 0 else 0.0
        return min(1.0, self.liabilities_cents / self.assets_cents)


@dataclass(frozen=True)
class Snapshot:
    """某一天的净资产快照。"""

    id: int
    snapshot_date: str
    total_assets_cents: int
    total_liabilities_cents: int
    created_at: str

    @property
    def net_cents(self) -> int:
        return self.total_assets_cents - self.total_liabilities_cents

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Snapshot":
        return cls(
            id=int(row["id"]),
            snapshot_date=str(row["snapshot_date"]),
            total_assets_cents=int(row["total_assets_cents"]),
            total_liabilities_cents=int(row["total_liabilities_cents"]),
            created_at=str(row["created_at"]),
        )


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _check_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"name 必须是字符串，收到 {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError("账户名称不能为空")
    return text


def _check_kind(value: str) -> str:
    if value not in KINDS:
        raise ValueError(f"未知的账户类型: {value!r}，可选 {list(KINDS)}")
    return value


# 余额上限（分）：约 100 亿元，纯属防手滑输入一串 0
MAX_BALANCE_CENTS: int = 10_000_000_000_00


def _check_balance(value: int) -> int:
    """余额校验。

    **允许负数**：流水联动扣款可能把账户扣成负数（透支、余额没及时更新），
    这时拒绝记账比让余额变负更烦人。负数在界面上会标红，提示"该对账了"。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"balance_cents 必须是整数，收到 {type(value).__name__}")
    if abs(value) > MAX_BALANCE_CENTS:
        raise ValueError(f"金额过大: {value}")
    return value


class AccountRepository:
    """``accounts`` 与 ``net_worth_snapshots`` 的读写。"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._db.connection

    # ---------- 新增 ----------

    def add(
        self,
        name: str,
        kind: str = ASSET,
        balance_cents: int = 0,
        category: str = "",
        note: str = "",
    ) -> int:
        """新增账户并返回 id；同时刷新当天净资产快照。"""
        now = _now()
        cursor = self._conn.execute(
            "INSERT INTO accounts (name, kind, balance_cents, category, note, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _check_name(name),
                _check_kind(kind),
                _check_balance(balance_cents),
                category,
                note,
                now,
                now,
            ),
        )
        self._conn.commit()
        self.refresh_snapshot()
        return int(cursor.lastrowid)

    # ---------- 查询 ----------

    def get(self, account_id: int) -> Account | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return Account.from_row(row) if row else None

    def list_all(self, kind: str | None = None) -> list[Account]:
        """账户列表；资产在前、负债在后，同类内按 sort_order。"""
        if kind is None:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM accounts ORDER BY kind, sort_order, id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM accounts WHERE kind = ? "
                "ORDER BY sort_order, id",
                (_check_kind(kind),),
            ).fetchall()
        return [Account.from_row(r) for r in rows]

    def list_by_kind(self, kind: str) -> list[Account]:
        return self.list_all(kind)

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()
        return int(row["n"])

    def totals(self, kind: str | None = None) -> NetWorth:
        """汇总资产与负债；``kind`` 只影响"这一边"的查询（内部使用）。"""
        if kind is not None:
            _check_kind(kind)
            row = self._conn.execute(
                "SELECT COALESCE(SUM(balance_cents), 0) AS total "
                "FROM accounts WHERE kind = ?",
                (kind,),
            ).fetchone()
            total = int(row["total"])
            return (
                NetWorth(assets_cents=total, liabilities_cents=0)
                if kind == ASSET
                else NetWorth(assets_cents=0, liabilities_cents=total)
            )

        rows = self._conn.execute(
            "SELECT kind, COALESCE(SUM(balance_cents), 0) AS total "
            "FROM accounts GROUP BY kind"
        ).fetchall()
        by_kind = {str(r["kind"]): int(r["total"]) for r in rows}
        return NetWorth(
            assets_cents=by_kind.get(ASSET, 0),
            liabilities_cents=by_kind.get(LIABILITY, 0),
        )

    def category_totals(self, kind: str) -> list[tuple[str, int]]:
        """某一边按类别汇总，金额从大到小。"""
        rows = self._conn.execute(
            "SELECT category, SUM(balance_cents) AS total FROM accounts "
            "WHERE kind = ? GROUP BY category ORDER BY total DESC, category ASC",
            (_check_kind(kind),),
        ).fetchall()
        return [
            (str(r["category"]) or "未分类", int(r["total"])) for r in rows
        ]

    def list_categories(self, kind: str) -> list[str]:
        """某一类型下出现过的类别（按使用次数降序），用于对话框的候选。

        与 ``CATEGORY_PRESETS`` 的区别：预置项是"可能用到"，这里是"实际用过"。
        两者在对话框里合并展示，常用类别因此会排到前面。
        """
        rows = self._conn.execute(
            "SELECT category, COUNT(*) AS n FROM accounts "
            "WHERE kind = ? AND category <> '' "
            "GROUP BY category ORDER BY n DESC, category ASC",
            (_check_kind(kind),),
        ).fetchall()
        return [str(r["category"]) for r in rows]

    # ---------- 修改 ----------

    def update(
        self,
        account_id: int,
        *,
        name: str | Any = _UNSET,
        kind: str | Any = _UNSET,
        balance_cents: int | Any = _UNSET,
        category: str | Any = _UNSET,
        note: str | Any = _UNSET,
    ) -> bool:
        """按字段更新；未传的保持原值。更新后刷新当天快照。"""
        assignments: list[str] = []
        params: list[Any] = []

        if name is not _UNSET:
            assignments.append("name = ?")
            params.append(_check_name(name))
        if kind is not _UNSET:
            assignments.append("kind = ?")
            params.append(_check_kind(kind))
        if balance_cents is not _UNSET:
            assignments.append("balance_cents = ?")
            params.append(_check_balance(balance_cents))
        if category is not _UNSET:
            assignments.append("category = ?")
            params.append(category)
        if note is not _UNSET:
            assignments.append("note = ?")
            params.append(note)

        if not assignments:
            return self.get(account_id) is not None

        assignments.append("updated_at = ?")
        params.append(_now())
        params.append(account_id)

        cursor = self._conn.execute(
            f"UPDATE accounts SET {', '.join(assignments)} WHERE id = ?", params
        )
        self._conn.commit()
        self.refresh_snapshot()
        return cursor.rowcount > 0

    # ---------- 余额调整 ----------

    def adjust_balance(
        self, account_id: int, delta_cents: int, *, touch_snapshot: bool = True
    ) -> bool:
        """在现有余额上加减（流水联动用），返回是否命中。

        用 ``balance_cents = balance_cents + ?`` 而不是先读后写：并发或多条流水
        连续调整时，读-改-写会丢更新。
        """
        if isinstance(delta_cents, bool) or not isinstance(delta_cents, int):
            raise TypeError(f"delta_cents 必须是整数，收到 {type(delta_cents).__name__}")
        if delta_cents == 0:
            return self.get(account_id) is not None
        cursor = self._conn.execute(
            "UPDATE accounts SET balance_cents = balance_cents + ?, updated_at = ? "
            "WHERE id = ?",
            (delta_cents, _now(), account_id),
        )
        self._conn.commit()
        if cursor.rowcount and touch_snapshot:
            self.refresh_snapshot()
        return cursor.rowcount > 0

    # ---------- 删除 ----------

    def delete(self, account_id: int) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM accounts WHERE id = ?", (account_id,)
        )
        self._conn.commit()
        self.refresh_snapshot()
        return cursor.rowcount > 0

    # ---------- 快照 ----------

    def refresh_snapshot(self, day: str | date | datetime | None = None) -> Snapshot:
        """把当前总额写成当天快照（同一天重复调用覆盖，不新增行）。"""
        target = normalize_date(day) if day is not None else date.today().isoformat()
        totals = self.totals()
        self._conn.execute(
            "INSERT INTO net_worth_snapshots "
            "(snapshot_date, total_assets_cents, total_liabilities_cents, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(snapshot_date) DO UPDATE SET "
            "total_assets_cents = excluded.total_assets_cents, "
            "total_liabilities_cents = excluded.total_liabilities_cents",
            (target, totals.assets_cents, totals.liabilities_cents, _now()),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id, snapshot_date, total_assets_cents, total_liabilities_cents, "
            "created_at FROM net_worth_snapshots WHERE snapshot_date = ?",
            (target,),
        ).fetchone()
        return Snapshot.from_row(row)

    def list_snapshots(self, limit: int | None = None) -> list[Snapshot]:
        """快照列表，**按日期升序**（旧 → 新），可直接用于画折线。

        给 ``limit`` 时取最近 N 条，但仍以升序返回——折线的 x 轴必须是从
        过去到现在，调用方不需要再反转。
        """
        if limit is None:
            rows = self._conn.execute(
                "SELECT id, snapshot_date, total_assets_cents, "
                "total_liabilities_cents, created_at "
                "FROM net_worth_snapshots ORDER BY snapshot_date ASC"
            ).fetchall()
        else:
            if limit <= 0:
                return []
            rows = self._conn.execute(
                "SELECT * FROM ("
                "  SELECT id, snapshot_date, total_assets_cents, "
                "         total_liabilities_cents, created_at "
                "  FROM net_worth_snapshots ORDER BY snapshot_date DESC LIMIT ?"
                ") ORDER BY snapshot_date ASC",
                (limit,),
            ).fetchall()
        return [Snapshot.from_row(r) for r in rows]

    def latest_snapshot(self) -> Snapshot | None:
        row = self._conn.execute(
            "SELECT id, snapshot_date, total_assets_cents, total_liabilities_cents, "
            "created_at FROM net_worth_snapshots "
            "ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        return Snapshot.from_row(row) if row else None
