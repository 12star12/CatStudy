"""数据库访问模块（第一阶段占位）。

后续职责：
- 管理 SQLite 数据库连接，数据库文件位于 data/ 目录；
  该目录下的 *.db 文件已在 .gitignore 中忽略，不会被上传到 GitHub；
- 首次运行时创建表结构（宠物状态、专注记录、成长数据等）；
- 为计时与成长模块提供统一的读写接口。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# 本文件位于 core/ 目录下，因此项目根目录是其上一级
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
DB_PATH: Path = DATA_DIR / "catstudy.db"


class DatabaseManager:
    """SQLite 数据库管理器，当前仅为骨架，不建立真实连接。"""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path: Path = db_path
        self._connection: sqlite3.Connection | None = None

    def connect(self) -> None:
        """确保 data/ 目录存在，建立连接并初始化表结构。"""
        # TODO: DATA_DIR.mkdir(exist_ok=True)
        # TODO: sqlite3.connect(self.db_path) 并执行 CREATE TABLE 语句
        raise NotImplementedError("数据库连接将在后续阶段实现")

    def close(self) -> None:
        """安全关闭数据库连接。"""
        # TODO: 若连接存在则提交并关闭
        if self._connection is not None:
            self._connection.close()
            self._connection = None
