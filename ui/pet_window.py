"""桌面宠物窗口模块（第三阶段 / 帧契约解耦版）。

保留第二阶段的全部窗口能力：无边框、透明背景、始终置顶、左键拖拽、
右键菜单、透明区域鼠标穿透；图形部分改为订阅 AnimationPlayer
的待机动画（眨眼 + 呼吸起伏），本窗口不再硬编码任何像素图案或帧名。

第四阶段新增两个打开学习记录的入口：右键菜单「学习记录…」与双击猫身。
两者都只发出 ``studyRecordsRequested`` 信号，不直接创建窗口——窗口的
创建与复用由 main.py 接线，桌宠因此仍然不依赖数据库与业务层。

与素材的耦合点只有两处，且都通过 SpriteSheet 暴露的语义接口访问：
- ``sprite.roles.base``：窗口首次显示时用哪一帧；
- ``sprite.mask_region_with_offsets()``：全帧轮廓并集 × 呼吸偏移的遮罩。
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QHideEvent,
    QMouseEvent,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import QApplication, QInputDialog, QLabel, QMenu, QWidget

from core.timer import FocusTimer, TimerMode, TimerState
from ui.sprite import (
    CAT_ASSETS_DIR,
    AnimationPlayer,
    SpriteSheet,
    possible_offsets,
)
from ui.timer_bubble import TimerBubble

# 默认角色素材：第一只正式角色（单帧 sit，39x48 网格 @2x = 78x96 显示）
# 旧的 idle.json（16x16 @8x 眨眼动画）与其余旧素材均原样保留，切换只需改这一行。
DEFAULT_SPRITE_PATH: Path = CAT_ASSETS_DIR / "cat_sit.json"

# 自行判定双击时允许的最大位移（逻辑像素）：手指微抖仍算双击，但拖拽不会被误判
DOUBLE_CLICK_MAX_SHIFT: int = 6

# 同一次双击的去重窗口（秒）。平台若也派发了一次双击事件，
# 这一次双击只应打开一次窗口。
REQUEST_DEDUPE_SECONDS: float = 0.35


def _max_down_offset() -> int:
    """呼吸下沉的最大像素量，用于给窗口预留垂直余量。"""
    return max((off.y() for off in possible_offsets()), default=0)


class PetWindow(QWidget):
    """桌面宠物悬浮窗。"""

    # 请求打开学习记录窗口。窗口本身不创建、不持有记录窗口，
    # 只负责发出请求，由 main.py 接线——这样桌宠不依赖数据库与业务层。
    studyRecordsRequested = Signal()

    # 一次专注结束后广播 (模式, 科目, 实际秒数)，由 main.py 负责落库。
    # 桌宠不 import 仓储层，与上面同一个理由：UI 不碰数据库。
    focusSessionFinished = Signal(str, str, int)

    # 计时气泡的刷新间隔：250ms 足够让秒数看起来连续，又不至于空转
    TICK_MS: int = 250
    # 结束提示（"✓ 25 分钟已记录"）的停留时长
    FLASH_MS: int = 2600

    def __init__(
        self,
        sprite_path=None,
        default_subject: str = "专注",
        timer: FocusTimer | None = None,
    ) -> None:
        super().__init__()
        self._drag_offset: QPoint | None = None

        # 自行判定双击所需的状态（见 mousePressEvent 的说明）
        self._last_press_at: float | None = None
        self._last_press_pos: QPoint = QPoint()
        self._last_request_at: float | None = None
        # 同一次物理按下可能被派发两次（子标签与窗口各一次），用它去重
        self._left_pressed: bool = False

        # 专注计时：计时器只管时间，科目与落库都不在这里
        self._timer = timer if timer is not None else FocusTimer()
        self._subject: str = default_subject or "专注"
        self._default_subject: str = self._subject
        # 会话还没结束（用于"到点只结算一次"）
        self._finish_pending: bool = False
        # 结束提示的令牌：新会话开始后，旧的隐藏回调要自动失效
        self._flash_token: object | None = None

        # 动画相关对象；窗口只消费帧信号，不关心时间轴细节
        self._sprite = SpriteSheet(
            sprite_path if sprite_path is not None else DEFAULT_SPRITE_PATH
        )
        self._dpr: float = float(self.devicePixelRatioF())
        self._player = AnimationPlayer(self._sprite, parent=self, dpr=self._dpr)
        self._player.frameChanged.connect(self._on_frame_changed)

        # 计时气泡与本窗口分离（理由见 ui/timer_bubble.py 顶部说明）
        self._bubble = TimerBubble()
        self._tick = QTimer(self)
        self._tick.setInterval(self.TICK_MS)
        self._tick.timeout.connect(self._on_tick)

        self._setup_window()
        self._setup_ui()
        self._setup_context_menu()

    # ---------- 初始化 ----------

    def _setup_window(self) -> None:
        """配置无边框、置顶、工具窗与透明背景等窗口属性。"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("CatStudy Pet")

    def _setup_ui(self) -> None:
        """搭建展示像素猫的标签，窗口预留呼吸余量并设置遮罩。"""
        width, height = self._sprite.frame_size(self._dpr)

        self._label = QLabel(self)
        self._label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._label.move(0, 0)
        self._label.resize(width, height)
        self._label.setPixmap(self._sprite.base_pixmap(self._dpr))

        self.resize(width, height + _max_down_offset())
        self._setup_mask()

    def _setup_mask(self) -> None:
        """遮罩 = 所有帧轮廓的并集 × 全部呼吸偏移。

        取全帧并集而非只取静止帧，可避免未来加入摆尾/抬爪帧时，超出静止帧
        轮廓的像素被窗口遮罩静默裁掉。
        """
        self.setMask(
            self._sprite.mask_region_with_offsets(
                self._dpr, offsets=possible_offsets()
            )
        )

    def _setup_context_menu(self) -> None:
        """构建右键菜单：专注计时 + 学习记录 + 退出。"""
        self._menu = QMenu(self)

        # ---- 专注 ----
        self.focus_menu = self._menu.addMenu("专注")
        self.pomodoro_action = self.focus_menu.addAction("开始番茄钟（25 分钟）")
        self.pomodoro_action.triggered.connect(
            lambda _checked=False: self.start_focus(TimerMode.POMODORO)
        )
        self.stopwatch_action = self.focus_menu.addAction("开始正计时")
        self.stopwatch_action.triggered.connect(
            lambda _checked=False: self.start_focus(TimerMode.STOPWATCH)
        )
        self.focus_menu.addSeparator()
        self.pause_action = self.focus_menu.addAction("暂停")
        self.pause_action.triggered.connect(
            lambda _checked=False: self.toggle_pause()
        )
        self.finish_action = self.focus_menu.addAction("结束并保存")
        self.finish_action.triggered.connect(
            lambda _checked=False: self.finish_focus()
        )
        self.discard_action = self.focus_menu.addAction("放弃本次")
        self.discard_action.triggered.connect(
            lambda _checked=False: self.discard_focus()
        )
        # 菜单展开前按当前状态刷新可用性与文案（"暂停"↔"继续"）
        self._menu.aboutToShow.connect(self._sync_menu_state)

        self.study_action = self._menu.addAction("学习记录…")
        # triggered 会带一个 bool 参数，用 lambda 吞掉，避免多参传进无参信号
        self.study_action.triggered.connect(
            lambda _checked=False: self.studyRecordsRequested.emit()
        )

        self._menu.addSeparator()
        quit_action = self._menu.addAction("退出程序")
        quit_action.triggered.connect(QApplication.quit)

    def _sync_menu_state(self) -> None:
        """按计时器当前状态决定哪些菜单项可点。

        "开始"两项在会话进行中禁用（避免误触把当前专注清零），
        "暂停/结束/放弃"反之只在会话进行中可用。
        """
        active = self._timer.is_active
        self.pomodoro_action.setEnabled(not active)
        self.stopwatch_action.setEnabled(not active)
        self.pause_action.setEnabled(active)
        self.finish_action.setEnabled(active)
        self.discard_action.setEnabled(active)
        self.pause_action.setText(
            "继续" if self._timer.state is TimerState.PAUSED else "暂停"
        )

    # ---------- 专注计时 ----------

    @property
    def timer(self) -> FocusTimer:
        """当前计时器（只读用；测试与 main.py 会读它的状态）。"""
        return self._timer

    def start_focus(self, mode: TimerMode, subject: str | None = None) -> bool:
        """开始一次专注；返回是否真的开始（用户取消科目输入则返回 False）。

        ``subject`` 为 None 时弹输入框问科目，默认带上一次用过的值，
        直接回车即开始——正常情况下多按一次回车就能开跑。
        """
        if self._timer.is_active:
            return False
        if subject is None:
            subject = self._ask_subject()
            if subject is None:
                return False

        self._subject = subject
        self._default_subject = subject
        self._timer.start(mode)
        self._finish_pending = True
        self._flash_token = None
        self._bubble.set_text(self._timer.display_text())
        self._bubble.show_near(self)
        self._tick.start()
        return True

    def toggle_pause(self) -> None:
        """在暂停与继续之间切换。"""
        if self._timer.state is TimerState.RUNNING:
            self._timer.pause()
            self._bubble.set_text(self._paused_text(), accent=False)
        elif self._timer.state is TimerState.PAUSED:
            self._timer.resume()
            self._bubble.set_text(self._timer.display_text())

    def finish_focus(self) -> None:
        """手动结束并保存；秒数不足 1 分钟时不产生记录（由 main.py 判定）。"""
        if not self._finish_pending:
            return
        self._complete_focus()

    def discard_focus(self) -> None:
        """放弃本次专注：不做任何记录。"""
        if not self._finish_pending:
            return
        self._finish_pending = False
        self._timer.reset()
        self._tick.stop()
        self._hide_bubble()

    def _ask_subject(self) -> str | None:
        """弹一次科目输入框；取消返回 None，留空则记"专注"。"""
        text, accepted = QInputDialog.getText(
            self, "开始专注", "这次学的是什么？", text=self._default_subject
        )
        if not accepted:
            return None
        return text.strip() or "专注"

    def _paused_text(self) -> str:
        """暂停时在读数前加一个暂停符号，一眼能看出不是卡住了。"""
        return "⏸ " + self._timer.display_text()

    def _on_tick(self) -> None:
        """每 250ms 刷新一次读数；番茄钟到点时自动结算。"""
        if self._finish_pending and self._timer.state is TimerState.FINISHED:
            self._complete_focus()
            return
        if self._flash_token is not None:
            # 正在显示"已记录"提示，别让读数把它顶掉
            return
        self._bubble.set_text(self._timer.display_text())

    def _complete_focus(self) -> None:
        """结算一次会话：停表、发出落库信号、给一句结果提示。"""
        self._finish_pending = False
        seconds = self._timer.stop()
        self._tick.stop()
        self.focusSessionFinished.emit(self._timer.mode.value, self._subject, seconds)

        minutes = seconds // 60
        if minutes >= 1:
            message = f"✓ {minutes} 分钟已记录"
        else:
            message = "不足 1 分钟，未记录"
        self._flash(message)

    def _flash(self, message: str) -> None:
        """短暂显示一条结果提示，随后自动隐藏。"""
        token = object()
        self._flash_token = token
        self._bubble.set_text(message, accent=True)
        self._bubble.show_near(self)

        def _hide() -> None:
            # 期间用户可能已经开了新会话，令牌对不上就不动它
            if self._flash_token is token:
                self._hide_bubble()

        QTimer.singleShot(self.FLASH_MS, _hide)

    def _hide_bubble(self) -> None:
        self._flash_token = None
        self._bubble.hide()

    # ---------- 高 DPI ----------

    def event(self, e: QEvent) -> bool:
        """监听 DPR 变化（窗口跨屏移动时），重建像素与遮罩。"""
        dpr_change = getattr(QEvent.Type, "DevicePixelRatioChange", None)
        if dpr_change is not None and e.type() == dpr_change:
            self._rebuild_for_dpr()
        return super().event(e)

    def _rebuild_for_dpr(self) -> None:
        """按新的 devicePixelRatio 重新取整数倍像素图并重算遮罩。"""
        dpr = float(self.devicePixelRatioF())
        if abs(dpr - self._dpr) < 1e-6:
            return
        self._dpr = dpr
        self._player.set_device_pixel_ratio(dpr)
        self._setup_ui()

    # ---------- 动画生命周期 ----------

    def showEvent(self, event: QShowEvent) -> None:
        """窗口显示时启动动画，避免不可见时空转耗电。"""
        super().showEvent(event)
        self._player.start()

    def hideEvent(self, event: QHideEvent) -> None:
        """窗口隐藏时停止动画。"""
        super().hideEvent(event)
        self._player.stop()
        self._bubble.hide()

    def moveEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        """拖动窗口时让计时气泡跟着走。

        气泡是独立窗口（见 ui/timer_bubble.py），不会自动跟随父窗口，
        只能在这里同步位置。
        """
        super().moveEvent(event)
        if self._bubble.isVisible():
            self._bubble.show_near(self)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        """关闭桌宠时一并收掉气泡，避免留下一个无主的浮窗。"""
        self._tick.stop()
        self._bubble.close()
        super().closeEvent(event)

    def _on_frame_changed(self, pixmap: QPixmap, offset: QPoint) -> None:
        """帧信号槽：切换图像并在标签内做呼吸偏移，窗口本身不移动。"""
        self._label.setPixmap(pixmap)
        self._label.move(offset)

    # ---------- 鼠标交互 ----------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键按下：记录拖拽起点，并自行判定是否构成双击。

        为什么不用 ``mouseDoubleClickEvent`` 单独判定：桌宠是置顶的
        ``Qt.Tool`` 窗口，实测首次被点击时系统会把这一次点击消耗在激活上，
        ``WM_LBUTTONDBLCLK`` 不一定会派发（实测 5 次里只有 3 次成功）。
        因此这里按"连续两次按下、间隔小于系统双击间隔、位移很小"
        自行判定，平台派发的双击事件仍保留作为兜底。
        """
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        if self._left_pressed:
            # 一次物理按下偶尔会被派发两次（子标签 → 窗口），
            # 不去重会把"按下一次"误判成"双击"，拖动时会莫名弹出窗口
            return
        self._left_pressed = True

        now = time.monotonic()
        position = event.position().toPoint()
        is_double = (
            self._last_press_at is not None
            and (now - self._last_press_at) * 1000 <= QApplication.doubleClickInterval()
            and (position - self._last_press_pos).manhattanLength() <= DOUBLE_CLICK_MAX_SHIFT
        )
        if is_double:
            self._last_press_at = None
            self._request_study_window()
        else:
            self._last_press_at = now
        self._last_press_pos = position

        self._drag_offset = (
            event.globalPosition().toPoint()
            - self.frameGeometry().topLeft()
        )
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """左键按住移动时，按光标位置同步移动窗口。"""
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """左键释放后结束拖拽状态。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_pressed = False
            self._drag_offset = None
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """平台派发的双击（兜底路径）。

        ``mousePressEvent`` 里已经做过一次判定，同一次双击可能走到这里，
        因此统一走带时间去重的 ``_request_study_window``，避免打开两次。
        双击不触碰 ``_drag_offset``：只要鼠标没移动，窗口位置不变。
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._request_study_window()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _request_study_window(self) -> None:
        """发出打开请求，并对短时间内的重复请求去重。"""
        now = time.monotonic()
        if (
            self._last_request_at is not None
            and now - self._last_request_at < REQUEST_DEDUPE_SECONDS
        ):
            return
        self._last_request_at = now
        self.studyRecordsRequested.emit()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """在光标位置弹出右键菜单。"""
        self._menu.exec(event.globalPos())
