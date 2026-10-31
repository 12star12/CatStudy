"""精灵素材加载与动画调度模块（第三阶段）。

- SpriteSheet：从 assets/cat/ 下的 JSON 素材读取像素图案，
  用 QPainter 预渲染为 QPixmap 并缓存，运行时只切换引用、不实时绘制；
- AnimationPlayer：QTimer 驱动的帧调度器，按时间轴计算当前帧与
  呼吸偏移，通过 frameChanged 信号通知窗口。

未来添加睡觉、走路、开心等状态时，只需新增对应 JSON 素材并切换
SpriteSheet，窗口交互逻辑无需改动。
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap

# 项目根目录与猫咪素材目录（本文件位于 ui/ 下）
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
CAT_ASSETS_DIR: Path = PROJECT_ROOT / "assets" / "cat"

# 动画时间轴参数（单位：tick，每 tick 100ms）
TICK_MS: int = 100
BLINK_INTERVAL: int = 34  # 每 3.4 秒一次眨眼，避免过于频繁
BLINK_SEQUENCE: tuple[str, ...] = ("half", "closed", "closed", "half")
BREATH_CYCLE: int = 20  # 呼吸周期 2 秒
BREATH_DOWN_MIN: int = 6  # 身体下沉（dy=1）的 tick 区间
BREATH_DOWN_MAX: int = 13


class SpriteSheet:
    """加载并渲染一个动画状态（如 idle）的全部像素帧。"""

    def __init__(self, json_path: Path) -> None:
        with open(json_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)

        self.cell_pixels: int = int(data["cell_pixels"])
        self.state_name: str = str(data.get("state", json_path.stem))
        self._palette: dict[str, str] = dict(data["palette"])
        self._patterns: dict[str, tuple[str, ...]] = {
            name: tuple(lines) for name, lines in data["frames"].items()
        }
        self._cache: dict[str, QPixmap] = {}
        self._validate()

    def _validate(self) -> None:
        """校验所有帧尺寸一致，且图案字符都能在调色板中找到。"""
        if not self._patterns:
            raise ValueError("素材文件中没有任何帧")
        first = next(iter(self._patterns.values()))
        rows, cols = len(first), len(first[0])
        for name, lines in self._patterns.items():
            if len(lines) != rows or any(len(line) != cols for line in lines):
                raise ValueError(f"帧 {name} 尺寸不一致，应为 {rows}x{cols}")
            for line in lines:
                for symbol in line:
                    if symbol != "." and symbol not in self._palette:
                        raise ValueError(f"帧 {name} 含未定义颜色字符: {symbol}")

    @property
    def frame_size(self) -> tuple[int, int]:
        """返回单帧的实际像素尺寸（宽, 高）。"""
        first = next(iter(self._patterns.values()))
        return (
            len(first[0]) * self.cell_pixels,
            len(first) * self.cell_pixels,
        )

    def frame_names(self) -> tuple[str, ...]:
        return tuple(self._patterns)

    def pixmap(self, name: str) -> QPixmap:
        """返回指定帧的 QPixmap，首次访问时渲染并缓存。"""
        if name not in self._patterns:
            raise KeyError(f"素材中不存在帧: {name}")
        if name not in self._cache:
            self._cache[name] = self._render(self._patterns[name])
        return self._cache[name]

    def _render(self, pattern: tuple[str, ...]) -> QPixmap:
        """把字符图案逐格绘制为带透明背景的 QPixmap。"""
        rows, cols = len(pattern), len(pattern[0])
        pixmap = QPixmap(cols * self.cell_pixels, rows * self.cell_pixels)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        try:
            for row, line in enumerate(pattern):
                for col, symbol in enumerate(line):
                    color = self._palette.get(symbol)
                    if color is None:
                        continue
                    painter.fillRect(
                        col * self.cell_pixels,
                        row * self.cell_pixels,
                        self.cell_pixels,
                        self.cell_pixels,
                        QColor(color),
                    )
        finally:
            painter.end()
        return pixmap


class AnimationPlayer(QObject):
    """按固定 tick 推进动画，输出当前帧 QPixmap 与呼吸偏移。"""

    frameChanged = Signal(QPixmap, QPoint)

    def __init__(self, sprite: SpriteSheet, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sprite = sprite
        self._tick_count: int = 0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def plan_at(tick: int) -> tuple[str, QPoint]:
        """纯函数：返回指定 tick 的帧名与绘制偏移，不依赖事件循环。"""
        blink_phase = tick % BLINK_INTERVAL
        if 1 <= blink_phase <= len(BLINK_SEQUENCE):
            frame_name = BLINK_SEQUENCE[blink_phase - 1]
        else:
            frame_name = "open"

        breath_phase = tick % BREATH_CYCLE
        dy = 1 if BREATH_DOWN_MIN <= breath_phase <= BREATH_DOWN_MAX else 0
        return frame_name, QPoint(0, dy)

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
        self.frameChanged.emit(self._sprite.pixmap(frame_name), offset)
