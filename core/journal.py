"""日记的存储与读取。

一天一篇，用 ``entry_date`` 上的 UNIQUE 约束保证。和学习记录的区别见
``core/database.py`` 里 ``_TABLE_JOURNAL`` 上方那段说明：学习记录是"发生额"
（一天可以有很多条，各有科目和时长），日记是"这一天的整体印象"（一天一份，
没有科目维度）。两者是不同概念，硬塞进一张表会让查询到处打补丁。

一个刻意的行为：**保存空内容等于删除**。用户删光正文后不该在列表里留一条
"空白日记"，否则列表越用越脏、点进去什么都没有。所以 ``save()`` 在正文
去空白后为空时直接删行，并返回 None。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from core.database import DatabaseManager
from core.study_records import normalize_date

# 正文长度上限（字符）。一亿字够任何人写，主要是防手滑粘贴整个文件进来
MAX_CONTENT_LENGTH: int = 1_000_000

_COLUMNS = "id, entry_date, content, created_at, updated_at"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _check_content(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"日记正文必须是字符串，收到 {type(value).__name__}")
    if len(value) > MAX_CONTENT_LENGTH:
        raise ValueError(f"日记过长（{len(value)} 字符）")
    return value


@dataclass(frozen=True)
class JournalEntry:
    """一天的日记。"""

    id: int
    entry_date: str            # ISO 'YYYY-MM-DD'
    content: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "JournalEntry":
        return cls(
            id=int(row["id"]),
            entry_date=str(row["entry_date"]),
            content=str(row["content"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @property
    def word_count(self) -> int:
        """正文字数。

        用 ``len`` 而不是"按空格分词"：中文没有词边界，按词算出来的数字既不准
        也没有直觉；用户对"多少字"的理解就是字符数（Word 的中文计数也是这么算的）。
        换行和首尾空白不计入。
        """
        return len(self.content.strip())

    @property
    def summary(self) -> str:
        """列表里用的一行摘要：把换行压成空格。"""
        return " ".join(self.content.split())


class JournalRepository:
    """日记的增删改查。"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._db.connection

    # ---------- 读 ----------

    def get(self, day: str | date | datetime) -> JournalEntry | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM journal_entries WHERE entry_date = ?",
            (normalize_date(day),),
        ).fetchone()
        return None if row is None else JournalEntry.from_row(row)

    def list_recent(self, limit: int | None = None) -> list[JournalEntry]:
        """按日期倒序返回，最新的在前。

        ``limit`` 是"最近 N 篇"而不是"前 N 篇"：传了 limit 也仍然从最新开始数，
        列表要显示的就是最近的日记。
        """
        sql = f"SELECT {_COLUMNS} FROM journal_entries ORDER BY entry_date DESC"
        params: tuple = ()
        if limit is not None:
            if limit < 0:
                raise ValueError("limit 不能为负数")
            sql += " LIMIT ?"
            params = (int(limit),)
        return [JournalEntry.from_row(r) for r in self._conn.execute(sql, params)]

    def list_by_month(self, year: int, month: int) -> list[JournalEntry]:
        """某个月的日记（含闰年与 12 月跨年），日期倒序。"""
        if not 1 <= month <= 12:
            raise ValueError(f"月份非法: {month}")
        first = date(year, month, 1).isoformat()
        last = date(year + (month // 12), (month % 12) + 1, 1).isoformat()
        return [
            JournalEntry.from_row(r)
            for r in self._conn.execute(
                f"SELECT {_COLUMNS} FROM journal_entries "
                "WHERE entry_date >= ? AND entry_date < ? ORDER BY entry_date DESC",
                (first, last),
            )
        ]

    def count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) AS n FROM journal_entries").fetchone()["n"]
        )

    def first_date(self) -> str | None:
        """最早一篇的日期，用于"开始写作那天"这类展示。"""
        row = self._conn.execute(
            "SELECT MIN(entry_date) AS d FROM journal_entries"
        ).fetchone()
        return None if row is None or row["d"] is None else str(row["d"])

    # ---------- 写 ----------

    def save(self, day: str | date | datetime, content: str) -> JournalEntry | None:
        """写入或覆盖某天的日记；内容为空则删掉这一天的记录。

        返回保存后的条目，被删掉（内容为空）时返回 None。
        """
        iso = normalize_date(day)
        text = _check_content(content)
        if not text.strip():
            self.delete(iso)
            return None

        now = _now()
        self._conn.execute(
            "INSERT INTO journal_entries (entry_date, content, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(entry_date) DO UPDATE SET "
            "content = excluded.content, updated_at = excluded.updated_at",
            (iso, text, now, now),
        )
        self._conn.commit()
        return self.get(iso)

    def delete(self, day: str | date | datetime) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM journal_entries WHERE entry_date = ?",
            (normalize_date(day),),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ---------- 列表用的轻量查询 ----------

    def dates(self) -> set[str]:
        """所有有日记的日期，给日历打标记用（不加载正文，省内存）。"""
        return {
            str(r["entry_date"])
            for r in self._conn.execute("SELECT entry_date FROM journal_entries")
        }
