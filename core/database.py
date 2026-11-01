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
# v3 -> v4：新增 expenses 表（记账）
# v4 -> v5：新增 accounts（资产/负债账户）与 net_worth_snapshots（净资产快照）
# v5 -> v6：流水加 kind（收入/支出）与 account_id（联动哪个账户）；
#           accounts.balance_cents 放开负数（联动扣款可能透支）
# v6 -> v7：新增 journal_entries（日记，一天一篇）
SCHEMA_VERSION: int = 7

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

# 流水表：支出与收入共用一张表，靠 kind 区分
# - amount_cents 用"分"而不是浮点元：0.1+0.2 != 0.3 这类误差在账本里不可接受
# - amount_cents 恒为正数，方向只由 kind 决定（存负数会让汇总公式到处取反）
# - account_id 为 NULL = 这条流水不联动资产负债表，只记"花了/赚了多少"
#   ON DELETE SET NULL：账户被删掉后流水保留，只是不再追溯影响
# - 分类就是一段文本，允许自由输入，不为几个选项建表
_TABLE_EXPENSES = """
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_date TEXT    NOT NULL
                 CHECK (expense_date IS date(expense_date)),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    kind         TEXT    NOT NULL DEFAULT 'expense'
                 CHECK (kind IN ('expense', 'income')),
    account_id   INTEGER REFERENCES accounts (id) ON DELETE SET NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

# 索引：按日期筛选是最高频查询；按科目统计次之
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_study_records_study_date "
    "ON study_records (study_date)",
    "CREATE INDEX IF NOT EXISTS idx_study_records_subject "
    "ON study_records (subject)",
    "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses (expense_date)",
    "CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses (category)",
)

# ---------- 资产 / 负债（v5） ----------
#
# 这是"存量"模型，和 expenses 的"发生额"模型不是一回事：
# - expenses 记"今天花了 30 块"，是一件事；
# - accounts 记"这张卡里现在有 8000 块"，是一个时点的状态。
#
# 因此余额只能手工维护（用户选的就是这个方式）。如果改成"每笔记增减自动累加"，
# 一旦漏记一笔，余额就永久跑偏，而且没有对账入口——手工改余额本身就是对账。
#
# 金额仍用整数分。`kind` 决定符号：
#   净资产 = Σ(asset) - Σ(liability)
# v5 时余额强制 >= 0；v6 起放开了——流水联动扣款可能把账户扣成负数（透支），
# 这时直接拒绝记账比让余额变负更烦人。负数在界面上用红色提示"对不上账"。
_TABLE_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    kind          TEXT    NOT NULL CHECK (kind IN ('asset', 'liability')),
    balance_cents INTEGER NOT NULL DEFAULT 0,
    category      TEXT    NOT NULL DEFAULT '',
    note          TEXT    NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

# 净资产快照：一天最多一条，靠 UNIQUE 约束 + UPSERT 覆盖。
#
# 为什么存"总资产/总负债"而不是只存净资产：净值是把两个数相减得到的，
# 只存净值就永远无法区分"资产涨了 5 万"和"负债少了 5 万"，而这两件事
# 的性质完全不同，以后要出报表也拿不回明细。
_TABLE_NET_WORTH = """
CREATE TABLE IF NOT EXISTS net_worth_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date           TEXT    NOT NULL UNIQUE
                            CHECK (snapshot_date IS date(snapshot_date)),
    total_assets_cents      INTEGER NOT NULL DEFAULT 0,
    total_liabilities_cents INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

# 账户相关索引单独放：v1 -> v2 的整表重建会重跑 `_INDEXES`，
# 那时 accounts 表可能还不存在，混在一起会报 "no such table"。
_ACCOUNT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_accounts_kind ON accounts (kind)",
)

# 日记：一天一篇，靠 UNIQUE(entry_date) 保证。
#
# 为什么不复用 study_records 的 content 字段：那张表一行 = 一段有科目的学习，
# 一天可以有很多行，是"发生额"式的记录；日记是"这一天整体怎么样"，一天只有
# 一份，且没有科目、时长这些维度。塞进同一张表会让两个概念互相污染：
# 想查"今天学了多久"要把日记行排除，想查"今天的日记"要限定只有一个。
#
# content 允许空串：新建但还没写的时候就是空串，界面据此判断"这一天没内容"，
# 仓储层则在保存空内容时直接删行（见 core/journal.py），列表里不会留空壳。
_TABLE_JOURNAL = """
CREATE TABLE IF NOT EXISTS journal_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT    NOT NULL UNIQUE
               CHECK (entry_date IS date(entry_date)),
    content    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

# 日记按日期倒序翻页是最主要的读法，索引建在日期上
_JOURNAL_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries (entry_date)",
)

# 建表 + 建索引，顺序执行即为完整初始化
SCHEMA_STATEMENTS: tuple[str, ...] = (
    _TABLE_APP_META,
    _TABLE_STUDY_RECORDS,
    # accounts 必须排在 expenses 前面：后者有 account_id 外键指向它
    _TABLE_ACCOUNTS,
    _TABLE_EXPENSES,
    _TABLE_NET_WORTH,
    _TABLE_JOURNAL,
    *_INDEXES,
    *_ACCOUNT_INDEXES,
    *_JOURNAL_INDEXES,
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
        if from_version < 4:
            # 建表语句本身是 CREATE TABLE IF NOT EXISTS，直接执行即可
            self.connection.execute(_TABLE_EXPENSES)
        if from_version < 5:
            self.connection.execute(_TABLE_ACCOUNTS)
            self.connection.execute(_TABLE_NET_WORTH)
            for statement in _ACCOUNT_INDEXES:
                self.connection.execute(statement)
        if from_version < 6:
            self._rebuild_accounts_v6()
            self._add_flow_columns_v6()
        if from_version < 7:
            # 建表语句自己是 IF NOT EXISTS，直接执行即可
            self.connection.execute(_TABLE_JOURNAL)
            for statement in _JOURNAL_INDEXES:
                self.connection.execute(statement)

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

    def _add_flow_columns_v6(self) -> None:
        """v5 -> v6：给 expenses 加 kind 与 account_id。

        老流水全部按 'expense' 处理（当时只有支出），account_id 为 NULL
        （当时没有联动），语义上正好。先查表结构，保证重复执行幂等。
        """
        conn = self.connection
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(expenses)")}
        if "kind" not in columns:
            conn.execute(
                "ALTER TABLE expenses ADD COLUMN kind TEXT NOT NULL DEFAULT 'expense'"
            )
        if "account_id" not in columns:
            # SQLite 的 ADD COLUMN 可以带 REFERENCES，默认值必须是 NULL
            conn.execute("ALTER TABLE expenses ADD COLUMN account_id INTEGER "
                         "REFERENCES accounts (id) ON DELETE SET NULL")

    def _rebuild_accounts_v6(self) -> None:
        """v5 -> v6：去掉 accounts.balance_cents 的 >= 0 约束。

        SQLite 改不了既有 CHECK，只能重建。此时 expenses 还没有 account_id
        列（它在下一步才加），所以不必担心外键指向被重命名的旧表。
        """
        conn = self.connection
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
        if not columns:
            return

        conn.execute("ALTER TABLE accounts RENAME TO accounts__v5")
        conn.execute(_TABLE_ACCOUNTS)
        conn.execute(
            "INSERT INTO accounts "
            "(id, name, kind, balance_cents, category, note, sort_order, "
            " created_at, updated_at) "
            "SELECT id, name, kind, balance_cents, category, note, sort_order, "
            "       created_at, updated_at FROM accounts__v5"
        )
        conn.execute("DROP TABLE accounts__v5")
        # 索引跟着旧表一起被删掉了，重建
        for statement in _ACCOUNT_INDEXES:
            conn.execute(statement)

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
