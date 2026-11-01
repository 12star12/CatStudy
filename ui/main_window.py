"""主面板窗口（学习记录 / 日记 / 资产 / 流水）与它的生命周期管理器。

``MainWindow`` 只做三件事：建窗口、把各页装进 ``QStackedWidget``、维护顶部
页签的选中态。``StudyWindowManager`` 负责"全局只有一个面板窗口"：首次打开时
创建，之后无论点多少次菜单、双击多少次猫，都复用同一个实例。

页签不是写死的：传了哪个仓储就出现哪一页，因此 ``MainWindow(repo)`` 只有
学习记录，加上日记仓储才多出「日记」，再加账本/账户仓储才多出「流水」「资产」。
这样测试可以只测需要的那部分。

顺序上学习记录和日记挨着（都属于"我今天做了什么"），资产和流水挨着
（都属于"钱"），而不是按传入参数排列。

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

from core.accounts import AccountRepository
from core.expenses import ExpenseRepository
from core.journal import JournalRepository
from core.study_records import StudyRecordRepository
from ui.assets_view import AssetsView
from ui.expense_view import ExpenseView
from ui.journal_view import JournalView
from ui.study_view import StudyRecordView


class MainWindow(QMainWindow):
    """学习 / 资产 / 流水的主面板。"""

    def __init__(
        self,
        repository: StudyRecordRepository,
        parent: QWidget | None = None,
        expense_repository: ExpenseRepository | None = None,
        account_repository: AccountRepository | None = None,
        journal_repository: JournalRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("CatStudy")
        # 三栏布局（左页签 / 中列表 / 右卡片）比原来的两栏更吃宽度
        self.resize(960, 600)
        self.setMinimumSize(820, 520)

        self.view = StudyRecordView(repository, self)
        self.journal_view: JournalView | None = (
            JournalView(journal_repository, self, repository)
            if journal_repository is not None
            else None
        )
        self.assets_view: AssetsView | None = (
            AssetsView(account_repository, self)
            if account_repository is not None
            else None
        )
        self.expense_view: ExpenseView | None = (
            ExpenseView(expense_repository, self, account_repository)
            if expense_repository is not None
            else None
        )

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget(container)
        self.stack.addWidget(self.view)

        # 页签顺序：学习记录 → 日记 → 资产 → 流水。
        # 学习记录与日记相邻（都是"今天做了什么"），资产在流水前
        # （"现在有多少"比"这月花了什么"更常看）。
        self._tabs: list[tuple[QPushButton, QWidget]] = []
        self.study_tab = self._make_tab("学习记录", self.view)
        self.journal_tab: QPushButton | None = None
        self.assets_tab: QPushButton | None = None
        self.expense_tab: QPushButton | None = None

        if self.journal_view is not None:
            self.stack.addWidget(self.journal_view)
            self.journal_tab = self._make_tab("日记", self.journal_view)
        if self.assets_view is not None:
            self.stack.addWidget(self.assets_view)
            self.assets_tab = self._make_tab("资产", self.assets_view)
        if self.expense_view is not None:
            self.stack.addWidget(self.expense_view)
            self.expense_tab = self._make_tab("流水", self.expense_view)

        if self._tabs:
            layout.addLayout(self._build_switch())
            self._tabs[0][0].setChecked(True)

        layout.addWidget(self.stack, 1)
        self.setCentralWidget(container)

    # ---------- 页签 ----------

    def _make_tab(self, label: str, page: QWidget) -> QPushButton:
        """建一个页签按钮并登记，供 ``show_page`` 同步选中态。"""
        button = QPushButton(label, self)
        button.setObjectName("viewTab")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # 用 indexOf 而不是写死下标：页数随传入的仓储变化，写死会错位
        button.clicked.connect(
            lambda _checked=False, widget=page: self.show_page(
                self.stack.indexOf(widget)
            )
        )
        self._tabs.append((button, page))
        return button

    def _build_switch(self) -> QHBoxLayout:
        """顶部的页签行。

        做成一组互斥胶囊按钮而不是 ``QTabWidget``：自带标签页的边框与圆角
        和笔记本风不搭，样式改不动。
        """
        row = QHBoxLayout()
        row.setContentsMargins(18, 12, 18, 0)
        row.setSpacing(8)
        for button, _page in self._tabs:
            row.addWidget(button)
        row.addStretch(1)
        return row

    def show_page(self, index: int) -> None:
        """切换页面并同步按钮的选中态；越界请求直接忽略。"""
        if not 0 <= index < self.stack.count():
            return
        self.stack.setCurrentIndex(index)
        current = self.stack.currentWidget()
        for button, page in self._tabs:
            button.setChecked(page is current)

    def current_page(self) -> QWidget:
        return self.stack.currentWidget()

    # ---------- 刷新 ----------

    def refresh(self) -> None:
        """重新加载所有页；窗口再次显示、或有数据写入时调用。"""
        self.view.refresh()
        if self.journal_view is not None:
            self.journal_view.refresh()
        if self.assets_view is not None:
            self.assets_view.refresh()
        if self.expense_view is not None:
            self.expense_view.refresh()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        # 隐藏期间可能有别的地方改了数据（番茄钟落库、改了余额），
        # 每次显示都重载一次，避免展示过期内容
        super().showEvent(event)
        self.refresh()


class StudyWindowManager:
    """面板窗口的创建与复用，保证应用内只有一个实例。"""

    def __init__(
        self,
        repository: StudyRecordRepository,
        expense_repository: ExpenseRepository | None = None,
        account_repository: AccountRepository | None = None,
        journal_repository: JournalRepository | None = None,
    ) -> None:
        self._repository = repository
        self._expenses = expense_repository
        self._accounts = account_repository
        self._journal = journal_repository
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
        """显示面板；已存在则复用并置前，不重复创建。

        窗口关闭只是隐藏（Qt 默认不销毁），所以再次打开拿到的是同一个
        对象，``showEvent`` 会触发一次刷新，数据不会停留在旧状态。
        """
        if self._window is None:
            self._window = MainWindow(
                self._repository,
                expense_repository=self._expenses,
                account_repository=self._accounts,
                journal_repository=self._journal,
            )
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window
