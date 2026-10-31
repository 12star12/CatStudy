"""桌面宠物窗口模块（第三阶段）。

保留第二阶段的全部窗口能力：无边框、透明背景、始终置顶、左键拖拽、
右键菜单退出、透明区域鼠标穿透；图形部分改为订阅 AnimationPlayer
的待机动画（眨眼 + 呼吸起伏），本窗口不再硬编码任何像素图案。

动画素材与调度分别位于 assets/cat/idle.json 与 ui/sprite.py。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import (
    QContextMenuEvent,
    QHideEvent,
    QMouseEvent,
    QPixmap,
    QRegion,
    QShowEvent,
)
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QWidget

from ui.sprite import CAT_ASSETS_DIR, AnimationPlayer, SpriteSheet

# 呼吸下沉需要 1px 垂直余量，窗口高度比单帧图像多 1px
_BREATH_MARGIN: int = 1


class PetWindow(QWidget):
    """桌面宠物悬浮窗。"""

    def __init__(self) -> None:
        super().__init__()
        self._drag_offset: QPoint | None = None

        # 动画相关对象；窗口只消费帧信号，不关心时间轴细节
        self._sprite = SpriteSheet(CAT_ASSETS_DIR / "idle.json")
        self._player = AnimationPlayer(self._sprite, parent=self)
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
        """搭建展示像素猫的标签，窗口预留 1px 呼吸余量并设置遮罩。"""
        width, height = self._sprite.frame_size

        self._label = QLabel(self)
        self._label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._label.move(0, 0)
        self._label.resize(width, height)
        self._label.setPixmap(self._sprite.pixmap("open"))

        self.resize(width, height + _BREATH_MARGIN)
        self._setup_mask()

    def _setup_mask(self) -> None:
        """遮罩覆盖呼吸的两个垂直位置，区域之外的透明部分鼠标穿透。"""
        base_region = QRegion(self._sprite.pixmap("open").mask())
        self.setMask(base_region.united(base_region.translated(0, 1)))

    def _setup_context_menu(self) -> None:
        """构建右键菜单。"""
        self._menu = QMenu(self)
        quit_action = self._menu.addAction("退出程序")
        quit_action.triggered.connect(QApplication.quit)

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
