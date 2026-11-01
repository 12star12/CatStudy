"""走路动画与开机自启动的测试。

走路素材是从用户提供的 GIF 转出来的，这里只校验"契约"层面的东西：
帧尺寸一致、roles 能被解析、播放器能按时间切帧、状态切换不抛错。
像素好不好看只能靠肉眼，不适合写成断言。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core import autostart
from core.timer import FocusTimer, TimerMode
from ui.pet_window import DEFAULT_SPRITE_PATH, PetWindow
from ui.sprite import WALK_FRAME_MS, AnimationPlayer, SpriteSheet

_APP: QApplication | None = None
WALK_ASSET = Path(__file__).resolve().parent.parent / "assets" / "cat" / "cat_study.json"


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class StudyAssetTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(WALK_ASSET.read_text(encoding="utf-8"))

    def test_asset_ships_sit_and_walk_frames(self):
        self.assertIn("sit", self.data["frames"])
        walk = self.data["roles"]["walk"]
        self.assertEqual(len(walk), 8)
        for name in walk:
            self.assertIn(name, self.data["frames"])

    def test_all_frames_share_one_canvas(self):
        grid = tuple(self.data["grid"])
        for name, rows in self.data["frames"].items():
            self.assertEqual((len(rows[0]), len(rows)), grid, name)

    def test_roles_resolve_into_sprite(self):
        sprite = SpriteSheet(WALK_ASSET)
        self.assertIs(sprite.roles.has_walk, True)
        self.assertEqual(len(sprite.roles.walk), 8)
        self.assertEqual(sprite.roles.base, "sit")

    def test_sprite_detects_default_asset(self):
        # 桌宠默认就该用这张合并素材，换了要显式改默认值
        self.assertEqual(DEFAULT_SPRITE_PATH.name, "cat_study.json")


class WalkPlayerTests(unittest.TestCase):
    def setUp(self):
        self.sprite = SpriteSheet(WALK_ASSET)
        self.player = AnimationPlayer(self.sprite)

    def test_idle_is_completely_still(self):
        """休息时必须完全静止：帧不变、偏移恒为 0（旧版有 1px 呼吸抖动）。"""
        for tick in range(0, 400):
            name, offset = self.player.plan_at(tick)
            self.assertEqual(name, "sit", f"tick={tick}")
            self.assertEqual((offset.x(), offset.y()), (0, 0), f"tick={tick}")

    def test_walking_cycles_through_frames(self):
        self.player.set_walking(True)
        frames = {self.player.plan_at(tick)[0] for tick in range(0, 120)}
        self.assertEqual(frames, set(self.sprite.roles.walk))

    def test_walk_frame_timing(self):
        self.player.set_walking(True)
        # tick=0 -> 第 0 帧；tick=1(100ms) 仍是第 0 帧；tick=2(200ms) 进入第 1 帧
        self.assertEqual(self.player.plan_at(0)[0], "walk_0")
        self.assertEqual(self.player.plan_at(1)[0], "walk_0")
        self.assertEqual(self.player.plan_at(2)[0], "walk_1")
        # 一整轮耗时 = 帧数 × 每帧毫秒 = 960ms；tick 是 100ms，取整到 1000ms 回到首帧
        cycle_ticks = -(-len(self.sprite.roles.walk) * WALK_FRAME_MS // 100)
        self.assertEqual(self.player.plan_at(cycle_ticks)[0], "walk_0")

    def test_walking_back_to_idle(self):
        self.player.set_walking(True)
        self.assertTrue(self.player.walking)
        self.player.set_walking(False)
        self.assertFalse(self.player.walking)
        self.assertEqual(self.player.plan_at(37)[0], "sit")

    def test_asset_without_walk_degrades_safely(self):
        sit_only = Path(__file__).resolve().parent.parent / "assets" / "cat" / "cat_sit.json"
        player = AnimationPlayer(SpriteSheet(sit_only))
        player.set_walking(True)  # 素材没有 walk 帧
        self.assertFalse(player.walking)
        self.assertEqual(player.plan_at(12)[0], "sit")


class PetWalkStateTests(unittest.TestCase):
    def setUp(self):
        self.pet = PetWindow(timer=FocusTimer(pomodoro_seconds=60), default_subject="数学")
        self.addCleanup(self.pet.close)

    def test_walks_while_focusing(self):
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.assertTrue(self.pet._player.walking)

    def test_stops_when_finished(self):
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.pet.finish_focus()
        self.assertFalse(self.pet._player.walking)

    def test_stops_when_discarded(self):
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.pet.discard_focus()
        self.assertFalse(self.pet._player.walking)


class AutostartTests(unittest.TestCase):
    """注册表操作跑在临时子键上，绝不碰真实的 Run 键。"""

    KEY = r"Software\CatStudyTest\Run"

    def setUp(self):
        if not autostart.is_supported():
            self.skipTest("非 Windows 平台")
        import winreg

        winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.KEY).Close()
        autostart.disable(self.KEY)
        self.addCleanup(autostart.disable, self.KEY)

    def test_command_uses_pythonw_and_main(self):
        cmd = autostart.command()
        self.assertIn("pythonw.exe", cmd.lower())
        self.assertIn("main.py", cmd)
        # 两个路径都要带引号，否则带空格的路径会被拆开
        self.assertEqual(cmd.count('"'), 4)

    def test_enable_disable_roundtrip(self):
        self.assertFalse(autostart.is_enabled(self.KEY))
        self.assertTrue(autostart.enable(self.KEY))
        self.assertTrue(autostart.is_enabled(self.KEY))
        self.assertEqual(autostart.current_value(self.KEY), autostart.command())
        self.assertTrue(autostart.disable(self.KEY))
        self.assertFalse(autostart.is_enabled(self.KEY))

    def test_disable_when_absent_is_false(self):
        self.assertFalse(autostart.disable(self.KEY))

    def test_set_enabled_returns_real_state(self):
        # 返回的是"操作之后的真实状态"，不是"操作是否成功"
        self.assertTrue(autostart.set_enabled(True, self.KEY))
        self.assertFalse(autostart.set_enabled(False, self.KEY))
        self.assertFalse(autostart.is_enabled(self.KEY))


class TempDirGuard(unittest.TestCase):
    def test_tempdir_is_usable(self):
        # 兜底用例：确保本文件的临时目录机制在 Windows 上正常
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(Path(tmp).is_dir())


if __name__ == "__main__":
    unittest.main()
