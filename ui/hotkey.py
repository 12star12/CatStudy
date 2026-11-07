"""Windows 全局热键：Ctrl+Alt+Space 暂停 / 继续专注。

为什么不用 ``QShortcut``：桌宠是 ``Qt.Tool`` 窗口，绝大部分时间没有焦点，
应用级快捷键只在窗口获得焦点时才触发。而"站起来要去洗手间"的那一刻，
恰恰是最不可能先去找窗口点一下的时候——快捷键必须对**整个系统**生效。

代价与边界：

1. **只用 ctypes，不引新依赖**（这个项目连 PySide6 之外的东西都不想装）。
2. **非 Windows 平台全部空转**：``register()`` 返回 False，不抛异常，
   测试与将来的跨平台构建都不会因为缺一只 user32 而失败。
3. **消息在桌宠窗口自己的 ``nativeEvent`` 里收**。注册时把桌宠的原生句柄
   当 hwnd，``WM_HOTKEY`` 就直接投递到那个窗口，不需要额外的消息钩子线程。
4. ``MOD_NOREPEAT``：按住不放只算一次。否则按住空格会在一秒内把计时
   暂停/继续几十次，看起来像程序疯了。
"""

from __future__ import annotations

import ctypes
import sys

# 热键编号：注册与识别都靠它，取个不像窗口 ID 的值
HOTKEY_ID: int = 0xC0DE
# 给用户看的写法（菜单里也用这一份，避免两处不一致）
HOTKEY_LABEL: str = "Ctrl+Alt+Space"

MOD_ALT: int = 0x0001
MOD_CONTROL: int = 0x0002
MOD_NOREPEAT: int = 0x4000
VK_SPACE: int = 0x20

WM_HOTKEY: int = 0x0312

# Qt 把 Windows 原生消息包成这个事件类型交给 nativeEvent
NATIVE_MSG_TYPE: bytes = b"windows_generic_MSG"


def is_supported() -> bool:
    """当前平台是否支持全局热键（目前只有 Windows 有实现）。"""
    return sys.platform == "win32"


def _user32():
    if not is_supported():
        return None
    return ctypes.windll.user32


def register(hwnd: int) -> bool:
    """把 Ctrl+Alt+Space 绑到给定窗口；成功返回 True。

    失败是正常情况（比如被别的软件先占了），调用方不应因此报错——
    桌宠还有单击暂停和右键菜单，快捷键只是锦上添花。
    """
    user32 = _user32()
    if user32 is None or not hwnd:
        return False
    try:
        return bool(
            user32.RegisterHotKey(
                int(hwnd),
                HOTKEY_ID,
                MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                VK_SPACE,
            )
        )
    except OSError:  # 极少数受限环境下 windll 调用会抛，别让桌宠起不来
        return False


def unregister(hwnd: int) -> None:
    """解绑；窗口销毁前调用，避免残留一个指向死句柄的热键。"""
    user32 = _user32()
    if user32 is None or not hwnd:
        return
    try:
        user32.UnregisterHotKey(int(hwnd), HOTKEY_ID)
    except OSError:
        pass


def is_hotkey_message(event_type, message) -> bool:
    """判断一条原生消息是不是我们注册的那个热键。

    ``message`` 是 Qt 给的 ``MSG*`` 地址（sip.voidptr），按 ``ctypes`` 还原成
    ``MSG`` 结构体再比对 ``message`` 与 ``wParam``。
    """
    if not is_supported():
        return False
    try:
        if bytes(event_type) != NATIVE_MSG_TYPE:
            return False
    except TypeError:  # 已经是 bytes 或其他可比较对象
        if event_type != NATIVE_MSG_TYPE:
            return False
    from ctypes import wintypes

    msg = wintypes.MSG.from_address(int(message))
    return int(msg.message) == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID
