"""SQLite 数据库基础设施（第三阶段 · 第一小步）。

职责（仅"连接 + 结构"，不含业务查询）：
- 定位数据库文件：项目根目录下的 ``data/catstudy.db``，由 ``__file__``
  推导，不依赖任何硬编码绝对路径，整个项目可任意搬迁；
- 建立并复用连接，设置 ``row_factory`` 与必要 PRAGMA；
- **幂等**地创建表与索引：应用每次启动都会执行一次检查，
  表已存在时不会重复创建、不会丢数据；
- 通过 ``app_meta`` 记录 schema 版本，为后续迁移留出入口。

边界：
- 本模块不写任何业务 SQL，业务读写见 ``core/study_records.py``；
- UI 层（``ui/``）不得出现任何 SQL，也不得直接 import sqlite3。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# 本文件位于 core/ 目录下，因此项目根目录是其上一级
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
DB_PATH: Path = DATA_DIR / "catstudy.db"

# 当前 schema 版本；未来改表结构时递增，并在 _migrate 中补对应步骤
# v1 -> v2：study_date 的 CHECK 由"仅格式正则"改为"格式 + 真实日历日期"
# v2 -> v3：新增 source 列，标记记录来源（番茄钟 / 正计时 / 手工录入）
SCHEMA_VERSION: int = 3

# ---------- 表结构 ----------

_TABLE_APP_META = """
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""

# 学习记录表
# - 同一天允许多条记录：study_date 上不建唯一约束
# - duration_minutes 允许为空（只记"学了什么"而不记时长同样合法）
# - content 允许为空串（只填日期和科目也合法）
#
# 关于 study_date 的校验（重要）：
#   只用 GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' 只能拦住**格式**，
#   实测 '2026-02-30'、'2026-13-01'、'2026-00-10' 全部会被放行（它们是
#   符合该模式的 10 个字符）。因此改用日期回环比较：
#       study_date IS date(study_date)
#   SQLite 的 date() 会把 '2026-02-30' 归一化成 '2026-03-02'、把 '2026-13-01'
#   判为 NULL；只有"原样合法"的日期才与自身相等。该表达式同时强制了格式
#   （'2026-3-5'、'20260305'、'2026-03-05 10:00:00' 均不相等而被拒绝）
#   和真实存在性（含闰年：2024-02-29 通过，2026-02-29 拒绝）。
#
# - created_at / updated_at 由 datetime('now','localtime') 兜底，
#   即使绕过仓储层直接写库也能得到本地时间
#
# - source 记录这条记录从哪来（'pomodoro' / 'stopwatch' / NULL=手工录入）。
#   故意不写 CHECK 约束：来源种类还会增加（例如将来的任务打卡），
#   加约束会让每次新增来源都要重建表；合法性由仓储层负责。
_TABLE_STUDY_RECORDS = """
CREATE TABLE IF NOT EXISTS study_records (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    study_date       TEXT    NOT NULL
                     CHECK (study_date IS date(study_date)),
    subject          TEXT    NOT NULL,
    duration_minutes INTEGER CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
    content          TEXT    NOT NULL DEFAULT '',
    source           TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

# 索引：按日期筛选是最高频查询；按科目统计次之
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_study_records_study_date "
    "ON study_records (study_date)",
    "CREATE INDEX IF NOT EXISTS idx_study_records_subject "
    "ON study_records (subject)",
)

# 建表 + 建索引，顺序执行即为完整初始化
SCHEMA_STATEMENTS: tuple[str, ...] = (
    _TABLE_APP_META,
    _TABLE_STUDY_RECORDS,
    *_INDEXES,
)


class DatabaseManager:
    """SQLite 连接与 schema 生命周期管理。"""

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        self.db_path: Path = Path(db_path)
        self._connection: sqlite3.Connection | None = None

    # ---------- 连接 ----------

    @property
    def connection(self) -> sqlite3.Connection:
        """已建立的连接；未连接时抛 RuntimeError，避免静默出错。"""
        if self._connection is None:
            raise RuntimeError("数据库尚未连接，请先调用 connect()")
        return self._connection

    @property
    def is_connected(self) -> bool:
        return self._connection is not None

    def connect(self) -> sqlite3.Connection:
        """确保父目录存在、建立连接并初始化表结构（可重复调用）。"""
        if self._connection is not None:
            return self._connection

        # data/ 目录可能被清空，或首次运行时尚不存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # WAL 提升读写并发；副作用是生成 .db-wal / .db-shm，已在 .gitignore 忽略
        conn.execute("PRAGMA journal_mode = WAL")
        self._connection = conn

        self.ensure_schema()
        return conn

    def close(self) -> None:
        """提交并安全关闭连接；未连接时为空操作。"""
        if self._connection is None:
            return
        try:
            self._connection.commit()
        finally:
            self._connection.close()
            self._connection = None

    # ---------- schema ----------

    def ensure_schema(self) -> None:
        """幂等建表建索引；库中版本落后时自动迁移到 ``SCHEMA_VERSION``。"""
        conn = self.connection
        with conn:  # 上下文管理器负责提交/回滚
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)

            current = self._read_version()
            if current is None:
                # 全新库：直接写入当前版本
                conn.execute(
                    "INSERT INTO app_meta (key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                return

            if current < SCHEMA_VERSION:
                self._migrate(current)
                conn.execute(
                    "UPDATE app_meta SET value = ? WHERE key = ?",
                    (str(SCHEMA_VERSION), "schema_version"),
                )

    def _read_version(self) -> int | None:
        row = self.connection.execute(
            "SELECT value FROM app_meta WHERE key = ?", ("schema_version",)
        ).fetchone()
        return int(row["value"]) if row else None

    def schema_version(self) -> int | None:
        """读取库中记录的 schema 版本；未初始化时为 None。"""
        return self._read_version()

    # ---------- 迁移 ----------

    def _migrate(self, from_version: int) -> None:
        """把旧库逐版本升级到当前 schema。"""
        if from_version < 2:
            self._rebuild_study_records_v2()
        if from_version < 3:
            self._add_source_column_v3()

    def _add_source_column_v3(self) -> None:
        """v2 -> v3：给 study_records 增加 source 列。

        ``ADD COLUMN`` 是原地操作，不重建表、不丢数据；老记录该列为 NULL，
        语义上正好等于"手工录入"。重复执行前先查表结构，保证幂等。
        """
        conn = self.connection
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(study_records)")}
        if "source" in columns:
            return
        conn.execute("ALTER TABLE study_records ADD COLUMN source TEXT")

    def _rebuild_study_records_v2(self) -> None:
        """v1 -> v2：把 study_date 的 CHECK 从"仅格式"升级为"真实日历日期"。

        SQLite 不支持修改既有 CHECK，只能重建表。为避免迁移中途失败留下
        半成品，先校验旧数据是否全部满足新约束，再执行重建。
        """
        conn = self.connection

        bad = conn.execute(
            "SELECT COUNT(*) AS n FROM study_records "
            "WHERE study_date IS NOT date(study_date)"
        ).fetchone()["n"]
        if bad:
            raise RuntimeError(
                f"数据库迁移中止：study_records 中有 {bad} 条记录的 study_date "
                "不是合法日历日期，无法通过新约束。请先手工修正这些记录后重启。"
            )

        before = conn.execute("SELECT COUNT(*) AS n FROM study_records").fetchone()["n"]

        conn.execute("ALTER TABLE study_records RENAME TO study_records__v1")
        conn.execute(_TABLE_STUDY_RECORDS)
        conn.execute(
            "INSERT INTO study_records "
            "(id, study_date, subject, duration_minutes, content, created_at, updated_at) "
            "SELECT id, study_date, subject, duration_minutes, content, created_at, updated_at "
            "FROM study_records__v1"
        )
        conn.execute("DROP TABLE study_records__v1")
        for statement in _INDEXES:
            conn.execute(statement)

        after = conn.execute("SELECT COUNT(*) AS n FROM study_records").fetchone()["n"]
        if after != before:
            raise RuntimeError(f"数据库迁移异常：记录数 {before} -> {after}")

    def table_exists(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def index_exists(self, name: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    # ---------- 上下文管理 ----------

    def __enter__(self) -> "DatabaseManager":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def init_database(db_path: Path | str | None = None) -> DatabaseManager:
    """应用启动入口：连接数据库并确保表结构就绪。

    :param db_path: 自定义数据库路径（测试用）；默认 ``data/catstudy.db``。
    :return: 已连接、schema 已就绪的 DatabaseManager。
    """
    manager = DatabaseManager(db_path if db_path is not None else DB_PATH)
    manager.connect()
    return manager
