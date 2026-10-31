"""第 4 步：桌宠入口与应用接线测试。

覆盖三件事：
1. 桌宠的两个入口（右键菜单、双击）都能发出打开请求；
2. 双击不影响原有的拖拽行为；
3. 记录窗口全程只有一个实例，关掉再开能刷新到最新数据。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from core.database import DatabaseManager
from core.study_records import StudyRecordRepository
from main import configure_application
from ui.main_window import MainWindow, StudyWindowManager
from ui.pet_window import PetWindow

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


def _mouse_event(kind: QEvent.Type, global_xy: tuple[float, float] = (100.0, 100.0),
                 buttons: Qt.MouseButton = Qt.MouseButton.LeftButton) -> QMouseEvent:
    """构造鼠标事件：本地坐标与全局坐标用同一组值即可。"""
    point = QPointF(*global_xy)
    return QMouseEvent(
        kind, point, point,
        Qt.MouseButton.LeftButton, buttons,
        Qt.KeyboardModifier.NoModifier,
    )


class PetWindowEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pet = PetWindow()
        self.addCleanup(self.pet.deleteLater)
        self.requests: list[int] = []
        self.pet.studyRecordsRequested.connect(lambda: self.requests.append(1))

    def test_menu_has_study_and_quit_actions(self) -> None:
        texts = [a.text() for a in self.pet._menu.actions() if not a.isSeparator()]
        # 第一项是「专注」子菜单（番茄钟/正计时），其余保持原有入口
        self.assertEqual(texts, ["专注", "学习记录…", "退出程序"])

    def test_menu_action_emits_request(self) -> None:
        self.pet.study_action.trigger()
        self.assertEqual(len(self.requests), 1)

    def test_double_click_emits_request(self) -> None:
        self.pet.mouseDoubleClickEvent(
            _mouse_event(QEvent.Type.MouseButtonDblClick)
        )
        self.assertEqual(len(self.requests), 1)

    def test_two_presses_without_release_do_not_open(self) -> None:
        """同一次物理按下被派发两次时，不能误判成双击。

        实测拖拽开始时窗口会连收两次 press，若不去重，一拖动就会弹出记录窗口。
        """
        event = _mouse_event(QEvent.Type.MouseButtonPress)
        self.pet.mousePressEvent(event)
        self.pet.mousePressEvent(event)
        self.assertEqual(self.requests, [])

    def test_press_release_press_opens(self) -> None:
        press = _mouse_event(QEvent.Type.MouseButtonPress)
        release = _mouse_event(QEvent.Type.MouseButtonRelease, buttons=Qt.MouseButton.NoButton)
        self.pet.mousePressEvent(press)
        self.pet.mouseReleaseEvent(release)
        self.pet.mousePressEvent(press)
        self.assertEqual(len(self.requests), 1)

    def test_right_click_does_not_emit_request(self) -> None:
        event = QMouseEvent(
            QEvent.Type.MouseButtonDblClick, QPointF(10, 10), QPointF(10, 10),
            Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.pet.mouseDoubleClickEvent(event)
        self.assertEqual(self.requests, [], "右键双击不应打开记录窗口")


class DragStillWorksTest(unittest.TestCase):
    """双击入口不能破坏原有拖拽行为。"""

    def setUp(self) -> None:
        self.pet = PetWindow()
        self.addCleanup(self.pet.deleteLater)
        self.pet.move(300, 300)

    def test_drag_moves_window(self) -> None:
        start = self.pet.pos()
        self.pet.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, (320.0, 330.0)))
        self.assertIsNotNone(self.pet._drag_offset)

        self.pet.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (400.0, 370.0)))
        moved = self.pet.pos() - start
        self.assertEqual((moved.x(), moved.y()), (80, 40))

        self.pet.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, (400.0, 370.0)))
        self.assertIsNone(self.pet._drag_offset)

    def test_double_click_does_not_move_window(self) -> None:
        start = self.pet.pos()
        # Qt 的双击序列：press → release → dblClick → release
        self.pet.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, (320.0, 330.0)))
        self.pet.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, (320.0, 330.0)))
        self.pet.mouseDoubleClickEvent(_mouse_event(QEvent.Type.MouseButtonDblClick, (320.0, 330.0)))
        self.pet.mouseReleaseEvent(_mouse_event(QEvent.Type.MouseButtonRelease, (320.0, 330.0)))

        self.assertEqual(self.pet.pos(), start, "没移动鼠标时双击不应移动窗口")
        self.assertIsNone(self.pet._drag_offset, "双击后不应残留拖拽状态")


class _RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = StudyRecordRepository(self.db)


class StudyWindowManagerTest(_RepoCase):
    def test_returns_same_instance(self) -> None:
        manager = StudyWindowManager(self.repo)
        first = manager.open()
        self.addCleanup(first.deleteLater)
        second = manager.open()
        self.assertIs(first, second)
        self.assertIs(manager.window, first)

    def test_single_window_count(self) -> None:
        def existing() -> int:
            return sum(1 for w in QApplication.topLevelWidgets() if isinstance(w, MainWindow))

        manager = StudyWindowManager(self.repo)
        before = existing()

        windows = [manager.open() for _ in range(3)]
        self.addCleanup(windows[0].deleteLater)

        self.assertEqual(windows[0], windows[1])
        self.assertEqual(windows[1], windows[2])
        # 用增量而不是绝对数量：同进程内其它用例也创建过 MainWindow
        self.assertEqual(existing() - before, 1, "重复打开不应创建多个记录窗口")

    def test_reopen_after_close_refreshes_data(self) -> None:
        manager = StudyWindowManager(self.repo)
        window = manager.open()
        self.addCleanup(window.deleteLater)
        QApplication.processEvents()
        self.assertEqual(window.view.table.rowCount(), 0)

        window.close()
        QApplication.processEvents()
        self.assertFalse(window.isVisible())

        # 窗口关着的时候新增数据，重新打开应该看得到
        self.repo.add(date.today().isoformat(), "数学", duration_minutes=30)

        again = manager.open()
        QApplication.processEvents()
        self.assertIs(again, window)
        self.assertTrue(window.isVisible())
        self.assertEqual(window.view.table.rowCount(), 1)

    def test_created_lazily(self) -> None:
        manager = StudyWindowManager(self.repo)
        self.assertIsNone(manager.window, "未点击入口前不应创建窗口")


class ApplicationConfigTest(unittest.TestCase):
    def test_quit_on_last_window_closed_disabled(self) -> None:
        app = QApplication.instance() or QApplication([])
        original = app.quitOnLastWindowClosed()
        self.addCleanup(app.setQuitOnLastWindowClosed, original)

        app.setQuitOnLastWindowClosed(True)
        configure_application(app)
        self.assertFalse(
            app.quitOnLastWindowClosed(),
            "必须关掉，否则关闭记录窗口会连桌宠一起退出",
        )
