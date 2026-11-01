"""日记页面：左边按时间线回看，右边写当天的内容。

设计取舍：

1. **左侧不用日历，用列表**。学习记录用日历是因为"哪天学了什么"要按格子找；
   日记是连续的文字，人回看时是"往上翻"，不是"点格子"。列表还能直接带一行
   摘要，扫一眼就知道那天写了什么，日历做不到这一点。
   顺带也避免把 ``study_view`` 里那套自绘星期行 + 列对齐再复制一遍。
2. **自动保存，没有保存按钮**。写日记最怕"写了半天忘了点保存"。输入停下
   1.2 秒就落库，切换日期、切页签、关窗口前都会先 flush 一次。
3. **空内容等于删除**（在仓储层实现）。清空正文后列表里那条自动消失，
   不会留一堆点进去什么都没有的空壳。

编辑器只负责显示与收集文本，所有读写都走 ``JournalRepository``；
本文件里没有一行 SQL。
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.journal import JournalRepository
from core.study_records import StudyRecordRepository

# 左栏宽度：放得下"11-01 周日"加一行十几个字的摘要
RAIL_WIDTH: int = 236

# 输入停止多久后自动保存（毫秒）。太短会在打字过程中频繁写库，
# 太长则"刚写完就关窗口"容易丢字。
AUTOSAVE_MS: int = 1200

# 列表摘要最多显示多少字
SUMMARY_LIMIT: int = 16

WEEKDAY_NAMES: tuple[str, ...] = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

PLACEHOLDER = (
    "今天发生了什么？\n\n"
    "学了什么、卡在哪里、想到什么，随手写几句就行。\n"
    "停下打字 1 秒会自动保存。"
)


class JournalView(QWidget):
    """日记页。"""

    # 某天的日记被保存/删除后发出，供外层刷新统计
    entryChanged = Signal(str)

    def __init__(
        self,
        repository: JournalRepository,
        parent: QWidget | None = None,
        study_repository: StudyRecordRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repository
        self._study = study_repository
        self._date: date = date.today()
        # 加载正文时 textChanged 也会触发，用它抑制"一加载就变脏"
        self._loading: bool = False
        self._dirty: bool = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_MS)
        self._save_timer.timeout.connect(self.save_now)

        self._build_ui()
        self._connect_signals()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        rail = QFrame(self)
        rail.setObjectName("paperPanel")
        rail.setFixedWidth(RAIL_WIDTH)

        title = QLabel("日记", rail)
        title.setObjectName("railTitle")

        self.new_button = QPushButton("＋ 写今天", rail)
        self.new_button.setObjectName("primaryButton")
        self.new_button.setToolTip("跳到今天并开始写")

        self.list = QListWidget(rail)
        self.list.setObjectName("journalList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setWordWrap(True)

        self.count_label = QLabel("", rail)
        self.count_label.setObjectName("emptyHint")

        rail_box = QVBoxLayout(rail)
        rail_box.setContentsMargins(14, 14, 14, 14)
        rail_box.setSpacing(10)
        rail_box.addWidget(title)
        rail_box.addWidget(self.new_button)
        rail_box.addWidget(self.list, 1)
        rail_box.addWidget(self.count_label)

        # ---- 右：日期导航 + 编辑器 ----
        panel = QFrame(self)
        panel.setObjectName("paperPanel")

        self.prev_button = QPushButton("‹", panel)
        self.prev_button.setObjectName("cardNavButton")
        self.prev_button.setToolTip("前一天")
        self.next_button = QPushButton("›", panel)
        self.next_button.setObjectName("cardNavButton")
        self.next_button.setToolTip("后一天")

        self.title_label = QLabel("", panel)
        self.title_label.setObjectName("dayTitleLabel")

        self.today_button = QPushButton("今天", panel)
        self.today_button.setObjectName("linkButton")

        nav = QHBoxLayout()
        # 箭头和标题之间留一点空，否则「‹ 2026 年 11 月 1 日」读起来像一个整体
        nav.setSpacing(10)
        nav.addWidget(self.prev_button)
        nav.addWidget(self.title_label)
        nav.addWidget(self.next_button)
        nav.addStretch(1)
        nav.addWidget(self.today_button)

        self.editor = QPlainTextEdit(panel)
        self.editor.setObjectName("journalEditor")
        self.editor.setPlaceholderText(PLACEHOLDER)
        self.editor.setFrameShape(QFrame.Shape.NoFrame)

        self.status_label = QLabel("", panel)
        self.status_label.setObjectName("journalStatus")
        self.study_label = QLabel("", panel)
        self.study_label.setObjectName("journalStatus")
        self.study_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addWidget(self.status_label)
        footer.addStretch(1)
        footer.addWidget(self.study_label)

        panel_box = QVBoxLayout(panel)
        panel_box.setContentsMargins(18, 16, 18, 14)
        panel_box.setSpacing(10)
        panel_box.addLayout(nav)
        panel_box.addWidget(self.editor, 1)
        panel_box.addLayout(footer)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)
        root.addWidget(rail)
        root.addWidget(panel, 1)

    def _connect_signals(self) -> None:
        self.list.itemSelectionChanged.connect(self._on_list_selection)
        self.editor.textChanged.connect(self._on_text_changed)
        self.prev_button.clicked.connect(lambda: self.shift_day(-1))
        self.next_button.clicked.connect(lambda: self.shift_day(1))
        self.today_button.clicked.connect(self.go_to_today)
        self.new_button.clicked.connect(self.write_today)

    # ------------------------------------------------------------------
    # 日期
    # ------------------------------------------------------------------

    def selected_date(self) -> date:
        return self._date

    def set_selected_date(self, day: date) -> None:
        """切到某一天；切之前先把当前未保存的内容落库。"""
        if not isinstance(day, date):
            raise TypeError(f"日期必须是 date，收到 {type(day).__name__}")
        if day == self._date and not self._dirty:
            return
        self.save_now()
        self._date = day
        self._load_current()
        self._select_in_list(day)

    def shift_day(self, delta: int) -> None:
        self.set_selected_date(self._date + timedelta(days=delta))

    def go_to_today(self) -> None:
        self.set_selected_date(date.today())

    def write_today(self) -> None:
        """跳到今天并把光标放进编辑器，省一次点击。"""
        self.go_to_today()
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """重载列表与当天正文。

        已有未保存的输入时**不覆盖编辑器**——否则切页签回来手一抖就丢字。
        """
        self._reload_list()
        if not self._dirty:
            self._load_current()

    def _load_current(self) -> None:
        entry = self._repo.get(self._date)
        text = "" if entry is None else entry.content

        self._loading = True
        # 关掉撤销历史：换一天后按 Ctrl+Z 不该跳回上一天的文本
        self.editor.setUndoRedoEnabled(False)
        self.editor.setPlainText(text)
        self.editor.setUndoRedoEnabled(True)
        self._loading = False

        self._dirty = False
        self._update_header()
        self._update_status()
        self._select_in_list(self._date)

    def _reload_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        entries = self._repo.list_recent()
        for entry in entries:
            item = QListWidgetItem(self._item_text(entry.entry_date, entry.summary))
            item.setData(Qt.ItemDataRole.UserRole, entry.entry_date)
            item.setToolTip(entry.summary or "（空）")
            item.setSizeHint(QSize(0, 46))
            self.list.addItem(item)
        self.list.blockSignals(False)

        total = len(entries)
        self.count_label.setText(f"共 {total} 篇" if total else "还没有写过日记")

    @staticmethod
    def _item_text(iso_date: str, summary: str) -> str:
        day = date.fromisoformat(iso_date)
        label = f"{day.month:02d}-{day.day:02d} {WEEKDAY_NAMES[day.weekday()]}"
        text = summary[:SUMMARY_LIMIT] or "（空）"
        if len(summary) > SUMMARY_LIMIT:
            text += "…"
        return f"{label}\n{text}"

    def _select_in_list(self, day: date) -> None:
        iso = day.isoformat()
        self.list.blockSignals(True)
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == iso:
                self.list.setCurrentRow(row)
                break
        else:
            # 这一天还没写：清掉选中，避免列表里停在别的日期上误导
            self.list.clearSelection()
            self.list.setCurrentRow(-1)
        self.list.blockSignals(False)

    def _on_list_selection(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        iso = item.data(Qt.ItemDataRole.UserRole)
        if not iso:
            return
        self.set_selected_date(date.fromisoformat(str(iso)))

    # ------------------------------------------------------------------
    # 保存
    # ------------------------------------------------------------------

    def _on_text_changed(self) -> None:
        if self._loading:
            return
        self._dirty = True
        self._save_timer.start()
        self._update_status()

    def save_now(self) -> None:
        """立即落库（切换日期、隐藏窗口、点保存时都走这里）。"""
        if not self._dirty:
            return
        self._save_timer.stop()
        self._repo.save(self._date, self.editor.toPlainText())
        self._dirty = False
        self._update_status(saved=True)
        self._reload_list()
        self._select_in_list(self._date)
        self.entryChanged.emit(self._date.isoformat())

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------------
    # 文案
    # ------------------------------------------------------------------

    def _update_header(self) -> None:
        day = self._date
        self.title_label.setText(
            f"{day.year} 年 {day.month} 月 {day.day} 日 · {WEEKDAY_NAMES[day.weekday()]}"
        )
        is_today = day == date.today()
        self.today_button.setEnabled(not is_today)

    def _update_status(self, saved: bool = False) -> None:
        chars = len(self.editor.toPlainText().strip())
        if self._dirty:
            text = f"编辑中… {chars} 字" if chars else "编辑中…"
        elif chars == 0:
            text = "这一天还没写"
        elif saved:
            text = f"已保存 · {chars} 字"
        else:
            text = f"{chars} 字"
        self.status_label.setText(text)

        self.study_label.setText(self._study_summary())

    def _study_summary(self) -> str:
        """当天学了多久。没有学习仓储时返回空串（页面仍可用）。"""
        if self._study is None:
            return ""
        records = self._study.list_by_date(self._date)
        minutes = sum(r.duration_minutes or 0 for r in records)
        if not records:
            return ""
        if minutes <= 0:
            return f"当天记了 {len(records)} 条学习"
        return f"当天专注 {minutes} 分钟"

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名风格)
        # 切页签或被关闭时先把没落库的内容写下去，避免"写了半天丢了"
        self.save_now()
        super().hideEvent(event)
