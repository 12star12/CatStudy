"""CatStudy 界面主题：调色板与全局样式表。

配色直接取自坐姿像素猫素材（``assets/cat/cat_sit.json``）的调色板，
让界面与桌宠角色视觉同源，避免"UI 一套色、猫一套色"的割裂感。

设计约束（与项目整体风格一致）：
- 纯色平铺，不使用渐变、阴影、模糊等装饰效果；
- 圆角统一 8px，留白优先于描边；
- 只用一套暖色，不引入第二套强调色，避免界面花哨。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅用于类型标注，import 时不需要 Qt
    from PySide6.QtWidgets import QApplication


class Palette:
    """界面用色，均取自猫咪素材调色板。"""

    # 底色与表面
    CREAM = "#FCF5EC"        # 窗口底色（猫的白胸）
    SURFACE = "#FFFFFF"       # 卡片/表格底色
    SURFACE_WARM = "#FAF1E6"  # 表头、次级表面

    # 强调色
    ACCENT = "#FBB054"        # 主体橘：选中态、主按钮
    ACCENT_LIGHT = "#FCB457"  # 亮橘：悬停
    ACCENT_DARK = "#EB7E35"   # 暗橘：边框、按下
    HIGHLIGHT = "#FDEBD6"     # 选中行背景

    # 文字
    TEXT = "#402210"          # 主文字（猫的描边深褐）
    TEXT_MUTED = "#8A6A52"    # 次级文字
    TEXT_DISABLED = "#B9AFA5"

    # 线条与语义色
    BORDER = "#E6D9CE"
    BORDER_SOFT = "#EFE6DC"
    DANGER = "#B24B49"        # 删除按钮文字
    DANGER_BG = "#FBE9E8"
    DANGER_BORDER = "#F29391"

    # ---- 笔记本风（学习记录窗口改版）----
    # 取自参考图的实测色值：窗口底 #FDE5CB、纸面 #FFF6DE、卡片 #FBF0DC
    NOTEBOOK_BG = "#FDE5CB"
    # 用户要求"日历要奶油配色"：纸面整体提亮到近奶白，只留很淡的米黄，
    # 靠玫瑰粉点缀撑住层次，否则整窗会发土。
    PAPER = "#FFFBF1"
    PAPER_DEEP = "#FFF4DE"
    PAPER_CARD = "#FFFCF6"
    NOTEBOOK_BORDER = "#EBD8C0"
    RULE = "#EFE1CC"          # 纸面横线/分隔线

    INK = "#7A5240"           # 纸上正文
    INK_STRONG = "#5C3B26"    # 标题
    INK_MUTED = "#A98363"     # 次级文字

    TAB_PINK = "#E3BCBD"      # 选中的科目标签
    TAB_YELLOW = "#FEE4A7"    # 未选中的科目标签（保留参考图的黄）
    ROSE = "#D4537E"          # 玫红强调：今天、有记录的日期
    INCOME = "#3F7A57"        # 收入金额（墨绿）。支出的金额保持深棕，不用红色避免满屏报警
    ROSE_SOFT = "#F5C3D0"
    BROWN_BUTTON = "#946746"  # 主按钮棕
    BROWN_BUTTON_HOVER = "#A87954"
    ROW_SELECTED = "#6B4F42"  # 记录行选中态（深棕底）


FONT_STACK = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif'

# 全局样式表。
#
# 两条刻意的取舍：
# 1. 不写 `QWidget { background-color: ... }`，否则会把日历、下拉弹层等
#    子控件一并染色，背景只给顶层容器；
# 2. 不写 `QWidget { color: ... }`。实测这条规则会下发到 QCalendarWidget
#    内部的视图，把「非本月日期」也画成本月同色，而且会**盖掉**
#    setDateTextFormat 设置的逐日期前景色——淡化相邻月份日期直接失效。
#    因此文字颜色一律按控件类型逐个指定，日历格子的配色交给
#    setDateTextFormat / setWeekdayTextFormat 精确控制。
STYLESHEET = f"""
QWidget {{
    font-family: {FONT_STACK};
    font-size: 13px;
}}

QMainWindow {{
    background-color: {Palette.NOTEBOOK_BG};
}}

QDialog {{
    background-color: {Palette.CREAM};
}}

QLabel {{
    color: {Palette.TEXT};
}}

QMenu {{
    background-color: {Palette.SURFACE};
    border: 1px solid {Palette.BORDER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {Palette.HIGHLIGHT};
}}

QToolTip {{
    background-color: {Palette.SURFACE};
    color: {Palette.TEXT};
    border: 1px solid {Palette.BORDER};
    padding: 4px 6px;
}}

QLabel#monthLabel {{
    font-size: 16px;
    font-weight: 500;
}}

QLabel#dayTitleLabel {{
    font-size: 17px;
    font-weight: 600;
}}

QLabel#summaryLabel {{
    color: {Palette.TEXT_MUTED};
}}

QPushButton {{
    background-color: {Palette.SURFACE};
    border: 1px solid {Palette.BORDER};
    border-radius: 10px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background-color: {Palette.HIGHLIGHT};
    border-color: {Palette.ACCENT};
}}
QPushButton:pressed {{
    background-color: {Palette.ACCENT};
}}
QPushButton:disabled {{
    color: {Palette.TEXT_DISABLED};
    border-color: {Palette.BORDER_SOFT};
    background-color: {Palette.SURFACE};
}}

QPushButton#primaryButton {{
    background-color: {Palette.BROWN_BUTTON};
    border-color: {Palette.ROW_SELECTED};
    color: {Palette.PAPER};
    font-weight: 500;
}}
QPushButton#primaryButton:hover {{
    background-color: {Palette.BROWN_BUTTON_HOVER};
    border-color: {Palette.BROWN_BUTTON};
}}
QPushButton#primaryButton:disabled {{
    background-color: #C9AE9C;
    border-color: #C9AE9C;
    color: {Palette.PAPER};
}}

QPushButton#dangerButton {{
    color: {Palette.DANGER};
}}
QPushButton#dangerButton:hover {{
    background-color: {Palette.DANGER_BG};
    border-color: {Palette.DANGER_BORDER};
}}
/* id 选择器的优先级高于 :disabled 伪类，必须单独把禁用态改回来，
   否则没有选中行时「删除」仍显示为可用的红字 */
QPushButton#dangerButton:disabled {{
    color: {Palette.TEXT_DISABLED};
    background-color: {Palette.SURFACE};
    border-color: {Palette.BORDER_SOFT};
}}

QPushButton#navButton {{
    min-width: 28px;
    max-width: 28px;
    padding: 4px 0;
}}

QTableWidget {{
    background-color: {Palette.SURFACE};
    border: 1px solid {Palette.BORDER_SOFT};
    border-radius: 12px;
    gridline-color: {Palette.BORDER_SOFT};
    selection-background-color: {Palette.HIGHLIGHT};
    selection-color: {Palette.TEXT};
}}
QTableWidget::item {{
    padding: 6px;
}}
QHeaderView::section {{
    background-color: {Palette.SURFACE_WARM};
    border: none;
    border-bottom: 1px solid {Palette.BORDER_SOFT};
    padding: 6px;
    color: {Palette.TEXT_MUTED};
}}

QCalendarWidget QWidget {{
    background-color: {Palette.SURFACE};
}}
QCalendarWidget QAbstractItemView:enabled {{
    background-color: {Palette.SURFACE};
    selection-background-color: {Palette.ACCENT};
    selection-color: {Palette.TEXT};
}}
/* 日历表头默认是系统灰，与暖色底不搭；单独铺成白色 */
QCalendarWidget QHeaderView::section {{
    background-color: {Palette.SURFACE};
    border: none;
    padding: 4px;
}}

/* ---------------- 滚动条 ----------------
   不写这一段，Windows 会画一条深色原生滚动条，在奶油纸上像一道裂口。
   轨道透明、手柄用浅赭色，悬停才加深；宽度收到 10px，箭头按钮直接去掉。 */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background-color: {Palette.BORDER};
    border-radius: 5px;
    min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {Palette.INK_MUTED};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background-color: {Palette.BORDER};
    border-radius: 5px;
    min-width: 36px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {Palette.INK_MUTED};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QLineEdit, QComboBox, QSpinBox, QDateEdit, QPlainTextEdit {{
    background-color: {Palette.SURFACE};
    border: 1px solid {Palette.BORDER};
    border-radius: 6px;
    padding: 4px 6px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDateEdit:focus, QPlainTextEdit:focus {{
    border-color: {Palette.ACCENT};
}}

/* ---------------- 笔记本风：学习记录窗口 ----------------
   这一组都用 id 选择器，只作用于记录窗口，不影响弹窗与桌宠菜单。 */

QFrame#subjectRail {{
    background-color: transparent;
    border: none;
}}

/* 科目滚动区：不自带白底，透出奶油色装订边；选择器只覆盖
   QScrollArea、视口和承载容器三层，不会波及科目按钮本身 */
QScrollArea#subjectScroll,
QScrollArea#subjectScroll > QWidget > QWidget {{
    background: transparent;
    border: none;
}}

QLabel#railTitle {{
    color: {Palette.INK_MUTED};
    font-size: 12px;
    letter-spacing: 3px;
}}

/* 科目页签：未选中是参考图里的鹅黄，选中切成粉，靠填色而不是描边区分 */
QPushButton#subjectTab {{
    background-color: {Palette.TAB_YELLOW};
    border: 1px solid {Palette.NOTEBOOK_BORDER};
    border-radius: 17px;
    padding: 8px 10px;
    color: {Palette.INK};
    text-align: center;
}}
QPushButton#subjectTab:hover {{
    background-color: #FFF1C9;
    border-color: {Palette.ROSE};
}}
QPushButton#subjectTab:checked {{
    background-color: {Palette.TAB_PINK};
    border-color: #D9A8AA;
    border-radius: 17px;
    font-weight: 600;
}}

/* 顶部「学习记录 / 账本」切换：两个互斥胶囊，浮在暖粉底上 */
QPushButton#viewTab {{
    background-color: {Palette.PAPER};
    border: 1px solid {Palette.NOTEBOOK_BORDER};
    border-radius: 16px;
    padding: 6px 18px;
    color: {Palette.INK};
}}
QPushButton#viewTab:hover {{
    border-color: {Palette.ROSE};
}}
QPushButton#viewTab:checked {{
    background-color: {Palette.TAB_PINK};
    border-color: #D9A8AA;
    color: {Palette.INK_STRONG};
    font-weight: 600;
}}

QFrame#paperPanel {{
    background-color: {Palette.PAPER_DEEP};
    border: 1px solid {Palette.NOTEBOOK_BORDER};
    border-radius: 18px;
}}

QFrame#calendarCard {{
    background-color: {Palette.PAPER_CARD};
    border: 1px solid {Palette.NOTEBOOK_BORDER};
    border-radius: 18px;
}}

QFrame#divider {{
    background-color: {Palette.RULE};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* ---------------- 日记页 ----------------
   编辑器直接铺在纸面上，不加边框：这块是"写字的纸"，不是"填内容的框" */

QListWidget#journalList {{
    background-color: transparent;
    border: none;
    outline: none;
}}
QListWidget#journalList::item {{
    border-radius: 10px;
    padding: 6px 8px;
    color: {Palette.INK};
}}
QListWidget#journalList::item:hover {{
    background-color: {Palette.PAPER};
}}
QListWidget#journalList::item:selected {{
    background-color: {Palette.HIGHLIGHT};
    color: {Palette.INK_STRONG};
}}

QPlainTextEdit#journalEditor {{
    background-color: transparent;
    border: none;
    padding: 2px 4px;
    color: {Palette.INK};
    font-size: 15px;
    selection-background-color: {Palette.TAB_PINK};
    selection-color: {Palette.INK_STRONG};
}}

QLabel#journalStatus {{
    color: {Palette.INK_MUTED};
    font-size: 12px;
}}

QLabel#dayTitleLabel {{
    color: {Palette.INK_STRONG};
    font-size: 16px;
    font-weight: 600;
}}

QLabel#summaryLabel {{
    color: {Palette.INK_MUTED};
}}

QLabel#weekdayLabel {{
    color: {Palette.INK_MUTED};
    font-size: 12px;
    padding: 2px 0;
}}

QLabel#statLabel {{
    color: {Palette.INK_MUTED};
    font-size: 12px;
}}

QLabel#statValue {{
    color: {Palette.INK_STRONG};
    font-size: 13px;
    font-weight: 500;
}}

QLabel#emptyHint {{
    color: {Palette.INK_MUTED};
}}

/* 记录表格：去掉白底与网格，用一条下细线分隔每行，看起来像纸上的横线 */
QTableWidget#recordTable {{
    background-color: transparent;
    border: none;
    selection-background-color: {Palette.ROW_SELECTED};
    selection-color: #FFE9CF;
}}
QTableWidget#recordTable::item {{
    border-bottom: 1px solid {Palette.RULE};
    padding: 6px 8px;
    color: {Palette.INK};
}}
QTableWidget#recordTable::item:selected {{
    background-color: {Palette.ROW_SELECTED};
    color: #FFE9CF;
}}
QTableWidget#recordTable QHeaderView {{
    background-color: {Palette.PAPER_DEEP};
}}
QTableWidget#recordTable QHeaderView::section {{
    background-color: {Palette.PAPER_DEEP};
    border: none;
    border-bottom: 1px solid {Palette.RULE};
    color: {Palette.INK_MUTED};
    padding: 4px 8px;
    font-weight: 400;
}}

/* 卡片内导航与日历：背景透明，交给卡片底色 */
QPushButton#cardNavButton {{
    background-color: transparent;
    border: none;
    color: {Palette.INK_MUTED};
    border-radius: 14px;
    min-width: 24px;
    max-width: 24px;
    padding: 2px 0;
}}
QPushButton#cardNavButton:hover {{
    background-color: {Palette.ROSE_SOFT};
    color: {Palette.INK_STRONG};
}}

/* 日历内部：必须给**实色**背景。
   实测写 transparent 时，QCalendarWidget 内部视图的区域在截图/拖动时会露出
   未绘制的黑底（dates 之间出现黑色块），看起来像窗口破了洞。

   这里**不能**用 `QCalendarWidget#calendar ...` 这种带 id 的层级选择器：
   对日历内部由 Qt 自己创建的部件它匹配不到，颜色会退回系统灰。旧的全局写法
   `QCalendarWidget QWidget` 才是有效的，因此沿用。 */
QCalendarWidget QWidget {{
    background-color: {Palette.PAPER_CARD};
}}
QCalendarWidget QAbstractItemView {{
    background-color: {Palette.PAPER_CARD};
}}
QCalendarWidget QAbstractItemView:enabled {{
    background-color: {Palette.PAPER_CARD};
    selection-background-color: {Palette.ROSE};
    selection-color: #FFF6DE;
    outline: none;
}}
QCalendarWidget QHeaderView::section {{
    background-color: {Palette.PAPER_CARD};
    border: none;
    color: {Palette.INK_MUTED};
    padding: 4px 0;
}}
QCalendarWidget QToolButton {{
    background-color: {Palette.PAPER_CARD};
    border: none;
    color: {Palette.INK_MUTED};
}}

QPushButton#linkButton {{
    background-color: transparent;
    border: none;
    color: {Palette.INK_MUTED};
    padding: 4px 6px;
}}
QPushButton#linkButton:hover {{
    color: {Palette.ROSE};
    background-color: transparent;
}}
"""


def apply_theme(app: "QApplication") -> None:
    """把主题应用到整个应用。

    **必须先把样式切到 Fusion**：Windows 默认的原生样式（windowsvista）会自己
    绘制表头、日历星期行等部件，完全不理会样式表——实测日历星期行始终是系统灰
    ``#F5F5F5``，选中时还会冒出一块系统蓝。Fusion 是 Qt 自绘样式，QSS 能真正
    生效，颜色才由我们说了算。

    **调用时机**：``QApplication`` 构造之后、任何窗口创建之前（见
    ``main.configure_application``）。这套色板与 QSS 不会自动生效，漏调用的
    表现是整窗白底灰边，而不是报错。
    """
    app.setStyle("Fusion")
    # 设置样式表之后，app.style() 会被 Qt 包装成 QStyleSheetStyle，
    # 再读 objectName / className 都拿不到真正的基样式。先把名字记下来，
    # 方便测试断言与线上排查（"到底有没有切到 Fusion"）。
    base_style = app.style().objectName() or app.style().metaObject().className()
    app.setStyleSheet(STYLESHEET)
    app.setProperty("catstudyBaseStyle", base_style)
