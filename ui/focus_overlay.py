"""全屏专注计时器。

使用场景决定了这里的每一个设计：人**不在**电脑前，可能在三米外的书桌上翻书，
只需要抬头一眼看到"还剩多久"。所以这不是一个可操作的界面，而是一块牌子。

三条取舍：

1. **不做按钮**。屏幕上放按钮，人就得走近、瞄准、点它——那不如看猫旁边的气泡。
   收起用 Esc 或点一下任意处，两个动作都不需要瞄准。
2. **深色半透明而不是纯黑或纯色**。纯黑会让人以为显示器坏了或系统待机了；
   纯色（比如橘色）在全屏面积上非常刺眼，看五分钟眼睛就累。半透明既压住了
   桌面上的图标和通知（这是"专注"的关键），又保留一点点层次感。
3. **弹出后的头 0.8 秒忽略点击**。窗口出现时鼠标本来就停在屏幕上，第一次点击
   常常是"我还没反应过来"的误触，不设冷却会让人觉得"怎么闪一下就没了"。

计时状态永远归 ``FocusTimer`` 管，本模块只读不写：收起窗口不等于停表，
这也是全屏牌子的意义——它只是把同一份时间换个尺寸显示。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import QWidget

from core.timer import FocusTimer, TimerMode, TimerState
from ui.theme import Palette

# 刷新间隔。计时只精确到秒，200ms 足够让秒数变化看起来是"立刻跳"，
# 又不至于为了画一块牌子每秒重绘几十次。
REFRESH_MS: int = 200

# 弹出后忽略点击的时长（毫秒）
CLICK_GUARD_MS: int = 800

# 完成态在屏幕上停留多久后自动收起（毫秒）
FINISHED_HOLD_MS: int = 3500

# 背景与前景
BACKDROP = QColor(0x17, 0x12, 0x10, 238)   # 近黑暖褐，留一点透明看见桌面轮廓
TEXT_MAIN = QColor(0xFF, 0xF6, 0xE6)       # 暖白：比纯白柔和，长时间看不刺眼
TEXT_SUB = QColor(0xC9, 0xA9, 0x8D)        # 次级说明
TEXT_DIM = QColor(0xA0, 0x8B, 0x79)        # 底部提示，压暗但还读得出来
TEXT_DONE = QColor(0x8F, 0xCF, 0x9B)       # 完成态
TEXT_PAUSED = QColor(0xB3, 0xA5, 0x99)     # 暂停：数字退到后面去

# 纵向排布（相对主屏高度）
RATIO_CLOCK: float = 0.50          # 大数字的中心线
GAP_LABEL: float = 0.055           # 模式标签与数字顶部的距离
GAP_SUBJECT: float = 0.045         # 数字底部与科目之间的距离
GAP_PROGRESS: float = 0.030        # 科目与进度条之间的距离
RATIO_HINT: float = 0.86           # 底部提示（固定贴底，不参与上面这套相对布局）

# 大数字占屏高的比例，以及横向最多占多宽
CLOCK_HEIGHT_RATIO: float = 0.32
CLOCK_MAX_WIDTH_RATIO: float = 0.86


class FocusOverlay(QWidget):
    """覆盖整个桌面的大号计时牌。"""

    # 窗口被收起（Esc / 点击 / 完成自动收起）。计时本身不受影响。
    dismissed = Signal()

    def __init__(self, timer: FocusTimer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._timer = timer
        self._subject: str = ""
        # 弹出时刻，用于点击冷却
        self._shown_at: float = 0.0
        # 完成态开始展示的时刻；None 表示还没进入完成态
        self._finished_at: float | None = None

        self._setup_window()
        self._clock = QTimer(self)
        self._clock.setInterval(REFRESH_MS)
        self._clock.timeout.connect(self.refresh)

    # ------------------------------------------------------------------
    # 窗口
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        """无边框、置顶、透明底。

        用 ``Qt.Window`` 而不是 ``Qt.Tool``：Tool 窗口没有任务栏条目，
        但某些 Win32 组合下会被压到普通窗口之下，全屏时反而盖不住。
        多一个任务栏条目在这场合作里无所谓——它也被自己盖住了。
        """
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("CatStudy 专注计时")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def set_subject(self, subject: str) -> None:
        self._subject = subject or ""
        self.update()

    @property
    def subject(self) -> str:
        return self._subject

    def show_fullscreen(self) -> None:
        """铺满所有屏幕并显示。

        几何取**所有屏幕的并集**：双屏时两块屏都会被盖住，视线扫到哪一侧都
        不会看到还亮着的桌面。文字仍然画在主屏中心（见 ``_content_rect``），
        否则居中位置会落在两块屏的接缝上，反而看不清。
        """
        self._fill_screens()
        self._finished_at = None
        self.refresh()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._shown_at = time.monotonic()
        self._clock.start()

    def dismiss(self) -> None:
        """收起（不停表）。"""
        if not self.isVisible():
            return
        self._clock.stop()
        self.hide()
        self.dismissed.emit()

    def refresh(self) -> None:
        """按计时器当前状态刷新；空闲或已超时停留完成态时自动收起。"""
        state = self._timer.state
        if state is TimerState.IDLE:
            # 会话被放弃（reset）后没有可显示的内容，直接撤掉
            self.dismiss()
            return
        if state is TimerState.FINISHED:
            if self._finished_at is None:
                self._finished_at = time.monotonic()
            elif (time.monotonic() - self._finished_at) * 1000 >= FINISHED_HOLD_MS:
                self.dismiss()
                return
        self.update()

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------

    def _fill_screens(self) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            self.setGeometry(0, 0, 1280, 720)
            return
        geometry = screens[0].geometry()
        for screen in screens[1:]:
            geometry = geometry.united(screen.geometry())
        self.setGeometry(geometry)

    def _content_rect(self) -> QRect:
        """文字绘制区域：主屏，换算到本窗口坐标系。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return self.rect()
        geo = screen.geometry()
        return QRect(geo.x() - self.x(), geo.y() - self.y(), geo.width(), geo.height())

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _clock_font(self, text: str, area: QRect) -> QFont:
        """按可用宽高拟合大数字字号。

        不同分辨率下写死字号必然出事：1080p 上合适的 200px，在 2K 屏上会显得
        很小，在 1366×768 上会溢出。这里从"屏高的 26%"起步，按实际文本宽度
        逐步缩小，直到放得下。
        """
        font = QFont(self.font())
        font.setBold(True)
        size = max(24, int(area.height() * CLOCK_HEIGHT_RATIO))
        max_width = int(area.width() * CLOCK_MAX_WIDTH_RATIO)
        while size > 16:
            font.setPixelSize(size)
            if QFontMetrics(font).horizontalAdvance(text) <= max_width:
                break
            size -= 4
        font.setPixelSize(size)
        return font

    def _sub_font(self, height_ratio: float, area: QRect) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(max(13, int(area.height() * height_ratio)))
        return font

    def _layout(self, area: QRect, font: QFont) -> dict[str, QRect]:
        """以数字的位置为锚点排出整屏布局。

        不能用"每行一个固定比例"：数字字号随分辨率变化，字号一大就会压到
        下面那行字上（实测 1440p 下"已完成"三个字直接盖住了科目）。改成
        先量出数字矩形，再往上下推，字号怎么变都不会撞。
        """
        clock_height = QFontMetrics(font).height()
        clock = QRect(
            area.x(),
            area.y() + int(area.height() * RATIO_CLOCK) - clock_height // 2,
            area.width(),
            clock_height,
        )
        label_gap = int(area.height() * GAP_LABEL)
        subject_gap = int(area.height() * GAP_SUBJECT)
        progress_gap = int(area.height() * GAP_PROGRESS)

        label = QRect(area.x(), clock.top() - label_gap - 44, area.width(), 44)
        subject = QRect(area.x(), clock.bottom() + subject_gap, area.width(), 52)
        progress = QRect(
            area.x(), subject.bottom() + progress_gap, area.width(), 0
        )
        hint = QRect(
            area.x(), area.y() + int(area.height() * RATIO_HINT), area.width(), 44
        )
        return {
            "clock": clock,
            "label": label,
            "subject": subject,
            "progress": progress,
            "hint": hint,
        }

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt 命名风格)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), BACKDROP)

        area = self._content_rect()
        state = self._timer.state
        finished = state is TimerState.FINISHED
        paused = state is TimerState.PAUSED

        if finished:
            self._paint_finished(painter, area)
        else:
            self._paint_running(painter, area, paused)

        painter.end()

    def _paint_running(self, painter: QPainter, area: QRect, paused: bool) -> None:
        clock_text = self._timer.display_text()

        if self._timer.mode is TimerMode.POMODORO:
            label = f"番茄钟 · {self._timer.pomodoro_seconds // 60} 分钟"
        else:
            label = "正计时"

        font = self._clock_font(clock_text, area)
        rects = self._layout(area, font)

        painter.setFont(self._sub_font(0.028, area))
        painter.setPen(TEXT_SUB)
        painter.drawText(
            rects["label"],
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            label,
        )

        painter.setFont(font)
        painter.setPen(TEXT_PAUSED if paused else TEXT_MAIN)
        painter.drawText(
            rects["clock"],
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            clock_text,
        )

        # 科目（暂停时补一句状态，免得以为程序卡住了）
        subject_line = self._subject or "专注"
        if paused:
            subject_line = f"已暂停 · {subject_line}"
        painter.setFont(self._sub_font(0.026, area))
        painter.setPen(TEXT_SUB)
        painter.drawText(
            rects["subject"],
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            subject_line,
        )

        if self._timer.mode is TimerMode.POMODORO:
            self._paint_progress(painter, area, rects["progress"].top())

        painter.setFont(self._sub_font(0.018, area))
        painter.setPen(TEXT_DIM)
        painter.drawText(
            rects["hint"],
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "Esc 或点击任意处收起，计时不会停",
        )

    def _paint_progress(self, painter: QPainter, area: QRect, y: int) -> None:
        """底部的细进度条：一眼看出"走到哪儿了"，比读数字更快。"""
        ratio = self.progress_ratio()
        width = int(area.width() * 0.44)
        height = max(6, int(area.height() * 0.006))
        x = area.x() + (area.width() - width) // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 34))
        painter.drawRoundedRect(QRect(x, y, width, height), height / 2, height / 2)
        filled = int(width * ratio)
        if filled > 0:
            painter.setBrush(QColor(Palette.ROSE))
            painter.drawRoundedRect(QRect(x, y, filled, height), height / 2, height / 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def progress_ratio(self) -> float:
        """番茄钟已走过的比例（0.0~1.0）；正计时没有终点，返回 0。

        单独提出来是为了能测：进度条画得对不对，肉眼很难判断几像素的差别，
        但换算出来的比例是可以断言的。
        """
        if self._timer.mode is not TimerMode.POMODORO:
            return 0.0
        total = max(1, self._timer.pomodoro_seconds)
        return min(1.0, max(0.0, self._timer.elapsed_seconds() / total))

    def _paint_finished(self, painter: QPainter, area: QRect) -> None:
        text = "已完成"
        font = self._clock_font(text, area)
        # 汉字是满格的，同样字号下比数字"重"得多；缩一成视觉重量才对得上
        font.setPixelSize(int(font.pixelSize() * 0.88))
        rects = self._layout(area, font)

        painter.setFont(font)
        painter.setPen(TEXT_DONE)
        painter.drawText(
            rects["clock"],
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

        minutes = int(self._timer.elapsed_seconds()) // 60
        detail = f"{minutes} 分钟" if minutes >= 1 else "不足 1 分钟"
        if self._subject:
            detail = f"{self._subject} · {detail}"
        painter.setFont(self._sub_font(0.026, area))
        painter.setPen(TEXT_SUB)
        painter.drawText(
            rects["subject"],
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            detail,
        )

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # 刚弹出时鼠标本来就压在屏幕上，那个点击不算"我要收起"
        if (time.monotonic() - self._shown_at) * 1000 < CLICK_GUARD_MS:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.dismiss()
            return
        super().mousePressEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._clock.stop()
        super().hideEvent(event)
