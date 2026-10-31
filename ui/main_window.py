"""主面板窗口模块（第一阶段占位）。

后续职责：
- 展示专注计时控制（开始、暂停、结束）与剩余时间；
- 展示宠物等级、经验、心情等状态及历史专注统计；
- 提供设置入口，并与 core 层各管理器协作。
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """应用主面板窗口，当前仅为骨架，不包含实际布局。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CatStudy 主面板")
        self.resize(480, 320)
        # TODO: 搭建计时控制区、宠物状态区与统计区的界面布局
