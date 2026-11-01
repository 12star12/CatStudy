"""开机自启动开关（Windows 注册表 Run 键）。

为什么用注册表而不是「启动」文件夹里的快捷方式：

- 启动文件夹需要一个合法的 .lnk，而本机禁止脚本实例化 COM，手写 Shell Link
  二进制又脆弱（踩过坑：中文描述按 ANSI 写入会把整个快捷方式写坏）；
- Run 键只存一条命令行字符串，``winreg`` 直接读写，可逆、可查、易于关掉。

写入的值形如::

    "D:\\CatStudy\\.venv\\Scripts\\pythonw.exe" "D:\\CatStudy\\main.py"

用 ``pythonw.exe`` 而不是 ``python.exe``，否则每次开机都会弹一个黑色控制台窗口。

所有函数在非 Windows 平台上是安全的空操作/False，方便在别的系统上跑测试。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 应用在注册表里的名字（同时是 Run 键下的值名）
VALUE_NAME: str = "CatStudy"

# HKCU 下的自启动键；用当前用户而不是 HKLM，不需要管理员权限
RUN_KEY: str = r"Software\Microsoft\Windows\CurrentVersion\Run"

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def is_supported() -> bool:
    return sys.platform == "win32"


def pythonw_path() -> Path:
    """当前解释器旁边的 pythonw.exe（venv 里一定存在）。"""
    return Path(sys.executable).with_name("pythonw.exe")


def command(root: Path | None = None) -> str:
    """要写进注册表的完整命令行。"""
    base = Path(root) if root is not None else PROJECT_ROOT
    interpreter = pythonw_path()
    if not interpreter.exists():  # 兜底：万一没有 pythonw 就用当前解释器
        interpreter = Path(sys.executable)
    return f'"{interpreter}" "{base / "main.py"}"'


def _open_key(write: bool, key_path: str):
    import winreg  # noqa: PLC0415 仅 Windows 需要

    flags = winreg.KEY_WRITE if write else winreg.KEY_READ
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, flags)


def current_value(key_path: str = RUN_KEY) -> str | None:
    """读出当前登记的启动命令；没有则返回 None。"""
    if not is_supported():
        return None
    import winreg  # noqa: PLC0415

    try:
        with _open_key(False, key_path) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError:
        return None


def is_enabled(key_path: str = RUN_KEY) -> bool:
    """是否已登记自启动。"""
    return current_value(key_path) is not None


def enable(key_path: str = RUN_KEY, root: Path | None = None) -> bool:
    """登记自启动；返回是否成功（已有值会被覆盖为当前路径）。"""
    if not is_supported():
        return False
    import winreg  # noqa: PLC0415

    try:
        with _open_key(True, key_path) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command(root))
        return True
    except OSError:
        return False


def disable(key_path: str = RUN_KEY) -> bool:
    """取消自启动；返回是否确实删掉了（本来就没有时为 False）。"""
    if not is_supported():
        return False
    import winreg  # noqa: PLC0415

    try:
        with _open_key(True, key_path) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY) -> bool:
    """按目标状态登记或取消，返回操作后的真实状态。"""
    if enabled:
        enable(key_path)
    else:
        disable(key_path)
    return is_enabled(key_path)
