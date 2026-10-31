"""成长系统模块（第一阶段占位）。

后续职责：
- 根据专注时长结算经验值（EXP, Experience Points）；
- 管理宠物等级（Level）与成长阶段（如幼年、成年）；
- 维护心情、亲密度等状态，并通过数据库层持久化。
"""

from __future__ import annotations


class GrowthSystem:
    """宠物成长系统，当前仅为骨架，不包含真实升级逻辑。"""

    def __init__(self, level: int = 1, experience: int = 0) -> None:
        self.level: int = level
        self.experience: int = experience
        # TODO: 定义升级所需经验曲线与各成长阶段的等级区间

    def add_experience(self, amount: int) -> None:
        """增加经验值，并在满足阈值时触发升级。"""
        # TODO: 累加经验、循环判定升级并返回等级变化事件
        raise NotImplementedError("经验结算将在后续阶段实现")

    def get_stage(self) -> str:
        """返回宠物当前成长阶段的文字描述。"""
        # TODO: 根据 self.level 映射到“幼年 / 少年 / 成年”等阶段
        raise NotImplementedError("成长阶段将在后续阶段实现")
