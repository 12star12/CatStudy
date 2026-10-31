"""专注计时核心逻辑（番茄钟 / 正计时）。

设计要点：

1. **纯逻辑，不依赖 Qt**。界面层只做两件事：每 250ms 读一次
   :meth:`FocusTimer.display_text` 显示，以及在需要时调用开始/暂停/结束。
   所有时间计算都在本模块，因此可以脱离 GUI 单元测试。
2. **用单调时钟的差值计时，而不是"每次 tick 累加 1 秒"**。后者在界面卡顿、
   电脑睡眠、系统时间被改动时都会跑偏；差值法只依赖时间点，不会累积误差。
   测试通过注入 ``clock`` 使用假时钟，无需真的等 25 分钟。
3. **番茄钟到点自动收敛**：任何一次状态查询都会先把"已经超过目标时长"的
   会话判定为 ``FINISHED``，累计时长钉在目标值上，界面不会看到负计时。

状态机（四个状态，方向不可逆，除 start 之外都只能从特定状态迁移）::

    IDLE --start--> RUNNING <--resume-- PAUSED
                      |  \\--pause-->        ^
                      |                     |
                      +--到点/结束--> FINISHED

    FINISHED --start--> RUNNING（开始下一次）
    任意状态 --reset--> IDLE
"""

from __future__ import annotations

import math
import time
from enum import Enum
from typing import Callable

# 经典番茄钟时长
POMODORO_MINUTES: int = 25


class TimerMode(str, Enum):
    """计时模式。继承 str 便于直接写进数据库/日志，不产生 "TimerMode.POMODORO"。"""

    POMODORO = "pomodoro"
    STOPWATCH = "stopwatch"


class TimerState(str, Enum):
    """计时状态。"""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


def format_clock(seconds: float) -> str:
    """把秒数格式化成 ``MM:SS``；超过 1 小时用 ``H:MM:SS``。

    向下取整而非四舍五入：显示的读数不应该比实际经过的时间快。
    """
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class FocusTimer:
    """一次专注会话的计时器（番茄钟倒计时 / 正计时秒表共用一套状态机）。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        pomodoro_seconds: int = POMODORO_MINUTES * 60,
    ) -> None:
        if pomodoro_seconds <= 0:
            raise ValueError(f"番茄钟时长必须为正数秒: {pomodoro_seconds}")
        self._clock: Callable[[], float] = clock or time.monotonic
        self._pomodoro_seconds: int = int(pomodoro_seconds)
        self._mode: TimerMode = TimerMode.POMODORO
        self._state: TimerState = TimerState.IDLE
        # 已经结束的分钟数（暂停/结束时定格），加上当前片段即为累计时长
        self._accumulated: float = 0.0
        # 当前片段的开始时刻；暂停或结束时置 None
        self._segment_start: float | None = None

    # ---------- 只读属性 ----------

    @property
    def mode(self) -> TimerMode:
        return self._mode

    @property
    def state(self) -> TimerState:
        # 读状态前先结算一次：番茄钟跑过目标时长后，任何观察（界面读状态、
        # 测试读状态）都应该看到 FINISHED，而不是等下一次 tick 才纠正
        self._settle_if_expired()
        return self._state

    @property
    def pomodoro_seconds(self) -> int:
        return self._pomodoro_seconds

    @property
    def is_running(self) -> bool:
        return self._state is TimerState.RUNNING

    @property
    def is_active(self) -> bool:
        """是否有会话正在进行（运行或暂停）；用于决定菜单项是否可用。"""
        return self._state in (TimerState.RUNNING, TimerState.PAUSED)

    # ---------- 状态迁移 ----------

    def start(self, mode: TimerMode = TimerMode.POMODORO) -> None:
        """开始一次新会话；已有会话会被直接丢弃（调用方应先询问用户）。"""
        if not isinstance(mode, TimerMode):
            raise TypeError(f"mode 必须是 TimerMode，收到 {type(mode).__name__}")
        self._mode = mode
        self._state = TimerState.RUNNING
        self._accumulated = 0.0
        self._segment_start = self._clock()

    def pause(self) -> None:
        """暂停；非运行态调用为空操作（界面重复点击不会出错）。"""
        if self._state is not TimerState.RUNNING:
            return
        self._accumulated = self._raw_elapsed()
        self._segment_start = None
        self._state = TimerState.PAUSED

    def resume(self) -> None:
        """从暂停恢复；非暂停态调用为空操作。"""
        if self._state is not TimerState.PAUSED:
            return
        self._segment_start = self._clock()
        self._state = TimerState.RUNNING

    def stop(self) -> int:
        """结束会话并返回累计秒数（向下取整）；之后状态为 FINISHED。"""
        elapsed = int(self.elapsed_seconds())
        self._accumulated = float(elapsed)
        self._segment_start = None
        self._state = TimerState.FINISHED
        return elapsed

    def reset(self) -> None:
        """丢弃当前会话（不产生记录），回到 IDLE。"""
        self._accumulated = 0.0
        self._segment_start = None
        self._state = TimerState.IDLE

    # ---------- 读数 ----------

    def elapsed_seconds(self) -> float:
        """已专注秒数。番茄钟到点后固定为目标时长，不会继续往上跑。"""
        self._settle_if_expired()
        if self._state is TimerState.RUNNING and self._segment_start is not None:
            return self._accumulated + (self._clock() - self._segment_start)
        return self._accumulated

    def remaining_seconds(self) -> float | None:
        """番茄钟剩余秒数；正计时没有终点，返回 None。"""
        if self._mode is not TimerMode.POMODORO:
            return None
        return max(0.0, self._pomodoro_seconds - self.elapsed_seconds())

    def duration_minutes(self) -> int:
        """向下取整的专注分钟数，直接用于写库。"""
        return int(self.elapsed_seconds()) // 60

    def display_text(self) -> str:
        """给界面显示的时间文本。

        番茄钟向上取整（一开始就显示 25:00，而不是 24:59），正计时向下取整。
        """
        if self._mode is TimerMode.POMODORO:
            remaining = self.remaining_seconds() or 0.0
            return format_clock(math.ceil(remaining))
        return format_clock(self.elapsed_seconds())

    # ---------- 内部 ----------

    def _raw_elapsed(self) -> float:
        """不触发到点判断的累计时长，供内部的"暂停/收敛"操作使用。"""
        if self._state is TimerState.RUNNING and self._segment_start is not None:
            return self._accumulated + (self._clock() - self._segment_start)
        return self._accumulated

    def _settle_if_expired(self) -> None:
        """番茄钟跑过目标时长时，把状态收敛为 FINISHED 并钉住累计值。"""
        if self._mode is not TimerMode.POMODORO:
            return
        if self._state is not TimerState.RUNNING or self._segment_start is None:
            return
        if self._raw_elapsed() < self._pomodoro_seconds:
            return
        self._accumulated = float(self._pomodoro_seconds)
        self._segment_start = None
        self._state = TimerState.FINISHED
