"""CatStudy 应用程序入口模块。

第二阶段：创建 QApplication 并显示桌面宠物窗口 PetWindow。
窗口自身的全部逻辑位于 ui/pet_window.py，本文件只负责启动。
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ui.pet_window import PetWindow


def main() -> int:
    """创建应用实例、显示宠物窗口并进入 Qt 事件循环，返回退出码。"""
    app = QApplication(sys.argv)
    pet = PetWindow()
    pet.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
