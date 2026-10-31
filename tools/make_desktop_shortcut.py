"""在桌面生成 CatStudy 的快捷方式（.lnk）。

为什么需要这个脚本：本机安全策略禁止脚本实例化 COM 对象，``WScript.Shell``
那条常规路线走不通；手写 Shell Link 二进制又极容易漏字段。这里用纯 Python 的
pylnk3 生成，它是完整的 Shell Link 实现（含目标 IDList），不碰 COM。

依赖（只装到临时目录即可，不必进项目 venv）::

    python -m pip install --target %TEMP%\\lnktool pylnk3

用法::

    python tools/make_desktop_shortcut.py                # 写到桌面
    python tools/make_desktop_shortcut.py --output x.lnk # 写到指定位置

**踩过的坑（务必保留 link_flags.IsUnicode = True）**：pylnk3 新建的 Lnk 默认
没有开启 IsUnicode 标志，此时写入的字符串按 ANSI 编码。英文路径侥幸能跑，
一旦有中文（比如描述「CatStudy 桌面学习伴侣」）就写成了错误的字节序列，
快捷方式双击毫无反应、也不报错——排查了很久才定位到这一行。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_SCRIPTS = PROJECT_ROOT / ".venv" / "Scripts"
TARGET = VENV_SCRIPTS / "pythonw.exe"
ICON = PROJECT_ROOT / "assets" / "icon" / "catstudy.ico"
DESCRIPTION = "CatStudy 桌面学习伴侣"
SHORTCUT_NAME = "CatStudy 桌宠.lnk"


def _import_pylnk3():
    """优先用项目 venv 里的，其次用临时目录安装的副本。"""
    try:
        import pylnk3  # noqa: F401
        return pylnk3
    except ImportError:
        pass

    fallback = Path(os.environ.get("TEMP", "")) / "lnktool"
    if fallback.is_dir():
        sys.path.insert(0, str(fallback))
        import pylnk3  # noqa: F401
        return pylnk3

    raise SystemExit(
        "缺少 pylnk3。请先执行：\n"
        r"  python -m pip install --target %TEMP%\lnktool pylnk3"
    )


def build_shortcut(output: Path) -> Path:
    """把快捷方式写到 ``output``，返回实际路径。"""
    pylnk3 = _import_pylnk3()
    from pylnk3 import (  # noqa: PLC0415 (依赖上面的动态导入)
        DRIVE_FIXED,
        DriveEntry,
        LinkInfo,
        LinkTargetIDList,
        Lnk,
        PathSegmentEntry,
        ROOT_MY_COMPUTER,
        RootEntry,
    )

    root = str(PROJECT_ROOT)
    target = str(TARGET)

    # 目标 IDList：我的电脑 -> D: -> CatStudy -> .venv -> Scripts -> pythonw.exe
    # 少了这一段，Windows 会认为快捷方式"没有关联的程序"
    id_list = LinkTargetIDList()
    id_list.items = [
        RootEntry(ROOT_MY_COMPUTER),
        DriveEntry(PROJECT_ROOT.drive or "D:"),
        PathSegmentEntry.create_for_path(root),
        PathSegmentEntry.create_for_path(str(PROJECT_ROOT / ".venv")),
        PathSegmentEntry.create_for_path(str(VENV_SCRIPTS)),
        PathSegmentEntry.create_for_path(target),
    ]

    link_info = LinkInfo()
    link_info.local = 1
    link_info.remote = 0
    link_info.drive_type = DRIVE_FIXED
    link_info.drive_serial = 0
    link_info.volume_label = ""
    link_info.local_base_path = target
    link_info.make_path()

    lnk = Lnk()
    lnk.shell_item_id_list = id_list
    lnk.link_info = link_info
    lnk.arguments = f'"{PROJECT_ROOT / "main.py"}"'
    lnk.working_dir = root
    if ICON.exists():
        lnk.icon = str(ICON)
    # 关键：不开这个标志，中文描述会按 ANSI 写坏整个快捷方式
    lnk.link_flags.IsUnicode = True
    lnk.description = DESCRIPTION

    output.parent.mkdir(parents=True, exist_ok=True)
    lnk.save(str(output))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 CatStudy 桌面快捷方式")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.path.expanduser("~")) / "Desktop" / SHORTCUT_NAME,
        help="快捷方式输出路径（默认写到桌面）",
    )
    args = parser.parse_args()

    if not TARGET.exists():
        raise SystemExit(f"找不到目标解释器：{TARGET}")

    path = build_shortcut(args.output)
    print(f"已生成：{path}（{path.stat().st_size} 字节）")
    print(f"目标：{TARGET} main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
