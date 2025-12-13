from datetime import datetime, timedelta

import pytest

from attention.ui import TaskState
from attention.i18n import translate


@pytest.fixture
def state() -> TaskState:
    ts = TaskState(language="en")
    ts.message = translate("en", "no_task")
    return ts


def test_start_and_elapsed(state: TaskState) -> None:
    state.start("Write docs", estimate_minutes=30)
    assert state.active
    assert state.text_color != ""
    assert state.time_text().startswith("Elapsed")


def test_pause_and_resume(state: TaskState, monkeypatch: pytest.MonkeyPatch) -> None:
    state.start("Test", estimate_minutes=1)
    fake_now = state.start_time + timedelta(seconds=120)  # type: ignore[operator]
    monkeypatch.setattr(state, "elapsed_seconds", lambda: int((fake_now - state.start_time).total_seconds()))  # type: ignore[arg-type]
    state.pause()
    assert state.paused
    paused_message = state.message
    state.resume()
    assert not state.paused
    assert state.message != paused_message


def test_stop_sets_no_task(state: TaskState) -> None:
    state.start("Test")
    state.stop()
    assert not state.active
    assert translate(state.language, "no_task") in state.message


def test_estimate_color_ranges(state: TaskState, monkeypatch: pytest.MonkeyPatch) -> None:
    state.start("Estimate", estimate_minutes=1)
    monkeypatch.setattr(state, "elapsed_seconds", lambda: 10)
    text, color = state.estimate_text()
    assert "1" in text
    assert color == "#4caf50"
    monkeypatch.setattr(state, "elapsed_seconds", lambda: 61)
    text, color = state.estimate_text()
    assert color in {"#ff9800", "#ff3b30", "#ffeb3b"}
