"""全屏计时牌的测试。

覆盖四层：
1. 显示的值必须和计时器一致（不多不少，不自己算一套时间）；
2. 状态驱动：空闲自动撤、暂停不变灰、到点转完成；
3. 交互：Esc 与点击都能收起，但刚弹出时的点击不算；
4. 与桌宠的接线：勾选是"偏好"，单场收起不能把偏好弄丢。
"""

from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from core.timer import FocusTimer, TimerMode, TimerState
from ui.focus_overlay import CLICK_GUARD_MS, FocusOverlay
from ui.pet_window import PetWindow

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class _Clock:
    """可控的单调时钟，避免测试真的等 25 分钟。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _press() -> QMouseEvent:
    point = QPointF(10.0, 10.0)
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        point,
        point,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _escape() -> QKeyEvent:
    return QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )


class _OverlayCase(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.timer = FocusTimer(clock=self.clock, pomodoro_seconds=1500)
        self.overlay = FocusOverlay(self.timer)
        self.addCleanup(self.overlay.deleteLater)

    def show(self) -> FocusOverlay:
        self.timer.start(TimerMode.POMODORO)
        self.overlay.show_fullscreen()
        return self.overlay


class OverlayContentTests(_OverlayCase):
    def test_covers_every_screen(self) -> None:
        overlay = self.show()
        geometry = QGuiApplication.screens()[0].geometry()
        for screen in QGuiApplication.screens()[1:]:
            geometry = geometry.united(screen.geometry())
        self.assertEqual(overlay.geometry(), geometry)
        self.assertTrue(overlay.isVisible())

    def test_clock_text_matches_timer(self) -> None:
        overlay = self.show()
        self.assertEqual(overlay._timer.display_text(), "25:00")
        self.clock.now += 372
        self.assertEqual(overlay._timer.display_text(), "18:48")

    def test_subject_is_kept(self) -> None:
        overlay = self.show()
        overlay.set_subject("数学")
        self.assertEqual(overlay.subject, "数学")

    def test_progress_ratio_tracks_pomodoro(self) -> None:
        overlay = self.show()
        self.assertAlmostEqual(overlay.progress_ratio(), 0.0)
        self.clock.now += 750  # 25 分钟的一半
        self.assertAlmostEqual(overlay.progress_ratio(), 0.5)

    def test_progress_ratio_clamped_when_finished(self) -> None:
        overlay = self.show()
        self.clock.now += 99999
        self.assertEqual(overlay.progress_ratio(), 1.0, "到点后不应超过 1")

    def test_stopwatch_has_no_progress(self) -> None:
        """正计时没有终点，进度条不该画（也不该除零）。"""
        self.timer.start(TimerMode.STOPWATCH)
        self.overlay.show_fullscreen()
        self.clock.now += 600
        self.assertEqual(self.overlay.progress_ratio(), 0.0)

    def test_paints_without_error_in_every_state(self) -> None:
        """三种状态都要能真正画一遍（offscreen 下 grab 会触发 paintEvent）。"""
        overlay = self.show()
        for state_setup in (
            lambda: None,                       # 运行中
            lambda: self.timer.pause(),         # 暂停
            lambda: self.timer.stop(),          # 已完成
        ):
            state_setup()
            pixmap = overlay.grab()
            self.assertFalse(pixmap.isNull(), f"状态 {self.timer.state.value} 绘制失败")


class OverlayStateTests(_OverlayCase):
    def test_dismiss_when_timer_reset(self) -> None:
        overlay = self.show()
        self.timer.reset()
        overlay.refresh()
        self.assertFalse(overlay.isVisible(), "会话被放弃后全屏牌必须撤掉")

    def test_finished_is_shown_then_auto_dismissed(self) -> None:
        overlay = self.show()
        self.timer.stop()
        overlay.refresh()
        self.assertTrue(overlay.isVisible(), "刚结束时应展示完成态")
        self.assertIsNotNone(overlay._finished_at)
        # 把完成时刻往前挪，模拟停留时间已过
        overlay._finished_at = time.monotonic() - 10
        overlay.refresh()
        self.assertFalse(overlay.isVisible(), "停留超时后应自动收起")

    def test_pause_keeps_overlay_alive(self) -> None:
        overlay = self.show()
        self.timer.pause()
        overlay.refresh()
        self.assertTrue(overlay.isVisible())
        self.assertIs(self.timer.state, TimerState.PAUSED)


class OverlayInteractionTests(_OverlayCase):
    def test_escape_hides(self) -> None:
        overlay = self.show()
        dismissed = []
        overlay.dismissed.connect(lambda: dismissed.append(True))
        overlay.keyPressEvent(_escape())
        self.assertFalse(overlay.isVisible())
        self.assertEqual(dismissed, [True])
        # 收起不等于停表
        self.assertTrue(self.timer.is_active)

    def test_click_hides_after_guard(self) -> None:
        overlay = self.show()
        overlay._shown_at = time.monotonic() - (CLICK_GUARD_MS + 100) / 1000
        overlay.mousePressEvent(_press())
        self.assertFalse(overlay.isVisible())

    def test_click_right_after_open_is_ignored(self) -> None:
        """刚弹出时鼠标本来就压在屏幕上，那个点击不该收掉它。"""
        overlay = self.show()
        overlay._shown_at = time.monotonic()
        overlay.mousePressEvent(_press())
        self.assertTrue(overlay.isVisible())

    def test_dismiss_is_idempotent(self) -> None:
        overlay = self.show()
        overlay.dismiss()
        overlay.dismiss()  # 重复调用不应抛错或重复发信号
        self.assertFalse(overlay.isVisible())


class PetOverlayWiringTests(unittest.TestCase):
    """桌宠菜单与全屏牌的接线。"""

    def setUp(self) -> None:
        self.clock = _Clock()
        self.pet = PetWindow(timer=FocusTimer(clock=self.clock, pomodoro_seconds=1500))
        self.addCleanup(self.pet.deleteLater)
        self.addCleanup(self.pet._hide_overlay)

    def test_menu_item_exists_and_is_checkable(self) -> None:
        self.assertEqual(self.pet.fullscreen_action.text(), "全屏计时")
        self.assertTrue(self.pet.fullscreen_action.isCheckable())
        self.assertFalse(self.pet.fullscreen_action.isChecked())

    def test_preference_opens_overlay_on_start(self) -> None:
        self.pet.fullscreen_action.setChecked(True)
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        overlay = self.pet.overlay
        assert overlay is not None
        self.assertTrue(overlay.isVisible())
        self.assertEqual(overlay.subject, "数学")

    def test_no_overlay_without_preference(self) -> None:
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.assertIsNone(self.pet.overlay, "没勾全屏就不该凭空建窗口")

    def test_single_session_dismiss_keeps_preference(self) -> None:
        """按 Esc 收起只是这一场不想看，偏好要留着。"""
        self.pet.fullscreen_action.setChecked(True)
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        assert self.pet.overlay is not None
        self.pet.overlay.dismiss()

        self.assertTrue(self.pet._fullscreen_preferred)
        # 菜单再次展开时，勾选仍应是勾上的
        self.pet._sync_menu_state()
        self.assertTrue(self.pet.fullscreen_action.isChecked())

    def test_unchecking_hides_overlay(self) -> None:
        self.pet.fullscreen_action.setChecked(True)
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.pet.fullscreen_action.setChecked(False)
        assert self.pet.overlay is not None
        self.assertFalse(self.pet.overlay.isVisible())
        self.assertFalse(self.pet._fullscreen_preferred)

    def test_checking_before_start_needs_no_timer(self) -> None:
        """先设偏好、之后再开始，也算数（不必在计时中才能勾）。"""
        self.pet.fullscreen_action.setChecked(True)
        self.assertIsNone(self.pet.overlay)
        self.pet.start_focus(TimerMode.STOPWATCH, subject="英语")
        assert self.pet.overlay is not None
        self.assertTrue(self.pet.overlay.isVisible())

    def test_discard_hides_overlay(self) -> None:
        self.pet.fullscreen_action.setChecked(True)
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.pet.discard_focus()
        assert self.pet.overlay is not None
        self.assertFalse(self.pet.overlay.isVisible())

    def test_hiding_pet_hides_overlay(self) -> None:
        self.pet.show()  # 未显示过的窗口调用 hide() 不会派发 hideEvent
        self.pet.fullscreen_action.setChecked(True)
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.pet.hide()
        assert self.pet.overlay is not None
        self.assertFalse(self.pet.overlay.isVisible())


if __name__ == "__main__":
    unittest.main()
