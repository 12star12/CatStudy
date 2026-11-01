"""学习记录窗口（主面板）与它的生命周期管理器。

``MainWindow`` 只做三件事：建窗口、装 ``StudyRecordView``、保存基本窗口属性。
``StudyWindowManager`` 负责"全局只有一个记录窗口"：首次打开时创建，
之后无论点了多少次菜单或双击了多少次猫，都复用同一个实例。

窗口生命周期由调用方（``main.py``）决定：关闭本窗口不退出应用，
桌宠窗口继续存在，这也是 ``app.setQuitOnLastWindowClosed(False)``
必须设置的原因——桌宠是 ``Qt.Tool`` 窗口，Qt 不把它算作主窗口。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.expenses import ExpenseRepository
from core.study_records import StudyRecordRepository
from ui.expense_view import ExpenseView
from ui.study_view import StudyRecordView


class MainWindow(QMainWindow):
    """学习记录管理窗口。"""

    def __init__(
        self,
        repository: StudyRecordRepository,
        parent: QWidget | None = None,
        expense_repository: ExpenseRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CatStudy · 学习记录")
        # 三栏布局（科目标签 / 记录列表 / 日历卡片）比原来的两栏更吃宽度
        self.resize(960, 600)
        self.setMinimumSize(820, 520)

        self.view = StudyRecordView(repository, self)
        self.expense_view: ExpenseView | None = (
            ExpenseView(expense_repository, self)
            if expense_repository is not None
            else None
        )

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget(container)
        self.stack.addWidget(self.view)
        if self.expense_view is not None:
            layout.addLayout(self._build_switch())
            self.stack.addWidget(self.expense_view)

        layout.addWidget(self.stack, 1)
        self.setCentralWidget(container)

    def _build_switch(self) -> QHBoxLayout:
        """顶部的「学习记录 / 账本」切换。

        做成两个互斥的胶囊按钮而不是 QTabWidget：自带标签页的边框与圆角
        和笔记本风不搭，样式改不动。
        """
        self.study_tab = QPushButton("学习记录", self)
        self.expense_tab = QPushButton("账本", self)
        for tab in (self.study_tab, self.expense_tab):
            tab.setObjectName("viewTab")
            tab.setCheckable(True)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)

        self.study_tab.setChecked(True)
        self.study_tab.clicked.connect(lambda: self.show_page(0))
        self.expense_tab.clicked.connect(lambda: self.show_page(1))

        row = QHBoxLayout()
        row.setContentsMargins(18, 12, 18, 0)
        row.setSpacing(8)
        row.addWidget(self.study_tab)
        row.addWidget(self.expense_tab)
        row.addStretch(1)
        return row

    def show_page(self, index: int) -> None:
        """切换页面并同步按钮的选中态。"""
        if index >= self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        self.study_tab.setChecked(index == 0)
        if self.expense_view is not None:
            self.expense_tab.setChecked(index == 1)

    def refresh(self) -> None:
        """重新加载数据；窗口再次显示时调用，保证看到的是最新内容。"""
        self.view.refresh()
        if self.expense_view is not None:
            self.expense_view.refresh()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        # 隐藏期间可能有别的地方改了数据（例如将来的计时器），
        # 每次显示都重载一次，避免展示过期内容
        super().showEvent(event)
        self.view.refresh()


class StudyWindowManager:
    """学习记录窗口的创建与复用，保证应用内只有一个实例。"""

    def __init__(
        self,
        repository: StudyRecordRepository,
        expense_repository: ExpenseRepository | None = None,
    ) -> None:
        self._repository = repository
        self._expenses = expense_repository
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
            self._window = MainWindow(self._repository, expense_repository=self._expenses)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window
