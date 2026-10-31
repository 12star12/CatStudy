"""专注计时模块（第一阶段占位）。

后续职责：
- 管理专注会话（如番茄钟，Pomodoro）的开始、暂停与结束；
- 通过 Qt 信号向外广播剩余时间与状态变化，供界面层订阅；
- 会话结束时把专注时长交给成长系统结算经验。
"""

from __future__ import annotations


class TimerManager:
    """专注计时器管理器，当前仅为骨架，不包含实际计时逻辑。"""

    def __init__(self) -> None:
        # TODO: 初始化默认专注时长（例如 25 分钟）与运行状态
        self._duration_minutes: int = 25
        self._is_running: bool = False

    def start(self) -> None:
        """开始一次专注会话。"""
        # TODO: 启动底层定时器并通知界面刷新
        self._is_running = True

    def pause(self) -> None:
        """暂停当前专注会话。"""
        # TODO: 实现暂停与恢复逻辑
        self._is_running = False

    def stop(self) -> None:
        """结束本次会话并结算实际专注时长。"""
        # TODO: 结算时长，并调用 GrowthSystem.add_experience 发放经验
        self._is_running = False
