# CatStudy 开发文档

> 版本：`2b119d6`（资产/负债、收支联动、全屏计时牌、日记，schema v7）
> 文档目标：**只读这份文档 + 仓库里的素材文件，能把这套程序重新手搓一遍**，并且知道每一步为什么这么做、错了会怎样。

---

## 0. 这份文档怎么用

| 你的目的 | 看哪几章 |
|---|---|
| 从零重建 | 第 3、4 章 → 按路线图逐层实现，每章末尾有验收清单 |
| 加功能 | 第 5 章（分层纪律）→ 第 6/8/9/10 章对应层 → 第 15 章 |
| 出 bug 排查 | 第 14 章陷阱清单，基本覆盖了已经踩过的全部坑 |
| 交接给别人 | 全文；重点第 4 章（重建顺序）与第 14 章（坑） |

文档里的所有常量、字段名、方法签名都取自当前代码，改代码时请同步改这里，否则这份文档会变成谎言。

---

## 1. 项目概览

**CatStudy** 是一个 Windows 桌面应用：一只像素橘白猫浮在桌面上，负责三件事——

1. **专注计时**：番茄钟（25 分钟）/ 正计时，结束后自动写进当天学习记录；
2. **学习记录**：笔记本风格的窗口，看每天学了什么、连续打卡多少天；
3. **资产与流水**：管自己的资产、负债与净资产走势，以及日常支出流水。

### 1.1 已实现

- 无边框透明置顶的桌宠窗口，可拖动、双击开面板、右键菜单
- 坐姿静止 / 学习时原地走 8 帧循环
- 番茄钟 + 正计时，暂停/继续/结束/放弃，猫下方浮动读口气泡
- 全屏计时牌：铺满整个桌面的大号倒计时，三米外可见，Esc 或点击收起（不停表）
- 学习记录：月历打标记、按科目筛选、当天列表、增删改、今日合计、连续打卡
- 日记：一天一篇、左栏时间线回看、右边写正文，停止打字 1.2 秒自动保存，清空正文即删除
- 资产：账户清单（资产/负债）、总资产/总负债/净资产、负债比例、近 30 天净资产走势
- 流水：收入与支出、分类筛选、可选联动账户余额、当月结余与分类明细、
  金额支持算式（`6.9+2.49`）
- 开机自启动开关（注册表）
- 476 项自动化测试

### 1.2 明确没做（别以为是漏了）

- 云同步、多设备、账号体系
- 独立的待办/任务系统（参考图里那栏，实际对应"当天学习记录"）
- 预算、报表导出、多币种
- 日记的图片/富文本：纯文本最稳，插入图片要处理存储、缩放、导出三件事
- 日记全文检索：现在只能按日期翻，找"上次写过什么"要靠翻列表
- 定期自动记账（房租、订阅这类），目前每笔都要手输
- 转账（从一个账户转到另一个账户）——现在只能记成一笔支出 + 一笔收入
- 宠物成长系统（`core/growth.py` 只有会抛 `NotImplementedError` 的骨架）
- 跨平台。`core/autostart.py` 在非 Windows 上是空操作，但窗口遮罩等行为只在 Windows 上验证过

---

## 2. 环境与目录

### 2.1 版本（实测可用，作为下限）

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.14.4 | 用了 `X \| None`、`from __future__ import annotations`，3.10+ 可跑 |
| PySide6 | 6.12.0 | Qt6。不要用 PyQt，代码里用的是 PySide6 的信号/枚举写法 |
| Pillow | 13.0.0 | 只用于素材提取和图标生成，运行时不依赖 |
| sqlite3 | 3.50.4 | Python 标准库，无需安装 |

`requirements.txt`：

```
PySide6>=6.12.0
Pillow>=13.0.0
```

### 2.2 目录结构

```
CatStudy/
├── main.py                     # 入口：连库 → 建 QApplication → 起桌宠 → 接线
├── requirements.txt
├── core/                       # 纯逻辑与数据，禁止 import PySide6
│   ├── database.py             # 连接、建表、迁移、版本
│   ├── study_records.py        # 学习记录仓储 + 日期归一化
│   ├── accounts.py             # 资产/负债账户 + 净资产快照
│   ├── journal.py              # 日记仓储（一天一篇）
│   ├── expenses.py             # 支出流水仓储 + 月度汇总
│   ├── timer.py                # 计时状态机（可注入假时钟）
│   ├── autostart.py            # 注册表 Run 键读写
│   └── growth.py               # 成长系统骨架（未实现）
├── ui/                         # 全部 Qt 代码
│   ├── theme.py                # 调色板 + 全局 QSS + apply_theme
│   ├── sprite.py               # JSON 素材加载、渲染、遮罩、动画调度
│   ├── pet_window.py           # 桌宠窗口
│   ├── timer_bubble.py         # 计时气泡（独立窗口）
│   ├── focus_overlay.py        # 全屏计时牌（铺满桌面的大号倒计时）
│   ├── formatting.py           # 纯函数：时长/金额/日期文案
│   ├── record_dialog.py        # 学习记录表单
│   ├── study_view.py           # 三栏学习记录视图
│   ├── journal_view.py         # 日记页（左时间线 + 右编辑器）
│   ├── account_dialog.py       # 资产/负债账户表单
│   ├── assets_view.py          # 三栏资产视图（含负债比例条）
│   ├── sparkline.py            # 净资产走势折线（自绘，零依赖）
│   ├── expense_dialog.py       # 支出表单
│   ├── expense_view.py         # 三栏流水视图
│   └── main_window.py          # 三页签容器 + StudyWindowManager
├── assets/
│   ├── cat/cat_study.json      # 当前使用的角色素材（唯一真源）
│   ├── cat/cat_sit.json        # 上一步的坐姿素材，保留
│   ├── cat/cat_walk.json       # GIF 提取出的走路素材，保留
│   ├── cat/idle.json           # 最早的 16x16 眨眼素材，保留
│   ├── cat/character_sit.*     # 旧素材存档，未使用
│   └── icon/catstudy.ico/png   # 由素材生成的应用图标
├── data/catstudy.db            # 运行时生成，已被 .gitignore 忽略
├── docs/                       # 本文件 + 旧交接文档
├── tools/
│   ├── extract_walk_frames.py  # GIF → 像素矩阵 JSON
│   └── make_desktop_shortcut.py# 生成桌面 .lnk
└── tests/                      # 476 项 unittest
```

### 2.3 建环境

```bat
cd /d D:\CatStudy
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2.4 运行

```bat
:: 有控制台，出错能看到 traceback（开发时用这个）
.venv\Scripts\python.exe main.py

:: 无控制台（日常使用 / 快捷方式用这个）
.venv\Scripts\pythonw.exe main.py
```

退出必须走**右键猫 →「退出程序」**。直接关窗口关不掉：应用设了 `setQuitOnLastWindowClosed(False)`（原因见 9.2）。

---

## 3. 从零重建路线图

按这个顺序做，每一步都能独立验证，不会到最后一起崩。

| 里程碑 | 做什么 | 验收方式 |
|---|---|---|
| **M0 骨架** | 建目录、`requirements.txt`、`.gitignore`（忽略 `.venv/`、`*.db`、`*.db-wal`、`__pycache__/`） | `python -c "import PySide6"` 通过 |
| **M1 桌宠** | `ui/sprite.py` + `ui/pet_window.py` + 一个最小 `main.py`：显示透明置顶猫，能拖，右键能退出 | 猫出现在屏幕上，透明区域点得到桌面（能点中下面的图标） |
| **M2 素材** | 把角色 JSON 装进 `assets/cat/`，`SpriteSheet` 按 JSON 渲染出 78×96 的猫 | 截图不糊、无白边、DPI 125% 下不缩小 |
| **M3 数据层** | `core/database.py` + `core/study_records.py`，建库建表、仓储 CRUD | 用 sqlite3 CLI 打开 `data/catstudy.db` 能看到表和索引；重复启动不报错 |
| **M4 记录界面** | `theme.py` → `formatting.py` → `record_dialog.py` → `study_view.py` → `main_window.py` | 月历能切月、点日期换列表、能增删改、相邻月份日期是灰的 |
| **M5 计时** | `core/timer.py` 状态机 + 桌宠菜单 + `timer_bubble.py` + `main.py` 落库 | 25 分钟到点自动写库；不足 1 分钟不写 |
| **M6 动画** | 素材加 `walk` 角色，`AnimationPlayer.set_walking()`，计时开始/结束联动 | 开始计时猫走，结束停 |
| **M7 流水** | `expenses` 表（含 `kind` 与 `account_id`）+ `core/expenses.py` + 两个 UI 文件 + 顶部页签 | 记一笔后当月收入/支出/结余都对；选账户时余额跟着变 |
| **M8 资产** | `accounts` + `net_worth_snapshots` 两表 + `core/accounts.py` + 三个 UI 文件（含自绘折线）+ 第三个页签 | 加账户后净资产、比例、走势都对；同一天多次改动只留一条快照 |
| **M9 分发** | 图标、桌面快捷方式、开机自启动、备份 | 双击桌面图标能起；勾上自启动后重启生效 |

经验：**M1/M2 一定要在真实屏幕上验**。离屏渲染（`QT_QPA_PLATFORM=offscreen`）下中文会变成方块，遮罩和透明效果也不准，只能看布局不能看观感。

---

## 4. 架构与分层纪律

```
main.py（接线层）
   │  只做：连库、建 QApplication、建对象、连信号
   ├──> ui/  ──────────────> core/（只依赖接口，不碰 SQL）
   │      pet_window / study_view / expense_view / dialogs
   └──> core/（仓储、计时、自启动）
```

### 4.1 三条硬规则

1. **`core/` 不许 import PySide6。** 计时、仓储必须能脱离 GUI 单测。`core/timer.py` 连 `QTimer` 都不用，靠外部 250ms 轮询读它。
2. **`ui/` 不许出现 SQL，也不许 import sqlite3。** 全部走仓储方法。这样换存储引擎、加缓存、加迁移都不用动界面。
3. **`pet_window.py` 不许 import 仓储。** 它只发信号（`studyRecordsRequested`、`focusSessionFinished`），落库在 `main.py`。桌宠因此可以在没有数据库的情况下单测。

### 4.2 依赖方向

`ui` → `core` 单向。`ui/main_window.py` 依赖 `ui/study_view.py` 和 `ui/expense_view.py`；`ui/study_view.py` 依赖 `ui/record_dialog.py` 和 `ui/formatting.py`。不存在 `core` 反向依赖 `ui`，也不存在 `ui` 模块之间的循环 import。

---

## 5. 数据层

### 5.1 库文件与连接

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent   # core/ 的上一级
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "catstudy.db"
```

路径由 `__file__` 推导，**不写死盘符**，所以整个项目搬到别的目录仍然能用。

`DatabaseManager.connect()` 做的事，顺序不能乱：

```python
self.db_path.parent.mkdir(parents=True, exist_ok=True)   # data/ 可能被删
conn = sqlite3.connect(str(self.db_path))
conn.row_factory = sqlite3.Row                            # 让查询结果支持 row["列名"]
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA journal_mode = WAL")                 # 读写并发更好
self._connection = conn
self.ensure_schema()
```

- 已连接时重复调用 `connect()` 直接返回旧连接（幂等）。
- `close()` 先 `commit()` 再关，`finally` 里保证连接被置空。
- 提供 `__enter__` / `__exit__`，可 `with DatabaseManager(p) as db:`。
- `init_database(path=None)` 是唯一对外入口，返回已连接的 manager。

### 5.2 表结构

#### app_meta

```sql
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
```

只存一行：`('schema_version', '4')`。

#### study_records

```sql
CREATE TABLE IF NOT EXISTS study_records (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    study_date       TEXT    NOT NULL
                     CHECK (study_date IS date(study_date)),
    subject          TEXT    NOT NULL,
    duration_minutes INTEGER CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
    content          TEXT    NOT NULL DEFAULT '',
    source           TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
```

设计要点，逐条都别改：

- **同一天允许多条**：`study_date` 上没有唯一约束。番茄钟一天攒好几条是常态。
- **`duration_minutes` 可空**：只记"学了什么"不记时长是合法的。UI 里 `0` 会转成 `NULL` 入库。
- **`content` 默认空串而非 NULL**：省掉界面里一堆 `None` 判断。
- **`source` 故意不加 CHECK**：来源种类以后会增加（任务打卡、导入），加约束就得重建表。合法性在仓储层用 `SOURCES` 白名单管。
- **日期约束是 `study_date IS date(study_date)`**，这是本项目最容易写错的一处，见 5.3。
- **时间戳带 `DEFAULT (datetime('now','localtime'))`**：即使有人绕过仓储直接 INSERT，也能得到本地时间。

#### expenses（收支流水）

```sql
CREATE TABLE IF NOT EXISTS expenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_date TEXT    NOT NULL
                 CHECK (expense_date IS date(expense_date)),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    category     TEXT    NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    kind         TEXT    NOT NULL DEFAULT 'expense'
                 CHECK (kind IN ('expense', 'income')),
    account_id   INTEGER REFERENCES accounts (id) ON DELETE SET NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
```

- `amount_cents` 是**整数分且恒为正**，方向只由 `kind` 决定。存负数的话，
  "本月支出 / 收入 / 结余 / 分类占比"每处都要判断符号，错一次就全错。
- `kind` 只有 `expense` / `income` 两种，用 CHECK 收死。
- **`account_id` 为 NULL 表示这条流水不联动资产负债表**。这是产品要求的核心：
  用户可以选择"只记一笔账，余额我自己对"，也可以挂钩到某个账户、写入时同步扣/加。
  两种用法共存于同一张表，靠这一个可空外键区分。
- `ON DELETE SET NULL`：账户被删掉时流水保留，只是不再追溯影响——比级联删除安全得多。
- 不建分类表：分类是自由文本，下拉只是候选名单。`list_categories(kind)` 从数据里聚合，
  不会出现空标签；收入与支出的候选清单是分开的两份（`CATEGORY_PRESETS` /
  `INCOME_CATEGORY_PRESETS`），避免"工资"出现在支出下拉里。

#### accounts（资产 / 负债账户）

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    kind          TEXT    NOT NULL CHECK (kind IN ('asset', 'liability')),
    balance_cents INTEGER NOT NULL DEFAULT 0 CHECK (balance_cents >= 0),
    category      TEXT    NOT NULL DEFAULT '',
    note          TEXT    NOT NULL DEFAULT '',
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
```

- `kind` 只有两个取值，用 CHECK 收死：资产 `asset`、负债 `liability`
- **余额强制 ≥ 0**，符号由 `kind` 决定，`净资产 = Σ(asset) − Σ(liability)`。
  允许负债存负数的话，这条公式要在两处取反，极易算错
- 不建分类表，`category` 是自由文本，下拉只是候选
- `sort_order` 目前没有 UI 入口，留着给以后的手动排序用

#### net_worth_snapshots（净资产快照）

```sql
CREATE TABLE IF NOT EXISTS net_worth_snapshots (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date           TEXT    NOT NULL UNIQUE
                            CHECK (snapshot_date IS date(snapshot_date)),
    total_assets_cents      INTEGER NOT NULL DEFAULT 0,
    total_liabilities_cents INTEGER NOT NULL DEFAULT 0,
    created_at              TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
```

两个设计决定：

1. **`snapshot_date` 上加了 UNIQUE**，配合 `INSERT ... ON CONFLICT DO UPDATE`，
   实现"一天最多一条，当天多次改动覆盖"。不这么做，一天改三次余额就会在走势图上
   插三个点，看起来像剧烈波动。
2. **分开存总资产和总负债**，不直接存净资产。只存净值就无法区分"资产涨了 5 万"
   和"负债少了 5 万"——这两件事性质完全不同，以后出报表也拿不回明细。

#### journal_entries（日记）

```sql
CREATE TABLE IF NOT EXISTS journal_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT    NOT NULL UNIQUE
               CHECK (entry_date IS date(entry_date)),
    content    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
)
```

**为什么不复用 `study_records.content`**：那张表一行 = 一段有科目的学习，一天可以有
很多行，是"发生额"式的；日记是"这一天整体怎么样"，一天只有一份，没有科目和时长
维度。塞进同一张表会让查询到处打补丁——查"今天学了多久"要排除日记行，查"今天的
日记"要限定只有一行。

`UNIQUE(entry_date)` 是"一天一篇"的唯一保证，也是 upsert 的冲突目标。日期校验沿用
`IS date()`（不是 `GLOB`，理由见 5.3）。

#### 索引

```sql
CREATE INDEX IF NOT EXISTS idx_study_records_study_date ON study_records (study_date);
CREATE INDEX IF NOT EXISTS idx_study_records_subject    ON study_records (subject);
CREATE INDEX IF NOT EXISTS idx_expenses_date            ON expenses (expense_date);
CREATE INDEX IF NOT EXISTS idx_expenses_category        ON expenses (category);
CREATE INDEX IF NOT EXISTS idx_accounts_kind            ON accounts (kind);
```

`SCHEMA_STATEMENTS` 元组 = 五张表 + 五个索引，`ensure_schema()` 按序执行，每句都是 `IF NOT EXISTS`，因此每次启动执行都安全。

**索引分成 `_INDEXES` 与 `_ACCOUNT_INDEXES` 两组**，不是随手分开的：v1→v2 的整表重建
会重跑 `_INDEXES`，那时 `accounts` 可能还不存在，把账户索引混进去会报
`no such table: accounts`。

### 5.3 为什么日期约束不能只用 GLOB

第一版写的是：

```sql
CHECK (study_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
```

它能拦住 `2026-3-5`，但**放行了 `2026-02-30`、`2026-13-01`、`2026-00-10`**——这些都是 10 个字符、都符合该模式。GLOB 里的 `[0-9]` 是字符类，不是"数字通配符"，没有语义校验能力。

正确写法：

```sql
CHECK (study_date IS date(study_date))
```

原理：SQLite 的 `date()` 会把 `'2026-02-30'` 归一化成 `'2026-03-02'`（与自身不等）、把 `'2026-13-01'` 判为 NULL（`x IS NULL` 为假），只有**原样合法**的日期才与自身相等。这一个表达式同时强制了：

- 格式：`'2026-3-5'`、`'20260305'`、`'2026-03-05 10:00:00'` 都不相等 → 拒绝
- 真实存在：`2024-02-29` 通过，`2026-02-29` 拒绝

Python 层必须给出一致的结论，`normalize_date()` 负责这件事（见 5.5）。

### 5.4 版本与迁移

`SCHEMA_VERSION = 4`。`_migrate(from_version)` 用 `if from_version < N` 串联，逐级升级：

| 版本 | 变更 | 实现 |
|---|---|---|
| v1 → v2 | 日期 CHECK 从 GLOB 改为 `IS date()` | `_rebuild_study_records_v2()`：SQLite 改不了既有 CHECK，只能重建表 |
| v2 → v3 | `study_records` 加 `source` 列 | `ALTER TABLE ... ADD COLUMN`，原地、不丢数据、先查 `PRAGMA table_info` 保证幂等 |
| v3 → v4 | 新增 `expenses` 表 | 直接执行建表语句（本身就是 `IF NOT EXISTS`） |
| v4 → v5 | 新增 `accounts` 与 `net_worth_snapshots` | 执行两条建表语句 + 账户索引 |
| v5 → v6 | 流水加 `kind`、`account_id`；账户余额放开负数 | 重建 `accounts`（去 CHECK）+ 两条 `ADD COLUMN` |
| v6 → v7 | 新增 `journal_entries`（日记） | 直接执行建表 + 建索引（都是 `IF NOT EXISTS`） |

v1 → v2 的重建流程，每一步都有原因：

```python
# 1. 先校验旧数据能否通过新约束，不合格就中止（别把坏数据搬过去）
bad = SELECT COUNT(*) WHERE study_date IS NOT date(study_date)
if bad: raise RuntimeError(说明要修哪些行)

# 2. 记住行数
before = SELECT COUNT(*)

# 3. 改名 → 建新表 → 复制 → 删旧表 → 重建索引
ALTER TABLE study_records RENAME TO study_records__v1
CREATE TABLE study_records (...)          # 新约束
INSERT INTO study_records (...) SELECT ... FROM study_records__v1
DROP TABLE study_records__v1
CREATE INDEX ...

# 4. 校验行数没变
if after != before: raise RuntimeError
```

版本号只在 `_migrate()` 全部跑完后才 `UPDATE app_meta`，中途抛异常则整个 `with conn:` 事务回滚，库停在旧版本，不会出现"版本说升了、表却没改"的半成品。

### 5.5 StudyRecordRepository

```python
class StudyRecordRepository:
    def __init__(self, db: DatabaseManager)
```

| 方法 | 签名 | 行为 / SQL 要点 |
|---|---|---|
| `add` | `(study_date, subject, content="", duration_minutes=None, source=None) -> int` | INSERT，返回 `lastrowid`；`commit()` |
| `get` | `(record_id: int) -> StudyRecord \| None` | 按主键 |
| `list_by_date` | `(study_date) -> list[StudyRecord]` | `WHERE study_date = ? ORDER BY created_at, id` |
| `list_by_date_range` | `(start, end) -> list` | `BETWEEN ? AND ?`，闭区间，用于整月打标记 |
| `list_recent` | `(limit=50) -> list` | `ORDER BY study_date DESC, created_at DESC, id DESC LIMIT ?`；`limit<=0` 返回 `[]` |
| `list_subjects` | `() -> list[str]` | `GROUP BY subject ORDER BY COUNT(*) DESC, subject ASC`，用于左侧标签 |
| `list_dates` | `() -> list[str]` | `SELECT DISTINCT study_date ORDER BY study_date DESC`，用于连续打卡 |
| `count` | `(study_date=None) -> int` | 给日期则只数当天 |
| `update` | `(record_id, *, study_date=_UNSET, subject=_UNSET, content=_UNSET, duration_minutes=_UNSET) -> bool` | 只拼传了的列；每次都更新 `updated_at`；返回 `rowcount > 0` |
| `delete` | `(record_id) -> bool` | 返回是否命中 |

`_UNSET` 是一个模块级 `object()` 哨兵，用来区分"没传"和"显式传 None"。没有它就无法实现"把时长清空"这个操作——`duration_minutes=None` 必须表示"设为 NULL"，而不是"不改"。

`update()` 里拼接的只是**固定的列名片段**，所有值仍走 `?` 绑定，不存在注入。

`StudyRecord` 是 `@dataclass(frozen=True)`，字段顺序：`id, study_date, subject, duration_minutes, content, created_at, updated_at, source=None`。`from_row()` 负责把 `sqlite3.Row` 转成它，`duration_minutes` 与 `source` 都做 `None` 兼容。

### 5.6 日期归一化

```python
def normalize_date(value: str | date | datetime) -> str   # -> 'YYYY-MM-DD'
```

- `datetime` → `.date()`
- `date` → `.isoformat()`
- `str` → 先 `date.fromisoformat()`；失败再试 `strptime("%Y-%m-%d")`（兼容 `2026-3-5` 这类未补零写法）；都失败抛 `ValueError`
- 其它类型 → `TypeError`

`date.fromisoformat()` 在 Python 3.11+ 已能接受 `2026-3-5`，但保留 `strptime` 兜底是为了低版本也能跑。

### 5.7 ExpenseRepository

```python
CATEGORY_PRESETS = ("吃饭", "交通", "学习", "购物", "娱乐", "其他")
INCOME_CATEGORY_PRESETS = ("工资", "兼职", "奖学金", "投资收益", "红包", "其他")
DEFAULT_CATEGORY = "其他"

FLOW_EXPENSE = "expense"; FLOW_INCOME = "income"
FLOW_LABELS = {"expense": "支出", "income": "收入"}
```

| 方法 | 签名 | 要点 |
|---|---|---|
| `add` | `(expense_date, amount_cents, category="其他", note="", kind="expense", account_id=None) -> int` | 金额必须 `> 0`；给 `account_id` 时同一次操作里改余额并刷快照 |
| `get` | `(expense_id) -> Expense \| None` | |
| `list_by_date` | `(expense_date) -> list` | 按创建顺序 |
| `list_by_month` | `(year, month, kind=None) -> list` | 日期倒序；`kind` 为 None 时收支都返回 |
| `month_total_cents` | `(year, month) -> int` | **只算支出**（历史方法，语义未变） |
| `month_income_cents` | `(year, month) -> int` | 只算收入 |
| `month_net_cents` | `(year, month) -> int` | 收入 − 支出，可为负 |
| `category_totals` | `(year, month, kind="expense") -> list[tuple[str, int]]` | `GROUP BY category ORDER BY SUM DESC` |
| `list_categories` | `(kind="expense") -> list[str]` | 按笔数降序，用于左侧标签 |
| `count` | `() -> int` | |
| `update` | `(expense_id, *, expense_date, amount_cents, category, note, kind, account_id)` | `_UNSET` 语义；改了金额/方向/账户会**先撤旧影响再施加新的** |
| `delete` | `(expense_id) -> bool` | 若联动过账户，会把那笔影响退回去 |

`Expense` 除了原字段还带 `kind`、`account_id`，以及两个派生属性：
`is_income`、`signed_cents`（收入为正、支出为负，求和直接用）。

**联动的核心是一个纯函数**，四种组合都能单测：

```python
def flow_delta(flow_kind, account_kind, amount_cents) -> int:
    # 支出+资产 → −金额   支出+负债 → +金额（刷信用卡，欠款变多）
    # 收入+资产 → +金额   收入+负债 → −金额（还信用卡，欠款变少）
```

`ExpenseRepository` 内部持有一个 `AccountRepository`（同一个连接），
余额调整与快照刷新都复用它，不重复实现。

**为什么联动逻辑放仓储层而不是界面层**：一次"记一笔 + 扣余额 + 存快照"
必须是一个原子动作。放界面就意味着调用方可能只做前两步，余额和流水从此对不上。

月份范围：

```python
def _month_range(year, month):
    if not 1 <= month <= 12: raise ValueError
    first = date(year, month, 1)
    last = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    return first, last
```

`month=12` 时 `12//12=1`、`12%12+1=1` → 次年 1 月 1 日减一天 = 12 月 31 日。闰年、月末都天然正确。

### 5.8 AccountRepository

```python
ASSET = "asset"; LIABILITY = "liability"
KIND_LABELS = {ASSET: "资产", LIABILITY: "负债"}
CATEGORY_PRESETS = {
    ASSET:     ("现金", "银行卡", "支付余额", "投资", "房产", "其它"),
    LIABILITY: ("信用卡", "花呗", "房贷", "车贷", "借款", "其它"),
}
```

| 方法 | 签名 | 要点 |
|---|---|---|
| `add` | `(name, kind=ASSET, balance_cents=0, category="", note="") -> int` | 写完自动刷新当天快照 |
| `get` | `(account_id) -> Account \| None` | |
| `list_all` | `(kind=None) -> list[Account]` | `ORDER BY kind, sort_order, id`；资产在前（`'asset' < 'liability'` 字典序正好） |
| `list_by_kind` | `(kind) -> list` | `list_all` 的别名，语义更清楚 |
| `count` | `() -> int` | |
| `totals` | `(kind=None) -> NetWorth` | 一次 `GROUP BY kind` 拿两边；`COALESCE(SUM, 0)` 保证空表返回 0 |
| `category_totals` | `(kind) -> list[tuple[str, int]]` | 某一边按类别汇总，金额降序，空类别显示"未分类" |
| `list_categories` | `(kind) -> list[str]` | 实际用过的类别（去空串、按次数降序），给对话框做候选 |
| `update` | `(account_id, *, name, kind, balance_cents, category, note)` | `_UNSET` 语义，只改传了的字段；写完刷新快照 |
| `delete` | `(account_id) -> bool` | 删完刷新快照 |
| `refresh_snapshot` | `(day=None) -> Snapshot` | UPSERT 当天；`day` 可指定历史日期（测试与补录用） |
| `list_snapshots` | `(limit=None) -> list[Snapshot]` | **升序返回**（旧→新），给 `limit` 时取最近 N 条但仍升序 |
| `latest_snapshot` | `() -> Snapshot \| None` | |

两个 dataclass：

```python
@dataclass(frozen=True)
class NetWorth:
    assets_cents: int
    liabilities_cents: int
    @property net_cents          # assets - liabilities，可为负
    @property liability_ratio    # 0.0~1.0

@dataclass(frozen=True)
class Snapshot:
    id, snapshot_date, total_assets_cents, total_liabilities_cents, created_at
    @property net_cents
```

`liability_ratio` 的两个边界，容易写错：

- 资产为 0 但有负债 → 返回 `1.0`（不能除零，也不能返回 0，否则"全是负债"会显示成"没有负债"）
- 资产为 0 且无负债 → `0.0`

### 5.9 为什么账户是独立模型（存量 vs 发生额）

| | `expenses`（发生额） | `accounts`（存量） |
|---|---|---|
| 语义 | 今天花了 30 块 | 这张卡现在有 8000 块 |
| 修改 | 新增一条，历史保留 | 直接覆盖，只保留当前值 |
| 聚合 | 按月求和 | 按类型求和（资产 / 负债） |
| 时间性 | 有日期，会累积 | 只有"现在"，历史靠快照 |

把存量塞进流水表，只能靠"用一条条调整记录逼近余额"：漏记一笔就永久跑偏，
而且没有对账入口。**手工改余额本身就是对账**，所以余额由用户直接填。

两者仍然可以**按需联动**：流水上有一个可空的 `account_id`，选了账户就在
写入时把影响加到余额上（规则见 `flow_delta`），不选就各记各的。这样
"余额以我为准"和"记完账自动扣"两种习惯都满足，而不是二选一——
如果强行只保留一种，另一类用户会觉得软件在跟自己作对。

### 5.10 金额为什么用整数分

`0.1 + 0.2 == 0.30000000000000004`。几十笔累加之后，账本总额会差几分钱，用户会认为软件算错了。所以：

- 存储、计算、传输全用 `int` 的"分"
- 只在显示时 `format_money()` → `¥1,250.00`
- 输入解析 `parse_money()` 用 `Decimal`，四舍五入到分（`ROUND_HALF_UP`），拒绝空串/负数/非数字/超上限（9999999 元）

### 5.11 金额输入支持算式

记账时常要把几笔零钱加在一起（`6.9+2.49`），逼用户先开计算器很反人类，
所以 `parse_money` 直接接受四则运算。

**绝不能用 `eval`**：输入框内容来自用户，等于把任意代码执行交给界面。
实现是 `ast.parse(text, mode="eval")` 后自己遍历，只放行四类节点：

| 允许 | 拒绝 |
|---|---|
| `Constant`（int / float） | 字符串、布尔、复数 |
| `UnaryOp`（`+` / `-`） | 取反 `~`、`not` |
| `BinOp`（`+ - * /`） | 幂 `**`、取模、位运算 |
| `Expression` | 函数调用、属性访问、推导式、条件表达式 |

除法除零抛"除数不能为 0"；全角 `＋－×÷（）` 先统一成半角（中文输入法很常见）。
算式长度上限 120 字符，防误粘贴一大段文本。

---

### 5.12 JournalRepository

```python
MAX_CONTENT_LENGTH = 1_000_000   # 一亿字够任何人写，主要是防误粘贴整个文件
```

| 方法 | 签名 | 要点 |
|---|---|---|
| `get` | `(day) -> JournalEntry \| None` | |
| `save` | `(day, content) -> JournalEntry \| None` | upsert；**内容为空则删行并返回 None** |
| `delete` | `(day) -> bool` | 返回是否真的删掉了 |
| `list_recent` | `(limit=None) -> list` | 日期倒序；`limit` 是"最近 N 篇" |
| `list_by_month` | `(year, month) -> list` | 上界用下月 1 号，天然处理 12 月跨年 |
| `count` / `first_date` | `() -> int` / `() -> str \| None` | |
| `dates` | `() -> set[str]` | 只取日期不取正文，供标记用 |

`JournalEntry` 带两个派生属性：

```python
@property word_count   # len(content.strip())，中文按字符计
@property summary      # " ".join(content.split())，把换行压成空格
```

字数用字符数而不是分词：中文没有词边界，按词算既不准也没有直觉；Word 的中文
计数也是字符数。

**空内容即删除**是刻意的：用户删光正文后不该在列表里留一条空白日记，否则列表
越用越脏、点进去什么都没有。这条规则放在仓储层而不是界面层，是为了让任何调用方
（包括以后的导入/同步）都自动遵守。

---

## 6. 计时核心 `core/timer.py`

### 6.1 状态机

```
IDLE --start--> RUNNING <--resume-- PAUSED
                  |  \--pause-->       ^
                  |                    |
                  +--到点/stop--> FINISHED
FINISHED --start--> RUNNING（下一次会话）
任意状态 --reset--> IDLE
```

```python
class TimerMode(str, Enum):   POMODORO="pomodoro"; STOPWATCH="stopwatch"
class TimerState(str, Enum):  IDLE="idle"; RUNNING="running"; PAUSED="paused"; FINISHED="finished"

POMODORO_MINUTES = 25
```

继承 `str` 是为了能直接 `.value` 写进数据库、打日志，不会出现 `"TimerMode.POMODORO"`。

### 6.2 计时模型：不是"每秒加一"

内部只有两个数：

```python
self._accumulated: float        # 已结束片段的秒数
self._segment_start: float|None # 当前片段的起点（单调时钟）
```

- `start()`：`_accumulated = 0`，`_segment_start = clock()`
- `pause()`：把当前片段折进 `_accumulated`，`_segment_start = None`
- `resume()`：`_segment_start = clock()`
- 读数：`_accumulated + (clock() - _segment_start)`（运行中）或 `_accumulated`

好处：界面卡顿、电脑睡眠、系统时间被改都不会让累计值跑偏——因为它只依赖时间点，不累加误差。代价是需要一个单调时钟，所以 `clock` 默认是 `time.monotonic`，且**必须可注入**（测试用假时钟）。

### 6.3 番茄钟自动收敛

```python
def _settle_if_expired(self):
    if mode 不是 POMODORO: return
    if state 不是 RUNNING: return
    if self._raw_elapsed() < self._pomodoro_seconds: return
    self._accumulated = float(self._pomodoro_seconds)
    self._segment_start = None
    self._state = FINISHED
```

它在 `state` 属性、`elapsed_seconds()` 里都会被调用。原因：如果只在 tick 里判断，那么"界面每 250ms 才读一次"与"任何一次外部读状态"可能给出不一致的结论。放在读路径上，任何人看到的都已经是收敛后的结果，且累计时长钉死在 1500 秒，不会出现负计时或 25:01。

### 6.4 显示取整

```python
def format_clock(seconds) -> str      # MM:SS，超过 1 小时 H:MM:SS，向下取整

def display_text(self) -> str:
    if POMODORO: return format_clock(math.ceil(remaining))  # 一开始显示 25:00
    return format_clock(elapsed)                            # 正计时向下取整
```

番茄钟必须向上取整，否则刚点开始就显示 `24:59`，看起来像已经过了一秒。

`duration_minutes()` = `int(elapsed_seconds()) // 60`，向下取整，直接用于写库。

### 6.5 落库规则（在 `main.py`，不在 timer 里）

```python
def save_focus_session(repository, manager, mode, subject, seconds, study_date=None):
    minutes = seconds // 60
    if minutes < 1:
        return None                      # 不足 1 分钟不写库
    record_id = repository.add(
        study_date=study_date or date.today(),
        subject=subject,
        duration_minutes=minutes,
        source=mode,                     # 'pomodoro' / 'stopwatch'
    )
    manager.refresh_if_open()            # 面板开着就立刻刷新
    return record_id
```

- 过滤 <1 分钟：防止"点错菜单立刻结束"塞一堆 0 分钟记录，把日历和统计污染掉。
- 日期取**结束时**的本地日期（跨零点的会话记在结束那天）。
- 科目来自开始时输入框，默认取最近一条记录的科目，没有则 `"专注"`（`FALLBACK_SUBJECT`）。

### 6.6 验收清单

用假时钟写的用例应覆盖：

- 正计时 90 秒 → `display_text() == "01:30"`
- 番茄钟刚开始 → `"25:00"`；过 1 秒 → `"24:59"`
- 番茄钟跑到 1501 秒 → `state == FINISHED`、`elapsed_seconds() == 1500`
- 暂停 10 分钟后恢复，累计值不包含暂停的 10 分钟
- `stop()` 返回整数秒，且不是负数
- 非法时序调用（未开始就 `pause()`、暂停态 `resume()` 两次）不抛异常

---

## 7. 素材与渲染管线

### 7.1 JSON 契约

`assets/cat/cat_study.json` 既是素材也是唯一真源，PNG 只是渲染产物（甚至可以不生成）。

```json
{
  "name": "cat_study",
  "version": 1,
  "state": "study",
  "grid": [39, 48],
  "cell_pixels": 2,
  "scale": "nearest",
  "palette": { "#": "#402210", "O": "#FBB054", ... },
  "roles": { "base": "sit", "walk": ["walk_0", ..., "walk_7"] },
  "frames": {
    "sit":    ["....", "...."],
    "walk_0": ["....", "...."]
  }
}
```

| 字段 | 含义 | 约束 |
|---|---|---|
| `grid` | `[列数, 行数]` | 所有帧的尺寸必须与首帧一致，否则 `_validate()` 抛错 |
| `cell_pixels` | 一个字符格 = 多少逻辑像素 | 当前 2 → 39×2=78、48×2=96 |
| `scale` | 缩放方式 | 固定 `"nearest"`，代码不读（渲染本身就关抗锯齿） |
| `palette` | 字符 → `#RRGGBB` | 帧里出现的每个非空字符都必须在这里，否则抛错 |
| `roles.base` | 静止帧 | 必填（缺省取第一帧） |
| `roles.blink` | 眨眼帧序列 | 可空；空则不做眨眼动画 |
| `roles.walk` | 走路帧序列 | 可空；非空时**至少 2 帧**，否则抛错 |
| `frames` | 帧名 → 行数组 | 每行长度必须等于列数 |

**空像素**：`.` 和 ` `（空格）都表示透明。`.` 是早期手绘习惯，空格是"把走路帧贴进 39×48 画布"时补位用的。两者等价，代码里由 `EMPTY_SYMBOLS = frozenset({".", " "})` 统一处理。

### 7.2 尺寸公式

```python
device_cell = max(1, floor(cell_pixels * dpr + 0.5))     # 每格占几个物理像素
frame_size  = (round(cols * device_cell / dpr), round(rows * device_cell / dpr))  # 逻辑尺寸
pixmap      = QPixmap(cols * device_cell, rows * device_cell); pixmap.setDevicePixelRatio(dpr)
```

当前素材在 DPR=1.5 下：`device_cell = floor(3.5) = 3` → pixmap 117×144 物理；`frame_size = (78, 96)` 逻辑。窗口实测 78×97（多出的 1px 是给呼吸下沉预留的余量）。

**必须用 half-up，不能用内置 `round`。** `round(2 * 1.25) == 2`（银行家舍入），会让 `cell_pixels=2` 的素材在 125% 缩放下整体缩小 20%。`floor(x + 0.5)` 得到 3，偏向略放大，视觉上更可接受。

### 7.3 渲染

```python
painter.setRenderHint(Antialiasing, False)
painter.setRenderHint(SmoothPixmapTransform, False)
painter.setPen(NoPen)
for 每行每格:
    if symbol 在 palette 里:
        painter.fillRect(col*cell, row*cell, cell, cell, QColor(调色板色))
pixmap.setDevicePixelRatio(dpr)
```

- 逐格 `fillRect` 而不是 `drawPixmap` 缩放原图：**每一格都是整数像素矩形，永远不会出现插值模糊**。
- 渲染结果按 `(帧名, dpr)` 缓存，切换帧不重绘。
- `QPixmap` 必须在 QApplication 建好之后创建（Qt 的硬性要求）。

### 7.4 遮罩

窗口用 `setMask()` 裁成猫的轮廓，否则透明区域虽然在视觉上透明，鼠标事件却仍被窗口吃掉（点不到下面的桌面）。

实现：**直接从字符网格推导**，不用 `QPixmap.mask()`。

```python
def _row_runs(self):     # 所有帧的并集，每行合并成若干连续区间 [(x0,x1), ...]
def mask_region(self):   # 把每个区间按 device_cell 换算成 QRect，合并成 QRegion
def mask_region_with_offsets(self, dpr, offsets):  # 再并上所有可能偏移
```

三个关键决定：

1. **取所有帧的并集**，不只取静止帧。以后加摆尾/抬爪帧时，超出静止帧轮廓的像素不会被悄悄裁掉。
2. **不能用 `QPixmap.mask()`**：它返回的是**设备像素**，再当作逻辑坐标 `setMask` 会错位（DPR≠1 时遮罩明显偏大/偏移）。
3. **区间合并**：如果每格一个 `QRegion` 再 union，39×48 会有上千次合并，启动明显卡顿；按行合并成连续区间只要几十个矩形。

`PetWindow` 里还把遮罩与 `possible_offsets()` 并了一次。当前 `plan_at()` 恒返回 `QPoint(0,0)`（呼吸已停用），这条逻辑实际不起作用，但保留着：一旦恢复呼吸动画，遮罩会自动包含下沉 1px 的区域，不需要再改这里。

### 7.5 动画调度

```python
TICK_MS = 100          # 动画 tick
BLINK_INTERVAL = 34    # 每 34 tick = 3.4 秒眨一次
WALK_FRAME_MS = 120    # 走路每帧 120ms，8 帧 ≈ 0.96 秒一轮
```

`AnimationPlayer`：

```python
plan_at(tick) -> (帧名, QPoint偏移)     # 纯函数，可单测
```

- `walking=True` 且素材有 `walk` 帧 → `roles.walk_frame(tick)`，偏移 `(0,0)`
- 否则 → `plan_frame(tick, roles, blink_interval)`（眨眼动画），偏移 `(0,0)`

`walk_frame()` 按**毫秒**换算而不是按 tick 计数：`elapsed = tick * 100; frames[(elapsed // 120) % len(frames)]`。这样改 `TICK_MS` 不会连带改变走路速度。

`set_walking()` 内部做 `walking and roles.has_walk`，素材没有走路帧时**静默退化为静止**，不抛异常——旧的 `idle.json` 和 `cat_sit.json` 因此仍能直接用。

`start()` 先立即发一帧再启定时器，避免窗口出现"空白几百毫秒"。

### 7.6 新增一种动画（例如摆尾）的手搓清单

1. 在 JSON 的 `frames` 里加帧，尺寸必须与现有帧完全一致（例如都 39×48）。
2. 在 `roles` 里加一个键，如 `"idle_tail": ["tail_0","tail_1","tail_2"]`。
3. `FrameRoles` 加字段 + `has_*` 属性 + `*_frame()` 方法（照抄 `walk`）。
4. `_resolve_roles()` 里解析并校验帧名存在、数量 ≥2。
5. `AnimationPlayer.plan_at()` 里加分支，状态标志（如 `_playing_tail`）与 `set_*()` 方法。
6. 在 `PetWindow` 的合适时机调用 `set_*()`。
7. **不需要动遮罩**：并集已经把新帧算进去了。
8. 加测试：帧名轮转、一圈后回到首帧、缺少帧时报错。

### 7.7 从 GIF 提取像素帧

`tools/extract_walk_frames.py`，用法：

```bat
.venv\Scripts\python.exe tools\extract_walk_frames.py "C:\path\to\cat.gif"
```

算法，按顺序：

1. **去背景**：把"高亮度 + 近乎无彩色"的像素判为背景——`max(r,g,b) >= 225 and (max-min) <= 14`，或 `alpha < 40`。从四边泛洪（BFS），只有与边缘连通的背景才剔除，猫身内部的白色（胸毛）不会被误删。
2. **网格采样**：`CELL = 10`。每个 10×10 格取**不透明像素的中位色**——中位数对 JPEG 噪点不敏感，均值会偏。
3. **判空**：一格内不透明像素少于 `10*10*0.2 = 20` 个，判为空格。比例不能太高，腿很细。
4. **映射调色板**：加权 RGB 距离 `2R² + 4G² + 3B²`（近似人眼敏感度），取最近的调色板符号。这样走路的猫和坐姿的猫共用一个色板，不会一只偏黄一只偏红。
5. **去噪**：某格四邻没有同色格时，用它邻居里最多的颜色替换。只处理孤立格，描边（相邻的深棕）不会被动。
6. **并集裁切**：8 帧共用同一个包围盒，保证动画时猫不会左右跳。
7. 输出 `assets/cat/cat_walk.json`（`cell_pixels: 4`）+ 一张 `cat_walk_preview.png` 供人眼检查。

**为什么 CELL 是 10 不是 20**：源 GIF 是 380×508，按 20px 采样整只猫只有 18×18 格，耳朵和腿会被整体吞掉，只剩一团橘色。10px 得到 35×36 格，勉强能还原四腿。这是试出来的，文档记下来省得下次再试。

**合并进主素材**：走路帧是 35×36，坐姿是 39×48。直接换素材会导致窗口尺寸跳变，因此把走路帧**底部居中贴进 39×48 的空白画布**，得到 `cat_study.json`：

```python
ox, oy = (39 - 35) // 2, 48 - 36      # (2, 12)
canvas[oy + y][ox + x] = walk[y][x]
```

### 7.8 应用图标

从 `cat_sit.json` 的 `sit` 帧渲染，按最近邻放大到 256/128/64/48/32/24/16，居中放进正方形透明画布，用 Pillow 存成多尺寸 `.ico` + 一张 `.png`。图标里特意不做圆角/描边处理——Windows 自己会加。

---

## 8. 桌宠窗口 `ui/pet_window.py`

### 8.1 窗口属性

```python
self.setWindowFlags(
    Qt.WindowType.FramelessWindowHint        # 无标题栏
    | Qt.WindowType.WindowStaysOnTopHint     # 永远置顶
    | Qt.WindowType.Tool                     # 不进任务栏、不抢焦点
)
self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
self.setWindowTitle("CatStudy Pet")
```

`Qt.Tool` 带来两个后果，必须知道：

- 任务栏没有图标（符合桌宠习惯）
- **Qt 不把它当"主窗口"**，所以 `setQuitOnLastWindowClosed(False)` 必须设，否则关掉记录窗口时整个应用会退出（猫也会消失）

### 8.2 构建顺序

```python
width, height = sprite.frame_size(dpr)
label = QLabel(self); label.resize(width, height)
label.setPixmap(sprite.base_pixmap(dpr))
label.setAttribute(WA_TransparentForMouseEvents, True)   # 点击穿透到窗口
self.resize(width, height + max_down_offset)
self._setup_mask()                                       # 必须在 resize 之后
```

顺序错了遮罩尺寸就对不上。`max_down_offset` 当前为 1（呼吸下沉幅度），即使不呼吸也留着，避免将来改回去时窗口把猫脚裁掉。

### 8.3 DPR 变化

跨屏拖动（100% → 150%）时像素会糊。监听：

```python
def event(self, e):
    if e.type() == QEvent.Type.DevicePixelRatioChange:   # 用 getattr 兜版本差异
        self._rebuild_for_dpr()
    return super().event(e)
```

`_rebuild_for_dpr()` 比对 DPR 是否真的变了（`abs(dpr - old) < 1e-6` 直接返回），然后更新 player 的 DPR 并重建 UI + 遮罩。

### 8.4 拖拽

```python
mousePressEvent:  _drag_offset = globalPosition - frameGeometry().topLeft()
mouseMoveEvent:   if _drag_offset 且有左键: move(globalPosition - _drag_offset)
mouseReleaseEvent: _drag_offset = None
```

用 `frameGeometry().topLeft()` 而不是 `pos()`：无边框窗口两者通常相同，但用 `frameGeometry` 更稳。

### 8.5 双击：为什么不用 `mouseDoubleClickEvent`

这是本项目最反直觉的一处。

**现象**：桌宠是置顶的 `Qt.Tool` 窗口，首次被点击时系统把这次点击消耗在"激活窗口"上，`WM_LBUTTONDBLCLK` 不一定派发。实测 5 次里只有 3 次能收到双击事件。

**解法**：在 `mousePressEvent` 里自己判：

```python
is_double = (
    _last_press_at is not None
    and (now - _last_press_at) * 1000 <= QApplication.doubleClickInterval()
    and (position - _last_press_pos).manhattanLength() <= DOUBLE_CLICK_MAX_SHIFT   # 6px
)
```

命中就开面板并清空 `_last_press_at`（防止第三次点击又触发一次）；否则只记录时间和位置。

**第二个坑**：一次物理按下偶尔会被派发**两次**（子标签一次、窗口一次，探针日志里同时间戳同坐标两个 press）。如果不处理，单次按下在 6px 内紧跟下一次按下就会被误判为双击——表现是"拖一下猫，记录窗口莫名其妙弹出来"。

解法是加一个布尔守卫：

```python
if self._left_pressed:
    return            # 同一次按下的第二次派发，直接忽略
self._left_pressed = True
...
mouseReleaseEvent: self._left_pressed = False
```

**第三层保险**：`mouseDoubleClickEvent` 仍然保留（平台真派发了就走这里），但统一走 `_request_study_window()`，它带 0.35 秒去重（`REQUEST_DEDUPE_SECONDS`），同一次双击只会打开一次窗口。

三层叠加后实测 5/5 成功。

### 8.6 右键菜单

顺序固定，`tests/test_app_wiring.py` 里有断言：

```
专注 ▸   开始番茄钟（25 分钟） / 开始正计时 / ─── / 暂停 / 结束并保存 / 放弃本次
         ─── / 全屏计时（checkable）
开机自启动   （checkable）
学习记录…
───
退出程序
```

`_sync_menu_state()` 挂在 `aboutToShow` 上，每次展开前按计时器状态刷新：

- 会话进行中：两个"开始"禁用（防止误触把当前专注清零）
- 无会话：「暂停/结束/放弃」禁用
- `pause_action` 文案在「暂停」和「继续」之间切换

`setChecked` 会触发 `toggled` 信号。菜单展开时只是"回显"自动启动状态，必须先 `blockSignals(True)`，否则一展开菜单就会去写注册表。

### 8.7 计时交互流程

```
start_focus(mode, subject=None)
  ├─ timer.is_active → return False
  ├─ subject is None → _ask_subject()（QInputDialog，默认上次科目，取消返回 None）
  ├─ timer.start(mode); _finish_pending = True
  ├─ player.set_walking(True)          # 猫开始走
  ├─ bubble.set_text(display_text()); bubble.show_near(self)
  ├─ _tick.start()                     # 250ms 刷新读数
  └─ _fullscreen_preferred → _show_overlay()   # 上次勾了全屏才自动铺满

_on_tick()
  ├─ _finish_pending 且 timer.state == FINISHED → _complete_focus()   # 番茄钟到点
  ├─ _flash_token 不为空 → return       # 正在显示"已记录"，别被读数顶掉
  └─ bubble.set_text(display_text())

_complete_focus()
  ├─ _finish_pending = False; seconds = timer.stop(); _tick.stop()
  ├─ player.set_walking(False)
  ├─ focusSessionFinished.emit(mode.value, subject, seconds)   # 落库交给 main.py
  └─ _flash("✓ N 分钟已记录" 或 "不足 1 分钟，未记录")

discard_focus()
  └─ _finish_pending = False; timer.reset(); _tick.stop(); set_walking(False); 隐藏气泡与全屏牌
```

`_flash()` 用**令牌**处理"提示还没消失，用户又开了新会话"：

```python
token = object(); self._flash_token = token
QTimer.singleShot(2600, lambda: self._hide_bubble() if self._flash_token is token else None)
```

新会话开始时把 `_flash_token` 置 None，旧的隐藏回调自然失效，不会把新会话的读数一起关掉。

### 8.8 气泡为什么是独立窗口

`PetWindow` 设了 `setMask()`（猫的轮廓）。**子控件落在遮罩之外的部分会被直接裁掉**，气泡贴在猫下方就会整个消失。

所以 `TimerBubble` 是一个独立的无边框置顶窗口：

```python
setWindowFlags(FramelessWindowHint | WindowStaysOnTopHint | Tool | WindowTransparentForInput)
setAttribute(WA_TranslucentBackground)
setAttribute(WA_ShowWithoutActivating)     # 弹出不抢焦点
setAttribute(WA_TransparentForMouseEvents) # 点它等于点空气
```

跟随方式：`PetWindow.moveEvent()` 里调 `bubble.show_near(self)`。定位逻辑：默认贴在猫下方居中，下方空间不够（贴到屏幕底）就翻到上方，水平方向夹在可用区域内。

绘制：`drawRoundedRect`（半径 9）+ 半透明暖黑底 + 等宽粗体 13px（Consolas，缺失则 Courier New）。暂停时文本前加 `⏸`；结算提示用橙色描边（`accent=True`）。

### 8.9 生命周期

| 事件 | 行为 |
|---|---|
| `showEvent` | `player.start()` |
| `hideEvent` | `player.stop()` + 藏气泡（不可见时空转耗电） |
| `moveEvent` | 同步气泡位置 |
| `closeEvent` | 停 tick + 关气泡（否则留下一个无主的浮窗） |
| `hideEvent` 追加 | 收起全屏牌（它是独立顶层窗口，不会跟着猫消失） |

### 8.10 全屏计时牌 `ui/focus_overlay.py`

给"人不在电脑前"准备的：屏幕铺满一块牌子，三米外抬头就能读出还剩多久。

```
┌──────────────────────────────────────────────┐
│                                              │
│              番茄钟 · 25 分钟                 │
│                                              │
│                 18:48                        │  ← 字号 = min(屏高 × 0.32, 宽度拟合)
│                                              │
│                   数学                        │
│              ▬▬▬▬▬▬▬▬▬▬─────────              │  ← 玫红进度条，走完 25 分钟
│                                              │
│        Esc 或点击任意处收起，计时不会停         │
└──────────────────────────────────────────────┘
```

**窗口属性**：`Qt.Window | FramelessWindowHint | WindowStaysOnTopHint` + `WA_TranslucentBackground`。

- 用 `Qt.Window` 而不是 `Qt.Tool`：Tool 窗口没有任务栏条目，但某些 Win32 组合下会被
  压到普通窗口之下，全屏时反而盖不住。多一个任务栏条目无所谓——它也被自己盖住了。
- 几何取**所有屏幕的并集**（`QRect.united`），双屏时两块都盖住；但文字画在**主屏**中心，
  否则居中位置会落在两块屏的接缝上。

**三条取舍**（都写在文件头注释里）：

| 决定 | 原因 |
|---|---|
| 不做按钮 | 屏幕上放按钮，人就得走近、瞄准、点它——那不如直接看猫旁边的气泡 |
| 深色半透明（alpha 238）而非纯黑或纯色 | 纯黑像显示器坏了/待机；纯色大面积刺眼。半透明压住图标与通知，又留一点层次 |
| 弹出后 800ms 内忽略点击 | 窗口出现时鼠标本来就压在屏幕上，那次点击是"还没反应过来"，不设冷却会让人觉得闪一下就没了 |

**布局以数字为锚点**，不是每行一个固定比例：

```python
clock = QRect(area.x(), area.y() + area.height()*0.50 - h//2, area.width(), h)
label   = QRect(area.x(), clock.top()    - gap_label   - 44, area.width(), 44)
subject = QRect(area.x(), clock.bottom() + gap_subject,      area.width(), 52)
```

固定比例会在字号变大时把下面那行字压住——1440p 下"已完成"三个字实测直接盖住了科目。
先量出数字矩形再往上下推，字号怎么变都不会撞。

**字号自适应**：`_clock_font()` 从"屏高的 32%"起步，按 `QFontMetrics.horizontalAdvance`
逐步缩小到放得下（横向上限 86% 屏宽）。写死字号在 1080p 合适、2K 上偏小、1366×768 上溢出。

**状态由计时器驱动**（每 200ms `refresh()` 读一次，不自己算时间）：

| 计时状态 | 牌子表现 |
|---|---|
| RUNNING | 暖白大数字 + 玫红进度条 |
| PAUSED | 数字转灰 + 科目行前加"已暂停" |
| FINISHED | 换成绿色「已完成」+「数学 · 25 分钟」，停留 3.5 秒后自动收起 |
| IDLE（被放弃） | 立即收起 |

**勾选状态是"偏好"，不是"当前是否可见"**。这条容易做错：

- 勾上 = 下次开始专注自动铺满
- 按 Esc 或点一下 = 只收起这一场，勾选保持
- 菜单展开时回填的是 `_fullscreen_preferred`，**不能**读 `overlay.isVisible()`

否则按一次 Esc 偏好就被清掉，这个开关退化成纯手动，每次都得重新勾。

### 8.11 完成庆祝礼花 `ui/celebration.py`

一次专注满 1 分钟落库后，全屏炸开几簇像素礼花 + 一句祝贺，约 4.2 秒自动消散。
由 `PetWindow._complete_focus()` 触发（`minutes >= 1` 才放，不足 1 分钟只有气泡提示）。

三条取舍（延续"猫不索取"）：

| 取舍 | 理由 |
|---|---|
| `WA_TransparentForMouseEvents` + `WA_ShowWithoutActivating` | 礼花不是要人操作的东西：点击穿透到底下的计时牌/桌面，弹出瞬间不抢正在打字的人的焦点 |
| 不设按钮、不问"再来一个？" | 庆祝只属于刚完成的那段专注；推销下一轮是养成 App 的钩子 |
| 像素方块粒子（关闭抗锯齿） | 猫是像素画，抗锯齿圆点会像别的 App 乱入 |

实现要点：

- 运动学是**纯函数**：`spawn_burst(cx, cy, rng)` 生成径向速度 + 随机寿命的
  `Particle`（颜色存 RGB 元组而非 QColor，纯数据可脱离 Qt 测试）；
  `advance(particles, dt, gravity)` 抛物线推进并剔除过期颗粒，**返回新列表不改入参**。
- 爆点计划 `BURST_SCHEDULE` 是 `(触发秒, x 比例, y 比例)` 的序列（4 簇，约 1.3 秒内放完），
  `_step()` 按 16ms 步进触发并推进。
- 窗口几何与 `focus_overlay` 同一套"所有屏幕并集"规则；总时长 `DISPLAY_MS=4200`，
  前 220ms 淡入、末 600ms 淡出（`_fade_alpha` 乘到每个粒子和文字上）。
- 文字 = 暖白 `#FFF6E6` + 近黑暖褐阴影（同计时牌），任何桌面壁纸下都可读。
- 接线：`PetWindow.start_focus()` 开新会话时 `dismiss()` 未散完的旧礼花；
  `PetWindow.celebration` 属性供测试断言。

测试：`tests/test_celebration.py`——纯函数（数量/速度界/重力/过期/不可变）、
窗口（穿透属性/自动消散/重放重置）、接线（番茄钟与正计时的文字区分、
不足 1 分钟不放、新会话撤旧礼花）。

---

## 9. 界面层

### 9.1 主题 `ui/theme.py`

#### 调色板（两套，都取自猫的素材）

基础暖色：

| 名称 | 值 | 用途 |
|---|---|---|
| `CREAM` | `#FCF5EC` | 对话框底色 |
| `SURFACE` | `#FFFFFF` | 卡片/表格 |
| `SURFACE_WARM` | `#FAF1E6` | 次级表面 |
| `ACCENT` | `#FBB054` | 主橘：选中、主按钮 |
| `ACCENT_LIGHT` / `ACCENT_DARK` | `#FCB457` / `#EB7E35` | 悬停 / 边框 |
| `HIGHLIGHT` | `#FDEBD6` | 选中行 |
| `TEXT` | `#402210` | 主文字（猫的描边色） |
| `TEXT_MUTED` / `TEXT_DISABLED` | `#8A6A52` / `#B9AFA5` | 次级 / 禁用 |
| `BORDER` / `BORDER_SOFT` | `#E6D9CE` / `#EFE6DC` | 线条 |
| `DANGER` / `DANGER_BG` / `DANGER_BORDER` | `#B24B49` / `#FBE9E8` / `#F29391` | 删除 |

笔记本风（记录窗口用）：

| 名称 | 值 | 用途 |
|---|---|---|
| `NOTEBOOK_BG` | `#FDE5CB` | 窗口外框暖橘粉 |
| `PAPER` | `#FFFBF1` | 纸面（近奶白） |
| `PAPER_DEEP` | `#FFF4DE` | 表头、次级纸面 |
| `PAPER_CARD` | `#FFFCF6` | 日历卡片 |
| `NOTEBOOK_BORDER` | `#EBD8C0` | 卡片描边 |
| `RULE` | `#EFE1CC` | 纸面分隔线 |
| `INK` / `INK_STRONG` / `INK_MUTED` | `#7A5240` / `#5C3B26` / `#A98363` | 纸上文字三档 |
| `TAB_PINK` / `TAB_YELLOW` | `#E3BCBD` / `#FEE4A7` | 科目标签选中 / 未选 |
| `ROSE` / `ROSE_SOFT` | `#D4537E` / `#F5C3D0` | 今天、有记录的日期 |
| `BROWN_BUTTON` / `_HOVER` | `#946746` / `#A87954` | 主按钮 |
| `ROW_SELECTED` | `#6B4F42` | 记录行选中 |

配色来自参考图实测取色。改配色时**只改这个类**，不要在各处写死十六进制。

#### `apply_theme(app)`

```python
def apply_theme(app):
    app.setStyle("Fusion")        # 必须！否则 QSS 对表头等部件无效
    app.setStyleSheet(STYLESHEET)
```

**为什么必须切 Fusion**：Windows 默认样式（`windowsvista`）会自己绘制表头、日历星期行等部件，**完全不理会样式表**。实测日历星期行永远是系统灰 `#F5F5F5`，选中时还会冒出一块系统蓝。Fusion 是 Qt 自绘样式，QSS 才真正生效。这一条踩了很久，别再省。

#### 三条 QSS 纪律

1. **不写全局 `QWidget { background-color }`**：会把日历、下拉弹层等一切子控件一起染色。背景只给顶层容器（`QMainWindow`、`QDialog`、带 `objectName` 的面板）。
2. **不写全局 `QWidget { color }`**：这条会下发到 `QCalendarWidget` 内部视图，把逐日期前景色**盖掉**，导致"相邻月份日期淡化"完全失效。文字颜色按控件类型逐个指定，日历格子用 `setDateTextFormat` 精确控制。
3. **Qt 内部部件（表头、日历视图）要用"直接给控件挂样式"或全局选择器**：
   - 表格表头：`table.horizontalHeader().setStyleSheet("QHeaderView::section {...}")` 最稳
   - 日历内部：只能写全局的 `QCalendarWidget QWidget { ... }` / `QCalendarWidget QHeaderView::section { ... }`，带 `#objectName` 的层级选择器**匹配不到**内部部件

### 9.2 面板结构（最多四页签）

```
MainWindow (QMainWindow, 960×600, 最小 820×520)
└── container
    ├── 顶部切换：[学习记录] [日记] [资产] [流水]  ← checkable QPushButton#viewTab
    └── QStackedWidget
        ├── 0  StudyRecordView   （总是有）
        ├── 1  JournalView       （有 JournalRepository 时）
        ├── 2  AssetsView        （有 AccountRepository 时）
        └── 3  ExpenseView       （有 ExpenseRepository 时）
```

用 `QStackedWidget` + 一组胶囊按钮，不用 `QTabWidget`：自带标签页的边框与圆角跟
笔记本风不搭，QSS 改不动。

**页签是动态的**：传了哪个仓储就出现哪一页，但**顺序不随传参变化**——学习记录与
日记相邻（都是"我今天做了什么"），资产与流水相邻（都是"钱"）。因此
`MainWindow(repo)` 只有一页，`MainWindow(repo, journal_repository=...)` 有两页，
全都传则是四页。

按钮的点击回调里用 `self.stack.indexOf(page)` 取下标，**不能写死 1/2/3**，否则少传
一个仓储就会切错页。测试里也不要写死下标，按页签文字找（见 `test_journal.py`）。

`showEvent` 里调 `self.refresh()`，刷新全部页：窗口隐藏期间可能有别处改了数据
（番茄钟落库、改了余额），不刷新会看到旧内容。

### 9.3 学习记录三栏 `ui/study_view.py`

```
┌──────┬────────────────────────────┬──────────────┐
│ 科目 │ 10月31日 周六      3条·105分 │ ‹ 2026年10月 ›│
│ 全部 │ ┌────┬──────┬────────────┐ │ 一二三四五六日 │
│ 数学 │ │科目│ 时长 │ 学习内容    │ │   月历网格    │
│ 英语 │ ├────┼──────┼────────────┤ │ ──────────    │
│ 工作 │ │数学│25 分 │订正错题…    │ │ 今日    连续  │
│      │ └────┴──────┴────────────┘ │ 75 分钟  6 天 │
│      │ [＋新增][编辑][删除]        │  回到今天     │
└──────┴────────────────────────────┴──────────────┘
  116px         自适应                      288px
```

常量：`TABLE_HEADERS = ("科目","时长","学习内容")`、`CONTENT_PREVIEW_LIMIT = 60`、`SUBJECT_TAB_ALL = "全部"`、`RAIL_WIDTH = 116`、`CARD_WIDTH = 288`。

#### 数据加载分两级

- **换月**：`list_by_date_range(本月1日, 本月末)` 一次取回整月，**只用来给日历打标记**
- **点某天**：`list_by_date(day)` 取当天，填表格

不要每次点日期都全表扫描。

#### 科目标签

`_rebuild_subject_tabs()` **整体重建**（先 `takeAt(0)` 全部 `deleteLater()`，再按 `list_subjects()` 重建）。科目数量少，整体重建比增量对比更可靠，也不会在"删掉某科最后一条记录"后留下一个点不出内容的空标签。筛选的科目消失时自动回落「全部」。

#### 日历的四个坑

1. **相邻月份日期不淡化**：实测 Qt 6.12 不会自动区分。必须自己算出网格首尾（`first - weekday()` 到 `last + (6 - last.weekday())`），把非本月日期用 `setDateTextFormat` 设成 `TEXT_DISABLED`。**先淡化再打标记**，否则有记录的日期会被淡化覆盖。
2. **内置星期行改不动**：系统灰 `#E9E7E3`，QSS 和调色板都无效。解法是关掉内置表头（`NoHorizontalHeader`），自己排一行 `QLabel`，在 `showEvent`/`resizeEvent` 里按 `calendar.findChild(QAbstractItemView)` 的实际位置设置左右边距来逐列对齐。
3. **不要给日历 stretch 高度**：会把它拉满，行距稀得像表格。也不要完全交给 `sizeHint`（只有 120px，6 行会挤在一起）。固定 `setFixedHeight(200)`，一行约 29px。
4. **相邻月份取色**：周末用 `ROSE` 而非默认大红，跟暖色调不打架。

#### 记录行

- 记录的 `id` 挂在**第一列**的 `Qt.ItemDataRole.UserRole` 上，用于"选中行 → 记录"反查
- 学习内容压成单行（`flatten_content`，超过 60 字截断加 `…`），完整内容放 `setToolTip`
- 无记录时显示 `empty_hint`，避免一片空白让人以为窗口坏了
- `_NoFocusRectDelegate` 去掉单元格虚线焦点框——表格只读，那个框会让人以为能直接输入

#### 写操作后的定位

`_after_write(study_date, record_id)`：如果用户把记录挪到了别的日期，日历跟过去；然后 `refresh()`；最后重新选中那条记录。否则用户会以为记录丢了。

#### 可替换的模态方法

```python
def _ask_record(self, record) -> dict | None     # 正常弹 RecordDialog
def _confirm_delete(self, subject) -> bool       # 正常弹 QMessageBox
```

测试里直接替换成假函数，避免模态事件循环把测试卡死。**新增任何弹窗都要照这个模式**写，否则那个功能就没法单测。

### 9.4 流水 `ui/expense_view.py`

同构三栏：左筛选栏（116px）、中当月流水、右月度汇总卡（250px）。

```
┌──────┬────────────────────────────────────┬──────────────┐
│ 类型 │ ‹ 2026 年 11 月 ›         共 7 笔   │ 本月结余      │
│ 全部 │ ┌────┬────────┬───────┬────┬────┐ │ ¥8,681.50    │
│ 支出 │ │日期│ 分类    │ 金额   │账户│备注│ │ ──────────   │
│ 收入 │ ├────┼────────┼───────┼────┼────┤ │ 收入 ¥9,200  │
│ 分类 │ │11-07│支出·吃饭│ -¥220 │ —  │火锅│ │ 支出  ¥518   │
│ 全部 │ │11-03│收入·工资│+¥8000 │招行│到账│ │ ──────────   │
│ 吃饭 │ └────┴────────┴───────┴────┴────┘ │ 分类明细      │
│ 交通 │ [＋记一笔][编辑][删除]              │ 吃饭 ¥255     │
└──────┴────────────────────────────────────┴──────────────┘
  116px              自适应                      250px
```

- 表头 `("日期","分类","金额","账户","备注")`，固定宽 100/108/104/96，备注伸展。
  **分类列必须 ≥ 108px**：它要放「支出 · 吃饭」这种 6~7 个字，78px 会截成「支出 · …」
- 分类列带方向前缀；金额：收入 `+¥` 墨绿（`Palette.INCOME`），支出 `-¥` 深棕。
  支出**不用红色**，否则一屏红色看着像全是警报
- 「账户」列显示账户名；未联动的显示 `—`；账户被删后显示 `—` 且悬停提示"已被删除"
- 左栏分两组：**类型**（全部 / 支出 / 收入）与**分类**（动态，候选随类型变）。
  两组筛选叠加生效
- 月份导航在**中栏顶部**（不在右卡），左右 `‹ ›` 切月
- 右卡：本月结余大数字（26px，**正负同色**，见下面"结余评语"）、
  收入 / 支出两行、分类明细（支出前 4 项 + 收入前 3 项，收入带 `＋`）
- 记账后 `_jump_to(日期)`：把显示月份切到那笔所属月份，否则"保存后凭空消失"
- 金额右对齐（`AlignRight | AlignVCenter`），其他列左对齐

**右卡永远是本月全量，不受左侧筛选影响**（与资产页同一原则）。

#### 结余评语 `format_balance_hint(income, expense)`

大数字下面那行小字由这个纯函数产出（`ui/formatting.py`，可单测）。文案有三条优先级：

| 优先级 | 目标 | 落地做法 |
|---|---|---|
| 1 | **先让人愿意继续记账** | 不评价"你花多了"，只说"还差多少"；负结余**不标红** |
| 2 | **再引导创收** | "省一笔或多赚一笔"把两条路并列，不只教省钱 |
| 3 | **记录本身要被肯定** | 只要记了就给正反馈，哪怕结余很薄 |

| 条件 | 文案 |
|---|---|
| 收支都为 0 | `""`（视图回退为"还没有流水"） |
| 收入 0、有支出 | 收入还没记，补上更清楚 |
| 有收入、支出 0 | 只记了收入，花销也别漏 |
| 结余 < 0 | 还差 ¥X，省一笔或多赚一笔 |
| 结余 = 0 | 正好打平，记得很准 |
| 结余率 ≥ 50% | 存下一半以上，很稳 |
| 结余率 ≥ 20% | 有结余，攒得住 |
| 其他 | 结余不多，稳住就好 |

两处容易写反的地方：

1. **收入为 0 要先判**。很多人只记花钱不记进账，此时的"负结余"根本不是花超了，
   而是数据缺一半。直接按 `net < 0` 去骂，会把人骂跑。
2. **负结余不标红**。月初没发工资、刚交完房租，结余必然为负，这是常态不是错误。
   给红色等于给"记账"这个动作贴处罚标签，记一次被警告一次，人就不想记了。
   方向交给文案去讲，颜色保持中性（`INK_STRONG`）。

文案长度实测都 ≤ 181px，而卡片可用宽度 216px，全部一行放得下；`setWordWrap(True)`
只是给超大金额兜底。

### 9.5 资产 `ui/assets_view.py`

```
┌──────┬────────────────────────────┬────────────────┐
│ 类型 │ 资产与负债      共 6 个账户 │ 净资产          │
│ 全部 │ ┌────┬────────┬──────┬────┐│ ¥14,550.50     │
│ 资产 │ │名称│ 类别   │ 余额 │备注││ ────────────   │
│ 负债 │ ├────┼────────┼──────┼────┤│ 总资产 ¥20,750 │
│      │ │银行卡│资产·银行卡│8200│工资卡│ 总负债 ¥6,200 │
│      │ │花呗 │负债·花呗│1200│还款││ 负债占资产 30% │
│      │ └────┴────────┴──────┴────┘│ [====    ]     │
│      │ [＋新增][编辑][删除]        │ 走势 · 30 天    │
│      │                            │   ╱╲__/        │
│      │                            │ 较 10-25 +…    │
└──────┴────────────────────────────┴────────────────┘
  116px         自适应                     264px
```

- 左栏固定三项：全部 / 资产 / 负债（不是从数据聚合，因为类型只有两种）
- 中栏表格 `("名称","类别","余额","备注")`，名称伸展，其余 112/124/124；
  类别列显示 `类型 · 类别`（如「负债 · 花呗」），**列宽小于 110 会截成「资产 · 银…」**
- 负债行的余额用玫红（`Palette.ROSE`），资产用默认深棕
- 右卡：净资产大数字（负值转 `DANGER` 红并提示"负债大于资产"）、总资产 / 总负债、
  负债比例条、近 30 天走势折线、与最早一天相比的变化量

**两个刻意的行为**：

1. **右卡汇总不受左侧筛选影响**。筛到"只看负债"时净资产必须还是整体的；
   否则用户会以为资产凭空消失了。
2. **写操作后自动存当天快照**（由仓储完成，视图不管）。所以"改余额"和"看到曲线变化"
   是同一次点击的结果，不需要另设"保存快照"按钮。

`_RatioBar`（8px 高的圆角条）和 `Sparkline` 都是自绘的，不引图表库。

### 9.6 走势折线 `ui/sparkline.py`

`Sparkline.set_values(list[int])`，只接受"旧 → 新"顺序（`list_snapshots` 就这么返回）。

三个绘制细节，都是调出来的：

| 细节 | 值 | 原因 |
|---|---|---|
| 纵向余量 `RANGE_MARGIN_RATIO` | 0.25 | 不留余量时最高点贴顶、最低点贴底，波动看起来比实际剧烈 |
| 左右留白 `PADDING_SIDE` | 6 | 末端圆点压在边框上会像被裁掉 |
| 数据不足 2 点 | 画虚线基线 + 说明文字 | 一个点无法表达趋势，画出来只会让人误读 |

净值跨越 0 时额外画一条虚线零线（`low < 0 < high`），负资产一眼能看出来。

### 9.7 对话框约定

`RecordDialog`、`ExpenseDialog`、`AccountDialog` 共享四条约定：

1. **一框两用**：`record/expense=None` 为新增，传入对象为编辑
2. **只收集不落库**：暴露 `values() -> dict`，键名与仓储字段一一对应，调用方拿去做 `repo.add(**values)`
3. **错误就地显示**：表单底部一行红字（`Palette.DANGER`），**不弹 QMessageBox**。省一次点击，也不会阻塞事件循环导致测试没法跑
4. **下拉可编辑**：`QComboBox.setEditable(True)`，预置项只是候选，允许自由输入

细节：

- 时长用 `QSpinBox(0..600)`，`setSpecialValueText("未填写")`，**0 在入库时转成 NULL**
- `setCurrentText()` 会把整段文字选中（蓝底），编辑态打开时像"误选"，因此把光标挪到 0：`lineEdit().setCursorPosition(0)`
- 金额输入框支持 `12`、`12.5`、`￥12.50`、`1,200`、`12.505`（四舍五入到分），
  以及**四则算式** `6.9+2.49`、`3*4`、`(12+8)/2`
- `ExpenseDialog` 多了两个交互：顶部「支出 / 收入」互斥按钮（切换时重建分类候选，
  收入里不会出现"奶茶"），以及「账户」下拉。选了账户后表单底部会写一行
  「扣除「招行卡」¥9.39，净资产随之变化」——**联动的后果必须说清楚**，
  否则用户记完账发现余额被改了会以为是 bug

---

### 9.8 日记 `ui/journal_view.py`

```
┌────────────┬─────────────────────────────────────────┐
│ 日记        │ ‹  2026 年 11 月 1 日 · 周日  ›     今天 │
│ [＋ 写今天] │                                         │
│ 11-01 周日  │  今天状态还行。上午两小时把导数那章的     │
│ 今天状态…   │  错题重做了一遍……                       │
│ 10-31 周六  │                                         │
│ 看完《计算… │                                         │
│ 10-29 周四  │                                         │
│ 休息半天…   │  94 字              当天专注 75 分钟    │
│ 共 4 篇     │                                         │
└────────────┴─────────────────────────────────────────┘
   236px                       自适应
```

**左栏用列表而不是日历**：学习记录用日历是因为"哪天学了什么"要按格子找；日记是
连续的文字，回看时是"往上翻"，不是"点格子"。列表还能带一行摘要，扫一眼就知道那天
写了什么。顺带也不必把 `study_view` 那套自绘星期行 + 列对齐复制一遍。

**自动保存**（没有保存按钮）：

| 时机 | 动作 |
|---|---|
| `textChanged` | 置脏 + 重启 1.2 秒单次定时器 + 更新字数 |
| 定时器到点 | `save_now()` |
| 切日期 / 切页签 / 关窗口（`hideEvent`） | 先 `save_now()` 再继续 |

三个容易写错的地方：

1. **加载正文时不能被判成"用户改了"**。`setPlainText` 会触发 `textChanged`，
   所以加载期间置 `_loading` 标志跳过；否则一进页面就变脏，切日期时会把没动过的
   内容重复写一遍。
2. **加载时要顺手关掉撤销历史**（`setUndoRedoEnabled(False/True)` 包一层）。
   否则换一天后按 Ctrl+Z 会跳回上一天的文本，用户会以为串了。
3. **刷新时不要覆盖未保存的输入**。`refresh()` 只重载列表，正文仅在 `not _dirty`
   时重载——窗口 `showEvent` 会调 `refresh()`，若无条件重载，用户切页签回来手一抖
   就丢字。

选中态与日期是两套状态：`_select_in_list()` 在切换时先 `blockSignals(True)`，
否则 `setCurrentRow` 会反过来触发 `set_selected_date`，形成回环。

---

## 10. 接线 `main.py`

```python
def main() -> int:
    db = init_database()                       # 1. 连库 + 建表 + 迁移
    try:
        app = QApplication(sys.argv)
        configure_application(app)             # 2. setQuitOnLastWindowClosed(False)

        repository = StudyRecordRepository(db)  # 3. 仓储
        manager = StudyWindowManager(
            repository,
            ExpenseRepository(db),
            AccountRepository(db),
            JournalRepository(db),
        )

        pet = PetWindow(default_subject=last_subject(repository))  # 4. 桌宠
        pet.studyRecordsRequested.connect(manager.open)
        pet.focusSessionFinished.connect(
            lambda mode, subject, seconds:
                save_focus_session(repository, manager, mode, subject, seconds)
        )
        pet.show()

        return app.exec()                      # 5. 事件循环
    finally:
        db.close()                             # 退出时一定关库（提交 WAL）
```

两个信号的语义：

| 信号 | 参数 | 谁接 |
|---|---|---|
| `studyRecordsRequested` | 无 | `manager.open`（惰性创建、复用、置前） |
| `focusSessionFinished` | `(mode: str, subject: str, seconds: int)` | `save_focus_session`（过滤 + 落库 + 刷新） |

`last_subject()` 取最近一条记录的科目作为输入框默认值，没有记录则 `"专注"`。

`StudyWindowManager` 的三个仓储参数都是可选的，传哪个就多一页：

- `open()`：首次创建 `MainWindow`，之后 `show() + raise_() + activateWindow()`
- `refresh_if_open()`：只在窗口存在且可见时刷新；没开就什么都不做（下次打开自然会加载）
- Qt 默认关闭窗口只是隐藏，不销毁，所以再次打开是同一个实例，`showEvent` 会触发刷新

**关键**：`configure_application()` 里那句 `setQuitOnLastWindowClosed(False)` 不能省。桌宠是 `Qt.Tool`，Qt 不把它算主窗口；不关这个开关，用户关掉记录窗口时整个应用会退出。

---

## 11. 测试

### 11.1 运行

```bat
cd /d D:\CatStudy
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

只有标准库 `unittest`，**环境里没有 pytest，不要用**。

无显示器的环境需要 `set QT_QPA_PLATFORM=offscreen`，但**离屏下中文会渲染成方块、遮罩也不准**，只能验布局不能验观感。

### 11.2 分布（476 项）

| 文件 | 用例 | 覆盖 |
|---|---|---|
| `test_database.py` | 51 | 建表、索引、CRUD、日期校验、迁移、架构约束（ui 里不许有 SQL） |
| `test_accounts.py` | 41 | 账户仓储、净资产（含负值）、负债比例边界、快照覆盖与升序、v3→v5 迁移、资产视图增删改、折线极值、三页签 |
| `test_study_view.py` | 42 | 视图、切月、选日、表格渲染、打标记、增删改、选中、持久化、窗口属性 |
| `test_character_sit.py` | 35 | 素材加载、尺寸、透明、渲染、窗口、旧素材可用 |
| `test_timer.py` | 35 | 假时钟、格式、番茄钟、正计时、落库、source 列、桌宠联动 |
| `test_sprite.py` | 31 | 旧 idle 素材、单帧素材、遮罩并集、最近邻渲染、契约校验 |
| `test_expenses.py` | 70 | 金额格式化与算式、仓储、收支方向、账户联动（四种组合/编辑反做/删除退回）、对话框、流水视图、结余评语（含无指责措辞扫描） |
| `test_ui_formatting.py` | 26 | 时长、日期标题、汇总、压平、金额解析 |
| `test_record_dialog.py` | 18 | 默认值、取值、回填、校验 |
| `test_walk_animation.py` | 17 | 素材角色、走路轮转、桌宠联动、自启动 |
| `test_app_wiring.py` | 14 | 菜单、双击、拖拽、manager、应用配置（含主题已应用） |
| `test_focus_overlay.py` | 22 | 铺满几何、读数一致、三态绘制、进度比例、Esc/点击/冷却、偏好与可见性解耦、收起联动 |
| `test_journal.py` | 38 | 日记仓储（覆盖/空删/排序/月度边界/非法日期）、v6→v7 迁移、视图自动保存与切日、页签顺序 |
| `test_notebook_view.py` | 12 | 科目标签、统计（今日合计、连续打卡） |
| `test_celebration.py` | 13 | 礼花纯函数（数量/速度界/重力/过期/不可变）、穿透窗口、自动消散、桌宠接线（文字区分/不足1分钟不放/新会话撤旧） |

合计 476 项，全部通过。

### 11.3 四类测试策略

1. **纯函数直测**：`formatting.py`、`timer.format_clock`、`FrameRoles.frame_at`。不建窗口，秒级完成。
2. **假时钟测时间**：`FocusTimer(clock=fake)`，`fake.now += 372` 就能"跳过" 6 分 12 秒。绝不 `sleep` 25 分钟。
3. **可替换模态**：视图里的 `_ask_record` / `_confirm_delete` / `_ask_expense` 被替换成假函数，路测增删改逻辑而不弹窗。
4. **临时数据库**：`tempfile.mkdtemp()` + `DatabaseManager(Path(tmp)/"t.db")`，每个用例独立库，测完关闭。不要碰 `data/catstudy.db`。

### 11.4 什么必须测，什么只能肉眼

必须测：数据正确性、日期约束、迁移、状态机时序、素材契约校验、菜单结构、信号发没发。

只能肉眼（真实屏幕 + 截图）：配色观感、圆角、对齐、字体、遮罩边缘、动画流畅度。做法是临时脚本 `win.grab().save(...)` 再打开图看，验完删掉临时文件。

---

## 12. 构建、分发、备份

### 12.1 Git 提交规范

前缀：`feat:` / `refactor:` / `fix:` / `chore:` / `docs:`。

**正文必须写"为什么"和踩了什么坑**，不要只写"改了点东西"。例如：

```
fix(ui): 日历星期行改用自绘

Windows 原生样式会自己绘制表头，QSS 与调色板都改不动，#F5F5F5 的横带
和暖色纸面格格不入。改用 NoHorizontalHeader + 自绘 QLabel 行，
在 resizeEvent 里按内部视图位置对齐列宽。
```

提交前：`git status` 干净、测试全过、临时预览图已删。

### 12.2 桌面快捷方式

```bat
.venv\Scripts\python.exe tools\make_desktop_shortcut.py
.venv\Scripts\python.exe tools\make_desktop_shortcut.py --output D:\test.lnk
```

用 `pylnk3` 生成（本机安全策略禁止脚本实例化 COM，`WScript.Shell` 走不通）。依赖只装到临时目录：

```bat
python -m pip install --target %TEMP%\lnktool pylnk3
```

**最关键的坑**：`pylnk3` 新建 `Lnk` 默认**不开 `IsUnicode`**，此时字符串按 ANSI 写入。纯英文路径侥幸能跑，一旦有中文（比如描述「CatStudy 桌面学习伴侣」）就把字节写坏，快捷方式双击**毫无反应也不报错**。必须：

```python
lnk.link_flags.IsUnicode = True
```

快捷方式内容：目标 `<项目>\.venv\Scripts\pythonw.exe`，参数 `"<项目>\main.py"`，工作目录项目根，图标 `assets\icon\catstudy.ico`。

### 12.3 开机自启动

写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，值名 `CatStudy`：

```
"D:\CatStudy\.venv\Scripts\pythonw.exe" "D:\CatStudy\main.py"
```

- 用 `HKCU` 不需要管理员权限
- 用 `pythonw.exe` 而不是 `python.exe`，否则每次开机弹黑窗
- API：`is_enabled()` / `enable()` / `disable()` / `set_enabled(bool)->bool`（返回**操作后的真实状态**，不是"操作是否成功"）
- 非 Windows 全部安全返回 False/None，测试可跨平台

### 12.4 备份

```bat
:: 建议每次达到可用里程碑都做一次，存在另一个盘
```

1. `git status` 确认要备份的内容
2. 打包：项目目录（排除 `.venv/`、`__pycache__/`、`data/*.db*`）
3. 记录 `certutil -hashfile <zip> SHA256` 与文件大小
4. 放到 `C:\Users\<用户>\Documents\CatStudy_backups\`（与 D 盘项目**跨盘**，防单盘故障）

数据库文件本身（`data/catstudy.db`）要**单独备份**：它在 `.gitignore` 里，不会进版本库。

### 12.5 迁移到新机器

1. 装 Python（3.10+），把项目放到任意路径
2. 建新 venv、装依赖（**不要复制 `.venv`**，里面的路径是写死的）
3. 首次运行会自动建 `data/` 与空库
4. 有旧数据就把 `catstudy.db`（连同 `-wal`/`-shm` 或先 `close()` 落盘）拷到 `data/`
5. 重跑 `tools/make_desktop_shortcut.py`（路径变了）
6. 如果之前开过自启动，重新勾一次（注册表里存的是绝对路径）

---

## 13. 陷阱清单

按"现象 → 原因 → 解法"记，都是实际踩过的。

| # | 现象 | 原因 | 解法 |
|---|---|---|---|
| 1 | `2026-02-30` 能入库 | `GLOB '[0-9]...'` 只校验格式，`[0-9]` 不是数字通配符 | `CHECK (study_date IS date(study_date))` |
| 2 | 迁移后行数变少 | 重建表时漏了列或复制条件写错 | 迁移前后各数一次行数，不等就抛异常回滚 |
| 3 | 125% 缩放下猫变小 20% | `round(2*1.25)==2` 银行家舍入 | `floor(x+0.5)` half-up |
| 4 | 高 DPI 遮罩错位 | `QPixmap.mask()` 是设备像素，被当逻辑坐标用 | 从字符网格推导遮罩 |
| 5 | 启动卡顿几百毫秒 | 每格一个 `QRegion` union | 按行合并成连续区间 |
| 6 | 猫走路时被裁掉耳朵 | 遮罩只取静止帧轮廓 | 取所有帧并集 |
| 7 | 双击只有 3/5 成功 | 置顶 Tool 窗首次点击被激活消耗 | 在 `mousePressEvent` 自行判定双击 |
| 8 | 拖一下就弹记录窗口 | 一次物理按下派发两次 press | `_left_pressed` 布尔守卫 |
| 9 | 双击开了两个窗口 | 自判 + 平台事件都触发 | 0.35s 去重 `_request_study_window()` |
| 10 | 关掉记录窗口猫也没了 | `Qt.Tool` 不算主窗口，默认关最后一个窗口就退出 | `setQuitOnLastWindowClosed(False)` |
| 11 | 气泡贴在猫下面看不见 | 父窗口 `setMask()` 把子控件裁掉 | 气泡做成独立窗口 |
| 12 | 气泡挡住拖动 | 独立窗口抢鼠标 | `WindowTransparentForInput` + `WA_TransparentForMouseEvents` |
| 13 | 气泡抢走输入焦点 | 独立窗口默认激活 | `WA_ShowWithoutActivating` |
| 14 | 拖动猫时气泡留在原地 | 气泡不跟随父窗口 | `moveEvent` 里 `show_near(self)` |
| 15 | 菜单一展开 | 自启动就被改了 | `setChecked` 前 `blockSignals(True)` |
| 16 | 关窗后浮窗残留 | 没在 `closeEvent` 收气泡 | `closeEvent` 里 `bubble.close()` |
| 17 | 日历星期行永远是灰的 | Windows 原生样式自己绘制表头，无视 QSS | `setStyle("Fusion")` / 自绘星期行 |
| 18 | 表头下面一条浅色横带 | 全局 `QHeaderView::section` 优先级更高，id 选择器盖不住 | 直接给该 header 设 `setStyleSheet` |
| 19 | 相邻月份日期不淡化 | 全局 `QWidget{color}` 覆盖了 `setDateTextFormat` | 不写全局 color，逐控件指定 |
| 20 | 日历出现黑色块 | 内部视图背景写 `transparent`，截图/拖动时露出未绘制区域 | 给 `QCalendarWidget QWidget` 实色 |
| 21 | 日历行距稀得像表格 | 纵向 stretch 把它拉满 | `setFixedHeight(200)` |
| 22 | 换月后旧月份还高亮 | 旧 `QTextCharFormat` 没清 | 记录已套用日期，换月前逐个清空 |
| 23 | 记录改到别的日期后"消失" | 视图还停在原日期 | `_after_write` 跟到新日期并重新选中 |
| 24 | 科目删光后留下空标签 | 标签是增量维护的 | 每次整体重建 + 筛选失效回落「全部」 |
| 25 | 时长 0 分钟刷满日历 | 误点菜单立刻结束也会写库 | `< 1 分钟不写库` |
| 26 | 暂停后又提示"已记录"被读数顶掉 | tick 覆盖了 flash 文案 | `_flash_token` 期间不刷读数 |
| 27 | 新会话开始时旧提示把新读数关掉 | `singleShot` 回调无标识 | 令牌比对，不匹配就忽略 |
| 28 | 番茄钟显示 `25:01` / 负计时 | 到点只在 tick 里判断 | `_settle_if_expired()` 挂在读路径上，钉住 1500 秒 |
| 29 | 点开始显示 `24:59` | 向下取整 | 番茄钟 `ceil`，正计时 `floor` |
| 30 | 快捷方式双击没反应也不报错 | `pylnk3` 默认 ANSI 写中文描述 | `link_flags.IsUnicode = True` |
| 31 | 开机弹黑色控制台 | 用了 `python.exe` | 用 `pythonw.exe` |
| 32 | 复制 `.venv` 到新机器跑不起来 | venv 里路径写死 | 重建 venv |
| 33 | 记账总额差几分 | 浮点累加误差 | 整数分存储 |
| 34 | 测试卡死在模态框 | 直接 `exec()` 真对话框 | 弹窗方法做成可替换 |
| 35 | 离屏测试中文全变方块 | 无字体环境 | 视觉验收必须在真实平台 |
| 36 | `2026-3-5` 被拒 | `fromisoformat` 严格 | 加 `strptime("%Y-%m-%d")` 兜底 |
| 37 | 一天改三次余额，走势图出现三个尖刺 | 快照表没有日期唯一约束 | `UNIQUE(snapshot_date)` + `ON CONFLICT DO UPDATE` |
| 38 | 净资产算成了"资产 + 负债" | 负债存成负数，公式里又减了一次 | 余额强制 ≥ 0，符号只由 `kind` 决定 |
| 39 | 资产表「类别」显示成「资产 · 银…」 | 列宽 92px 放不下 7 个字 | 加宽到 112px，备注让到 124px |
| 40 | 折线像过山车、端点贴边 | 纵向没留余量 | `RANGE_MARGIN_RATIO = 0.25` |
| 41 | 迁移测试在 Windows 报 `WinError 32` | `with TemporaryDirectory()` 退出时库还开着 | 先 `addCleanup(close)` 再 `addCleanup(tmp.cleanup)`（后进先出） |
| 42 | 少传一个仓储后页签切错页 | 回调里写死了 index 1 / 2 | 用 `self.stack.indexOf(page)` 取下标 |
| 43 | 有收入后"支出合计"把收入也算进去了 | 金额加了符号去存，汇总没按方向过滤 | 金额恒正，方向由 `kind` 决定，汇总显式 `WHERE kind = ?` |
| 44 | 改了一笔支出金额，余额对不上 | `update` 只改了流水行，没重新施加影响 | 先撤旧影响再施加新的（`link_changed` 判断） |
| 45 | 删掉账户后流水也没了 | 外键默认 `NO ACTION` / 级联删除 | `ON DELETE SET NULL`，流水保留只是不再追溯 |
| 46 | 迁移时 RENAME `accounts` 后外键指向旧表 | 先加 `account_id` 再重建表，RENAME 会带着外键一起改 | 顺序反过来：先重建 accounts，再加列 |
| 47 | 记完账余额悄悄变了，用户以为有 bug | 联动没有提示 | 对话框底部写清"从 X 扣除 ¥Y"，删除时确认框说明会撤回 |
| 48 | 截图里日期框的横线不见了 | `QDialog.grab()` 在 DPR 1.5 下重采样，1px 线被丢掉 | 别据此改格式；单独 `grab()` 那个控件确认 |
| 49 | 只记支出的人被负面评语劝退 | 把数据缺一半当成了花超了 | 收入为 0 时先提示收入还没记，负结余只陈述缺口 |
| 50 | 每记一笔支出大数字就变红一次 | 负结余用 `DANGER`，观感等同报错 | 正负同色 `INK_STRONG`，方向交给评语讲 |
| 51 | 全屏牌出现时"闪一下就没了" | 窗口弹出瞬间吃到鼠标按下 | 显示后 800ms 内忽略点击 |
| 52 | 大字号时下方文字被数字压住 | 每行用固定屏高比例，字一高就重叠 | 以数字矩形为锚点往上下推 |
| 53 | 按一次 Esc 后"全屏计时"勾选也没了 | 菜单回填读的是 `isVisible()` | 回填偏好 `_fullscreen_preferred`，可见性是临时状态 |
| 54 | 双屏时数字落在两屏接缝上 | 文字按并集居中 | 窗口取并集、文字画在主屏中心 |
| 55 | 一进日记页就显示"编辑中"，切日期还重复写库 | `setPlainText` 也触发 `textChanged` | 加载期间置 `_loading` 跳过 |
| 56 | 换一天后按 Ctrl+Z 跳回上一天的文本 | 撤销历史跨文档保留 | 加载时 `setUndoRedoEnabled(False/True)` 包一层清栈 |
| 57 | 切页签回来发现刚写的字没了 | 窗口 `showEvent` 无条件重载正文 | `refresh()` 只在 `not _dirty` 时重载 |
| 58 | 清空正文后列表里留一条空白日记 | 保存时没处理空内容 | 仓储层 `save()` 空内容直接删行 |
| 59 | 列表选中和当前日期互相触发 | `setCurrentRow` 会反向发选中信号 | 切换选中前 `blockSignals(True)` |

---

## 14. 扩展指南

### 14.1 加一个科目统计页

1. `StudyRecordRepository` 加 `subject_totals(start, end) -> list[tuple[str,int]]`（照 `category_totals` 写）
2. 新增 `ui/stats_view.py`，接受 repository，只读
3. `MainWindow._build_switch()` 加一个按钮，`stack.addWidget`
4. `MainWindow.refresh()` 里补一行刷新
5. 加测试：空数据、单科、多科排序

### 14.2 加收入（收支双向）

先想清楚要哪一种：

- **只想知道钱花在哪**：现在的 `expenses` 够用，收入不必进流水；
- **想管钱的总量**：`accounts` 已经在做这件事（余额手工维护），收入体现为
  "资产账户余额变大"，不需要额外的收入表。

如果确实要做完整的收支记账：

1. 给 `expenses` 加 `kind TEXT NOT NULL DEFAULT 'expense'`（schema v6 + 迁移，
   迁移时旧记录全部设为 `'expense'`），或者新建 `incomes` 表
2. 金额仍用整数分；"支出减、收入加"的符号只在**展示层**处理，存储保持正数
3. UI 加"收入/支出"分段选择，表格加一列类型，汇总卡分三行（收入 / 支出 / 结余）
4. 注意别和 `accounts` 打架：一份钱不要既在流水里累加、又在账户里手工填

### 14.3 改番茄钟时长

`POMODORO_MINUTES = 25`（`core/timer.py`）。`FocusTimer(pomodoro_seconds=...)` 支持注入，菜单文案里写死了「25 分钟」，改时长记得同步 `pet_window.py` 的菜单文字和测试断言。

要做多档（15/25/45），建议把档位表放在 `core/timer.py`，桌宠物菜单按表生成子项。

### 14.4 加"退出前确认"

`PetWindow._setup_context_menu()` 里把 `quit_action.triggered.connect(QApplication.quit)` 换成先检查 `self._timer.is_active`，正在计时就弹确认（记得也做成可替换方法，否则拖累测试）。

### 14.5 换角色素材

1. 新素材必须满足 JSON 契约（同尺寸帧、调色板覆盖所有字符）
2. 想保留走路动画，`roles.walk` 至少 2 帧，且所有帧画布尺寸一致（用"底部居中贴进大画布"的办法）
3. 改 `ui/pet_window.py` 的 `DEFAULT_SPRITE_PATH` 一行即可
4. 跑 `tests/test_character_sit.py` 与 `test_walk_animation.py`，尺寸/帧数断言可能需要跟着改
5. 重新生成图标（见 7.8）

---

## 15. 代码地图

| 文件 | 行数 | 关键符号 | 一句话职责 |
|---|---|---|---|
| `main.py` | 110 | `main`, `configure_application`, `last_subject`, `save_focus_session` | 启动时序与信号接线 |
| `core/database.py` | 398 | `DatabaseManager`, `SCHEMA_VERSION=5`, `init_database` | 连接、建表、迁移 |
| `core/study_records.py` | 286 | `StudyRecord`, `StudyRecordRepository`, `normalize_date`, `SOURCES` | 学习记录仓储 |
| `core/accounts.py` | 424 | `Account`, `AccountRepository`, `NetWorth`, `Snapshot`, `ASSET`/`LIABILITY` | 资产/负债与快照 |
| `core/journal.py` | 176 | `JournalEntry`, `JournalRepository`, `MAX_CONTENT_LENGTH` | 日记仓储 |
| `core/expenses.py` | 447 | `Expense`, `ExpenseRepository`, `flow_delta`, `FLOW_EXPENSE/INCOME` | 收支流水仓储 + 账户联动 |
| `core/timer.py` | 198 | `FocusTimer`, `TimerMode`, `TimerState`, `format_clock` | 计时状态机 |
| `core/autostart.py` | 114 | `is_enabled/set_enabled/command`, `RUN_KEY` | 注册表自启动 |
| `core/growth.py` | 28 | `GrowthSystem` | 骨架，未实现 |
| `ui/sprite.py` | 413 | `SpriteSheet`, `AnimationPlayer`, `FrameRoles`, `WALK_FRAME_MS` | 素材加载与动画调度 |
| `ui/pet_window.py` | 581 | `PetWindow`, `DEFAULT_SPRITE_PATH`, 三个 Signal | 桌宠窗口 |
| `ui/timer_bubble.py` | 109 | `TimerBubble` | 独立气泡窗口 |
| `ui/focus_overlay.py` | 390 | `FocusOverlay`, `REFRESH_MS`, `progress_ratio` | 全屏计时牌 |
| `ui/celebration.py` | 343 | `CelebrationOverlay`, `Particle`, `spawn_burst`, `advance`, `DISPLAY_MS` | 完成庆祝礼花（纯函数运动学 + 点击穿透窗口） |
| `ui/theme.py` | 443 | `Palette`, `STYLESHEET`, `apply_theme` | 配色与全局样式 |
| `ui/formatting.py` | 253 | `format_money`, `parse_money`, `format_balance_hint` | 纯函数文案 + 金额算式 + 结余评语 |
| `ui/record_dialog.py` | 184 | `RecordDialog`, `SUBJECT_PRESETS` | 学习记录表单 |
| `ui/study_view.py` | 735 | `StudyRecordView`, `RAIL_WIDTH`, `CARD_WIDTH` | 三栏学习记录 |
| `ui/journal_view.py` | 362 | `JournalView`, `AUTOSAVE_MS`, `SUMMARY_LIMIT` | 日记页 |
| `ui/expense_dialog.py` | 280 | `ExpenseDialog`, `NO_ACCOUNT` | 收支表单（方向/账户/算式） |
| `ui/expense_view.py` | 610 | `ExpenseView`, `COLUMN_WIDTHS` | 三栏流水（含结余卡） |
| `ui/account_dialog.py` | 187 | `AccountDialog` | 账户表单 |
| `ui/assets_view.py` | 531 | `AssetsView`, `_RatioBar`, `SPARKLINE_DAYS` | 三栏资产 |
| `ui/sparkline.py` | 154 | `Sparkline`, `RANGE_MARGIN_RATIO` | 净资产走势折线 |
| `ui/main_window.py` | 192 | `MainWindow`, `StudyWindowManager` | 三页签容器与窗口复用 |
| `tools/extract_walk_frames.py` | 228 | `background_mask`, `frame_grid`, `denoise` | GIF → 像素矩阵 |
| `tools/make_desktop_shortcut.py` | 131 | `main` | 生成 `.lnk` |

---

## 16. 一句话原则

- **数据正确性 > 界面好看 > 功能多**。金额和日期出错是致命的，圆角歪一点没人管。
- **能纯函数就别建窗口**。判断逻辑从 Qt 里拿出来，测试成本差一个数量级。
- **UI 不碰 SQL，桌宠不碰数据库**。所有耦合都放在 `main.py` 一处，改起来只改一个文件。
- **素材 JSON 是唯一真源**。PNG、图标都是产物，改需求改 JSON。
- **存量与发生额不要混用**。账户余额是"现在有多少"，支出流水是"发生了什么"；
  混在一张表里，漏记一笔就永久对不上账。两者用一个可空外键**按需关联**，
  而不是合并成一个模型。
- **用户输入永远不要 `eval`**。金额算式用 `ast` 白名单求值，多写 30 行换掉一个
  远程代码执行入口，这笔交易很划算。
- **踩过的坑写进注释**。这些坑几乎都不是"看代码能看出来"的，注释是唯一能防止下次重踩的东西。
