from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from .constants import HISTORY_FILE

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


@dataclass
class TaskRecord:
    timestamp: str
    event: str
    title: str

    @classmethod
    def create(cls, event: str, title: str) -> "TaskRecord":
        return cls(datetime.now().strftime(ISO_FORMAT), event, title)


def load_history(path: Path = HISTORY_FILE) -> dict[str, List[TaskRecord]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    history: dict[str, List[TaskRecord]] = {}
    for date_key, records in raw.items():
        if not isinstance(records, list):
            continue
        parsed: List[TaskRecord] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            timestamp = item.get("timestamp")
            event = item.get("event")
            title = item.get("title", "")
            if isinstance(timestamp, str) and isinstance(event, str):
                parsed.append(TaskRecord(timestamp=timestamp, event=event, title=title))
        if parsed:
            history[date_key] = parsed
    return history


def save_history(history: dict[str, List[TaskRecord]], path: Path = HISTORY_FILE) -> None:
    serializable = {
        date: [asdict(record) for record in records] for date, records in history.items()
    }
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")


def append_record(record: TaskRecord, path: Path = HISTORY_FILE) -> None:
    history = load_history(path)
    today = datetime.now().strftime("%Y-%m-%d")
    history.setdefault(today, []).append(record)
    save_history(history, path)
