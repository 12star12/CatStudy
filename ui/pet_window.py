"""桌面宠物窗口模块（第三阶段 / 帧契约解耦版）。

保留第二阶段的全部窗口能力：无边框、透明背景、始终置顶、左键拖拽、
右键菜单退出、透明区域鼠标穿透；图形部分改为订阅 AnimationPlayer
的待机动画（眨眼 + 呼吸起伏），本窗口不再硬编码任何像素图案或帧名。

与素材的耦合点只有两处，且都通过 SpriteSheet 暴露的语义接口访问：
- ``sprite.roles.base``：窗口首次显示时用哪一帧；
- ``sprite.mask_region_with_offsets()``：全帧轮廓并集 × 呼吸偏移的遮罩。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import (
    QContextMenuEvent,
    QHideEvent,
    QMouseEvent,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QWidget

from ui.sprite import (
    CAT_ASSETS_DIR,
    AnimationPlayer,
    SpriteSheet,
    possible_offsets,
)


def _max_down_offset() -> int:
    """呼吸下沉的最大像素量，用于给窗口预留垂直余量。"""
    return max((off.y() for off in possible_offsets()), default=0)


class PetWindow(QWidget):
    """桌面宠物悬浮窗。"""

    def __init__(self, sprite_path=None) -> None:
        super().__init__()
        self._drag_offset: QPoint | None = None

        # 动画相关对象；窗口只消费帧信号，不关心时间轴细节
        self._sprite = SpriteSheet(
            sprite_path if sprite_path is not None else CAT_ASSETS_DIR / "idle.json"
        )
        self._dpr: float = float(self.devicePixelRatioF())
        self._player = AnimationPlayer(self._sprite, parent=self, dpr=self._dpr)
        self._player.frameChanged.connect(self._on_frame_changed)

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
        """构建右键菜单。"""
        self._menu = QMenu(self)
        quit_action = self._menu.addAction("退出程序")
        quit_action.triggered.connect(QApplication.quit)

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

    def _on_frame_changed(self, pixmap: QPixmap, offset: QPoint) -> None:
        """帧信号槽：切换图像并在标签内做呼吸偏移，窗口本身不移动。"""
        self._label.setPixmap(pixmap)
        self._label.move(offset)

    # ---------- 鼠标交互 ----------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """左键按下时记录光标相对于窗口左上角的偏移。"""
        if event.button() == Qt.MouseButton.LeftButton:
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
            self._drag_offset = None
            event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """在光标位置弹出右键菜单。"""
        self._menu.exec(event.globalPos())
