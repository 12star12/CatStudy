"""第一只正式角色 ``assets/cat/cat_sit.json`` 的接入测试。

覆盖：加载、尺寸、透明度、调色板、DPR 缩放、像素边缘、窗口构建，
并复核旧素材（idle.json / character_sit.json）未被破坏。

运行：
    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.pet_window import DEFAULT_SPRITE_PATH, PetWindow  # noqa: E402
from ui.sprite import BREATH_AMPLITUDE, CAT_ASSETS_DIR, SpriteSheet  # noqa: E402

_app: QApplication | None = None

SIT_JSON = CAT_ASSETS_DIR / "cat_sit.json"
IDLE_JSON = CAT_ASSETS_DIR / "idle.json"
LEGACY_JSON = CAT_ASSETS_DIR / "character_sit.json"

# 素材规格（来自 v3_native 交付说明，断言即规格）
GRID = (39, 48)
CELL = 2
DISPLAY = (78, 96)


def setUpModule() -> None:
    global _app
    _app = QApplication.instance() or QApplication([])


class CharacterSitLoadTest(unittest.TestCase):
    """素材加载与契约解析。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sprite = SpriteSheet(SIT_JSON)

    def test_file_exists(self) -> None:
        self.assertTrue(SIT_JSON.is_file())

    def test_single_frame_named_sit(self) -> None:
        self.assertEqual(self.sprite.frame_names(), ("sit",))

    def test_roles_resolved_without_hardcoding(self) -> None:
        """素材没有 roles 字段，应自动退化为"第一帧 + 无眨眼"。"""
        self.assertEqual(self.sprite.roles.base, "sit")
        self.assertEqual(self.sprite.roles.blink, ())
        self.assertFalse(self.sprite.roles.has_blink)

    def test_state_and_cell_pixels(self) -> None:
        self.assertEqual(self.sprite.state_name, "sit")
        self.assertEqual(self.sprite.cell_pixels, CELL)

    def test_grid_size(self) -> None:
        self.assertEqual(self.sprite.grid_size, GRID)

    def test_rows_are_rectangular(self) -> None:
        rows = self.sprite._patterns["sit"]
        self.assertEqual(len(rows), GRID[1])
        self.assertEqual({len(r) for r in rows}, {GRID[0]})

    def test_no_keyerror_for_base_frame(self) -> None:
        pm = self.sprite.base_pixmap()
        self.assertFalse(pm.isNull())

    def test_player_never_requests_missing_frame(self) -> None:
        from ui.sprite import AnimationPlayer

        player = AnimationPlayer(self.sprite)
        for tick in range(500):
            name, _ = player.plan_at(tick)
            self.assertEqual(name, "sit")
            self.sprite.pixmap(name)  # 不应抛 KeyError


class CharacterSitSizeTest(unittest.TestCase):
    """尺寸：网格 → 显示像素。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sprite = SpriteSheet(SIT_JSON)

    def test_frame_size_is_78x96(self) -> None:
        self.assertEqual(self.sprite.frame_size(1.0), DISPLAY)

    def test_pixmap_matches_frame_size(self) -> None:
        pm = self.sprite.pixmap("sit", 1.0)
        self.assertEqual((pm.width(), pm.height()), DISPLAY)

    def test_display_height_is_96(self) -> None:
        """验收要求：96px 高度。"""
        _, h = self.sprite.frame_size(1.0)
        self.assertEqual(h, 96)
        self.assertEqual(h, GRID[1] * CELL)

    def test_dpr_keeps_logical_size_constant(self) -> None:
        """100% / 150% / 200% / 300% 下逻辑尺寸恒为 78x96。

        125%、175% 等让 ``cell_pixels × dpr`` 落到 .5 的缩放档位无法同时满足
        "整数设备格 + 逻辑尺寸不变"，见 test_dpr_fractional_scale_fallback。
        """
        for dpr in (1.0, 1.5, 2.0, 3.0):
            self.assertEqual(self.sprite.frame_size(dpr), DISPLAY, f"dpr={dpr}")

    def test_dpr_device_cell_is_integer(self) -> None:
        for dpr, expected in ((1.0, 2), (1.25, 3), (1.5, 3), (2.0, 4), (3.0, 6)):
            self.assertEqual(
                self.sprite.device_cell(dpr), expected, f"dpr={dpr}"
            )

    def test_dpr_fractional_scale_fallback(self) -> None:
        """125% 缩放：2×1.25=2.5，half-up 取 3 格 → 94x115（偏放大而非缩小）。

        这是像素块必须为整数设备像素带来的固有取舍，记录在案以免被误判为回归。
        """
        self.assertEqual(self.sprite.device_cell(1.25), 3)
        self.assertEqual(self.sprite.frame_size(1.25), (94, 115))

    def test_dpr_device_pixmap_grows_exactly(self) -> None:
        for dpr in (1.0, 1.5, 2.0):
            cell = self.sprite.device_cell(dpr)
            pm = self.sprite.pixmap("sit", dpr)
            self.assertEqual(pm.width(), GRID[0] * cell)
            self.assertEqual(pm.height(), GRID[1] * cell)
            self.assertAlmostEqual(pm.devicePixelRatio(), dpr)


class CharacterSitTransparencyTest(unittest.TestCase):
    """透明度、边距与调色板。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sprite = SpriteSheet(SIT_JSON)
        cls.img = cls.sprite.pixmap("sit", 1.0).toImage()

    def test_alpha_only_0_or_255(self) -> None:
        alphas = {
            self.img.pixelColor(x, y).alpha()
            for x in range(self.img.width())
            for y in range(self.img.height())
        }
        self.assertEqual(alphas, {0, 255}, "出现半透明像素，说明存在抗锯齿")

    def test_corners_transparent(self) -> None:
        w, h = self.img.width(), self.img.height()
        for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            self.assertEqual(self.img.pixelColor(x, y).alpha(), 0, f"({x},{y})")

    def test_margin_is_two_cells(self) -> None:
        """素材四周各留 2 格透明边距 → 显示层 4px。"""
        w, h = self.img.width(), self.img.height()
        for x in range(w):
            for y in range(2 * CELL):
                self.assertEqual(self.img.pixelColor(x, y).alpha(), 0, f"上边距 ({x},{y})")
                self.assertEqual(self.img.pixelColor(x, h - 1 - y).alpha(), 0, f"下边距 ({x},{y})")
        for y in range(h):
            for x in range(2 * CELL):
                self.assertEqual(self.img.pixelColor(x, y).alpha(), 0, f"左边距 ({x},{y})")
                self.assertEqual(self.img.pixelColor(w - 1 - x, y).alpha(), 0, f"右边距 ({x},{y})")

    def test_palette_has_eight_colors(self) -> None:
        self.assertEqual(len(self.sprite._palette), 8)

    def test_all_opaque_pixels_use_palette(self) -> None:
        allowed = {v.lower() for v in self.sprite._palette.values()}
        used = set()
        for x in range(self.img.width()):
            for y in range(self.img.height()):
                c = self.img.pixelColor(x, y)
                if c.alpha() == 255:
                    used.add(c.name().lower())
        self.assertTrue(used.issubset(allowed), f"越界颜色: {used - allowed}")
        self.assertEqual(len(used), 8, "调色板存在未使用色")

    def test_content_bbox(self) -> None:
        """内容边界应落在 2 格边距之内。"""
        w, h = self.img.width(), self.img.height()
        xs, ys = [], []
        for x in range(w):
            for y in range(h):
                if self.img.pixelColor(x, y).alpha() == 255:
                    xs.append(x)
                    ys.append(y)
        self.assertEqual((min(xs), max(xs)), (2 * CELL, w - 1 - 2 * CELL))
        self.assertEqual((min(ys), max(ys)), (2 * CELL, h - 1 - 2 * CELL))


class CharacterSitRenderTest(unittest.TestCase):
    """像素边缘：每格必须是纯色块，不允许插值。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sprite = SpriteSheet(SIT_JSON)

    def test_each_block_is_uniform(self) -> None:
        for dpr in (1.0, 1.5, 2.0):
            cell = self.sprite.device_cell(dpr)
            img = self.sprite.pixmap("sit", dpr).toImage()
            pattern = self.sprite._patterns["sit"]
            palette = {k: v.lower() for k, v in self.sprite._palette.items()}
            for gy in range(GRID[1]):
                for gx in range(GRID[0]):
                    symbol = pattern[gy][gx]
                    for dy in (0, cell // 2, cell - 1):
                        for dx in (0, cell // 2, cell - 1):
                            c = img.pixelColor(gx * cell + dx, gy * cell + dy)
                            if symbol == ".":
                                self.assertEqual(c.alpha(), 0)
                            else:
                                self.assertEqual(
                                    c.name().lower(), palette[symbol],
                                    f"dpr={dpr} 格({gx},{gy}) 被插值",
                                )

    def test_cache_per_dpr(self) -> None:
        a = self.sprite.pixmap("sit", 1.0)
        self.assertIs(a, self.sprite.pixmap("sit", 1.0))
        self.assertIsNot(a, self.sprite.pixmap("sit", 2.0))


class CharacterSitWindowTest(unittest.TestCase):
    """真实 PetWindow 构建（默认素材路径应为新角色）。"""

    def test_default_sprite_path(self) -> None:
        self.assertEqual(DEFAULT_SPRITE_PATH.name, "cat_sit.json")

    def test_window_builds_with_default_sprite(self) -> None:
        window = PetWindow()
        try:
            sprite = window._sprite
            self.assertEqual(sprite.frame_names(), ("sit",))
            w, h = sprite.frame_size(window._dpr)
            self.assertEqual((w, h), DISPLAY)
            self.assertEqual(window.width(), DISPLAY[0])
            self.assertEqual(window.height(), DISPLAY[1] + BREATH_AMPLITUDE)
        finally:
            window.close()

    def test_window_flags(self) -> None:
        window = PetWindow()
        try:
            flags = window.windowFlags()
            self.assertTrue(flags & Qt.WindowType.FramelessWindowHint)
            self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)
            self.assertTrue(window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        finally:
            window.close()

    def test_window_mask_not_empty(self) -> None:
        window = PetWindow()
        try:
            mask = window.mask()
            self.assertFalse(mask.isEmpty())
            w, h = DISPLAY
            # 遮罩应覆盖猫身中部、避开四角
            self.assertTrue(mask.contains(QPoint(w // 2, h // 2)))
            self.assertFalse(mask.contains(QPoint(0, 0)))
        finally:
            window.close()

    def test_label_shows_sprite(self) -> None:
        window = PetWindow()
        try:
            pm = window._label.pixmap()
            self.assertEqual((pm.width(), pm.height()), DISPLAY)
        finally:
            window.close()

    def test_press_drag_release_moves_window(self) -> None:
        """模拟左键拖拽：窗口应跟随光标位移。"""
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        window = PetWindow()
        try:
            window.move(300, 300)
            start = window.pos()
            local = QPointF(30.0, 40.0)
            global_start = QPointF(330.0, 340.0)

            press = QMouseEvent(
                QEvent.Type.MouseButtonPress, local, global_start,
                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            window.mousePressEvent(press)
            self.assertIsNotNone(window._drag_offset)

            move = QMouseEvent(
                QEvent.Type.MouseMove, local,
                QPointF(global_start.x() + 50, global_start.y() + 20),
                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            window.mouseMoveEvent(move)
            self.assertEqual(window.pos(), start + QPoint(50, 20))

            release = QMouseEvent(
                QEvent.Type.MouseButtonRelease, local, global_start,
                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            window.mouseReleaseEvent(release)
            self.assertIsNone(window._drag_offset)
        finally:
            window.close()

    def test_context_menu_has_quit(self) -> None:
        window = PetWindow()
        try:
            texts = [a.text() for a in window._menu.actions()]
            self.assertIn("退出程序", texts)
        finally:
            window.close()

    def test_player_emits_sit_frames(self) -> None:
        window = PetWindow()
        try:
            seen: list[tuple[str, int]] = []
            window._player.frameChanged.connect(
                lambda pm, off: seen.append((pm.width() and "ok", off.y()))
            )
            window._player.start()
            try:
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0][0], "ok")
            finally:
                window._player.stop()
        finally:
            window.close()


class LegacyAssetsIntactTest(unittest.TestCase):
    """旧素材必须完整保留且仍可加载。"""

    def test_all_asset_files_present(self) -> None:
        for name in (
            "idle.json",
            "character_sit.json",
            "character_sit.png",
            "character_sit_legacy.json",
            "character_sit_legacy.png",
            "character_sit_preview.png",
            "cat_sit.json",
        ):
            self.assertTrue((CAT_ASSETS_DIR / name).is_file(), f"缺少 {name}")

    def test_idle_json_still_works(self) -> None:
        sprite = SpriteSheet(IDLE_JSON)
        self.assertEqual(sprite.frame_names(), ("open", "half", "closed"))
        self.assertEqual(sprite.roles.blink, ("half", "closed", "closed", "half"))
        self.assertEqual(sprite.frame_size(1.0), (128, 128))

    def test_legacy_character_sit_still_loads(self) -> None:
        sprite = SpriteSheet(LEGACY_JSON)
        self.assertEqual(sprite.frame_names(), ("sit",))
        self.assertFalse(sprite.pixmap("sit").isNull())

    def test_legacy_asset_not_used_by_default(self) -> None:
        """默认路径必须指向新角色，而不是旧的 character_sit.json。"""
        self.assertNotEqual(DEFAULT_SPRITE_PATH, LEGACY_JSON)
        self.assertNotEqual(DEFAULT_SPRITE_PATH, IDLE_JSON)


if __name__ == "__main__":
    unittest.main(verbosity=2)
