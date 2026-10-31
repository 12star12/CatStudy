"""CatStudy 应用程序入口模块。

第三阶段：启动时先初始化本地 SQLite 数据库（data/catstudy.db），
确保库文件与表结构就绪（幂等，已存在则不做改动）；随后创建
QApplication 并显示桌面宠物窗口 PetWindow，退出时关闭数据库连接。
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from core.database import init_database
from ui.pet_window import PetWindow


def main() -> int:
    """初始化数据库、显示宠物窗口、进入 Qt 事件循环，返回退出码。"""
    db = init_database()
    try:
        app = QApplication(sys.argv)
        pet = PetWindow()
        pet.show()
        return app.exec()
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
