"""学习记录仓储层（第三阶段 · 第一小步）。

把 ``study_records`` 表的读写集中在此，UI 层只依赖本模块的
``StudyRecordRepository`` 接口，不接触任何 SQL 语句。

设计要点：
- **全部使用参数化 SQL**（``?`` 占位符），不做字符串拼接，杜绝注入；
- 日期统一归一化为 ISO ``YYYY-MM-DD`` 文本，便于排序与范围查询；
- 时间戳取本机本地时间，与 ``datetime('now','localtime')`` 的 DDL 默认值一致；
- 同一天允许任意多条记录，因此"按日期查询"返回列表而非单条。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from core.database import DatabaseManager

# 用于区分"未传该字段"与"显式传 None"（duration_minutes 允许清空）
_UNSET: Any = object()

_COLUMNS = "id, study_date, subject, duration_minutes, content, created_at, updated_at"


@dataclass(frozen=True)
class StudyRecord:
    """一条学习记录。"""

    id: int
    study_date: str            # ISO 'YYYY-MM-DD'
    subject: str
    duration_minutes: int | None
    content: str
    created_at: str            # 'YYYY-MM-DD HH:MM:SS'
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "StudyRecord":
        return cls(
            id=int(row["id"]),
            study_date=str(row["study_date"]),
            subject=str(row["subject"]),
            duration_minutes=(
                None if row["duration_minutes"] is None else int(row["duration_minutes"])
            ),
            content=str(row["content"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def normalize_date(value: str | date | datetime) -> str:
    """把日期归一化为 ISO ``YYYY-MM-DD``，非法输入抛 ValueError。

    兼容 ``2026-3-5`` 这类未补零写法（内部统一补零），
    但拒绝 ``2026/03/15``、``26-03-15`` 等歧义格式。
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            pass
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError(f"日期格式非法，应为 YYYY-MM-DD: {value!r}") from exc
    raise TypeError(f"不支持的日期类型: {type(value).__name__}")


def _now() -> str:
    """本地时间字符串，精度到秒，与 DDL 默认值格式一致。"""
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _check_duration(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"duration_minutes 必须是整数或 None，收到 {type(value).__name__}")
    if value < 0:
        raise ValueError(f"duration_minutes 不能为负数: {value}")
    return value


def _check_subject(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"subject 必须是字符串，收到 {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError("subject 不能为空")
    return text


class StudyRecordRepository:
    """``study_records`` 表的增删改查。"""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._db.connection

    # ---------- 新增 ----------

    def add(
        self,
        study_date: str | date | datetime,
        subject: str,
        content: str = "",
        duration_minutes: int | None = None,
    ) -> int:
        """新增一条记录并返回其 id。同一天可重复调用，产生多条记录。"""
        now = _now()
        cursor = self._conn.execute(
            "INSERT INTO study_records (study_date, subject, duration_minutes, "
            "content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                normalize_date(study_date),
                _check_subject(subject),
                _check_duration(duration_minutes),
                content,
                now,
                now,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    # ---------- 查询 ----------

    def get(self, record_id: int) -> StudyRecord | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM study_records WHERE id = ?", (record_id,)
        ).fetchone()
        return StudyRecord.from_row(row) if row else None

    def list_by_date(self, study_date: str | date | datetime) -> list[StudyRecord]:
        """某一天的全部记录，按创建顺序返回。"""
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM study_records WHERE study_date = ? "
            "ORDER BY created_at, id",
            (normalize_date(study_date),),
        ).fetchall()
        return [StudyRecord.from_row(r) for r in rows]

    def list_by_date_range(
        self,
        start: str | date | datetime,
        end: str | date | datetime,
    ) -> list[StudyRecord]:
        """闭区间 [start, end] 内的记录，按日期、创建顺序返回。"""
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM study_records "
            "WHERE study_date BETWEEN ? AND ? ORDER BY study_date, created_at, id",
            (normalize_date(start), normalize_date(end)),
        ).fetchall()
        return [StudyRecord.from_row(r) for r in rows]

    def list_recent(self, limit: int = 50) -> list[StudyRecord]:
        """最近 N 条记录（按日期倒序）。"""
        if limit <= 0:
            return []
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM study_records "
            "ORDER BY study_date DESC, created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [StudyRecord.from_row(r) for r in rows]

    def count(self, study_date: str | date | datetime | None = None) -> int:
        """记录总数；给定日期时只统计当天。"""
        if study_date is None:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM study_records").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM study_records WHERE study_date = ?",
                (normalize_date(study_date),),
            ).fetchone()
        return int(row["n"])

    # ---------- 修改 ----------

    def update(
        self,
        record_id: int,
        *,
        study_date: str | date | datetime | Any = _UNSET,
        subject: str | Any = _UNSET,
        content: str | Any = _UNSET,
        duration_minutes: int | None | Any = _UNSET,
    ) -> bool:
        """按字段更新记录，返回是否命中。

        未传的字段保持原值；``duration_minutes=None`` 为显式清空。
        """
        # 下面拼接的只是固定的列名片段，值全部走参数绑定，无注入风险
        assignments: list[str] = []
        params: list[Any] = []

        if study_date is not _UNSET:
            assignments.append("study_date = ?")
            params.append(normalize_date(study_date))
        if subject is not _UNSET:
            assignments.append("subject = ?")
            params.append(_check_subject(subject))
        if content is not _UNSET:
            assignments.append("content = ?")
            params.append(content)
        if duration_minutes is not _UNSET:
            assignments.append("duration_minutes = ?")
            params.append(_check_duration(duration_minutes))

        if not assignments:
            return self.get(record_id) is not None

        assignments.append("updated_at = ?")
        params.append(_now())
        params.append(record_id)

        cursor = self._conn.execute(
            f"UPDATE study_records SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ---------- 删除 ----------

    def delete(self, record_id: int) -> bool:
        """删除一条记录，返回是否命中。"""
        cursor = self._conn.execute(
            "DELETE FROM study_records WHERE id = ?", (record_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0
