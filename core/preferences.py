"""桌宠的界面偏好：屏幕位置与「锁定位置」，存成一个明文 JSON。

三条边界，都写在代码里当约束用：

1. **不进数据库。** ``data/catstudy.db`` 里装的是学习数据，用户备份时该带走
   的是记录，而不是"猫坐在哪个角"。把界面状态混进库，将来导数据给别人会
   连同屏幕布局一起送出去。
2. **不写注册表。** ``core/autostart.py`` 写 ``HKCU\\...\\Run`` 是因为系统只认
   那里；界面上能改的东西必须让用户看得见、删得掉，坏了自己删文件就恢复默认。
3. **读写失败一律静默。** 偏好丢了最多让猫回到默认位置，不该因为一个坐标
   把整个程序拦在启动之前。

位置还带一个现实问题：笔记本外接显示器拔掉以后，记忆里的坐标可能落在
已经不存在的屏幕上，猫就此消失。``clamp_position`` 负责把它拉回可见范围。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_PATH: Path = PROJECT_ROOT / "data" / "preferences.json"

# 文件里带版本号：将来字段改名时能判断是老格式还是脏数据
SCHEMA_VERSION: int = 1

# 记忆位置失效（屏幕拔了/分辨率变了）时退到主屏右下角的内缩量
FALLBACK_MARGIN_X: int = 32
FALLBACK_MARGIN_Y: int = 96


@dataclass(frozen=True)
class PetPreferences:
    """桌宠的界面偏好。不可变，改动走 ``with_*`` 返回新对象。"""

    locked: bool = False
    x: int | None = None
    y: int | None = None

    @property
    def position(self) -> tuple[int, int] | None:
        """记住的位置；从未拖动过时为 ``None``（此时不干预窗口默认位置）。"""
        if self.x is None or self.y is None:
            return None
        return self.x, self.y

    def with_position(self, x: int, y: int) -> PetPreferences:
        return replace(self, x=int(x), y=int(y))

    def with_locked(self, locked: bool) -> PetPreferences:
        return replace(self, locked=bool(locked))

    def to_dict(self) -> dict:
        return {
            "version": SCHEMA_VERSION,
            "pet": {"locked": self.locked, "x": self.x, "y": self.y},
        }


def from_dict(raw: object) -> PetPreferences:
    """从任意 JSON 内容解析；任何不对劲都退回默认值，不抛异常。"""
    if not isinstance(raw, dict):
        return PetPreferences()
    pet = raw.get("pet")
    if not isinstance(pet, dict):
        return PetPreferences()

    x = pet.get("x")
    y = pet.get("y")
    # bool 是 int 的子类，先排掉，否则 True 会被当成坐标 1
    valid = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
    if not (valid(x) and valid(y)):
        x = y = None

    return PetPreferences(locked=bool(pet.get("locked", False)), x=x, y=y)


def clamp_position(
    x: int,
    y: int,
    width: int,
    height: int,
    areas: list[tuple[int, int, int, int]],
) -> tuple[int, int]:
    """把窗口左上角夹回可见区域。``areas`` 为 ``(x, y, w, h)`` 列表，首个是主屏。

    判定用**窗口中心**而不是左上角：允许用户故意把猫半个身子挂在屏幕边缘
    （贴着任务栏或屏幕角是常见摆法），只有中心都跑出去了才认为它丢了。

    没有任何屏幕信息时原样返回——宁可不动，也不要凭空猜一个位置。
    """
    if not areas:
        return x, y

    center_x = x + width / 2
    center_y = y + height / 2
    for area_x, area_y, area_w, area_h in areas:
        if (
            area_x <= center_x <= area_x + area_w
            and area_y <= center_y <= area_y + area_h
        ):
            return x, y

    # 记忆里的位置已经不在任何屏幕上：退回主屏右下角，这是桌宠的常规落点
    area_x, area_y, area_w, area_h = areas[0]
    fallback_x = area_x + area_w - width - FALLBACK_MARGIN_X
    fallback_y = area_y + area_h - height - FALLBACK_MARGIN_Y
    return max(area_x, fallback_x), max(area_y, fallback_y)


class PreferenceStore:
    """``data/preferences.json`` 的读写器。

    写文件走"临时文件 + 原子替换"：写完立刻断电也不会留下半个 JSON，
    而这个文件恰好会在每次拖动猫之后被写一次。
    """

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path: Path = Path(path)

    def load(self) -> PetPreferences:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # 文件不存在、没权限、半截 JSON —— 全部当"没有偏好"
            return PetPreferences()
        return from_dict(raw)

    def save(self, preferences: PetPreferences) -> bool:
        """写入偏好；返回是否成功。失败不影响程序，只是下次记不住。"""
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(
                json.dumps(preferences.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp, self.path)
            return True
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
