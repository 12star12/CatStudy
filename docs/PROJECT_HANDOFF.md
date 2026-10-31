# CatStudy 项目交接文档（PROJECT_HANDOFF）

> 最近更新：2026-10-31

## 一、项目定位与技术环境

- **产品定位**：CatStudy 是一款 Windows 11 本地桌面应用，打造温暖治愈的像素风桌面学习宠物，初始角色为一只橘白猫，提供类似 QQ 宠物的陪伴与成长体验。
- **目标平台**：Windows 11 桌面。
- **技术环境（实际）**：
  - Python 3.14.4（项目最初规划为 3.10，实际虚拟环境为 3.14.4，未重建）
  - PySide6 6.12.0
  - Pillow 13.0.0
  - SQLite（Python 标准库 sqlite3，尚未启用）
  - Git（可执行文件位于 `C:\Program Files\Git\cmd\git.exe`）
- **虚拟环境**：`.venv/`（已被 `.gitignore` 忽略，不会上传 GitHub）。

## 二、已完成阶段

1. **第一阶段：项目骨架**。建立完整目录结构与基础代码占位，配置 `.gitignore`（忽略虚拟环境、数据库、缓存、IDE/打包产物）。
2. **第二阶段：桌面悬浮窗**。实现无边框、透明背景、始终置顶的窗口，支持左键拖动、右键菜单（含「退出程序」），透明区域鼠标穿透。
3. **第三阶段：待机动画架构**。引入数据驱动三层架构：JSON 素材层 + `SpriteSheet`/`AnimationPlayer` 调度层 + 窗口层，旧 16×16 角色实现眨眼与呼吸。
4. **角色美术返工（当前重点）**。重新设计并经用户确认完整橘白坐姿猫，转换为真正的像素画，导出高清透明 PNG 与程序可读取的 `character_sit.json`。

## 三、关键文件及其作用

| 路径 | 作用 |
|---|---|
| `main.py` | 程序入口，创建 QApplication 并启动 PetWindow |
| `requirements.txt` | 依赖声明（PySide6、Pillow；sqlite3 为标准库） |
| `.gitignore` | 忽略 .venv、数据库、缓存、IDE/打包产物 |
| `ui/pet_window.py` | 无边框透明悬浮窗，拖动、右键菜单、帧信号订阅 |
| `ui/sprite.py` | SpriteSheet（加载/校验/渲染 JSON）与 AnimationPlayer（QTimer 帧调度） |
| `ui/main_window.py` | 主窗口占位（未开发） |
| `core/timer.py`、`database.py`、`growth.py` | 学习计时、数据库、成长系统占位（未开发，保持不重构） |
| `assets/cat/idle.json` | 旧 16×16 猫头三帧素材（保留，不再修改） |
| `assets/cat/character_sit.json` | **新完整坐姿猫像素素材（36×52，12 色调色板）** |
| `assets/cat/character_sit.png` | **新角色高清透明 PNG（2048×2048，RGBA）** |
| `assets/cat/character_sit_legacy.json/.png` | 被拒第一版的备份，防止内容丢失 |
| `assets/cat/character_sit_preview.png` | 第一版棋盘格预览（历史评审用） |
| `assets/room/`、`assets/ui/`、`data/` | 房间/UI 素材与数据目录，占位 |

## 四、当前猫咪素材的路径与规格

- **高清 PNG**：`assets/cat/character_sit.png`
  - 尺寸 2048×2048，模式 RGBA，真实 Alpha 通道
  - Alpha 仅含 0（透明）与 255（不透明），无半透明杂边
  - 角色边界框 bbox：(508, 170) – (1689, 1901)
  - 透明像素 2,937,221；不透明像素 1,257,083
- **像素 JSON**：`assets/cat/character_sit.json`
  - `state="sit"`，`cell_pixels=8`
  - 逻辑网格 36 列 × 52 行（渲染尺寸 288×416）
  - 12 色有限调色板，图案字符均在调色板内，所有行等长
  - 结构含头部（耳朵/眼睛/嘴套）、独立躯干、两条前腿、前爪、两侧后脚、右侧弯曲卷尾
- 已验证 128px 下结构清晰、64px 下仍可辨认完整身体。

## 五、尚未完成的任务

- 新角色尚未接入窗口（当前 `pet_window.py` 仍加载旧 `idle.json`）。
- 新角色的待机动画（眨眼、尾巴摆动）、睡觉、开心等多状态动画未制作。
- 学习计时、数据库、成长系统（`core/`）均未开发。
- 主窗口 `main_window.py` 未开发。
- Git 仓库尚无任何提交，新素材未被跟踪。

## 六、下一阶段建议

1. 先将新 `character_sit.json` 接入 `SpriteSheet`，在窗口中验证完整角色显示与透明穿透（回归测试）。
2. 再基于确认角色制作多帧动画（优先待机眨眼 + 尾巴摆动），保持素材与动画逻辑分离。
3. 之后再推进学习计时、数据库与成长系统，避免过早重构 `core/`。
4. 合适时进行首次 Git 提交，固定当前成果。

## 七、运行命令

```powershell
# 在项目根目录，使用虚拟环境 Python 启动
.\.venv\Scripts\python.exe main.py
```

## 八、已知问题与验收情况

- **角色美术**：完整橘白坐姿猫已通过用户确认；像素化版本 PNG 与 JSON 均通过本地结构检查（Alpha、尺寸、边界、等长、字符合法性）。
- **历史被拒版本**：第一版 28×27 角色观感仍像猫头，已备份为 `*_legacy`，未删除。
- **版本差异**：实际运行环境为 Python 3.14.4 而非规划的 3.10，目前功能正常，未重建环境。
- **待回归**：新角色接入窗口后的拖动、右键退出、透明穿透等功能需在接入后重新验证。
