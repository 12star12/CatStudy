"""完成庆祝：全屏礼花 + 一句祝贺。

使用场景：一次专注（番茄钟到点，或手动结束且满 1 分钟）落库成功后，
屏幕上炸开几簇像素礼花，配一句祝贺，几秒后自动消散。

三条取舍（延续 ui/focus_overlay.py 的思路，且与"猫不索取"一致）：

1. **点击穿透、不抢焦点**（``WA_TransparentForMouseEvents`` +
   ``WA_ShowWithoutActivating``）。礼花不是要人操作的东西：不需要瞄准、
   不需要关闭，点穿它之后底下的全屏计时牌照常收到收起手势。
2. **不问"再来一个？"**。庆祝只属于刚完成的那一段专注；推销下一轮是
   养成App的钩子，这里没有按钮、没有倒计时压力，时间一到自己走。
3. **礼花用像素方块**。猫是像素画的，粒子若用抗锯齿圆点会像另一个App
   乱入；方块颗粒与角色同一套视觉语言。

烟花运动学是纯函数（:func:`spawn_burst` / :func:`advance`），不依赖 Qt
对象，可直接单元测试；窗口只负责按 16ms 步进驱动它们。
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

# 总停留时长（毫秒）：礼花主体约 2.2 秒，文字再多陪 2 秒，最后 0.6 秒淡出
DISPLAY_MS: int = 4200
# 粒子步进间隔；16ms ≈ 60fps，足够顺滑，也不空转
TICK_MS: int = 16
# 重力加速度（px/s^2）：让颗粒有"被拽下来"的弧线，而不是直匀速飘
GRAVITY: float = 900.0
# 淡入 / 淡出时长（毫秒）
FADE_IN_MS: int = 220
FADE_OUT_MS: int = 600

# 礼花色板：全部取自猫咪素材与主题（橘系为主，点缀完成绿与玫瑰粉），
# 深浅背景下都可见。
FIREWORK_COLORS: tuple[tuple[int, int, int], ...] = (
    (0xFB, 0xB0, 0x54),  # 主体橘（Palette.ACCENT）
    (0xEB, 0x7E, 0x35),  # 暗橘（Palette.ACCENT_DARK）
    (0xFF, 0xF6, 0xE6),  # 暖白
    (0x8F, 0xCF, 0x9B),  # 完成绿（focus_overlay 的 TEXT_DONE）
    (0xF2, 0x93, 0x91),  # 玫瑰粉（Palette.DANGER_BORDER）
)

# 文字颜色与阴影（同 focus_overlay：暖白 + 近黑暖褐阴影，任何桌面都可读）
TEXT_MAIN = QColor(0xFF, 0xF6, 0xE6)
TEXT_SHADOW = QColor(0x17, 0x12, 0x10, 190)

# 文字纵向位置（相对屏幕高）
RATIO_HEADLINE: float = 0.40
GAP_SUB: float = 0.075

# 爆点计划：(触发时刻秒, 横向位置比例, 纵向位置比例)
BURST_SCHEDULE: tuple[tuple[float, float, float], ...] = (
    (0.00, 0.50, 0.34),
    (0.45, 0.30, 0.28),
    (0.90, 0.70, 0.30),
    (1.30, 0.50, 0.22),
)


@dataclass(frozen=True)
class Particle:
    """一颗礼花颗粒。颜色存 RGB 元组而非 QColor：纯数据可脱离 Qt 测试。"""

    x: float
    y: float
    vx: float
    vy: float
    color: tuple[int, int, int]
    ttl: float          # 总寿命（秒）
    life: float         # 剩余寿命（秒）
    size: int           # 方块边长（px），像素风


def spawn_burst(
    cx: float,
    cy: float,
    rng: random.Random,
    *,
    count: int = 70,
    speed_min: float = 150.0,
    speed_max: float = 430.0,
    ttl_min: float = 0.9,
    ttl_max: float = 1.8,
    size_min: int = 3,
    size_max: int = 6,
) -> list[Particle]:
    """在 (cx, cy) 处炸开一簇颗粒：径向随机速度 + 随机寿命。"""
    particles: list[Particle] = []
    for _ in range(count):
        angle = rng.uniform(0.0, 2.0 * math.pi)
        speed = rng.uniform(speed_min, speed_max)
        color = rng.choice(FIREWORK_COLORS)
        particles.append(
            Particle(
                x=cx,
                y=cy,
                vx=math.cos(angle) * speed,
                vy=math.sin(angle) * speed,
                color=color,
                ttl=rng.uniform(ttl_min, ttl_max),
                life=0.0,  # 由 advance 统一置为 ttl
                size=rng.randint(size_min, size_max),
            )
        )
    return [
        Particle(p.x, p.y, p.vx, p.vy, p.color, p.ttl, p.ttl, p.size)
        for p in particles
    ]


def advance(
    particles: list[Particle],
    dt: float,
    gravity: float = GRAVITY,
) -> list[Particle]:
    """推进 dt 秒：抛物线运动 + 寿命衰减，过期的颗粒被移除。

    返回**新列表**，不改传入列表（纯函数，测试无需关心顺序副作用）。
    """
    moved: list[Particle] = []
    for p in particles:
        remaining = p.life - dt
        if remaining <= 0.0:
            continue
        moved.append(
            Particle(
                x=p.x + p.vx * dt,
                y=p.y + p.vy * dt,
                vx=p.vx,
                vy=p.vy + gravity * dt,
                color=p.color,
                ttl=p.ttl,
                life=remaining,
                size=p.size,
            )
        )
    return moved


class CelebrationOverlay(QWidget):
    """铺满所有屏幕并集的礼花窗口。不接收任何输入，自动消散。"""

    def __init__(
        self,
        *,
        lifetime_ms: int = DISPLAY_MS,
        tick_ms: int = TICK_MS,
        rng: random.Random | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._lifetime_ms = int(lifetime_ms)
        self._tick_ms = int(tick_ms)
        self._rng = rng if rng is not None else random.Random()
        self._particles: list[Particle] = []
        self._schedule: list[tuple[float, float, float]] = list(BURST_SCHEDULE)
        self._started_at: float = 0.0
        self._last_step: float = 0.0
        self._headline: str = ""
        self._subtext: str = ""

        self._setup_window()
        self._clock = QTimer(self)
        self._clock.setInterval(self._tick_ms)
        self._clock.timeout.connect(self._step)

    # ------------------------------------------------------------------
    # 窗口
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # 点击穿透：礼花底下还有什么（计时牌、桌面图标），点谁都照常
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # 不抢焦点：弹出瞬间正在打字的人不应被夺走输入法
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("CatStudy 庆祝")

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def celebrate(self, headline: str, subtext: str) -> None:
        """放一场礼花。重复调用会重置并重新开始。"""
        self._headline = headline or ""
        self._subtext = subtext or ""
        self._particles = []
        self._schedule = list(BURST_SCHEDULE)
        self._fill_screens()
        self._started_at = time.monotonic()
        self._last_step = self._started_at
        self.show()
        self.raise_()
        self._clock.start()

    @property
    def headline(self) -> str:
        return self._headline

    @property
    def subtext(self) -> str:
        return self._subtext

    @property
    def particle_count(self) -> int:
        """当前屏幕上的颗粒数（测试用）。"""
        return len(self._particles)

    def dismiss(self) -> None:
        """立即撤掉（不停任何东西——这里本来就没有会话）。"""
        self._clock.stop()
        self.hide()

    # ------------------------------------------------------------------
    # 动画
    # ------------------------------------------------------------------

    def _step(self) -> None:
        now = time.monotonic()
        elapsed_ms = (now - self._started_at) * 1000.0
        if elapsed_ms >= self._lifetime_ms:
            self.dismiss()
            return
        dt = now - self._last_step
        self._last_step = now

        # 触发到达时刻的爆点（while 处理极小 tick 下同一时刻多个爆点）
        while self._schedule and self._schedule[0][0] <= elapsed_ms / 1000.0:
            _, fx, fy = self._schedule.pop(0)
            self._particles.extend(
                spawn_burst(
                    fx * self.width(),
                    fy * self.height(),
                    self._rng,
                )
            )
        self._particles = advance(self._particles, dt)
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _fade_alpha(self, elapsed_ms: float) -> float:
        """整体淡入淡出系数（0~1）。"""
        if elapsed_ms < FADE_IN_MS:
            return elapsed_ms / FADE_IN_MS
        tail_start = self._lifetime_ms - FADE_OUT_MS
        if elapsed_ms > tail_start:
            return max(0.0, (self._lifetime_ms - elapsed_ms) / FADE_OUT_MS)
        return 1.0

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        elapsed_ms = (time.monotonic() - self._started_at) * 1000.0
        alpha = self._fade_alpha(elapsed_ms)
        if alpha <= 0.0 and not self._particles:
            return

        painter = QPainter(self)
        try:
            for p in self._particles:
                # 像素方块 + 随寿命线性淡出
                life_ratio = max(0.0, p.life / p.ttl)
                color = QColor(*p.color, int(255 * alpha * life_ratio))
                painter.fillRect(
                    int(p.x), int(p.y), p.size, p.size, color
                )
            if self._headline:
                self._paint_text(painter, alpha)
        finally:
            painter.end()

    def _paint_text(self, painter: QPainter, alpha: float) -> None:
        height = max(self.height(), 1)
        headline_font = QFont()
        headline_font.setBold(True)
        headline_font.setPixelSize(int(height * 0.085))
        sub_font = QFont()
        sub_font.setPixelSize(max(int(height * 0.036), 14))

        painter.setFont(headline_font)
        metrics = painter.fontMetrics()
        hx = (self.width() - metrics.horizontalAdvance(self._headline)) // 2
        hy = int(height * RATIO_HEADLINE)
        self._draw_with_shadow(
            painter, hx, hy, self._headline, TEXT_SHADOW, TEXT_MAIN, alpha
        )

        if self._subtext:
            painter.setFont(sub_font)
            sub_metrics = painter.fontMetrics()
            sx = (self.width() - sub_metrics.horizontalAdvance(self._subtext)) // 2
            sy = hy + int(height * GAP_SUB)
            self._draw_with_shadow(
                painter, sx, sy, self._subtext, TEXT_SHADOW, TEXT_MAIN, alpha
            )

    def _draw_with_shadow(
        self,
        painter: QPainter,
        x: int,
        y: int,
        text: str,
        shadow: QColor,
        main: QColor,
        alpha: float,
    ) -> None:
        shadow_alpha = QColor(shadow)
        shadow_alpha.setAlpha(int(shadow.alpha() * alpha))
        main_alpha = QColor(main)
        main_alpha.setAlpha(int(255 * alpha))
        painter.setPen(shadow_alpha)
        painter.drawText(x, y + 3, text)
        painter.setPen(main_alpha)
        painter.drawText(x, y, text)

    # ------------------------------------------------------------------
    # 几何
    # ------------------------------------------------------------------

    def _fill_screens(self) -> None:
        """覆盖所有屏幕的并集（与 focus_overlay 同一套规则）。"""
        screens = QGuiApplication.screens()
        if not screens:
            self.setGeometry(0, 0, 1280, 720)
            return
        rect = screens[0].geometry()
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        self.setGeometry(rect)
