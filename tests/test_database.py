"""本地 SQLite 数据库基础设施测试。

覆盖：初始化与幂等、表结构、索引、增删改查、日期筛选、
参数化 SQL 安全性、UI 与 SQL 分离、Git 忽略规则。

运行：
    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import database as db_mod  # noqa: E402
from core.database import (  # noqa: E402
    DB_PATH,
    SCHEMA_VERSION,
    DatabaseManager,
    init_database,
)
from core.study_records import (  # noqa: E402
    StudyRecord,
    StudyRecordRepository,
    normalize_date,
)

EXPECTED_COLUMNS = [
    ("id", "INTEGER", 0, 1),                     # name, type, notnull, pk
    ("study_date", "TEXT", 1, 0),
    ("subject", "TEXT", 1, 0),
    ("duration_minutes", "INTEGER", 0, 0),
    ("content", "TEXT", 1, 0),
    ("source", "TEXT", 0, 0),                    # v3 新增：记录来源，可为空
    ("created_at", "TEXT", 1, 0),
    ("updated_at", "TEXT", 1, 0),
]


class TempDBTestCase(unittest.TestCase):
    """每个用例一个临时数据库，互不干扰。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.db_path = self.tmpdir / "sub" / "catstudy.db"   # 故意多一层目录
        self.db = init_database(self.db_path)
        self.repo = StudyRecordRepository(self.db)

    def tearDown(self) -> None:
        self.db.close()
        self._tmp.cleanup()


# --------------------------------------------------------------------------
# 初始化与 schema
# --------------------------------------------------------------------------


class InitializationTest(TempDBTestCase):
    def test_creates_parent_dir_and_file(self) -> None:
        self.assertTrue(self.db_path.exists(), "数据库文件未创建")
        self.assertTrue(self.db_path.parent.is_dir(), "data 上级目录未自动创建")

    def test_tables_created(self) -> None:
        self.assertTrue(self.db.table_exists("study_records"))
        self.assertTrue(self.db.table_exists("app_meta"))

    def test_indexes_created(self) -> None:
        self.assertTrue(self.db.index_exists("idx_study_records_study_date"))
        self.assertTrue(self.db.index_exists("idx_study_records_subject"))

    def test_schema_version_recorded(self) -> None:
        self.assertEqual(self.db.schema_version(), SCHEMA_VERSION)

    def test_columns_match_spec(self) -> None:
        rows = self.db.connection.execute(
            "PRAGMA table_info(study_records)"
        ).fetchall()
        actual = [(r["name"], r["type"], r["notnull"], r["pk"]) for r in rows]
        self.assertEqual(actual, EXPECTED_COLUMNS)

    def test_table_sql_constraints(self) -> None:
        sql = self.db.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='study_records'"
        ).fetchone()["sql"]
        self.assertIn("AUTOINCREMENT", sql.upper())
        self.assertIn("CHECK", sql.upper())
        # 日期字段上不允许唯一约束，否则同一天只能有一条记录
        self.assertNotIn("UNIQUE", sql.upper())

    def test_actual_date_check_sql(self) -> None:
        """实际 DDL 必须用 date() 回环校验，而不是只靠 GLOB 格式匹配。

        GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' 只能确保"10 个字符
        且形如 2026-02-30"，对不存在的日期无能为力。
        """
        sql = self.db.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='study_records'"
        ).fetchone()["sql"]
        normalized = " ".join(sql.split())
        self.assertIn("CHECK (study_date IS date(study_date))", normalized)
        self.assertNotIn("GLOB", normalized.upper())

    def test_date_index_used_by_query(self) -> None:
        plan = self.db.connection.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM study_records WHERE study_date = '2026-01-01'"
        ).fetchall()
        text = " ".join(str(r["detail"]) for r in plan)
        self.assertIn("idx_study_records_study_date", text)

    def test_connect_is_idempotent(self) -> None:
        conn_first = self.db.connection
        self.db.connect()
        self.assertIs(self.db.connect(), conn_first)

    def test_reconnect_preserves_data(self) -> None:
        record_id = self.repo.add("2026-03-01", "数学", "第一章")
        self.db.close()

        again = init_database(self.db_path)     # 模拟应用重启
        try:
            repo = StudyRecordRepository(again)
            self.assertEqual(repo.count(), 1)
            self.assertIsNotNone(repo.get(record_id))
            self.assertEqual(again.schema_version(), SCHEMA_VERSION)
        finally:
            again.close()

    def test_ensure_schema_does_not_wipe(self) -> None:
        self.repo.add("2026-03-02", "英语", "听力")
        self.db.ensure_schema()                 # 重复执行
        self.db.ensure_schema()
        self.assertEqual(self.repo.count(), 1)

    def test_default_path_is_relative_to_project(self) -> None:
        self.assertEqual(DB_PATH, PROJECT_ROOT / "data" / "catstudy.db")
        self.assertNotIn("C:", str(DB_PATH))
        self.assertTrue(str(DB_PATH).startswith(str(PROJECT_ROOT)))

    def test_unconnected_manager_raises(self) -> None:
        manager = DatabaseManager(self.tmpdir / "x.db")
        with self.assertRaises(RuntimeError):
            _ = manager.connection


# --------------------------------------------------------------------------
# 新增与查询
# --------------------------------------------------------------------------


class CreateQueryTest(TempDBTestCase):
    def test_add_returns_id(self) -> None:
        record_id = self.repo.add("2026-03-05", "数学", "函数", 45)
        self.assertIsInstance(record_id, int)
        self.assertGreater(record_id, 0)

    def test_get_roundtrip(self) -> None:
        record_id = self.repo.add("2026-03-05", "数学", "函数与导数", 45)
        rec = self.repo.get(record_id)
        self.assertIsInstance(rec, StudyRecord)
        self.assertEqual(rec.id, record_id)
        self.assertEqual(rec.study_date, "2026-03-05")
        self.assertEqual(rec.subject, "数学")
        self.assertEqual(rec.duration_minutes, 45)
        self.assertEqual(rec.content, "函数与导数")
        self.assertRegex(rec.created_at, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(rec.created_at, rec.updated_at)

    def test_multiple_records_same_day(self) -> None:
        for i in range(3):
            self.repo.add("2026-03-05", f"科目{i}", f"内容{i}")
        self.assertEqual(self.repo.count("2026-03-05"), 3)
        self.assertEqual(len(self.repo.list_by_date("2026-03-05")), 3)

    def test_duration_optional(self) -> None:
        record_id = self.repo.add("2026-03-06", "阅读", "只记内容")
        self.assertIsNone(self.repo.get(record_id).duration_minutes)

    def test_content_defaults_to_empty(self) -> None:
        record_id = self.repo.add("2026-03-06", "阅读")
        self.assertEqual(self.repo.get(record_id).content, "")

    def test_accepts_date_and_datetime(self) -> None:
        a = self.repo.add(date(2026, 3, 7), "A")
        b = self.repo.add(datetime(2026, 3, 7, 20, 0), "B")
        self.assertEqual(self.repo.get(a).study_date, "2026-03-07")
        self.assertEqual(self.repo.get(b).study_date, "2026-03-07")

    def test_list_by_date_only_returns_that_day(self) -> None:
        self.repo.add("2026-03-07", "当日")
        self.repo.add("2026-03-08", "次日")
        records = self.repo.list_by_date("2026-03-07")
        self.assertEqual([r.subject for r in records], ["当日"])

    def test_list_by_date_range_inclusive(self) -> None:
        for d in ("2026-03-01", "2026-03-03", "2026-03-05"):
            self.repo.add(d, d)
        records = self.repo.list_by_date_range("2026-03-01", "2026-03-03")
        self.assertEqual([r.study_date for r in records], ["2026-03-01", "2026-03-03"])

    def test_list_recent_order_and_limit(self) -> None:
        base = date(2026, 4, 1)
        for i in range(5):
            self.repo.add(base + timedelta(days=i), f"S{i}")
        recent = self.repo.list_recent(3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[0].study_date, "2026-04-05")

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(self.repo.get(999999))

    def test_count_total_and_by_date(self) -> None:
        self.repo.add("2026-03-09", "A")
        self.repo.add("2026-03-09", "B")
        self.repo.add("2026-03-10", "C")
        self.assertEqual(self.repo.count(), 3)
        self.assertEqual(self.repo.count("2026-03-09"), 2)


# --------------------------------------------------------------------------
# 修改与删除
# --------------------------------------------------------------------------


class UpdateDeleteTest(TempDBTestCase):
    def test_update_single_field(self) -> None:
        rid = self.repo.add("2026-03-11", "数学", "旧内容", 30)
        before = self.repo.get(rid)
        self.assertTrue(self.repo.update(rid, content="新内容"))
        after = self.repo.get(rid)
        self.assertEqual(after.content, "新内容")
        self.assertEqual(after.subject, "数学")           # 未传字段不变
        self.assertEqual(after.duration_minutes, 30)
        self.assertEqual(after.created_at, before.created_at)

    def test_update_refreshes_updated_at(self) -> None:
        rid = self.repo.add("2026-03-11", "数学")
        before = self.repo.get(rid)
        self.repo.update(rid, subject="物理")
        after = self.repo.get(rid)
        self.assertGreaterEqual(after.updated_at, before.updated_at)
        self.assertEqual(after.subject, "物理")

    def test_update_multiple_fields(self) -> None:
        rid = self.repo.add("2026-03-12", "数学", "内容", 10)
        self.assertTrue(
            self.repo.update(rid, study_date="2026-03-13", subject="化学", duration_minutes=90)
        )
        rec = self.repo.get(rid)
        self.assertEqual(
            (rec.study_date, rec.subject, rec.duration_minutes),
            ("2026-03-13", "化学", 90),
        )

    def test_update_duration_to_null(self) -> None:
        rid = self.repo.add("2026-03-12", "数学", "内容", 10)
        self.assertTrue(self.repo.update(rid, duration_minutes=None))
        self.assertIsNone(self.repo.get(rid).duration_minutes)

    def test_update_missing_returns_false(self) -> None:
        self.assertFalse(self.repo.update(999999, content="x"))

    def test_delete(self) -> None:
        rid = self.repo.add("2026-03-14", "历史")
        self.assertTrue(self.repo.delete(rid))
        self.assertIsNone(self.repo.get(rid))
        self.assertFalse(self.repo.delete(rid))


# --------------------------------------------------------------------------
# 参数化 SQL 与输入校验
# --------------------------------------------------------------------------


class SafetyAndValidationTest(TempDBTestCase):
    def test_sql_injection_in_subject_is_stored_literally(self) -> None:
        evil = "'; DROP TABLE study_records; --"
        rid = self.repo.add("2026-03-15", evil, "x")
        self.assertEqual(self.repo.get(rid).subject, evil)
        # 表必须还在
        self.assertTrue(self.db.table_exists("study_records"))
        self.assertEqual(self.repo.count(), 1)

    def test_quotes_in_content(self) -> None:
        text = "他说：“O'Reilly 的 《书》 里的 \\ 反斜杠”"
        rid = self.repo.add("2026-03-15", "阅读", text)
        self.assertEqual(self.repo.get(rid).content, text)

    def test_invalid_date_rejected(self) -> None:
        for bad in ("2026/03/15", "26-03-15", "2026-13-01", "not-a-date", ""):
            with self.assertRaises(ValueError, msg=f"应拒绝 {bad!r}"):
                self.repo.add(bad, "数学")

    def test_empty_subject_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.add("2026-03-15", "   ")

    def test_negative_duration_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.repo.add("2026-03-15", "数学", "", -5)

    def test_non_integer_duration_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.repo.add("2026-03-15", "数学", "", 12.5)

    def test_normalize_date_helper(self) -> None:
        self.assertEqual(normalize_date("2026-3-5"), "2026-03-05")
        self.assertEqual(normalize_date(date(2026, 3, 5)), "2026-03-05")
        self.assertEqual(normalize_date(datetime(2026, 3, 5, 23, 1)), "2026-03-05")

    def test_db_level_check_blocks_bad_format(self) -> None:
        """绕过仓储层直接写库时，DDL 的 CHECK 仍应拦住非法格式。"""
        for bad in ("2026/01/01", "2026-3-5", "20260305", "2026-03-05 10:00:00"):
            with self.assertRaises(sqlite3.IntegrityError, msg=f"应拒绝 {bad!r}"):
                self.db.connection.execute(
                    "INSERT INTO study_records (study_date, subject) VALUES (?, ?)",
                    (bad, "数学"),
                )

    def test_db_level_check_blocks_impossible_dates(self) -> None:
        """格式合法但日历上不存在的日期，必须被数据库层拒绝。"""
        for bad in (
            "2026-02-30",   # 2 月没有 30 号
            "2026-13-01",   # 没有 13 月
            "2026-00-10",   # 没有 0 月
            "2026-04-31",   # 4 月只有 30 天
            "2026-12-32",   # 没有 32 号
            "2026-02-29",   # 2026 不是闰年
        ):
            with self.assertRaises(sqlite3.IntegrityError, msg=f"应拒绝 {bad!r}"):
                self.db.connection.execute(
                    "INSERT INTO study_records (study_date, subject) VALUES (?, ?)",
                    (bad, "数学"),
                )
        self.assertEqual(self.repo.count(), 0)

    def test_db_level_accepts_real_dates(self) -> None:
        """真实存在的日期（含闰日）必须能通过数据库层约束。"""
        for good in ("2024-02-29", "2026-03-05", "1999-12-31", "2100-01-01"):
            self.db.connection.execute(
                "INSERT INTO study_records (study_date, subject) VALUES (?, ?)",
                (good, "数学"),
            )
        self.db.connection.commit()
        stored = [
            r["study_date"]
            for r in self.db.connection.execute(
                "SELECT study_date FROM study_records ORDER BY study_date"
            )
        ]
        self.assertEqual(
            stored, ["1999-12-31", "2024-02-29", "2026-03-05", "2100-01-01"]
        )

    def test_python_and_sqlite_agree(self) -> None:
        """Python 层与 SQLite 层对同一批输入的接受/拒绝结论必须一致。"""
        cases = [
            # (输入, Python 是否接受, 归一化结果或 None)
            ("2026-03-05", True, "2026-03-05"),
            ("2026-3-5", True, "2026-03-05"),        # Python 补零，DB 收归一化值
            ("2024-02-29", True, "2024-02-29"),
            ("2026-02-28", True, "2026-02-28"),
            ("2026-02-29", False, None),
            ("2026-02-30", False, None),
            ("2026-13-01", False, None),
            ("2026-00-10", False, None),
            ("2026-04-31", False, None),
            ("2026/03/05", False, None),
            ("26-03-05", False, None),
            ("not-a-date", False, None),
            ("", False, None),
        ]
        for raw, should_accept, expected in cases:
            with self.subTest(raw=raw):
                if should_accept:
                    self.assertEqual(normalize_date(raw), expected)
                    rid = self.repo.add(raw, "一致性")
                    self.assertEqual(self.repo.get(rid).study_date, expected)
                else:
                    with self.assertRaises(ValueError):
                        normalize_date(raw)
                    with self.assertRaises(ValueError):
                        self.repo.add(raw, "一致性")

    def test_leap_year_both_layers(self) -> None:
        rid = self.repo.add("2024-02-29", "闰年")
        self.assertEqual(self.repo.get(rid).study_date, "2024-02-29")
        with self.assertRaises(ValueError):
            self.repo.add("2026-02-29", "非闰年")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute(
                "INSERT INTO study_records (study_date, subject) VALUES (?, ?)",
                ("2026-02-29", "非闰年"),
            )


# --------------------------------------------------------------------------
# schema 迁移：v1（仅格式校验）-> v2（真实日历校验）
# --------------------------------------------------------------------------

# v1 的实际 DDL：study_date 只做 GLOB 格式匹配
OLD_V1_DDL = """
CREATE TABLE IF NOT EXISTS study_records (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    study_date       TEXT    NOT NULL
                     CHECK (study_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    subject          TEXT    NOT NULL,
    duration_minutes INTEGER CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
    content          TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""


def build_v1_database(path: Path, rows: list[tuple[str, str]] | None = None) -> None:
    """手工构造一个 v1 版数据库，用于验证迁移逻辑。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(OLD_V1_DDL)
        conn.execute(
            "CREATE INDEX idx_study_records_study_date ON study_records (study_date)"
        )
        conn.execute(
            "CREATE INDEX idx_study_records_subject ON study_records (subject)"
        )
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES ('schema_version', '1')"
        )
        for study_date, subject in rows or []:
            conn.execute(
                "INSERT INTO study_records (study_date, subject) VALUES (?, ?)",
                (study_date, subject),
            )
        conn.commit()
    finally:
        conn.close()


class MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.db_path = self.tmpdir / "catstudy.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_v1_is_migrated_and_data_preserved(self) -> None:
        build_v1_database(
            self.db_path,
            [("2026-03-01", "数学"), ("2026-03-01", "英语")],
        )
        db = init_database(self.db_path)
        try:
            self.assertEqual(db.schema_version(), SCHEMA_VERSION)
            repo = StudyRecordRepository(db)
            self.assertEqual(repo.count(), 2)
            self.assertEqual(
                sorted(r.subject for r in repo.list_by_date("2026-03-01")),
                ["数学", "英语"],
            )
            # 迁移后索引仍在
            self.assertTrue(db.index_exists("idx_study_records_study_date"))
            self.assertTrue(db.index_exists("idx_study_records_subject"))
            # 旧表已被清理
            self.assertFalse(db.table_exists("study_records__v1"))
        finally:
            db.close()

    def test_migrated_table_rejects_impossible_dates(self) -> None:
        build_v1_database(self.db_path, [("2026-03-01", "数学")])
        db = init_database(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                db.connection.execute(
                    "INSERT INTO study_records (study_date, subject) VALUES (?, ?)",
                    ("2026-02-30", "数学"),
                )
        finally:
            db.close()

    def test_migration_is_idempotent(self) -> None:
        build_v1_database(self.db_path, [("2026-03-02", "物理")])
        for _ in range(3):
            db = init_database(self.db_path)
            try:
                self.assertEqual(db.schema_version(), SCHEMA_VERSION)
                self.assertEqual(StudyRecordRepository(db).count(), 1)
            finally:
                db.close()

    def test_migration_aborts_when_old_rows_are_invalid(self) -> None:
        """旧库里若存在非法日期，迁移必须中止并给出可读错误，而不是悄悄丢数据。"""
        build_v1_database(self.db_path, [("2026-02-30", "脏数据")])
        manager = DatabaseManager(self.db_path)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                manager.connect()
            self.assertIn("迁移中止", str(ctx.exception))
        finally:
            manager.close()
        # 中止后旧数据仍在，未被破坏
        conn = sqlite3.connect(str(self.db_path))
        try:
            n = conn.execute("SELECT COUNT(*) FROM study_records").fetchone()[0]
            self.assertEqual(n, 1)
        finally:
            conn.close()


# --------------------------------------------------------------------------
# 架构约束：SQL 不得进 UI
# --------------------------------------------------------------------------


class ArchitectureTest(unittest.TestCase):
    SQL_PATTERN = re.compile(
        r"\b(SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE)\b",
        re.IGNORECASE,
    )

    def test_ui_has_no_sql_or_sqlite(self) -> None:
        offenders = []
        for path in (PROJECT_ROOT / "ui").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "sqlite3" in text:
                offenders.append(f"{path.name}: import sqlite3")
            if self.SQL_PATTERN.search(text):
                offenders.append(f"{path.name}: 含 SQL 语句")
        self.assertEqual(offenders, [], f"UI 层不应出现数据库细节: {offenders}")

    def test_study_records_module_uses_placeholders(self) -> None:
        text = (PROJECT_ROOT / "core" / "study_records.py").read_text(encoding="utf-8")
        self.assertIn("?", text, "应使用参数化占位符")
        # 不应出现 f-string 直接拼接值的 UPDATE ... SET '...'
        self.assertNotRegex(text, r"execute\(\s*f?\"[^\"]*'\{")


class GitIgnoreTest(unittest.TestCase):
    def test_gitignore_covers_database_files(self) -> None:
        text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in ("*.db", "*.db-wal", "*.db-shm", "*.db-journal"):
            self.assertIn(pattern, text, f".gitignore 缺少 {pattern}")

    def test_schema_code_is_not_ignored(self) -> None:
        text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("core/", text)
        self.assertNotIn("database.py", text)
        self.assertNotIn("study_records.py", text)


class StartupWiringTest(unittest.TestCase):
    def test_main_initializes_database_on_start(self) -> None:
        """main.py 必须在启动时调用 init_database。"""
        import main as entry

        self.assertIs(entry.init_database, db_mod.init_database)
        source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("init_database()", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
