from __future__ import annotations

import json
from datetime import datetime

from attention.config import TaskConfig
from attention.task_state import StoredTask


def test_task_config_persists_saved_tasks(tmp_path) -> None:
    start_time = datetime(2026, 3, 16, 9, 30, 0)
    task = StoredTask(
        id="task-1",
        title="Write docs",
        estimate_minutes=25,
        active=True,
        paused=False,
        start_time=start_time,
        elapsed_before_pause_seconds=120,
        text_color="#ff3b30",
    )
    path = tmp_path / "config.json"
    config = TaskConfig(tasks=[task], current_task_id=task.id, message=task.title)

    config.save(path)
    loaded = TaskConfig.load(path)

    assert loaded.current_task_id == "task-1"
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].title == "Write docs"
    assert loaded.tasks[0].estimate_minutes == 25
    assert loaded.tasks[0].active is True
    assert loaded.tasks[0].start_time == start_time
    assert loaded.tasks[0].elapsed_before_pause_seconds == 120


def test_task_config_migrates_legacy_message_to_task(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "message": "Legacy task",
                "language": "en",
            }
        ),
        encoding="utf-8",
    )

    loaded = TaskConfig.load(path)

    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].title == "Legacy task"
    assert loaded.current_task_id == loaded.tasks[0].id
