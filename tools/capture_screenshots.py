"""生成 README 用的界面截图。

两条硬规矩：

1. **绝不使用真实数据库。** 先经 sqlite backup API 复制到临时目录，再把副本里的
   账户、金额、流水、日记全部替换成演示数据。真实库处于 WAL 模式，直接复制 .db
   会丢掉尚未 checkpoint 的事务，所以必须走 backup。
2. **必须跑在真实平台**（不能用 offscreen），否则字体度量与样式表渲染都会失真。

页签切换走 ``MainWindow.show_page``，与用户点击路径一致，选中态才对。
"""

from __future__ import annotations

import random
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.accounts import ASSET, LIABILITY  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
SOURCE_DB = ROOT / "data" / "catstudy.db"

# 演示账户：(名称, 类型, 余额分, 分类, 备注)
DEMO_ACCOUNTS: tuple[tuple[str, str, int, str, str], ...] = (
    ("工资卡", ASSET, 1_286_400, "现金", "日常开销"),
    ("基金账户", ASSET, 452_600, "投资", "定投"),
    ("零钱", ASSET, 86_300, "现金", ""),
    ("校园卡", ASSET, 15_600, "现金", "饭卡"),
    ("信用卡", LIABILITY, 218_000, "信用", "每月还"),
    ("花呗", LIABILITY, 96_800, "信用", ""),
)

DEMO_EXPENSES: tuple[tuple[str, int, str, str], ...] = (
    ("吃饭", 3_250, "食堂", "expense"),
    ("吃饭", 2_800, "外卖", "expense"),
    ("交通", 600, "地铁", "expense"),
    ("学习", 12_900, "一本书", "expense"),
    ("娱乐", 4_500, "电影", "expense"),
    ("兼职", 120_000, "稿费", "income"),
)

DEMO_JOURNALS: tuple[str, ...] = (
    (
        "今天把数据库那一章的迁移重新过了一遍。\n\n"
        "v1 到 v7 一级一级往上走，比删库重建麻烦得多，但数据一条都不会丢。"
        "写的时候有个感觉：能随便推倒重来的东西，通常也不会被认真对待。\n\n"
        "晚上调日历的样式，折腾半天才发现是系统原生控件盖住了样式表，"
        "切到 Fusion 之后才吃设置。这种坑不踩一次根本想不到。"
    ),
    (
        "上午去图书馆，占到了靠窗那个位置。\n\n"
        "把线性代数的投影部分重新推了一遍，之前一直把「正交」当成一个计算技巧，"
        "今天才反应过来它其实是在回答「这两个东西有没有重叠的部分」。"
        "换成这个说法之后，回归、因子共线性、控制变量，突然变成同一件事。\n\n"
        "下午效率一般，两个小时只推进了一小节。"
    ),
    (
        "今天没怎么学进去，干脆早点收工。\n\n"
        "把桌宠的走路动画帧数从 12 帧降到 8 帧，120 毫秒一帧，反而更顺。"
        "有时候不是越细越好，是节奏对了好。"
    ),
    (
        "开了一天的会，晚上只挤出一个番茄钟。\n\n"
        "但还是打开了。这点很重要——不需要每天都很好，只需要别断。"
    ),
)


def snapshot_database(target: Path) -> None:
    """用 sqlite backup API 复制，保证 WAL 里未落盘的事务也被带上。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SOURCE_DB) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def anonymize(db_path: Path) -> None:
    """把副本里的一切私人信息换成演示数据，原始数据一个字都不留。"""
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM accounts")
        conn.executemany(
            "INSERT INTO accounts (name, kind, balance_cents, category, note,"
            " sort_order) VALUES (?, ?, ?, ?, ?, ?)",
            [(*row, index) for index, row in enumerate(DEMO_ACCOUNTS)],
        )

        conn.execute("DELETE FROM expenses")
        # 全部落在今天：首页按“本月”过滤，日期往前推很容易跨月只剩一笔。
        conn.executemany(
            "INSERT INTO expenses (expense_date, amount_cents, category, note, kind)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (date.today().isoformat(), amount, category, note, kind)
                for category, amount, note, kind in DEMO_EXPENSES
            ],
        )

        conn.execute("DELETE FROM journal_entries")
        conn.executemany(
            "INSERT INTO journal_entries (entry_date, content) VALUES (?, ?)",
            [
                ((date.today() - timedelta(days=index)).isoformat(), text)
                for index, text in enumerate(DEMO_JOURNALS)
            ],
        )

        # 净值走势：造 30 天缓慢上行带波动，最后一天与账户合计对齐
        total_assets = sum(cents for _n, kind, cents, _c, _note in DEMO_ACCOUNTS if kind == ASSET)
        total_liabilities = sum(
            cents for _n, kind, cents, _c, _note in DEMO_ACCOUNTS if kind == LIABILITY
        )
        conn.execute("DELETE FROM net_worth_snapshots")
        rng = random.Random(20261101)  # 固定种子，重跑截图得到同一张图
        # 起点取当前总资产的 82%，用 29 天线性补回今天，中间叠一点噪声。
        # 最后一天必须严格等于账户合计，否则折线末段会跳崖。
        floor = total_assets * 82 // 100
        rows = []
        for back in range(29, -1, -1):
            ratio = (29 - back) / 29
            assets = floor + int((total_assets - floor) * ratio)
            if back:
                assets += rng.randint(-16_000, 16_000)
            else:
                assets = total_assets
            rows.append(((date.today() - timedelta(days=back)).isoformat(), assets, total_liabilities))
        conn.executemany(
            "INSERT INTO net_worth_snapshots"
            " (snapshot_date, total_assets_cents, total_liabilities_cents)"
            " VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()


def settle(app) -> None:
    for _ in range(4):
        app.processEvents()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from core.database import init_database
    from core.expenses import ExpenseRepository
    from core.journal import JournalRepository
    from core.accounts import AccountRepository
    from core.study_records import StudyRecordRepository
    from main import configure_application
    from ui.main_window import StudyWindowManager

    if not SOURCE_DB.is_file():
        print(f"找不到数据库：{SOURCE_DB}")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="catstudy-shot-"))
    shot_db = temp_dir / "shot.db"
    snapshot_database(shot_db)
    anonymize(shot_db)

    app = QApplication(sys.argv)
    configure_application(app)

    db = init_database(shot_db)
    manager = StudyWindowManager(
        StudyRecordRepository(db),
        ExpenseRepository(db),
        AccountRepository(db),
        JournalRepository(db),
    )
    window = manager.open()
    window.resize(1040, 700)
    settle(app)

    # 文件名用英文：GitHub 渲染中文路径会转义，链接容易断
    slugs = ("study", "journal", "assets", "flows")
    for index, (button, _page) in enumerate(window._tabs):
        window.show_page(index)
        settle(app)
        slug = slugs[index] if index < len(slugs) else f"page-{index + 1}"
        window.grab().save(str(OUT / f"{index + 1}-{slug}.png"))
        print(f"saved {index + 1}-{slug}.png  ({button.text()})")

    db.close()
    shutil.rmtree(temp_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
