from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from .constants import (
    ACTIVE_TEXT_COLOR,
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE,
    DEFAULT_LANGUAGE,
    DEFAULT_MESSAGE,
    DEFAULT_OUTLINE_COLOR,
    DEFAULT_TEXT_COLOR,
    DEFAULT_TRANSPARENCY,
    PAUSE_TEXT_COLOR,
    STOP_TEXT_COLOR,
    TIME_TEXT_COLOR,
)
from .i18n import strip_pause_prefix, translate


@dataclass
class StoredTask:
    """Serializable task snapshot used for task switching and persistence."""

    title: str
    id: str = field(default_factory=lambda: uuid4().hex)
    estimate_minutes: Optional[int] = None
    active: bool = False
    paused: bool = False
    start_time: Optional[datetime] = None
    elapsed_before_pause_seconds: int = 0
    text_color: str = STOP_TEXT_COLOR

    def display_message(self, language: str) -> str:
        title = self.title.strip()
        if not title:
            return translate(language, "no_task")
        if self.paused:
            prefix = translate(language, "pause_prefix")
            return f"{prefix} {title}"
        return title


@dataclass
class TaskState:
    """Mutable task status used by the UI and tests."""

    message: str = DEFAULT_MESSAGE
    language: str = DEFAULT_LANGUAGE
    text_color: str = DEFAULT_TEXT_COLOR
    outline_color: str = DEFAULT_OUTLINE_COLOR
    transparency: float = DEFAULT_TRANSPARENCY
    font_family: str = DEFAULT_FONT_FAMILY
    font_size: int = DEFAULT_FONT_SIZE
    estimate_minutes: Optional[int] = None
    active: bool = False
    paused: bool = False
    start_time: Optional[datetime] = None
    elapsed_before_pause: timedelta = field(default_factory=timedelta)

    def task_name(self) -> str:
        return strip_pause_prefix(self.message).strip()

    def start(self, task_name: str, estimate_minutes: Optional[int] = None) -> None:
        task_name = task_name.strip()
        if not task_name:
            return
        self.message = task_name
        self.estimate_minutes = estimate_minutes
        self.active = True
        self.paused = False
        self.start_time = datetime.now()
        self.elapsed_before_pause = timedelta()
        self.text_color = ACTIVE_TEXT_COLOR

    def pause(self) -> None:
        if not self.active or self.paused:
            return
        if self.start_time:
            self.elapsed_before_pause += datetime.now() - self.start_time
        self.paused = True
        self.text_color = PAUSE_TEXT_COLOR
        prefix = translate(self.language, "pause_prefix")
        self.message = f"{prefix} {self.task_name()}"

    def resume(self) -> None:
        if not self.active or not self.paused:
            return
        self.paused = False
        self.text_color = ACTIVE_TEXT_COLOR
        self.message = self.task_name()
        self.start_time = datetime.now()

    def stop(self) -> None:
        self.active = False
        self.paused = False
        self.start_time = None
        self.elapsed_before_pause = timedelta()
        self.message = translate(self.language, "no_task")
        self.text_color = STOP_TEXT_COLOR
        self.estimate_minutes = None

    def load_stored_task(self, task: StoredTask | None) -> None:
        if task is None:
            self.active = False
            self.paused = False
            self.start_time = None
            self.elapsed_before_pause = timedelta()
            self.estimate_minutes = None
            self.text_color = STOP_TEXT_COLOR
            self.message = translate(self.language, "no_task")
            return
        self.estimate_minutes = task.estimate_minutes
        self.active = task.active
        self.paused = task.paused
        self.start_time = task.start_time
        self.elapsed_before_pause = timedelta(seconds=task.elapsed_before_pause_seconds)
        self.text_color = task.text_color or STOP_TEXT_COLOR
        self.message = task.display_message(self.language)

    def to_stored_task(self, task_id: str) -> StoredTask:
        return StoredTask(
            id=task_id,
            title=self.task_name(),
            estimate_minutes=self.estimate_minutes,
            active=self.active,
            paused=self.paused,
            start_time=self.start_time,
            elapsed_before_pause_seconds=max(
                0, int(self.elapsed_before_pause.total_seconds())
            ),
            text_color=self.text_color,
        )

    def elapsed_seconds(self) -> int:
        elapsed = self.elapsed_before_pause
        if self.active and not self.paused and self.start_time:
            elapsed += datetime.now() - self.start_time
        return max(0, int(elapsed.total_seconds()))

    def _elapsed_label(self, elapsed_seconds: int) -> str:
        if elapsed_seconds < 60:
            return translate(self.language, "time_elapsed_less_minute")
        minutes = elapsed_seconds // 60
        if minutes < 60:
            return translate(self.language, "time_elapsed_minutes", minutes=minutes)
        hours, rem = divmod(minutes, 60)
        if rem == 0:
            return translate(self.language, "time_elapsed_hours_only", hours=hours)
        return translate(self.language, "time_elapsed_hours", hours=hours, minutes=rem)

    def time_text(self) -> str:
        if not self.active or not self.start_time:
            return ""
        start_label = translate(self.language, "time_started")
        start_time_str = self.start_time.strftime("%H:%M:%S")
        return f"{start_label}: {start_time_str}"

    def estimate_text(self) -> tuple[str, str]:
        if not self.active or not self.start_time:
            return "", STOP_TEXT_COLOR
        elapsed_label = self._elapsed_label(self.elapsed_seconds())
        if not self.estimate_minutes:
            return elapsed_label, TIME_TEXT_COLOR
        elapsed = self.elapsed_seconds()
        est_seconds = max(1, self.estimate_minutes * 60)
        ratio = elapsed / est_seconds
        if ratio <= 0.5:
            color = "#4caf50"
        elif ratio <= 0.8:
            color = "#ffeb3b"
        elif ratio <= 1.0:
            color = "#ff9800"
        else:
            color = "#ff3b30"
        if ratio <= 1.0:
            estimate_text = translate(
                self.language, "estimate_label", minutes=self.estimate_minutes
            )
        else:
            over_min = (elapsed - est_seconds + 59) // 60
            estimate_text = translate(self.language, "estimate_over_label", minutes=over_min)
        return f"{elapsed_label} · {estimate_text}", color
