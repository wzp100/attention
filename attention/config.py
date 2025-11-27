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
from .i18n import SUPPORTED_LANGUAGES


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
    schedule: list[dict[str, str]] = field(default_factory=list)

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
        schedule = ensure_schedule(data.get("schedule"))
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
            schedule=schedule,
        )

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
