"""CatStudy 应用程序入口模块。

启动顺序：初始化本地 SQLite 数据库（``data/catstudy.db``，幂等）→
创建 QApplication → 显示桌宠窗口 → 进入事件循环；退出时关闭数据库连接。

第四阶段起多了两个细节：

1. ``quitOnLastWindowClosed`` 必须关掉。桌宠是 ``Qt.Tool`` 窗口，Qt 不把
   它算作"主窗口"，若不关，用户关掉学习记录窗口时整个应用会一起退出，
   表现为"关了个记录面板，猫也消失了"。
2. 学习记录窗口由 ``StudyWindowManager`` 统一创建与复用，入口是桌宠的
   ``studyRecordsRequested`` 信号（右键菜单 / 双击猫身各发一次）。
"""

from __future__ import annotations

import sys
from datetime import date

from PySide6.QtWidgets import QApplication

from core.accounts import AccountRepository
from core.database import init_database
from core.expenses import ExpenseRepository
from core.journal import JournalRepository
from core.study_records import StudyRecordRepository
from ui.main_window import StudyWindowManager
from ui.pet_window import PetWindow
from ui.theme import apply_theme

# 科目输入框的默认值：还没有任何记录时用它
FALLBACK_SUBJECT = "专注"


def configure_application(app: QApplication) -> None:
    """应用级设置。

    两件事都必须在这里做，而且要在任何窗口创建之前：

    1. 关掉 ``quitOnLastWindowClosed``——桌宠是 ``Qt.Tool``，Qt 不把它算作
       主窗口，不关掉会导致"关闭记录窗口时连猫一起退出"；
    2. 加载主题。``ui/theme.py`` 里那套暖色色板与 QSS 不会自动生效，
       漏了这一行界面就是 Qt 默认的白底灰边（曾经真实发生过：所有截图
       脚本都手动调了 apply_theme，所以开发时看不出来）。
    """
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)


def last_subject(repository: StudyRecordRepository) -> str:
    """最近一条记录用过的科目，作为下次计时输入框的默认值。"""
    recent = repository.list_recent(1)
    return recent[0].subject if recent else FALLBACK_SUBJECT


def save_focus_session(
    repository: StudyRecordRepository,
    manager: StudyWindowManager,
    mode: str,
    subject: str,
    seconds: int,
    study_date: date | None = None,
) -> int | None:
    """把一次专注计时落库，返回新记录 id；不足 1 分钟不写库（返回 None）。

    过滤不足 1 分钟的会话是为了避免"点错菜单立刻结束"留下一条 0 分钟记录，
    把日历塞满噪音。真正的时长由 ``core.timer`` 给出，这里只做取整与落库。
    """
    minutes = seconds // 60
    if minutes < 1:
        return None
    record_id = repository.add(
        study_date=study_date if study_date is not None else date.today(),
        subject=subject,
        duration_minutes=minutes,
        source=mode,
    )
    # 记录窗口可能正开着，立刻刷新，避免用户看到旧数据
    manager.refresh_if_open()
    return record_id


def main() -> int:
    """初始化数据库、显示宠物窗口、进入 Qt 事件循环，返回退出码。"""
    db = init_database()
    try:
        app = QApplication(sys.argv)
        configure_application(app)

        repository = StudyRecordRepository(db)
        manager = StudyWindowManager(
            repository,
            ExpenseRepository(db),
            AccountRepository(db),
            JournalRepository(db),
        )

        pet = PetWindow(default_subject=last_subject(repository))
        pet.studyRecordsRequested.connect(manager.open)
        pet.focusSessionFinished.connect(
            # 信号带的是 (模式, 科目, 秒数)，多出来的参数用 lambda 收敛掉
            lambda mode, subject, seconds: save_focus_session(
                repository, manager, mode, subject, seconds
            )
        )
        pet.show()

        return app.exec()
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
