from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable, Optional

try:  # pragma: no cover - import guard to allow headless tests
    from PyQt6 import QtCore, QtGui, QtWidgets
except Exception as exc:  # pragma: no cover - handled at runtime
    from types import SimpleNamespace

    QtCore = SimpleNamespace(QObject=object, QTimer=object, Qt=None)  # type: ignore[assignment]
    QtGui = QtWidgets = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:  # pragma: no cover
    _IMPORT_ERROR = None

from .config import ensure_schedule

Translator = Callable[[str, object], str] | Callable[[str], str]


@dataclass
class ScheduleEntry:
    label: str
    start: str
    end: str


if QtWidgets is None:
    # Placeholders for test environments without Qt
    class ScheduleOverlay:  # pragma: no cover - not used without Qt
        ...

    class ScheduleManagerDialog:  # pragma: no cover - not used without Qt
        ...
else:
    class ScheduleOverlay(QtWidgets.QDialog):
        def __init__(
            self,
            translator: Translator,
            font_family: str,
            base_size: int,
            parent: QtWidgets.QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self.translator = translator
            self.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint)
            self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
            self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setModal(False)
            self.setStyleSheet("background-color: black; color: white;")

            time_size = max(72, base_size * 3)
            focus_size = max(36, base_size * 2)
            schedule_size = max(22, base_size + 6)

            self._time_label = QtWidgets.QLabel()
            self._time_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._time_label.setFont(
                QtGui.QFont(font_family, time_size, QtGui.QFont.Weight.Bold)
            )

            self._current_label = QtWidgets.QLabel()
            self._current_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._current_label.setWordWrap(True)
            self._current_label.setFont(
                QtGui.QFont(font_family, focus_size, QtGui.QFont.Weight.Bold)
            )

            self._schedule_label = QtWidgets.QLabel()
            self._schedule_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._schedule_label.setWordWrap(True)
            self._schedule_label.setFont(QtGui.QFont(font_family, schedule_size))

            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(60, 60, 60, 60)
            layout.addWidget(self._time_label)
            layout.addSpacing(20)
            layout.addWidget(self._current_label)
            layout.addSpacing(20)
            layout.addWidget(self._schedule_label, 1)
            self.setLayout(layout)

        def update_content(
            self,
            now: datetime,
            current: ScheduleEntry,
            next_entry: ScheduleEntry | None,
            entries: list[ScheduleEntry],
            active_index: int,
        ) -> None:
            self._time_label.setText(now.strftime("%H:%M:%S"))
            current_text = self.translator(
                "overlay_current",
                label=current.label,
                start=current.start,
                end=current.end,
            )
            remaining = self._format_remaining(now, current.end)
            remaining_line = self.translator("overlay_remaining", time=remaining)
            self._current_label.setText(f"{current_text}\n{remaining_line}")

            lines = [self.translator("overlay_schedule_title")]
            for idx, entry in enumerate(entries):
                prefix = "> " if idx == active_index else "  "
                lines.append(f"{prefix}{entry.start} - {entry.end}  {entry.label}")
            if next_entry:
                lines.append(
                    self.translator(
                        "overlay_next",
                        label=next_entry.label,
                        start=next_entry.start,
                        end=next_entry.end,
                    )
                )
            self._schedule_label.setText("\n".join(lines))
            self.showFullScreen()
            self.raise_()
            self.activateWindow()

        def _format_remaining(self, now: datetime, end: str) -> str:
            try:
                end_time = datetime.strptime(end, "%H:%M").time()
            except ValueError:
                return "00:00"
            end_dt = now.replace(
                hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0
            )
            if end_dt < now:
                end_dt += timedelta(days=1)
            total_seconds = max(0, int((end_dt - now).total_seconds()))
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours:
                return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            return f"{minutes:02d}:{seconds:02d}"


if QtWidgets is not None:
    class ScheduleManagerDialog(QtWidgets.QDialog):
        def __init__(
            self,
            translator: Translator,
            entries: list[ScheduleEntry],
            parent: QtWidgets.QWidget | None = None,
        ) -> None:
            super().__init__(parent)
            self.translator = translator
            self.entries = entries
            self.setWindowTitle(self.translator("schedule_title"))
            self.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
            self.setModal(True)
            self.setLayout(QtWidgets.QVBoxLayout())

            self._list = QtWidgets.QListWidget(self)
            self.layout().addWidget(self._list)

            button_row = QtWidgets.QHBoxLayout()
            self._add_button = QtWidgets.QPushButton(self.translator("schedule_add"))
            self._edit_button = QtWidgets.QPushButton(self.translator("schedule_edit"))
            self._delete_button = QtWidgets.QPushButton(self.translator("schedule_delete"))
            for btn in (self._add_button, self._edit_button, self._delete_button):
                button_row.addWidget(btn)
            self.layout().addLayout(button_row)

            self._add_button.clicked.connect(lambda: self._open_editor(None))
            self._edit_button.clicked.connect(self._edit_selected)
            self._delete_button.clicked.connect(self._delete_selected)

            self._refresh_list()

        def _refresh_list(self) -> None:
            self._list.clear()
            for entry in self.entries:
                self._list.addItem(f"{entry.start} - {entry.end}  {entry.label}")

        def _edit_selected(self) -> None:
            row = self._list.currentRow()
            if row < 0:
                QtWidgets.QMessageBox.information(
                    self,
                    self.translator("notice_title"),
                    self.translator("schedule_no_selection"),
                )
                return
            self._open_editor(row)

        def _delete_selected(self) -> None:
            row = self._list.currentRow()
            if row < 0:
                QtWidgets.QMessageBox.information(
                    self,
                    self.translator("notice_title"),
                    self.translator("schedule_no_selection"),
                )
                return
            confirm = QtWidgets.QMessageBox.question(
                self,
                self.translator("notice_title"),
                self.translator("confirm_delete_schedule"),
            )
            if confirm != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            self.entries.pop(row)
            self._refresh_list()

        def _open_editor(self, index: Optional[int]) -> None:
            if index is not None and (index < 0 or index >= len(self.entries)):
                return
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle(self.translator("schedule_title"))
            form = QtWidgets.QFormLayout(dialog)
            current = (
                self.entries[index]
                if index is not None
                else ScheduleEntry(self.translator("schedule_default_label"), "12:00", "13:00")
            )
            label_edit = QtWidgets.QLineEdit(current.label)
            start_edit = QtWidgets.QLineEdit(current.start)
            end_edit = QtWidgets.QLineEdit(current.end)
            form.addRow(self.translator("schedule_label"), label_edit)
            form.addRow(self.translator("schedule_start"), start_edit)
            form.addRow(self.translator("schedule_end"), end_edit)

            buttons = QtWidgets.QDialogButtonBox(
                QtWidgets.QDialogButtonBox.StandardButton.Save
                | QtWidgets.QDialogButtonBox.StandardButton.Cancel
            )
            form.addRow(buttons)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)

            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return
            label = label_edit.text().strip() or self.translator("schedule_default_label")
            start = self._normalize_time(start_edit.text())
            end = self._normalize_time(end_edit.text())
            if not start or not end:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.translator("notice_title"),
                    self.translator("error_invalid_time"),
                )
                return
            start_minutes = self._to_minutes(start)
            end_minutes = self._to_minutes(end)
            if start_minutes is None or end_minutes is None or start_minutes >= end_minutes:
                QtWidgets.QMessageBox.critical(
                    self,
                    self.translator("notice_title"),
                    self.translator("error_time_order"),
                )
                return
            entry = ScheduleEntry(label=label, start=start, end=end)
            if index is None:
                self.entries.append(entry)
            else:
                self.entries[index] = entry
            self.entries.sort(key=lambda e: e.start)
            self._refresh_list()

        def _normalize_time(self, value: str) -> str | None:
            try:
                dt = datetime.strptime(value.strip(), "%H:%M")
                return dt.strftime("%H:%M")
            except ValueError:
                return None

        def _to_minutes(self, value: str) -> int | None:
            try:
                parts = datetime.strptime(value, "%H:%M")
                return parts.hour * 60 + parts.minute
            except ValueError:
                return None


class ScheduleController(QtCore.QObject):
    def __init__(
        self,
        translator: Translator,
        font_family: str,
        base_size: int,
        schedule: Iterable[dict[str, str]],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        if QtWidgets is None:
            raise SystemExit(
                "PyQt6 is required for schedule features. Install with: pip install PyQt6"
            ) from _IMPORT_ERROR
        super().__init__(parent)
        self.translator = translator
        self.font_family = font_family
        self.base_size = base_size
        self.entries = [ScheduleEntry(**entry) for entry in ensure_schedule(list(schedule))]
        self._last_lock_marker: tuple[str, str, str] | None = None
        self._last_lock_timestamp: datetime | None = None
        self._last_pre_notice_marker: tuple[str, str, str] | None = None
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._overlay: ScheduleOverlay | None = None

    def set_font(self, family: str, size: int) -> None:
        self.font_family = family
        self.base_size = size
        if self._overlay:
            self._overlay.close()
            self._overlay = None

    def set_schedule(self, entries: Iterable[dict[str, str]]) -> list[ScheduleEntry]:
        sanitized = ensure_schedule(list(entries))
        self.entries = [ScheduleEntry(**entry) for entry in sanitized]
        self._last_pre_notice_marker = None
        if not self.entries:
            self.hide_overlay()
        return self.entries

    def open_manager(self, parent: QtWidgets.QWidget | None = None) -> list[ScheduleEntry]:
        dialog = ScheduleManagerDialog(self.translator, list(self.entries), parent)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            # The dialog does not use accept/reject, so we keep current entries.
            pass
        self.entries = dialog.entries
        if not self.entries:
            self.hide_overlay()
        return self.entries

    def start(self) -> None:
        if self.entries:
            self._timer.start(1000)

    def stop(self) -> None:
        self._timer.stop()
        self.hide_overlay()
        self._last_lock_marker = None
        self._last_lock_timestamp = None
        self._last_pre_notice_marker = None

    def hide_overlay(self) -> None:
        if self._overlay:
            self._overlay.hide()
        self._overlay = None

    def _tick(self) -> None:
        if not self.entries:
            return
        now = datetime.now()
        minutes = now.hour * 60 + now.minute
        today = now.date().isoformat()
        lock_marker: tuple[str, str, str] | None = None
        overlay_marker: tuple[str, str] | None = None
        pre_notice_marker: tuple[str, str, str] | None = None
        for index, entry in enumerate(self.entries):
            start_minutes = self._to_minutes(entry.start)
            end_minutes = self._to_minutes(entry.end)
            if start_minutes is None or end_minutes is None:
                continue
            if start_minutes <= minutes < end_minutes:
                lock_marker = (today, entry.start, entry.end)
                overlay_marker = (entry.start, entry.end)
                next_entry = self.entries[index + 1] if index + 1 < len(self.entries) else None
                self._show_overlay(now, entry, next_entry, index)
                if self._should_lock_again(lock_marker, now):
                    self._lock_workstation()
                    self._last_lock_marker = lock_marker
                    self._last_lock_timestamp = now
                break
            if minutes < start_minutes:
                pre_notice_marker = (today, entry.start, entry.end)
                if start_minutes - minutes <= 30:
                    if self._should_notify_pre_lock(pre_notice_marker):
                        self._notify_pre_lock(entry)
                        self._last_pre_notice_marker = pre_notice_marker
                break
        if overlay_marker is None:
            self.hide_overlay()
        if lock_marker is None:
            self._last_lock_marker = None
            self._last_lock_timestamp = None
        if pre_notice_marker is None:
            self._last_pre_notice_marker = None

    def _show_overlay(
        self, now: datetime, entry: ScheduleEntry, next_entry: ScheduleEntry | None, index: int
    ) -> None:
        overlay = self._overlay or ScheduleOverlay(
            translator=self.translator,
            font_family=self.font_family,
            base_size=self.base_size,
            parent=self.parent(),
        )
        self._overlay = overlay
        overlay.update_content(now, entry, next_entry, self.entries, index)

    def _lock_workstation(self) -> None:
        if not sys.platform.startswith("win"):
            return
        try:
            ctypes.windll.user32.LockWorkStation()
        except Exception:
            QtWidgets.QMessageBox.critical(
                self.parent(),
                self.translator("notice_title"),
                self.translator("error_lock_failed"),
            )

    def _should_lock_again(self, marker: tuple[str, str, str], now: datetime) -> bool:
        if self._last_lock_marker != marker:
            return True
        if self._last_lock_timestamp is None:
            return True
        return now - self._last_lock_timestamp >= timedelta(seconds=15)

    def _should_notify_pre_lock(self, marker: tuple[str, str, str]) -> bool:
        return self._last_pre_notice_marker != marker

    def _notify_pre_lock(self, entry: ScheduleEntry) -> None:
        message = self.translator(
            "schedule_prelock_notice", label=entry.label, start=entry.start, end=entry.end
        )
        title = self.translator("notice_title")
        parent = self.parent()
        tray = getattr(parent, "_tray", None)
        if isinstance(tray, QtWidgets.QSystemTrayIcon):  # type: ignore[unreachable]
            tray.showMessage(title, message, QtWidgets.QSystemTrayIcon.MessageIcon.Information)
            return
        QtWidgets.QMessageBox.information(parent, title, message)

    def _to_minutes(self, value: str) -> int | None:
        try:
            parts = datetime.strptime(value, "%H:%M")
            return parts.hour * 60 + parts.minute
        except ValueError:
            return None
