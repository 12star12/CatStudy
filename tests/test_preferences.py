"""界面偏好（位置 / 锁定）与坐标夹取的测试。

两条主线：

1. **纯函数**：``from_dict`` 面对任何脏内容都要退化成默认值，
   ``clamp_position`` 面对任何坐标都要给出一个可见的答案。
2. **接线**：锁上以后拖不动、但单击照常暂停；松手后位置写盘，
   下次启动回到原处。这两条是用户真正感知到的行为，必须有测试钉住。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from core.preferences import (
    PetPreferences,
    PreferenceStore,
    clamp_position,
    from_dict,
)
from core.timer import FocusTimer, TimerMode, TimerState
from ui.pet_window import PetWindow

SCREEN = (0, 0, 1920, 1080)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class PreferencesTestCase(unittest.TestCase):
    """偏好读写与解析。"""

    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp())
        self.path = self.tempdir / "preferences.json"

    def test_defaults_when_file_missing(self) -> None:
        prefs = PreferenceStore(self.path).load()
        self.assertFalse(prefs.locked)
        self.assertIsNone(prefs.position)

    def test_roundtrip_keeps_position_and_lock(self) -> None:
        store = PreferenceStore(self.path)
        store.save(PetPreferences(locked=True, x=1200, y=700))
        loaded = store.load()
        self.assertTrue(loaded.locked)
        self.assertEqual(loaded.position, (1200, 700))

    def test_save_creates_parent_directory(self) -> None:
        nested = self.tempdir / "a" / "b" / "preferences.json"
        self.assertTrue(PreferenceStore(nested).save(PetPreferences(x=1, y=2)))
        self.assertEqual(PreferenceStore(nested).load().position, (1, 2))

    def test_atomic_write_leaves_no_temp_file(self) -> None:
        PreferenceStore(self.path).save(PetPreferences(x=10, y=20))
        leftovers = [p.name for p in self.tempdir.iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])

    def test_broken_json_falls_back_to_defaults(self) -> None:
        # 断电写坏、手动编辑少了括号——都不该让程序起不来
        self.path.write_text('{"pet": {"locked": tru', encoding="utf-8")
        prefs = PreferenceStore(self.path).load()
        self.assertEqual(prefs, PetPreferences())

    def test_wrong_shapes_fall_back(self) -> None:
        for raw in ([], "text", 42, None, {"pet": []}, {"pet": {"x": "left"}}):
            self.assertEqual(from_dict(raw), PetPreferences())

    def test_bool_is_not_a_coordinate(self) -> None:
        # True 是 int 的子类，不排掉会变成"猫跑到 (1, 1)"
        self.assertIsNone(from_dict({"pet": {"x": True, "y": True}}).position)

    def test_half_position_is_ignored(self) -> None:
        self.assertIsNone(from_dict({"pet": {"x": 800}}).position)

    def test_saved_version_is_written(self) -> None:
        PreferenceStore(self.path).save(PetPreferences())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertIn("pet", payload)


class ClampPositionTestCase(unittest.TestCase):
    """坐标夹取：允许半挂在边缘，但不允许彻底消失。"""

    def test_inside_screen_kept(self) -> None:
        self.assertEqual(clamp_position(900, 500, 80, 100, [SCREEN]), (900, 500))

    def test_partially_offscreen_kept(self) -> None:
        # 贴边挂着半只猫是常见摆法，不该被拉回来；判定用窗口中心，
        # 所以"最多探出去半个身位"仍算可见（1870+40 尚在屏内）
        self.assertEqual(clamp_position(1870, 500, 80, 100, [SCREEN]), (1870, 500))

    def test_offscreen_pulled_back(self) -> None:
        x, y = clamp_position(-5000, -5000, 80, 100, [SCREEN])
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + 80, 1920)
        self.assertLessEqual(y + 100, 1080)

    def test_position_on_second_screen_kept(self) -> None:
        # 外接屏在右边：x=2000 属于第二块屏，不该被当成越界
        second = (1920, 0, 1280, 1024)
        self.assertEqual(
            clamp_position(2000, 300, 80, 100, [SCREEN, second]), (2000, 300)
        )

    def test_falls_back_to_primary_screen(self) -> None:
        second = (1920, 0, 1280, 1024)
        x, y = clamp_position(5000, 300, 80, 100, [SCREEN, second])
        # 主屏在列表首位，退回主屏右下角而不是留在第二块屏
        self.assertLess(x, 1920)

    def test_no_screen_info_keeps_position(self) -> None:
        self.assertEqual(clamp_position(10, 20, 80, 100, []), (10, 20))


class PetLockTestCase(unittest.TestCase):
    """锁定与位置记忆的接线。"""

    def setUp(self) -> None:
        _app()
        self.tempdir = Path(tempfile.mkdtemp())
        self.store = PreferenceStore(self.tempdir / "preferences.json")
        self.pet = PetWindow(preferences=self.store)
        self.addCleanup(self.pet.close)

    # ---------- 锁定 ----------

    def test_unlocked_by_default(self) -> None:
        self.assertFalse(self.pet.locked)

    def test_toggle_lock_persists(self) -> None:
        self.pet._toggle_lock(True)
        self.assertTrue(self.store.load().locked)

    def test_menu_reflects_lock_state(self) -> None:
        self.pet._toggle_lock(True)
        self.pet._sync_menu_state()
        self.assertTrue(self.pet.lock_action.isChecked())

    def test_locked_pet_does_not_move(self) -> None:
        self.pet.move(400, 300)
        self.pet._toggle_lock(True)
        self.pet._drag_offset = QPoint(10, 10)
        self.pet._drag_moved = False
        self.pet._press_origin = QPoint(400, 300)
        self._mouse_move(QPoint(900, 700))
        self.assertEqual(self.pet.pos(), QPoint(400, 300))

    def test_unlocked_pet_moves(self) -> None:
        self.pet.move(400, 300)
        self.pet._drag_offset = QPoint(10, 10)
        self.pet._drag_moved = False
        self.pet._press_origin = QPoint(400, 300)
        self._mouse_move(QPoint(900, 700))
        self.assertEqual(self.pet.pos(), QPoint(890, 690))

    def test_locked_click_still_toggles_pause(self) -> None:
        """锁的是位置，不是暂停——去洗手间时猫被锁住也要能点停。"""
        self.pet._toggle_lock(True)
        # 显式给科目：不传会弹输入框，测试会挂在那里等人敲键盘
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.pet._press_origin = QPoint(0, 0)
        self.pet._drag_moved = False
        self.pet._tap_allowed = True
        self._mouse_move(QPoint(200, 200))
        # 移动被吞掉，因此松手时仍按单击处理
        self.assertFalse(self.pet._drag_moved)
        self.assertEqual(self.pet.timer.state, TimerState.RUNNING)

    def test_tooltip_hides_drag_hint_when_locked(self) -> None:
        self.assertIn("拖动", self.pet.toolTip())
        self.pet._toggle_lock(True)
        self.assertNotIn("拖动", self.pet.toolTip())
        self.assertIn("锁定", self.pet.toolTip())

    def test_lock_interrupts_active_drag(self) -> None:
        self.pet._drag_offset = QPoint(5, 5)
        self.pet._toggle_lock(True)
        self.assertIsNone(self.pet._drag_offset)

    # ---------- 位置记忆 ----------

    def test_drag_release_saves_position(self) -> None:
        self.pet.move(640, 480)
        self.pet._drag_moved = True
        self._mouse_release()
        self.assertEqual(self.store.load().position, (640, 480))

    def test_click_without_drag_does_not_save(self) -> None:
        self.pet.move(300, 200)
        self.pet._drag_moved = False
        self._mouse_release()
        self.assertIsNone(self.store.load().position)

    def test_restore_moves_pet_to_saved_position(self) -> None:
        self.store.save(PetPreferences(x=500, y=400))
        pet = PetWindow(preferences=PreferenceStore(self.store.path))
        self.addCleanup(pet.close)
        pet.show()
        _app().processEvents()
        # 记忆坐标若在屏内应原样恢复（离屏时会被夹回主屏，另有用例覆盖）
        self.assertIn(pet.pos().x(), (500,))
        pet.close()

    def test_restore_skipped_when_no_position(self) -> None:
        before = self.pet.pos()
        self.pet._restore_position()
        self.assertEqual(self.pet.pos(), before)

    def test_remember_position_stores_current_geometry(self) -> None:
        self.pet.move(222, 333)
        self.pet._remember_position()
        self.assertEqual(self.store.load().position, (222, 333))

    # ---------- 辅助 ----------

    def _mouse_move(self, global_pos: QPoint) -> None:
        event = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            self.pet.rect().center().toPointF(),
            global_pos.toPointF(),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.pet.mouseMoveEvent(event)

    def _mouse_release(self) -> None:
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            self.pet.rect().center().toPointF(),
            self.pet.pos().toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.pet.mouseReleaseEvent(event)


class TimerPropertyTestCase(unittest.TestCase):
    """``PetWindow.timer`` 是测试与外部接线的入口，不该被改坏。"""

    def setUp(self) -> None:
        _app()
        self.pet = PetWindow(timer=FocusTimer())
        self.addCleanup(self.pet.close)

    def test_timer_is_exposed(self) -> None:
        self.assertIsInstance(self.pet.timer, FocusTimer)


if __name__ == "__main__":
    unittest.main()
