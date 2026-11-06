"""完成庆祝礼花的测试。

覆盖三层：
1. 运动学纯函数：爆点数量、速度上限、重力推进、过期剔除、不改入参；
2. 窗口行为：点击穿透属性、文字可达、到时自动消散；
3. 与桌宠的接线：满 1 分钟的完成场次放礼花，文字按模式区分，
   新会话开始时上一场的礼花立刻撤掉。
"""

from __future__ import annotations

import os
import random
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.timer import FocusTimer, TimerMode
from ui.celebration import (
    GRAVITY,
    Particle,
    CelebrationOverlay,
    advance,
    spawn_burst,
)
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


class SpawnBurstTest(unittest.TestCase):
    def test_default_count_and_bounds(self) -> None:
        rng = random.Random(7)
        particles = spawn_burst(100.0, 200.0, rng)
        self.assertEqual(len(particles), 70)
        for p in particles:
            speed = (p.vx**2 + p.vy**2) ** 0.5
            self.assertGreaterEqual(speed, 150.0 - 1e-9)
            self.assertLessEqual(speed, 430.0 + 1e-9)
            self.assertGreater(p.ttl, 0.0)
            # 出生点即爆点
            self.assertEqual((p.x, p.y), (100.0, 200.0))
            # 初始寿命 = 总寿命
            self.assertEqual(p.life, p.ttl)

    def test_deterministic_with_same_seed(self) -> None:
        a = spawn_burst(0.0, 0.0, random.Random(3))
        b = spawn_burst(0.0, 0.0, random.Random(3))
        self.assertEqual(a, b)


class AdvanceTest(unittest.TestCase):
    def _particle(self, **kwargs) -> Particle:
        base = dict(x=0.0, y=0.0, vx=10.0, vy=20.0, color=(1, 2, 3),
                    ttl=2.0, life=2.0, size=4)
        base.update(kwargs)
        return Particle(**base)

    def test_gravity_and_motion(self) -> None:
        particles = [self._particle()]
        moved = advance(particles, 0.5)
        self.assertEqual(len(moved), 1)
        p = moved[0]
        self.assertAlmostEqual(p.x, 10.0 * 0.5)
        self.assertAlmostEqual(p.y, 20.0 * 0.5)
        self.assertAlmostEqual(p.vy, 20.0 + GRAVITY * 0.5)
        self.assertAlmostEqual(p.life, 2.0 - 0.5)

    def test_expired_removed(self) -> None:
        particles = [self._particle(life=0.1), self._particle(life=5.0)]
        moved = advance(particles, 0.2)
        self.assertEqual(len(moved), 1)
        self.assertAlmostEqual(moved[0].life, 4.8)

    def test_does_not_mutate_input(self) -> None:
        particles = [self._particle()]
        snapshot = list(particles)
        advance(particles, 1.0)
        self.assertEqual(particles, snapshot)

    def test_empty_stays_empty(self) -> None:
        self.assertEqual(advance([], 1.0), [])


class CelebrationOverlayTest(unittest.TestCase):
    def _make(self, **kwargs) -> CelebrationOverlay:
        return CelebrationOverlay(
            lifetime_ms=kwargs.pop("lifetime_ms", 150),
            tick_ms=kwargs.pop("tick_ms", 16),
            rng=random.Random(1),
            **kwargs,
        )

    def test_transparent_and_non_activating(self) -> None:
        overlay = self._make()
        self.assertTrue(
            overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        )
        self.assertTrue(
            overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        )
        self.assertTrue(
            overlay.windowFlags() & Qt.WindowType.FramelessWindowHint
        )
        self.assertTrue(
            overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        )

    def test_celebrate_shows_then_auto_dismisses(self) -> None:
        overlay = self._make()
        overlay.celebrate("🎉 番茄钟完成", "25 分钟已经记进今天，干得漂亮")
        self.assertEqual(overlay.headline, "🎉 番茄钟完成")
        self.assertEqual(overlay.subtext, "25 分钟已经记进今天，干得漂亮")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if not overlay.isVisible():
                break
            time.sleep(0.01)
        self.assertFalse(overlay.isVisible())

    def test_recelebrate_resets(self) -> None:
        overlay = self._make(lifetime_ms=10_000)
        overlay.celebrate("第一次", "第一次副标题")
        # 粒子在第一个 tick 才生成，转几下事件循环等它出现
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and overlay.particle_count == 0:
            QApplication.processEvents()
            time.sleep(0.01)
        count_first = overlay.particle_count
        self.assertGreater(count_first, 0)
        overlay.celebrate("第二次", "第二次副标题")
        self.assertEqual(overlay.headline, "第二次")
        self.assertEqual(overlay.subtext, "第二次副标题")
        # 重置后同样要等下一个 tick 才有新颗粒
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and overlay.particle_count == 0:
            QApplication.processEvents()
            time.sleep(0.01)
        self.assertGreater(overlay.particle_count, 0)
        overlay.dismiss()
        self.assertFalse(overlay.isVisible())


class PetWindowWiringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.pet = PetWindow(
            timer=FocusTimer(clock=self.clock, pomodoro_seconds=1500)
        )

    def tearDown(self) -> None:
        self.pet.close()
        if self.pet.celebration is not None:
            self.pet.celebration.dismiss()

    def test_pomodoro_finish_triggers_celebration(self) -> None:
        self.assertTrue(
            self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        )
        self.clock.now += 1500.0  # 到点
        self.pet._on_tick()       # 结算
        celebration = self.pet.celebration
        self.assertIsNotNone(celebration)
        self.assertIn("番茄钟", celebration.headline)
        self.assertIn("25 分钟", celebration.subtext)

    def test_stopwatch_finish_uses_generic_headline(self) -> None:
        self.assertTrue(
            self.pet.start_focus(TimerMode.STOPWATCH, subject="项目")
        )
        self.clock.now += 1200.0  # 手动结束前跑了 20 分钟
        self.pet.finish_focus()
        celebration = self.pet.celebration
        self.assertIsNotNone(celebration)
        self.assertIn("专注完成", celebration.headline)
        self.assertIn("20 分钟", celebration.subtext)

    def test_short_session_does_not_celebrate(self) -> None:
        self.assertTrue(
            self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        )
        self.clock.now += 30.0  # 不足 1 分钟
        self.pet._on_tick()
        self.assertIsNone(self.pet.celebration)

    def test_new_session_dismisses_old_celebration(self) -> None:
        self.assertTrue(
            self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        )
        self.clock.now += 1500.0
        self.pet._on_tick()
        celebration = self.pet.celebration
        self.assertIsNotNone(celebration)
        celebration.celebrate("🎉 番茄钟完成", "占位副标题")
        QApplication.processEvents()
        self.assertTrue(celebration.isVisible())

        # 上一场没散完就开新一场：立刻撤
        self.assertTrue(
            self.pet.start_focus(TimerMode.STOPWATCH, subject="项目")
        )
        self.assertFalse(celebration.isVisible())


if __name__ == "__main__":
    unittest.main()
