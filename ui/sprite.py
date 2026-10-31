"""精灵素材加载与动画调度模块（第三阶段 / 帧契约解耦版）。

设计要点
--------
- **帧名不再硬编码**：素材通过 JSON 的 ``roles`` 字段声明"哪个是静止帧、
  哪一串是眨眼帧"，代码里不出现任何具体帧名字面量；
- **单帧素材可用**：素材只有一帧（如 ``sit``）时自动退化为"静止帧 + 无眨眼"；
- **遮罩取全帧并集**：``mask_region()`` 合并所有帧的轮廓，未来加摆尾/抬爪
  帧时超出区域的像素不会被窗口遮罩裁掉；
- **整数倍最近邻渲染**：按 ``cell_pixels × devicePixelRatio`` 取整得到每格
  的设备像素数，逐格 fillRect，并关闭抗锯齿与平滑变换，永不出现插值模糊。
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QRegion

# 项目根目录与猫咪素材目录（本文件位于 ui/ 下）
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
CAT_ASSETS_DIR: Path = PROJECT_ROOT / "assets" / "cat"

# 动画时间轴参数（单位：tick，每 tick 100ms）
TICK_MS: int = 100
BLINK_INTERVAL: int = 34  # 每 3.4 秒一次眨眼，避免过于频繁
BREATH_CYCLE: int = 20  # 呼吸周期 2 秒
BREATH_DOWN_MIN: int = 6  # 身体下沉（dy=1）的 tick 区间
BREATH_DOWN_MAX: int = 13
BREATH_AMPLITUDE: int = 1  # 下沉幅度（像素）


@dataclass(frozen=True)
class FrameRoles:
    """素材声明的帧角色：静止帧 + 眨眼帧序列。

    ``blink`` 为空表示该素材没有眨眼动画（例如只有一帧的 ``sit``）。
    """

    base: str
    blink: tuple[str, ...] = ()

    @property
    def has_blink(self) -> bool:
        return bool(self.blink)

    def frame_at(self, tick: int, interval: int = BLINK_INTERVAL) -> str:
        """返回指定 tick 应显示的帧名（纯计算，不依赖事件循环）。"""
        if not self.blink:
            return self.base
        phase = tick % interval
        if 1 <= phase <= len(self.blink):
            return self.blink[phase - 1]
        return self.base


def plan_offset(tick: int) -> QPoint:
    """纯函数：返回指定 tick 的呼吸偏移。"""
    phase = tick % BREATH_CYCLE
    dy = BREATH_AMPLITUDE if BREATH_DOWN_MIN <= phase <= BREATH_DOWN_MAX else 0
    return QPoint(0, dy)


def possible_offsets() -> tuple[QPoint, ...]:
    """时间轴上可能出现过的全部偏移（用于计算窗口遮罩）。"""
    dys = {0}
    if BREATH_DOWN_MIN <= BREATH_DOWN_MAX:
        dys.add(BREATH_AMPLITUDE)
    return tuple(QPoint(0, dy) for dy in sorted(dys))


def plan_frame(tick: int, roles: FrameRoles, interval: int = BLINK_INTERVAL) -> str:
    """纯函数：返回指定 tick 的帧名。"""
    return roles.frame_at(tick, interval)


class SpriteSheet:
    """加载并渲染一个动画状态（如 idle）的全部像素帧。"""

    def __init__(self, json_path: Path) -> None:
        self.path: Path = Path(json_path)
        with open(self.path, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        self.cell_pixels: int = int(data["cell_pixels"])
        self.state_name: str = str(data.get("state", self.path.stem))
        self._palette: dict[str, str] = dict(data["palette"])
        self._patterns: "OrderedDict[str, tuple[str, ...]]" = OrderedDict(
            (str(name), tuple(lines)) for name, lines in data["frames"].items()
        )
        self._cache: dict[tuple[str, float], QPixmap] = {}
        self._validate()
        self._roles = self._resolve_roles(data.get("roles"))

    # ---------- 校验与角色解析 ----------

    def _validate(self) -> None:
        """校验所有帧尺寸一致，且图案字符都能在调色板中找到。"""
        if not self._patterns:
            raise ValueError(f"素材文件中没有任何帧: {self.path}")
        first = next(iter(self._patterns.values()))
        rows, cols = len(first), len(first[0])
        for name, lines in self._patterns.items():
            if len(lines) != rows or any(len(line) != cols for line in lines):
                raise ValueError(f"帧 {name} 尺寸不一致，应为 {rows}x{cols}")
            for line in lines:
                for symbol in line:
                    if symbol != "." and symbol not in self._palette:
                        raise ValueError(f"帧 {name} 含未定义颜色字符: {symbol}")

    def _resolve_roles(self, raw: object) -> FrameRoles:
        """从素材的 ``roles`` 字段解析帧角色；缺省时安全退化。

        缺省规则（不依赖任何具体帧名）：
        - ``base`` = 素材中的第一帧；
        - ``blink`` = 空，即不做眨眼。
        """
        names = self.frame_names()
        if not isinstance(raw, dict):
            return FrameRoles(base=names[0])

        base = str(raw.get("base") or names[0])
        if base not in self._patterns:
            raise ValueError(
                f"roles.base 指向不存在的帧: {base!r}，可选: {list(names)}"
            )

        blink_raw = raw.get("blink") or ()
        if isinstance(blink_raw, str):
            raise ValueError("roles.blink 必须是帧名数组，不能是单个字符串")
        blink = tuple(str(n) for n in blink_raw)
        missing = [n for n in blink if n not in self._patterns]
        if missing:
            raise ValueError(
                f"roles.blink 含不存在的帧: {missing}，可选: {list(names)}"
            )
        return FrameRoles(base=base, blink=blink)

    # ---------- 基本信息 ----------

    @property
    def roles(self) -> FrameRoles:
        return self._roles

    @property
    def base_frame(self) -> str:
        """静止帧名（不眨眼时显示的帧）。"""
        return self._roles.base

    @property
    def grid_size(self) -> tuple[int, int]:
        """网格尺寸（列, 行）。"""
        first = next(iter(self._patterns.values()))
        return len(first[0]), len(first)

    def frame_names(self) -> tuple[str, ...]:
        return tuple(self._patterns)

    def device_cell(self, dpr: float = 1.0) -> int:
        """每格在物理设备上占多少像素（取整，保证块边缘锐利）。"""
        return max(1, int(round(self.cell_pixels * float(dpr))))

    def frame_size(self, dpr: float = 1.0) -> tuple[int, int]:
        """单帧的逻辑像素尺寸（宽, 高），供窗口布局使用。"""
        cols, rows = self.grid_size
        cell = self.device_cell(dpr)
        return (round(cols * cell / dpr), round(rows * cell / dpr))

    # ---------- 渲染 ----------

    def pixmap(self, name: str, dpr: float = 1.0) -> QPixmap:
        """返回指定帧的 QPixmap，首次访问时按 DPR 渲染并缓存。

        渲染按 ``cell_pixels × dpr`` 取整后的整数格宽逐格填充并设置
        DevicePixelRatio，因此在高分屏下仍是 1:1 的整数倍放大，不会被平滑插值。
        """
        if name not in self._patterns:
            raise KeyError(
                f"素材中不存在帧: {name!r}，可选: {list(self._patterns)}"
            )
        key = (name, round(float(dpr), 3))
        if key not in self._cache:
            self._cache[key] = self._render(self._patterns[name], float(dpr))
        return self._cache[key]

    def base_pixmap(self, dpr: float = 1.0) -> QPixmap:
        """静止帧的 QPixmap（窗口初始化用）。"""
        return self.pixmap(self._roles.base, dpr)

    def _render(self, pattern: tuple[str, ...], dpr: float = 1.0) -> QPixmap:
        """把字符图案逐格绘制为带透明背景的 QPixmap（无抗锯齿）。"""
        rows, cols = len(pattern), len(pattern[0])
        cell = self.device_cell(dpr)
        pixmap = QPixmap(cols * cell, rows * cell)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.setPen(Qt.PenStyle.NoPen)
            for row, line in enumerate(pattern):
                for col, symbol in enumerate(line):
                    color = self._palette.get(symbol)
                    if color is None:
                        continue
                    painter.fillRect(
                        col * cell,
                        row * cell,
                        cell,
                        cell,
                        QColor(color),
                    )
        finally:
            painter.end()

        pixmap.setDevicePixelRatio(float(dpr))
        return pixmap

    # ---------- 遮罩 ----------

    def _row_runs(self) -> list[list[tuple[int, int]]]:
        """所有帧轮廓的并集，按行合并为连续区间 ``[(x0, x1), ...]``。"""
        cols, rows = self.grid_size
        merged = [[False] * cols for _ in range(rows)]
        for pattern in self._patterns.values():
            for y, line in enumerate(pattern):
                for x, symbol in enumerate(line):
                    if symbol != ".":
                        merged[y][x] = True

        runs: list[list[tuple[int, int]]] = []
        for y in range(rows):
            row_runs: list[tuple[int, int]] = []
            x = 0
            while x < cols:
                if not merged[y][x]:
                    x += 1
                    continue
                start = x
                while x < cols and merged[y][x]:
                    x += 1
                row_runs.append((start, x - 1))
            runs.append(row_runs)
        return runs

    def mask_region(self, dpr: float = 1.0) -> QRegion:
        """返回并集轮廓的窗口遮罩区域（逻辑坐标）。

        直接由字符网格推导，与 DPR 无关，避免从 QPixmap.mask() 取设备
        像素导致高 DPI 下遮罩尺寸错位。
        """
        cell = self.device_cell(dpr) / float(dpr)  # 每格的逻辑像素
        region = QRegion()
        for y, row_runs in enumerate(self._row_runs()):
            top = round(y * cell)
            bottom = round((y + 1) * cell)
            height = max(1, bottom - top)
            for x0, x1 in row_runs:
                left = round(x0 * cell)
                right = round((x1 + 1) * cell)
                region = region.united(
                    QRegion(QRect(left, top, max(1, right - left), height))
                )
        return region

    def mask_region_with_offsets(
        self, dpr: float = 1.0, offsets: Iterable[QPoint] | None = None
    ) -> QRegion:
        """全帧轮廓并集 × 全部呼吸偏移的合并遮罩。"""
        base = self.mask_region(dpr)
        region = QRegion(base)
        for off in offsets if offsets is not None else possible_offsets():
            if off.x() or off.y():
                region = region.united(base.translated(off.x(), off.y()))
        return region


class AnimationPlayer(QObject):
    """按固定 tick 推进动画，输出当前帧 QPixmap 与呼吸偏移。"""

    frameChanged = Signal(QPixmap, QPoint)

    def __init__(
        self,
        sprite: SpriteSheet,
        parent: QObject | None = None,
        blink_interval: int = BLINK_INTERVAL,
        dpr: float = 1.0,
    ) -> None:
        super().__init__(parent)
        self._sprite = sprite
        self._roles: FrameRoles = sprite.roles
        self._blink_interval: int = int(blink_interval)
        self._dpr: float = float(dpr)
        self._tick_count: int = 0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # ---------- 属性 ----------

    @property
    def sprite(self) -> SpriteSheet:
        return self._sprite

    @property
    def roles(self) -> FrameRoles:
        return self._roles

    @property
    def dpr(self) -> float:
        return self._dpr

    def set_device_pixel_ratio(self, dpr: float) -> None:
        self._dpr = float(dpr)

    @property
    def tick(self) -> int:
        return self._tick_count

    # ---------- 时间轴（纯函数，便于测试） ----------

    def plan_at(self, tick: int) -> tuple[str, QPoint]:
        """返回指定 tick 的帧名与绘制偏移。"""
        return (
            plan_frame(tick, self._roles, self._blink_interval),
            plan_offset(tick),
        )

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """立即发射第一帧并启动定时器。"""
        self._emit_current()
        self._timer.start(TICK_MS)

    def stop(self) -> None:
        self._timer.stop()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        self._tick_count += 1
        self._emit_current()

    def _emit_current(self) -> None:
        frame_name, offset = self.plan_at(self._tick_count)
        self.frameChanged.emit(self._sprite.pixmap(frame_name, self._dpr), offset)
