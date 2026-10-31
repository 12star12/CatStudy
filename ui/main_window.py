"""学习记录窗口（主面板）与它的生命周期管理器。

``MainWindow`` 只做三件事：建窗口、装 ``StudyRecordView``、保存基本窗口属性。
``StudyWindowManager`` 负责"全局只有一个记录窗口"：首次打开时创建，
之后无论点了多少次菜单或双击了多少次猫，都复用同一个实例。

窗口生命周期由调用方（``main.py``）决定：关闭本窗口不退出应用，
桌宠窗口继续存在，这也是 ``app.setQuitOnLastWindowClosed(False)``
必须设置的原因——桌宠是 ``Qt.Tool`` 窗口，Qt 不把它算作主窗口。
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QWidget

from core.study_records import StudyRecordRepository
from ui.study_view import StudyRecordView


class MainWindow(QMainWindow):
    """学习记录管理窗口。"""

    def __init__(
        self,
        repository: StudyRecordRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CatStudy · 学习记录")
        # 三栏布局（科目标签 / 记录列表 / 日历卡片）比原来的两栏更吃宽度
        self.resize(960, 600)
        self.setMinimumSize(820, 520)

        self.view = StudyRecordView(repository, self)
        self.setCentralWidget(self.view)

    def refresh(self) -> None:
        """重新加载数据；窗口再次显示时调用，保证看到的是最新内容。"""
        self.view.refresh()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        # 隐藏期间可能有别的地方改了数据（例如将来的计时器），
        # 每次显示都重载一次，避免展示过期内容
        super().showEvent(event)
        self.view.refresh()


class StudyWindowManager:
    """学习记录窗口的创建与复用，保证应用内只有一个实例。"""

    def __init__(self, repository: StudyRecordRepository) -> None:
        self._repository = repository
        self._window: MainWindow | None = None

    @property
    def window(self) -> MainWindow | None:
        """已创建的窗口；尚未打开过时为 None。"""
        return self._window

    def refresh_if_open(self) -> None:
        """窗口已打开时刷新；没打开就什么都不做（下次打开自然会加载）。"""
        if self._window is not None and self._window.isVisible():
            self._window.refresh()

    def open(self) -> MainWindow:
        """显示记录窗口；已存在则复用并置前，不重复创建。

        窗口关闭只是隐藏（Qt 默认不销毁），所以再次打开拿到的是同一个
        对象，``showEvent`` 会触发一次刷新，数据不会停留在旧状态。
        """
        if self._window is None:
            self._window = MainWindow(self._repository)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window
