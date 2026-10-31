"""专注计时（番茄钟 / 正计时）的测试。

三组用例：

1. ``core.timer`` 的状态机与读数——用假时钟推进时间，不真的 sleep；
2. 落库规则（``main.save_focus_session``）——临时数据库，不碰真实数据；
3. 桌宠端的交互——开始/暂停/结束/放弃/菜单可用性，以及"番茄钟到点自动结算"。
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.database import DatabaseManager
from core.study_records import StudyRecordRepository
from core.timer import FocusTimer, TimerMode, TimerState, format_clock
from main import FALLBACK_SUBJECT, last_subject, save_focus_session
from ui.pet_window import PetWindow

_APP: QApplication | None = None


def setUpModule() -> None:
    global _APP
    if QApplication.instance() is None:
        _APP = QApplication([])


class FakeClock:
    """可手动推进的单调时钟。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FormatClockTests(unittest.TestCase):
    def test_short_durations(self):
        self.assertEqual(format_clock(0), "00:00")
        self.assertEqual(format_clock(9), "00:09")
        self.assertEqual(format_clock(59), "00:59")
        self.assertEqual(format_clock(60), "01:00")
        self.assertEqual(format_clock(3599), "59:59")

    def test_hour_rolls_over(self):
        self.assertEqual(format_clock(3600), "1:00:00")
        self.assertEqual(format_clock(3672), "1:01:12")

    def test_negative_and_fraction_floor(self):
        self.assertEqual(format_clock(-5), "00:00")
        self.assertEqual(format_clock(59.99), "00:59")


class PomodoroTimerTests(unittest.TestCase):
    def _make(self, minutes: int = 25) -> tuple[FocusTimer, FakeClock]:
        clock = FakeClock()
        return FocusTimer(clock=clock, pomodoro_seconds=minutes * 60), clock

    def test_initial_state(self):
        timer, _ = self._make()
        self.assertIs(timer.state, TimerState.IDLE)
        self.assertFalse(timer.is_active)
        self.assertEqual(timer.elapsed_seconds(), 0)

    def test_counts_down_from_full_duration(self):
        timer, clock = self._make()
        timer.start(TimerMode.POMODORO)
        self.assertEqual(timer.display_text(), "25:00")
        clock.advance(90)
        self.assertEqual(timer.elapsed_seconds(), 90)
        self.assertEqual(timer.remaining_seconds(), 25 * 60 - 90)
        self.assertEqual(timer.display_text(), "23:30")

    def test_pause_freezes_elapsed(self):
        timer, clock = self._make()
        timer.start(TimerMode.POMODORO)
        clock.advance(120)
        timer.pause()
        self.assertIs(timer.state, TimerState.PAUSED)
        clock.advance(600)  # 暂停期间过去的时间不算专注
        self.assertEqual(timer.elapsed_seconds(), 120)
        self.assertEqual(timer.remaining_seconds(), 25 * 60 - 120)

    def test_resume_continues_accumulating(self):
        timer, clock = self._make()
        timer.start(TimerMode.POMODORO)
        clock.advance(120)
        timer.pause()
        clock.advance(600)
        timer.resume()
        clock.advance(60)
        self.assertEqual(timer.elapsed_seconds(), 180)
        self.assertIs(timer.state, TimerState.RUNNING)

    def test_pause_and_resume_are_noops_in_wrong_state(self):
        timer, _ = self._make()
        timer.pause()  # IDLE 下暂停不应报错也不应改状态
        self.assertIs(timer.state, TimerState.IDLE)
        timer.resume()
        self.assertIs(timer.state, TimerState.IDLE)

    def test_expires_at_target_and_clamps(self):
        timer, clock = self._make()
        timer.start(TimerMode.POMODORO)
        clock.advance(25 * 60 + 45)  # 超时 45 秒
        self.assertIs(timer.state, TimerState.FINISHED)
        self.assertEqual(timer.elapsed_seconds(), 25 * 60)  # 钉在目标值
        self.assertEqual(timer.remaining_seconds(), 0)
        self.assertEqual(timer.display_text(), "00:00")

    def test_stop_returns_floored_seconds(self):
        timer, clock = self._make()
        timer.start(TimerMode.POMODORO)
        clock.advance(125.7)
        self.assertEqual(timer.stop(), 125)
        self.assertIs(timer.state, TimerState.FINISHED)
        self.assertEqual(timer.elapsed_seconds(), 125)

    def test_duration_minutes_floors(self):
        timer, clock = self._make()
        timer.start(TimerMode.POMODORO)
        clock.advance(59)
        self.assertEqual(timer.duration_minutes(), 0)
        clock.advance(61)
        self.assertEqual(timer.duration_minutes(), 2)

    def test_reset_clears_session(self):
        timer, clock = self._make()
        timer.start(TimerMode.POMODORO)
        clock.advance(300)
        timer.reset()
        self.assertIs(timer.state, TimerState.IDLE)
        self.assertEqual(timer.elapsed_seconds(), 0)

    def test_display_never_shows_zero_before_finish(self):
        timer, clock = self._make(minutes=1)
        timer.start(TimerMode.POMODORO)
        clock.advance(59.4)  # 还剩 0.6 秒，应该还是 00:01
        self.assertEqual(timer.display_text(), "00:01")


class StopwatchTests(unittest.TestCase):
    def test_counts_up_without_limit(self):
        clock = FakeClock()
        timer = FocusTimer(clock=clock)
        timer.start(TimerMode.STOPWATCH)
        self.assertEqual(timer.display_text(), "00:00")
        clock.advance(3661)
        self.assertEqual(timer.display_text(), "1:01:01")
        self.assertIsNone(timer.remaining_seconds())
        self.assertIs(timer.state, TimerState.RUNNING)  # 正计时不会自己结束

    def test_start_with_invalid_mode(self):
        timer = FocusTimer()
        with self.assertRaises(TypeError):
            timer.start("pomodoro")  # 只接受 TimerMode

    def test_rejects_non_positive_pomodoro(self):
        with self.assertRaises(ValueError):
            FocusTimer(pomodoro_seconds=0)

    def test_start_again_resets_previous_session(self):
        clock = FakeClock()
        timer = FocusTimer(clock=clock)
        timer.start(TimerMode.STOPWATCH)
        clock.advance(100)
        timer.start(TimerMode.POMODORO)
        self.assertEqual(timer.elapsed_seconds(), 0)
        self.assertIs(timer.mode, TimerMode.POMODORO)


class SaveFocusSessionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = DatabaseManager(Path(self._tmp.name) / "t.db")
        self.db.connect()
        self.addCleanup(self.db.close)
        self.repo = StudyRecordRepository(self.db)
        self.refreshed = 0

    def _manager(self):
        outer = self

        class _Manager:
            def refresh_if_open(self_inner):
                outer.refreshed += 1

        return _Manager()

    def test_pomodoro_writes_record_with_source(self):
        record_id = save_focus_session(
            self.repo, self._manager(), "pomodoro", "数学", 25 * 60, date(2026, 10, 31)
        )
        self.assertIsNotNone(record_id)
        record = self.repo.get(record_id)
        self.assertEqual(record.subject, "数学")
        self.assertEqual(record.duration_minutes, 25)
        self.assertEqual(record.source, "pomodoro")
        self.assertEqual(record.study_date, "2026-10-31")
        self.assertEqual(self.refreshed, 1)

    def test_stopwatch_seconds_are_floored_to_minutes(self):
        save_focus_session(
            self.repo, self._manager(), "stopwatch", "英语", 125, date(2026, 10, 31)
        )
        record = self.repo.list_by_date("2026-10-31")[0]
        self.assertEqual(record.duration_minutes, 2)
        self.assertEqual(record.source, "stopwatch")

    def test_under_one_minute_is_not_saved(self):
        record_id = save_focus_session(
            self.repo, self._manager(), "pomodoro", "数学", 59, date(2026, 10, 31)
        )
        self.assertIsNone(record_id)
        self.assertEqual(self.repo.count(), 0)
        self.assertEqual(self.refreshed, 0)

    def test_last_subject_falls_back_when_empty(self):
        self.assertEqual(last_subject(self.repo), FALLBACK_SUBJECT)

    def test_last_subject_uses_most_recent_record(self):
        self.repo.add(date(2026, 10, 29), "物理", duration_minutes=10)
        self.repo.add(date(2026, 10, 31), "化学", duration_minutes=5)
        self.assertEqual(last_subject(self.repo), "化学")


class SourceColumnTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "t.db"

    def test_fresh_database_has_source_column(self):
        db = DatabaseManager(self.path)
        db.connect()
        self.addCleanup(db.close)
        columns = {row["name"] for row in db.connection.execute("PRAGMA table_info(study_records)")}
        self.assertIn("source", columns)
        self.assertEqual(db.schema_version(), 3)

    def test_migration_from_v2_keeps_rows(self):
        # 先造一个 v2 结构的库（没有 source 列）
        db = DatabaseManager(self.path)
        db.connect()
        db.connection.execute("ALTER TABLE study_records DROP COLUMN source")
        db.connection.execute("UPDATE app_meta SET value = '2' WHERE key = 'schema_version'")
        db.connection.execute(
            "INSERT INTO study_records (study_date, subject, duration_minutes, content) "
            "VALUES ('2026-10-30', '历史科目', 30, '旧数据')"
        )
        db.connection.commit()
        db.close()

        db2 = DatabaseManager(self.path)
        db2.connect()
        self.addCleanup(db2.close)
        self.assertEqual(db2.schema_version(), 3)
        row = db2.connection.execute(
            "SELECT subject, source FROM study_records"
        ).fetchone()
        self.assertEqual(row["subject"], "历史科目")
        self.assertIsNone(row["source"])  # 老记录默认"未标注来源"

    def test_repository_rejects_unknown_source(self):
        db = DatabaseManager(self.path)
        db.connect()
        self.addCleanup(db.close)
        repo = StudyRecordRepository(db)
        with self.assertRaises(ValueError):
            repo.add("2026-10-31", "数学", source="telepathy")

    def test_blank_source_stored_as_null(self):
        db = DatabaseManager(self.path)
        db.connect()
        self.addCleanup(db.close)
        repo = StudyRecordRepository(db)
        record_id = repo.add("2026-10-31", "数学", source="   ")
        self.assertIsNone(repo.get(record_id).source)


class PetTimerTests(unittest.TestCase):
    """桌宠端的计时交互。用 60 秒番茄钟把"到点"压缩到一次假时钟推进。"""

    def setUp(self):
        self.clock = FakeClock()
        self.timer = FocusTimer(clock=self.clock, pomodoro_seconds=60)
        self.pet = PetWindow(timer=self.timer, default_subject="数学")
        self.addCleanup(self.pet.close)
        self.events: list[tuple[str, str, int]] = []
        self.pet.focusSessionFinished.connect(
            lambda mode, subject, seconds: self.events.append((mode, subject, seconds))
        )

    def test_start_shows_countdown_bubble(self):
        self.assertTrue(self.pet.start_focus(TimerMode.POMODORO, subject="数学"))
        self.assertIs(self.timer.state, TimerState.RUNNING)
        self.assertTrue(self.pet._bubble.isVisible())
        self.assertEqual(self.pet._bubble.text, "01:00")

    def test_start_refused_while_active(self):
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.assertFalse(self.pet.start_focus(TimerMode.STOPWATCH, subject="英语"))
        self.assertIs(self.timer.mode, TimerMode.POMODORO)

    def test_pause_and_resume_toggle(self):
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.clock.advance(30)
        self.pet._on_tick()
        self.assertEqual(self.pet._bubble.text, "00:30")

        self.pet.toggle_pause()
        self.assertIs(self.timer.state, TimerState.PAUSED)
        self.assertTrue(self.pet._bubble.text.startswith("⏸"))

        self.pet.toggle_pause()
        self.assertIs(self.timer.state, TimerState.RUNNING)

    def test_finish_emits_and_flashes(self):
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.clock.advance(90)
        self.pet.finish_focus()
        self.assertEqual(self.events, [("stopwatch", "数学", 90)])
        self.assertIn("已记录", self.pet._bubble.text)

    def test_discard_emits_nothing(self):
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.clock.advance(30)
        self.pet.discard_focus()
        self.assertEqual(self.events, [])
        self.assertIs(self.timer.state, TimerState.IDLE)
        self.assertFalse(self.pet._bubble.isVisible())

    def test_pomodoro_expiry_settles_exactly_once(self):
        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.clock.advance(61)
        self.pet._on_tick()          # 到点，第一次刷新即结算
        self.pet._on_tick()          # 再刷新不应重复结算
        self.pet.finish_focus()      # 手动结束也不应重复
        self.assertEqual(self.events, [("pomodoro", "数学", 60)])
        self.assertIn("1 分钟", self.pet._bubble.text)

    def test_under_one_minute_message(self):
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.clock.advance(20)
        self.pet.finish_focus()
        self.assertIn("不足 1 分钟", self.pet._bubble.text)

    def test_menu_actions_follow_state(self):
        self.pet._sync_menu_state()
        self.assertTrue(self.pet.pomodoro_action.isEnabled())
        self.assertFalse(self.pet.pause_action.isEnabled())

        self.pet.start_focus(TimerMode.POMODORO, subject="数学")
        self.pet._sync_menu_state()
        self.assertFalse(self.pet.pomodoro_action.isEnabled())
        self.assertTrue(self.pet.pause_action.isEnabled())
        self.assertEqual(self.pet.pause_action.text(), "暂停")

        self.pet.toggle_pause()
        self.pet._sync_menu_state()
        self.assertEqual(self.pet.pause_action.text(), "继续")

    def test_bubble_follows_window_move(self):
        self.pet.start_focus(TimerMode.STOPWATCH, subject="数学")
        self.pet.move(400, 300)
        self.pet._bubble.show_near(self.pet)
        pet_center = self.pet.frameGeometry().center().x()
        bubble_center = self.pet._bubble.geometry().center().x()
        self.assertLessEqual(abs(pet_center - bubble_center), 2)


if __name__ == "__main__":
    unittest.main()
