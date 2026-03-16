from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .constants import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE,
    DEFAULT_LANGUAGE,
    DEFAULT_MESSAGE,
    DEFAULT_OUTLINE_COLOR,
    DEFAULT_TEXT_COLOR,
    DEFAULT_TRANSPARENCY,
)
from .i18n import NO_TASK_VALUES, SUPPORTED_LANGUAGES, strip_pause_prefix
from .task_state import StoredTask


def is_valid_color(value: str | None) -> bool:
    if not value:
        return False
    value = str(value).strip()
    if len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def ensure_color(value: str | None, fallback: str) -> str:
    if value and is_valid_color(value):
        return str(value).strip().lower()
    return fallback


def ensure_transparency(value: float | str | None, fallback: float) -> float:
    if value is None:
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(1.0, max(0.2, number))


def ensure_font_size(value: int | str | None, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        size = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(8, min(96, size))


def ensure_language(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    code = value.lower()
    return code if code in SUPPORTED_LANGUAGES else fallback


def _normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value.strip(), "%H:%M")
        return dt.strftime("%H:%M")
    except ValueError:
        return None


def ensure_schedule(value) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    schedule: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        start = _normalize_time(item.get("start"))
        end = _normalize_time(item.get("end"))
        label = str(item.get("label") or "").strip() or "Break"
        if not start or not end or start == end:
            continue
        if start >= end:
            continue
        schedule.append({"start": start, "end": end, "label": label})
    schedule.sort(key=lambda entry: entry["start"])
    return schedule


def _parse_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _normalize_task_entry(value) -> StoredTask | None:
    if not isinstance(value, dict):
        return None
    title = strip_pause_prefix(str(value.get("title") or value.get("message") or "")).strip()
    if not title:
        return None
    estimate_minutes = value.get("estimate_minutes")
    if not isinstance(estimate_minutes, int) or estimate_minutes <= 0:
        estimate_minutes = None
    active = value.get("active")
    if not isinstance(active, bool):
        active = False
    paused = value.get("paused")
    if not isinstance(paused, bool):
        paused = False
    elapsed_before_pause_seconds = value.get("elapsed_before_pause_seconds")
    if not isinstance(elapsed_before_pause_seconds, int) or elapsed_before_pause_seconds < 0:
        elapsed_before_pause_seconds = 0
    start_time = _parse_datetime(value.get("start_time"))
    if paused and not active:
        active = True
    if active and not paused and start_time is None:
        start_time = datetime.now()
    text_color = ensure_color(value.get("text_color"), DEFAULT_TEXT_COLOR)
    task_id = str(value.get("id") or "").strip()
    return StoredTask(
        id=task_id or StoredTask(title=title).id,
        title=title,
        estimate_minutes=estimate_minutes,
        active=active,
        paused=paused,
        start_time=start_time,
        elapsed_before_pause_seconds=elapsed_before_pause_seconds,
        text_color=text_color,
    )


def ensure_tasks(value) -> list[StoredTask]:
    if not isinstance(value, list):
        return []
    tasks: list[StoredTask] = []
    seen_ids: set[str] = set()
    for item in value:
        task = _normalize_task_entry(item)
        if task is None:
            continue
        if task.id in seen_ids:
            task.id = StoredTask(title=task.title).id
        seen_ids.add(task.id)
        tasks.append(task)
    return tasks


@dataclass
class TaskConfig:
    message: str = DEFAULT_MESSAGE
    x: int | None = None
    y: int | None = None
    font_family: str = DEFAULT_FONT_FAMILY
    font_size: int = DEFAULT_FONT_SIZE
    text_color: str = DEFAULT_TEXT_COLOR
    outline_color: str = DEFAULT_OUTLINE_COLOR
    transparency: float = DEFAULT_TRANSPARENCY
    language: str = DEFAULT_LANGUAGE
    autostart: bool = False
    schedule: list[dict[str, str]] = field(default_factory=list)
    tasks: list[StoredTask] = field(default_factory=list)
    current_task_id: str | None = None

    @classmethod
    def load(cls, path: Path) -> "TaskConfig":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        message = str(data.get("message") or "").strip() or DEFAULT_MESSAGE
        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, int):
            x = None
        if not isinstance(y, int):
            y = None
        font_family = (
            str(data.get("font_family") or DEFAULT_FONT_FAMILY).strip()
            or DEFAULT_FONT_FAMILY
        )
        font_size = ensure_font_size(data.get("font_size"), DEFAULT_FONT_SIZE)
        text_color = ensure_color(data.get("text_color"), DEFAULT_TEXT_COLOR)
        outline_color = ensure_color(
            data.get("outline_color"), DEFAULT_OUTLINE_COLOR
        )
        transparency = ensure_transparency(
            data.get("transparency"), DEFAULT_TRANSPARENCY
        )
        language = ensure_language(data.get("language"), DEFAULT_LANGUAGE)
        autostart = data.get("autostart")
        if not isinstance(autostart, bool):
            autostart = False
        schedule = ensure_schedule(data.get("schedule"))
        tasks = ensure_tasks(data.get("tasks"))
        current_task_id = data.get("current_task_id")
        if not isinstance(current_task_id, str) or not current_task_id.strip():
            current_task_id = None
        if current_task_id not in {task.id for task in tasks}:
            current_task_id = tasks[0].id if tasks else None
        if not tasks:
            legacy_message = strip_pause_prefix(message).strip()
            if legacy_message and legacy_message not in {DEFAULT_MESSAGE, *NO_TASK_VALUES}:
                migrated_task = StoredTask(
                    title=legacy_message,
                    text_color=text_color,
                )
                tasks = [migrated_task]
                current_task_id = migrated_task.id
        return cls(
            message=message,
            x=x,
            y=y,
            font_family=font_family,
            font_size=font_size,
            text_color=text_color,
            outline_color=outline_color,
            transparency=transparency,
            language=language,
            autostart=autostart,
            schedule=schedule,
            tasks=tasks,
            current_task_id=current_task_id,
        )

    def save(self, path: Path) -> None:
        data = asdict(self)
        data["tasks"] = [
            {
                "id": task.id,
                "title": task.title,
                "estimate_minutes": task.estimate_minutes,
                "active": task.active,
                "paused": task.paused,
                "start_time": task.start_time.isoformat() if task.start_time else None,
                "elapsed_before_pause_seconds": task.elapsed_before_pause_seconds,
                "text_color": task.text_color,
            }
            for task in self.tasks
        ]
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
