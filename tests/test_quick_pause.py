"""一键暂停的测试（单击猫身 / 全局热键）。

覆盖四层：
1. 单击（没拖起来）在双击判定窗口过后切换暂停；
2. 拖拽不触发暂停，且小抖动不算拖拽、不移动窗口；
3. 双击只开学习记录，不顺手把计时停掉；
4. 热键路径：``handle_hotkey`` 的返回值与状态迁移，空闲时无事可做。
"""

from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from core.timer import FocusTimer, TimerMode, TimerState
from ui import hotkey
from ui.pet_window import PetWindow

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class _Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


def _press(global_point: QPoint) -> QMouseEvent:
    local = QPointF(6.0, 6.0)
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        local,
        QPointF(global_point),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _move(global_point: QPoint) -> QMouseEvent:
    local = QPointF(6.0, 6.0)
    return QMouseEvent(
        QEvent.Type.MouseMove,
        local,
        QPointF(global_point),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _release(global_point: QPoint) -> QMouseEvent:
    local = QPointF(6.0, 6.0)
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        local,
        QPointF(global_point),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _pump_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class QuickPauseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.pet = PetWindow(
            timer=FocusTimer(clock=self.clock, pomodoro_seconds=1500)
        )
        self.pet.move(200, 200)
        self.events: list[object] = []
        self.pet.studyRecordsRequested.connect(
            lambda: self.events.append("study")
        )

    def tearDown(self) -> None:
        self.pet.close()

    def _tap(self, point: QPoint | None = None) -> None:
        point = point if point is not None else QPoint(400, 400)
        self.pet.mousePressEvent(_press(point))
        self.pet.mouseReleaseEvent(_release(point))

    # ---------- 单击 ----------

    def test_single_click_pauses_then_resumes(self) -> None:
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self._tap()
        self.assertTrue(
            _pump_until(lambda: self.pet.timer.state is TimerState.PAUSED),
            "单击应在双击判定窗口过后暂停",
        )
        # 再单击一次继续（等上次的延时窗口过去，避免被判成双击）
        time.sleep((QApplication.doubleClickInterval() + 40) / 1000)
        self.pet._last_press_at = None
        self._tap()
        self.assertTrue(
            _pump_until(lambda: self.pet.timer.state is TimerState.RUNNING)
        )

    def test_single_click_when_idle_does_nothing(self) -> None:
        self._tap()
        self.assertTrue(_pump_until(lambda: self.pet._tap_token is None))
        self.assertIs(self.pet.timer.state, TimerState.IDLE)
        self.assertFalse(self.pet._bubble.isVisible())

    # ---------- 拖拽 ----------

    def test_drag_does_not_pause(self) -> None:
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        start = QPoint(400, 400)
        self.pet.mousePressEvent(_press(start))
        self.pet.mouseMoveEvent(_move(QPoint(460, 460)))
        self.pet.mouseReleaseEvent(_release(QPoint(460, 460)))
        # 等过一个完整的双击间隔，确认没有任何延时暂停被触发
        time.sleep((QApplication.doubleClickInterval() + 80) / 1000)
        QApplication.processEvents()
        self.assertIs(self.pet.timer.state, TimerState.RUNNING)
        self.assertEqual(self.pet.pos(), QPoint(260, 260))

    def test_small_jitter_moves_nothing(self) -> None:
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        start = QPoint(400, 400)
        self.pet.mousePressEvent(_press(start))
        self.pet.mouseMoveEvent(_move(QPoint(402, 401)))
        self.pet.mouseReleaseEvent(_release(QPoint(402, 401)))
        self.assertEqual(self.pet.pos(), QPoint(200, 200))
        # 3px 抖动仍算单击
        self.assertTrue(
            _pump_until(lambda: self.pet.timer.state is TimerState.PAUSED)
        )

    # ---------- 双击 ----------

    def test_double_click_opens_records_without_pausing(self) -> None:
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        point = QPoint(400, 400)
        self.pet.mousePressEvent(_press(point))
        self.pet.mouseReleaseEvent(_release(point))
        self.pet.mousePressEvent(_press(point))
        self.pet.mouseReleaseEvent(_release(point))
        self.assertEqual(self.events, ["study"])
        time.sleep((QApplication.doubleClickInterval() + 80) / 1000)
        QApplication.processEvents()
        self.assertIs(self.pet.timer.state, TimerState.RUNNING)

    # ---------- 热键 ----------

    def test_hotkey_toggles_pause(self) -> None:
        self.assertFalse(self.pet.handle_hotkey())  # 空闲：无事可做
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.assertTrue(self.pet.handle_hotkey())
        self.assertIs(self.pet.timer.state, TimerState.PAUSED)
        self.assertTrue(self.pet.handle_hotkey())
        self.assertIs(self.pet.timer.state, TimerState.RUNNING)

    def test_paused_cat_stops_walking(self) -> None:
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.pet.toggle_pause()
        self.assertFalse(self.pet._player.walking)
        self.pet.toggle_pause()
        self.assertTrue(self.pet._player.walking)

    def test_menu_shows_hotkey_hint(self) -> None:
        self.pet._sync_menu_state()
        self.assertIn(hotkey.HOTKEY_LABEL, self.pet.pause_action.text())

    @unittest.skipUnless(hotkey.is_supported(), "全局热键只有 Windows 实现")
    def test_register_and_unregister_do_not_raise(self) -> None:
        handle = int(self.pet.winId())
        hotkey.register(handle)
        hotkey.unregister(handle)  # 无论注册成功与否，解绑都不该抛


if __name__ == "__main__":
    unittest.main()
