"""ui/sprite.py 与 ui/pet_window.py 的帧契约测试。

覆盖两类素材：
- 旧版多帧素材 ``assets/cat/idle.json``（open/half/closed，含眨眼）；
- 单帧素材（如 ``sit``），验证无 KeyError、无眨眼、正常渲染。

运行：
    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

# 必须在导入 PySide6 前设置，避免无显示环境下创建窗口失败
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QRegion  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import sprite as sprite_mod  # noqa: E402
from ui.pet_window import PetWindow  # noqa: E402
from ui.sprite import (  # noqa: E402
    BLINK_INTERVAL,
    BREATH_AMPLITUDE,
    BREATH_CYCLE,
    BREATH_DOWN_MAX,
    BREATH_DOWN_MIN,
    CAT_ASSETS_DIR,
    AnimationPlayer,
    FrameRoles,
    SpriteSheet,
    plan_frame,
    plan_offset,
    possible_offsets,
)

_app: QApplication | None = None

IDLE_JSON = CAT_ASSETS_DIR / "idle.json"


def setUpModule() -> None:
    global _app
    _app = QApplication.instance() or QApplication([])


# --------------------------------------------------------------------------
# 工具：在临时目录生成素材 JSON
# --------------------------------------------------------------------------


def make_asset(
    tmpdir: Path,
    frames: dict[str, list[str]],
    cell_pixels: int = 4,
    roles: dict | None = None,
    state: str = "test",
    palette: dict[str, str] | None = None,
) -> Path:
    data = {
        "state": state,
        "cell_pixels": cell_pixels,
        "palette": palette or {"X": "#123456", "Y": "#654321"},
        "frames": frames,
    }
    if roles is not None:
        data["roles"] = roles
    path = tmpdir / f"{state}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def single_frame_rows(size: int = 8, symbol: str = "X") -> list[str]:
    """生成一个 size×size 的实心方块图案。"""
    return [symbol * size for _ in range(size)]


# --------------------------------------------------------------------------
# 旧素材：行为必须与改动前完全一致
# --------------------------------------------------------------------------


class LegacyIdleAssetTest(unittest.TestCase):
    """旧版 idle.json 的加载、角色解析与动画时间轴。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sprite = SpriteSheet(IDLE_JSON)

    def test_loads_three_frames(self) -> None:
        self.assertEqual(self.sprite.frame_names(), ("open", "half", "closed"))

    def test_roles_declared_in_asset(self) -> None:
        """角色来自 JSON，而非代码里的字面量。"""
        self.assertEqual(self.sprite.roles.base, "open")
        self.assertEqual(
            self.sprite.roles.blink, ("half", "closed", "closed", "half")
        )
        self.assertTrue(self.sprite.roles.has_blink)

    def test_blink_sequence_matches_legacy_behaviour(self) -> None:
        """逐 tick 比对旧的硬编码实现，1000 个 tick 完全一致。"""

        def legacy(tick: int) -> str:
            phase = tick % BLINK_INTERVAL
            if 1 <= phase <= 4:
                return ("half", "closed", "closed", "half")[phase - 1]
            return "open"

        for tick in range(1000):
            self.assertEqual(
                self.sprite.roles.frame_at(tick), legacy(tick), f"tick={tick}"
            )

    def test_breath_offset_matches_legacy_behaviour(self) -> None:
        def legacy(tick: int) -> QPoint:
            phase = tick % BREATH_CYCLE
            return QPoint(0, 1 if BREATH_DOWN_MIN <= phase <= BREATH_DOWN_MAX else 0)

        for tick in range(400):
            self.assertEqual(plan_offset(tick), legacy(tick), f"tick={tick}")

    def test_player_plan_at_is_unchanged(self) -> None:
        player = AnimationPlayer(self.sprite)
        self.assertEqual(player.plan_at(0), ("open", QPoint(0, 0)))
        # tick=1 起进入眨眼序列首帧，且此时呼吸相位为 1（不处于下沉区）
        self.assertEqual(player.plan_at(1), ("half", QPoint(0, 0)))
        self.assertEqual(player.plan_at(2), ("closed", QPoint(0, 0)))

    def test_base_pixmap_renders(self) -> None:
        pm = self.sprite.base_pixmap(1.0)
        self.assertFalse(pm.isNull())
        w, h = self.sprite.frame_size(1.0)
        self.assertEqual((pm.width(), pm.height()), (w, h))

    def test_frame_size_is_16x16_cells_at_8x(self) -> None:
        self.assertEqual(self.sprite.grid_size, (16, 16))
        self.assertEqual(self.sprite.frame_size(1.0), (128, 128))


# --------------------------------------------------------------------------
# 单帧素材：sit
# --------------------------------------------------------------------------


class SingleFrameAssetTest(unittest.TestCase):
    """只有一帧 sit 的素材必须能加载、渲染、播放，且不抛 KeyError。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.path = make_asset(
            self.tmpdir,
            frames={"sit": single_frame_rows(8)},
            cell_pixels=2,
            state="sit",
        )
        self.sprite = SpriteSheet(self.path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_single_frame_registered(self) -> None:
        self.assertEqual(self.sprite.frame_names(), ("sit",))

    def test_roles_default_to_first_frame_without_blink(self) -> None:
        self.assertEqual(self.sprite.roles.base, "sit")
        self.assertEqual(self.sprite.roles.blink, ())
        self.assertFalse(self.sprite.roles.has_blink)

    def test_pixmap_does_not_raise(self) -> None:
        pm = self.sprite.pixmap("sit")
        self.assertFalse(pm.isNull())

    def test_base_pixmap_matches_frame(self) -> None:
        self.assertEqual(self.sprite.base_pixmap().size(), self.sprite.pixmap("sit").size())

    def test_frame_size_follows_cell_pixels(self) -> None:
        self.assertEqual(self.sprite.frame_size(1.0), (16, 16))

    def test_plan_at_always_returns_sit(self) -> None:
        player = AnimationPlayer(self.sprite)
        for tick in range(300):
            name, _ = player.plan_at(tick)
            self.assertEqual(name, "sit", f"tick={tick}")

    def test_no_keyerror_when_player_emits(self) -> None:
        """模拟播放器实际取帧路径，确保不会因缺帧 KeyError。"""
        player = AnimationPlayer(self.sprite)
        seen: list[str] = []
        player.frameChanged.connect(lambda pm, off: seen.append(pm.cacheKey()))
        for tick in range(0, 120):
            name, offset = player.plan_at(tick)
            pm = self.sprite.pixmap(name, 1.0)  # 不应抛异常
            self.assertFalse(pm.isNull())
        self.assertTrue(seen == [])  # 未启动定时器，未触发信号
        self.assertEqual(player.is_running(), False)

    def test_start_stop_emits_without_error(self) -> None:
        player = AnimationPlayer(self.sprite)
        frames: list[tuple[int, int]] = []
        player.frameChanged.connect(
            lambda pm, off: frames.append((pm.width(), off.y()))
        )
        player.start()
        try:
            self.assertTrue(player.is_running())
            self.assertEqual(len(frames), 1)  # start 立即发首帧
        finally:
            player.stop()
        self.assertFalse(player.is_running())


# --------------------------------------------------------------------------
# 单帧素材：用真实窗口验证（这是原先会 KeyError: open 的场景）
# --------------------------------------------------------------------------


class SingleFrameWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pet_window_with_single_frame_asset(self) -> None:
        path = make_asset(
            self.tmpdir,
            frames={"sit": single_frame_rows(12)},
            cell_pixels=2,
            state="sit",
        )
        window = PetWindow(sprite_path=path)  # 改前这里必抛 KeyError
        try:
            self.assertFalse(window.mask().isEmpty())
            w, h = window._sprite.frame_size(window._dpr)
            self.assertEqual(window.width(), w)
            self.assertGreaterEqual(window.height(), h)
        finally:
            window.close()

    def test_pet_window_with_legacy_asset(self) -> None:
        window = PetWindow(sprite_path=IDLE_JSON)
        try:
            self.assertFalse(window.mask().isEmpty())
            self.assertEqual(window.width(), 128)
            self.assertEqual(window.height(), 128 + BREATH_AMPLITUDE)
        finally:
            window.close()


# --------------------------------------------------------------------------
# 遮罩：必须是所有帧的并集
# --------------------------------------------------------------------------


class MaskUnionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mask_covers_frames_beyond_base(self) -> None:
        """基帧只有左侧一列，第二帧在最右侧一列；遮罩必须都覆盖。"""
        cell = 4
        width = 10
        base_rows = ["X" + "." * (width - 1)] * 4
        wide_rows = ["." * (width - 1) + "X"] * 4
        path = make_asset(
            self.tmpdir,
            frames={"a": base_rows, "b": wide_rows},
            cell_pixels=cell,
            roles={"base": "a", "blink": ["b"]},
        )
        sprite = SpriteSheet(path)

        region = sprite.mask_region(1.0)
        # 基帧左边缘
        self.assertTrue(region.contains(QPoint(0, 0)))
        # 非基帧右边缘（改前只取基帧遮罩，这里会是 False）
        self.assertTrue(region.contains(QPoint((width - 1) * cell, 0)))
        # 中间空白区不应被覆盖
        self.assertFalse(region.contains(QPoint(width // 2 * cell, 0)))

    def test_mask_union_includes_breath_offsets(self) -> None:
        path = make_asset(
            self.tmpdir,
            frames={"a": single_frame_rows(8)},
            cell_pixels=4,
        )
        sprite = SpriteSheet(path)
        base = sprite.mask_region(1.0)
        merged = sprite.mask_region_with_offsets(1.0, offsets=possible_offsets())

        h = 8 * 4
        self.assertTrue(base.contains(QPoint(0, h - 1)))
        # 下沉 1px 后原底行移到 h，并集必须包含
        self.assertTrue(merged.contains(QPoint(0, h)))
        self.assertGreater(merged.boundingRect().height(), base.boundingRect().height())

    def test_window_mask_covers_all_frames(self) -> None:
        cell = 4
        base_rows = ["X" + "." * 9] * 4
        wide_rows = ["." * 9 + "X"] * 4
        path = make_asset(
            self.tmpdir,
            frames={"a": base_rows, "b": wide_rows},
            cell_pixels=cell,
            roles={"base": "a", "blink": ["b"]},
        )
        window = PetWindow(sprite_path=path)
        try:
            mask = window.mask()
            self.assertFalse(mask.isEmpty())
            self.assertTrue(mask.contains(QPoint(9 * cell, 0)))
        finally:
            window.close()

    def test_legacy_mask_covers_three_frames(self) -> None:
        sprite = SpriteSheet(IDLE_JSON)
        region = sprite.mask_region(1.0)
        self.assertFalse(region.isEmpty())
        # 与旧的"仅 open 帧遮罩"做了比较：并集不应小于单帧
        open_only = QRegion(sprite.pixmap("open").mask())
        self.assertGreaterEqual(region.boundingRect().width(), open_only.boundingRect().width())


# --------------------------------------------------------------------------
# 渲染：整数倍、最近邻、无插值
# --------------------------------------------------------------------------


class NearestNeighbourRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sprite = SpriteSheet(IDLE_JSON)

    def test_device_size_is_integer_multiple(self) -> None:
        cols, rows = self.sprite.grid_size
        for dpr in (1.0, 1.25, 1.5, 2.0):
            cell = self.sprite.device_cell(dpr)
            self.assertEqual(cell, math.floor(self.sprite.cell_pixels * dpr + 0.5))
            pm = self.sprite.pixmap("open", dpr)
            self.assertEqual(pm.width(), cols * cell)
            self.assertEqual(pm.height(), rows * cell)
            self.assertAlmostEqual(pm.devicePixelRatio(), dpr)

    def test_each_block_is_uniform(self) -> None:
        """每格 cell×cell 个设备像素必须完全同色 —— 证明没有平滑插值。"""
        for dpr in (1.0, 1.5, 2.0):
            cell = self.sprite.device_cell(dpr)
            pm = self.sprite.pixmap("open", dpr)
            img = pm.toImage()
            cols, rows = self.sprite.grid_size
            pattern = self.sprite._patterns["open"]
            palette = {k: v.lower() for k, v in self.sprite._palette.items()}

            checked = 0
            for gy in range(rows):
                for gx in range(cols):
                    symbol = pattern[gy][gx]
                    for dy in (0, cell // 2, cell - 1):
                        for dx in (0, cell // 2, cell - 1):
                            color = img.pixelColor(gx * cell + dx, gy * cell + dy)
                            if symbol == ".":
                                self.assertEqual(
                                    color.alpha(), 0,
                                    f"dpr={dpr} ({gx},{gy}) 透明格不透明",
                                )
                            else:
                                self.assertEqual(
                                    color.name().lower(), palette[symbol],
                                    f"dpr={dpr} ({gx},{gy})+({dx},{dy}) 颜色被插值",
                                )
                            checked += 1
            self.assertGreater(checked, 0)

    def test_transparent_background(self) -> None:
        img = self.sprite.pixmap("open", 1.0).toImage()
        alphas = {img.pixelColor(x, y).alpha() for x in range(img.width()) for y in range(img.height())}
        self.assertTrue(alphas.issubset({0, 255}), f"出现半透明像素: {alphas}")

    def test_cache_is_per_dpr(self) -> None:
        a = self.sprite.pixmap("open", 1.0)
        b = self.sprite.pixmap("open", 1.0)
        c = self.sprite.pixmap("open", 2.0)
        self.assertIs(a, b)
        self.assertIsNot(a, c)


# --------------------------------------------------------------------------
# 错误处理：非法 roles / 缺帧
# --------------------------------------------------------------------------


class ContractValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unknown_base_frame_raises_value_error(self) -> None:
        path = make_asset(
            self.tmpdir,
            frames={"sit": single_frame_rows(4)},
            roles={"base": "open"},
        )
        with self.assertRaises(ValueError) as ctx:
            SpriteSheet(path)
        self.assertIn("roles.base", str(ctx.exception))

    def test_unknown_blink_frame_raises_value_error(self) -> None:
        path = make_asset(
            self.tmpdir,
            frames={"sit": single_frame_rows(4)},
            roles={"base": "sit", "blink": ["closed"]},
        )
        with self.assertRaises(ValueError) as ctx:
            SpriteSheet(path)
        self.assertIn("roles.blink", str(ctx.exception))

    def test_unknown_frame_pixmap_raises_keyerror_with_hint(self) -> None:
        path = make_asset(self.tmpdir, frames={"sit": single_frame_rows(4)})
        sprite = SpriteSheet(path)
        with self.assertRaises(KeyError) as ctx:
            sprite.pixmap("open")
        self.assertIn("sit", str(ctx.exception))

    def test_explicit_roles_are_honoured(self) -> None:
        path = make_asset(
            self.tmpdir,
            frames={"idle": single_frame_rows(4), "blink1": single_frame_rows(4)},
            roles={"base": "idle", "blink": ["blink1", "blink1"]},
        )
        sprite = SpriteSheet(path)
        self.assertEqual(sprite.roles.base, "idle")
        self.assertEqual(sprite.roles.frame_at(1), "blink1")
        self.assertEqual(sprite.roles.frame_at(0), "idle")
        self.assertEqual(sprite.roles.frame_at(3), "idle")

    def test_empty_blink_never_blinks(self) -> None:
        roles = FrameRoles(base="sit", blink=())
        for tick in range(200):
            self.assertEqual(plan_frame(tick, roles), "sit")

    def test_single_string_blink_rejected(self) -> None:
        path = make_asset(
            self.tmpdir,
            frames={"sit": single_frame_rows(4)},
            roles={"base": "sit", "blink": "closed"},
        )
        with self.assertRaises(ValueError):
            SpriteSheet(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
