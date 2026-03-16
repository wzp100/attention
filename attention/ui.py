from __future__ import annotations

import copy
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - import guard to allow headless testing
    from PyQt6 import QtCore, QtGui, QtWidgets
except Exception as exc:  # pragma: no cover - handled at runtime
    QtCore = QtGui = QtWidgets = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:  # pragma: no cover - only evaluated when Qt is available
    _IMPORT_ERROR = None

QtWidgetBase = QtWidgets.QWidget if QtWidgets is not None else object
QtDialogBase = QtWidgets.QDialog if QtWidgets is not None else object

from .config import (
    TaskConfig,
    ensure_color,
    ensure_font_size,
    ensure_language,
    ensure_transparency,
)
from .constants import (
    CONFIG_FILE,
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE,
    DEFAULT_LANGUAGE,
    DEFAULT_MESSAGE,
    DEFAULT_OUTLINE_COLOR,
    DEFAULT_TEXT_COLOR,
    DEFAULT_TRANSPARENCY,
    STOP_TEXT_COLOR,
    TIME_TEXT_COLOR,
)
from .history import TaskRecord, append_record, load_history
from .i18n import NO_TASK_VALUES, translate
from .schedule import ScheduleController
from .settings import SettingsDialog
from .task_state import StoredTask, TaskState


def apply_outline_effect(label: QtWidgets.QLabel, color: str) -> None:
    effect = QtWidgets.QGraphicsDropShadowEffect(label)
    effect.setBlurRadius(4)
    effect.setOffset(0, 0)
    effect.setColor(QtGui.QColor(color))
    label.setGraphicsEffect(effect)


class TaskListDialog(QtDialogBase):
    def __init__(self, app: "TaskApp", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent or app)
        self.app = app
        self.setModal(True)
        self.setWindowTitle(app.tr("todo_title"))

        layout = QtWidgets.QVBoxLayout(self)
        self._list = QtWidgets.QListWidget(self)
        self._list.itemDoubleClicked.connect(self._switch_selected_and_close)
        self._list.currentItemChanged.connect(lambda *_args: self._sync_buttons())
        layout.addWidget(self._list)

        self._empty_label = QtWidgets.QLabel(app.tr("todo_empty"), self)
        self._empty_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)

        button_row = QtWidgets.QHBoxLayout()
        self._switch_button = QtWidgets.QPushButton(app.tr("todo_switch"), self)
        self._switch_button.clicked.connect(self._switch_selected)
        button_row.addWidget(self._switch_button)

        self._new_button = QtWidgets.QPushButton(app.tr("todo_add"), self)
        self._new_button.clicked.connect(self._create_task)
        button_row.addWidget(self._new_button)

        self._edit_button = QtWidgets.QPushButton(app.tr("todo_edit"), self)
        self._edit_button.clicked.connect(self._edit_selected)
        button_row.addWidget(self._edit_button)

        self._stop_button = QtWidgets.QPushButton(app.tr("todo_stop"), self)
        self._stop_button.clicked.connect(self._stop_selected)
        button_row.addWidget(self._stop_button)
        layout.addLayout(button_row)

        close_button = QtWidgets.QPushButton(app.tr("history_close"), self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self.resize(520, 360)
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        for task in self.app.config.tasks:
            item = QtWidgets.QListWidgetItem(self.app.format_task_list_item(task))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, task.id)
            if task.id == self.app.config.current_task_id:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self._list.addItem(item)
            if task.id == self.app.config.current_task_id:
                self._list.setCurrentItem(item)
        has_tasks = self._list.count() > 0
        self._list.setVisible(has_tasks)
        self._empty_label.setVisible(not has_tasks)
        if has_tasks and self._list.currentRow() < 0:
            self._list.setCurrentRow(0)
        self._sync_buttons()

    def _selected_task_id(self) -> str | None:
        item = self._list.currentItem()
        if item is None:
            return None
        task_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        return task_id if isinstance(task_id, str) else None

    def _sync_buttons(self) -> None:
        has_selection = self._selected_task_id() is not None
        self._switch_button.setEnabled(has_selection)
        self._edit_button.setEnabled(has_selection)
        self._stop_button.setEnabled(has_selection)

    def _switch_selected(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            return
        self.app.switch_task(task_id)
        self.refresh()

    def _switch_selected_and_close(self) -> None:
        self._switch_selected()
        self.accept()

    def _create_task(self) -> None:
        if self.app.start_task(parent=self):
            self.refresh()

    def _edit_selected(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            return
        self.app.edit_task(task_id, parent=self)
        self.refresh()

    def _stop_selected(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            return
        self.app.stop_task(task_id)
        self.refresh()


class TaskApp(QtWidgetBase):
    def __init__(self, config: TaskConfig, config_path: Path = CONFIG_FILE) -> None:
        if QtWidgets is None:
            raise SystemExit(
                "PyQt6 is required to run the UI. Install with: pip install PyQt6"
            ) from _IMPORT_ERROR
        self.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        super().__init__()
        self._app_icon = self._load_app_icon()
        if not self._app_icon.isNull():
            self.qt_app.setWindowIcon(self._app_icon)
            self.setWindowIcon(self._app_icon)
        self.config_path = config_path
        self.config = config
        self._normalize_task_selection()
        language = ensure_language(self.config.language, DEFAULT_LANGUAGE)
        self.state = TaskState(
            message=self.config.message or DEFAULT_MESSAGE,
            language=language,
            text_color=ensure_color(self.config.text_color, DEFAULT_TEXT_COLOR),
            outline_color=ensure_color(self.config.outline_color, DEFAULT_OUTLINE_COLOR),
            transparency=ensure_transparency(self.config.transparency, DEFAULT_TRANSPARENCY),
            font_family=self.config.font_family or DEFAULT_FONT_FAMILY,
            font_size=ensure_font_size(self.config.font_size, DEFAULT_FONT_SIZE),
        )
        if self._current_task() is not None:
            self.state.load_stored_task(self._current_task())
        elif self.state.message in NO_TASK_VALUES:
            self.state.load_stored_task(None)
        self.setWindowTitle(self.tr("app_title"))
        self.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(self.state.transparency)
        self._drag_pos: Optional[QtCore.QPoint] = None

        self._message_label = QtWidgets.QLabel(self.state.message)
        self._time_label = QtWidgets.QLabel("")
        self._estimate_label = QtWidgets.QLabel("")
        for lbl in (self._message_label, self._time_label, self._estimate_label):
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
        self._message_label.setObjectName("messageLabel")
        self._time_label.setObjectName("timeLabel")
        self._estimate_label.setObjectName("estimateLabel")

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(self._message_label)
        layout.addSpacing(4)
        layout.addWidget(self._time_label)
        layout.addSpacing(2)
        layout.addWidget(self._estimate_label)
        self.setLayout(layout)

        self._apply_font()

        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._refresh_labels)
        self._timer.start(1000)

        self._tray = self._build_tray_icon()
        self._tray.show()

        self.schedule_controller = ScheduleController(
            translator=self.tr,
            font_family=self.state.font_family,
            base_size=self.state.font_size,
            schedule=self.config.schedule,
            parent=self,
        )
        self.schedule_controller.start()

        self._restore_geometry()
        self._refresh_ui()

    # Translation helper
    def tr(self, key: str, **kwargs: object) -> str:
        return translate(self.state.language, key, **kwargs)

    def _normalize_task_selection(self) -> None:
        task_ids = {task.id for task in self.config.tasks}
        if self.config.current_task_id in task_ids:
            return
        self.config.current_task_id = self.config.tasks[0].id if self.config.tasks else None

    def _find_task(self, task_id: str | None) -> StoredTask | None:
        if not task_id:
            return None
        for task in self.config.tasks:
            if task.id == task_id:
                return task
        return None

    def _current_task(self) -> StoredTask | None:
        return self._find_task(self.config.current_task_id)

    def _replace_task(self, updated_task: StoredTask) -> None:
        for index, task in enumerate(self.config.tasks):
            if task.id == updated_task.id:
                self.config.tasks[index] = updated_task
                return
        self.config.tasks.append(updated_task)

    def _save_current_task_state(self) -> None:
        current_task = self._current_task()
        if current_task is None:
            return
        self._replace_task(self.state.to_stored_task(current_task.id))

    def _load_current_task_state(self) -> None:
        current_task = self._current_task()
        if current_task is not None:
            self.state.load_stored_task(current_task)
            return
        if (
            self.config.message
            and self.config.message != DEFAULT_MESSAGE
            and self.config.message not in NO_TASK_VALUES
        ):
            self.state.message = self.config.message
            self.state.active = False
            self.state.paused = False
            self.state.start_time = None
            self.state.elapsed_before_pause = timedelta()
            self.state.estimate_minutes = None
            self.state.text_color = ensure_color(self.config.text_color, STOP_TEXT_COLOR)
            return
        self.state.load_stored_task(None)

    def _switch_current_task(self, task_id: str | None) -> None:
        self._save_current_task_state()
        self.config.current_task_id = task_id
        self._load_current_task_state()

    def format_task_list_item(self, task: StoredTask) -> str:
        if task.paused:
            status = self.tr("todo_status_paused")
        elif task.active:
            status = self.tr("todo_status_running")
        else:
            status = self.tr("todo_status_saved")
        current = self.tr("todo_current") if task.id == self.config.current_task_id else ""
        suffix = f" [{current}]" if current else ""
        return f"{task.title} · {status}{suffix}"

    def _refresh_ui(self) -> None:
        self._refresh_labels()
        self._rebuild_tray_menu()

    # Geometry persistence
    def _restore_geometry(self) -> None:
        if self.config.x is not None and self.config.y is not None:
            self.move(self.config.x, self.config.y)
        self.adjustSize()
        if not self.isVisible():
            self.show()

    def _persist_geometry(self) -> None:
        self.config.x = self.x()
        self.config.y = self.y()
        self._persist_config()

    # Visual helpers
    def _apply_font(self) -> None:
        font = QtGui.QFont(self.state.font_family, self.state.font_size)
        bold_font = QtGui.QFont(font)
        bold_font.setBold(True)
        small_font = QtGui.QFont(font)
        small_font.setPointSize(max(8, font.pointSize() - 4))
        self._message_label.setFont(bold_font)
        self._time_label.setFont(small_font)
        self._estimate_label.setFont(small_font)

        message_palette = self._message_label.palette()
        message_palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(self.state.text_color))
        self._message_label.setPalette(message_palette)
        time_palette = self._time_label.palette()
        time_palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(TIME_TEXT_COLOR))
        self._time_label.setPalette(time_palette)

        apply_outline_effect(self._message_label, self.state.outline_color)
        apply_outline_effect(self._time_label, self.state.outline_color)
        apply_outline_effect(self._estimate_label, self.state.outline_color)

    def _should_autostart(self) -> bool:
        if self._current_task() is not None:
            return False
        message = self.state.message.strip()
        if not message:
            return False
        if message == DEFAULT_MESSAGE:
            return False
        if message in NO_TASK_VALUES:
            return False
        return True

    def _autostart_if_needed(self) -> None:
        if self.state.active or self.state.start_time is not None:
            return
        if not self._should_autostart():
            return
        self.state.start(self.state.message, self.state.estimate_minutes)
        new_task = self.state.to_stored_task(StoredTask(title=self.state.task_name()).id)
        self.config.tasks = [task for task in self.config.tasks if task.id != new_task.id]
        self.config.tasks.append(new_task)
        self.config.current_task_id = new_task.id
        self.config.message = self.state.message
        self.config.text_color = self.state.text_color

    def _refresh_labels(self) -> None:
        self._autostart_if_needed()
        self._message_label.setText(self.state.message)
        message_palette = self._message_label.palette()
        message_palette.setColor(
            QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(self.state.text_color)
        )
        self._message_label.setPalette(message_palette)
        self._time_label.setText(self.state.time_text())
        est_text, est_color = self.state.estimate_text()
        self._estimate_label.setText(est_text)
        est_palette = self._estimate_label.palette()
        est_palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(est_color))
        self._estimate_label.setPalette(est_palette)
        self.adjustSize()
        self._tray.setToolTip(self.state.message)

    # Context menu and tray
    def _build_tray_icon(self) -> QtWidgets.QSystemTrayIcon:
        tray = QtWidgets.QSystemTrayIcon(self)
        tray.setIcon(self._app_icon)
        tray.setToolTip(self.state.message)
        tray.activated.connect(self._handle_tray_activated)
        tray.setContextMenu(self._build_tray_menu())
        return tray

    def _rebuild_tray_menu(self) -> None:
        self._tray.setContextMenu(self._build_tray_menu())

    def _toggle_window_visibility(self) -> None:
        self.setVisible(not self.isVisible())
        self._rebuild_tray_menu()

    def _load_app_icon(self) -> QtGui.QIcon:
        icon_path = Path(__file__).resolve().parent.parent / "icon.png"
        return QtGui.QIcon(str(icon_path))

    def _autostart_supported(self) -> bool:
        return sys.platform.startswith("win")

    def _startup_folder(self) -> Path | None:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup"

    def _autostart_script_path(self) -> Path | None:
        startup_folder = self._startup_folder()
        if startup_folder is None:
            return None
        return startup_folder / "attention_autostart.bat"

    def _is_autostart_enabled(self) -> bool:
        if not self._autostart_supported():
            return False
        script_path = self._autostart_script_path()
        return script_path is not None and script_path.exists()

    def _resolve_python_executable(self) -> Path:
        python_exe = Path(sys.executable)
        if python_exe.name.lower() == "python.exe":
            pythonw_exe = python_exe.with_name("pythonw.exe")
            if pythonw_exe.exists():
                return pythonw_exe
        return python_exe

    def _resolve_autostart_command_parts(self) -> list[str] | None:
        if getattr(sys, "frozen", False):
            return [str(Path(sys.executable))]
        script_path = Path(sys.argv[0]).resolve()
        if not script_path.exists() or script_path.is_dir():
            fallback = Path(__file__).resolve().parent.parent / "floating_task.py"
            if fallback.exists():
                script_path = fallback
            else:
                return None
        python_exe = self._resolve_python_executable()
        return [str(python_exe), str(script_path)]

    def _build_autostart_command(self) -> str | None:
        parts = self._resolve_autostart_command_parts()
        if not parts:
            return None
        parts.extend(["--config", str(self.config_path.resolve())])
        return subprocess.list2cmdline(parts)

    def _set_autostart(self, enabled: bool) -> bool:
        if not self._autostart_supported():
            return False
        script_path = self._autostart_script_path()
        if script_path is None:
            return False
        try:
            if enabled:
                command = self._build_autostart_command()
                if not command:
                    raise RuntimeError("Unable to determine launch command.")
                script_path.parent.mkdir(parents=True, exist_ok=True)
                script_path.write_text(
                    "@echo off\n"
                    f"start \"\" {command}\n",
                    encoding="utf-8",
                )
            elif script_path.exists():
                script_path.unlink()
            return True
        except (OSError, RuntimeError) as exc:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("notice_title"),
                self.tr("error_autostart", error=str(exc)),
            )
            return False

    def _handle_tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_window_visibility()

    def _build_task_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        new_action = menu.addAction(self.tr("menu_new"))
        new_action.triggered.connect(self.start_task)
        has_task = self._current_task() is not None
        edit_action = menu.addAction(self.tr("menu_edit"))
        edit_action.triggered.connect(self._prompt_edit_message)
        edit_action.setEnabled(has_task)
        tasks_action = menu.addAction(self.tr("menu_tasks"))
        tasks_action.triggered.connect(self.show_task_list)
        pause_label = self.tr("menu_resume") if self.state.paused else self.tr("menu_pause")
        pause_action = menu.addAction(pause_label)
        pause_action.triggered.connect(self.toggle_pause)
        pause_action.setEnabled(self.state.active)
        stop_action = menu.addAction(self.tr("menu_stop"))
        stop_action.triggered.connect(self.stop_task)
        stop_action.setEnabled(has_task)
        return menu

    def _build_tray_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        toggle_action = menu.addAction(
            self.tr("tray_hide") if self.isVisible() else self.tr("tray_show")
        )
        toggle_action.triggered.connect(self._toggle_window_visibility)
        menu.addSeparator()
        new_action = menu.addAction(self.tr("menu_new"))
        new_action.triggered.connect(self.start_task)
        edit_action = menu.addAction(self.tr("menu_edit"))
        edit_action.triggered.connect(self._prompt_edit_message)
        edit_action.setEnabled(self._current_task() is not None)
        tasks_action = menu.addAction(self.tr("menu_tasks"))
        tasks_action.triggered.connect(self.show_task_list)
        pause_label = self.tr("menu_resume") if self.state.paused else self.tr("menu_pause")
        pause_action = menu.addAction(pause_label)
        pause_action.triggered.connect(self.toggle_pause)
        pause_action.setEnabled(self.state.active)
        stop_action = menu.addAction(self.tr("menu_stop"))
        stop_action.triggered.connect(self.stop_task)
        stop_action.setEnabled(self._current_task() is not None)
        menu.addSeparator()
        settings_action = menu.addAction(self.tr("settings_title"))
        settings_action.triggered.connect(self.open_settings)
        schedule_action = menu.addAction(self.tr("label_schedule_button"))
        schedule_action.triggered.connect(lambda: self._open_schedule_manager(self))
        history_action = menu.addAction(self.tr("menu_history"))
        history_action.triggered.connect(self.show_history)
        autostart_action = menu.addAction(self.tr("tray_autostart"))
        autostart_action.setCheckable(True)
        autostart_action.setChecked(self._is_autostart_enabled())
        autostart_action.triggered.connect(self._toggle_autostart)
        if not self._autostart_supported():
            autostart_action.setEnabled(False)
        menu.addSeparator()
        quit_action = menu.addAction(self.tr("tray_quit"))
        quit_action.triggered.connect(QtWidgets.QApplication.quit)
        return menu

    def _toggle_autostart(self, checked: bool) -> None:
        if not self._set_autostart(checked):
            action = self.sender()
            if isinstance(action, QtGui.QAction):
                action.setChecked(self._is_autostart_enabled())
            return
        self.config.autostart = checked
        self._persist_config()

    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        menu = self._build_task_menu()
        menu.exec(self.mapToGlobal(pos))

    # Events
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self._drag_pos = None
            self._persist_geometry()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._prompt_edit_message()
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        event.ignore()
        self.hide()
        self._rebuild_tray_menu()

    # Actions
    def start_task(self, parent: QtWidgets.QWidget | None = None) -> bool:
        dialog_parent = parent or self
        text, ok = QtWidgets.QInputDialog.getText(
            dialog_parent,
            self.tr("prompt_start_title"),
            self.tr("prompt_start_message"),
            text="",
        )
        if not ok:
            return False
        text = text.strip()
        if not text:
            QtWidgets.QMessageBox.warning(
                dialog_parent, self.tr("notice_title"), self.tr("error_empty")
            )
            return False
        est, ok_est = QtWidgets.QInputDialog.getInt(
            dialog_parent,
            self.tr("prompt_estimate_title"),
            self.tr("prompt_estimate_message"),
            value=0,
            min=0,
            max=24 * 60,
        )
        estimate = est if ok_est and est > 0 else None
        self._save_current_task_state()
        new_task = StoredTask(title=text)
        self.config.tasks.append(new_task)
        self.config.current_task_id = new_task.id
        self.state.start(text, estimate)
        self._save_current_task_state()
        self._persist_config()
        append_record(TaskRecord.create("start", text))
        self._refresh_ui()
        return True

    def toggle_pause(self) -> None:
        if self._current_task() is None or not self.state.active:
            return
        if self.state.paused:
            self.state.resume()
            append_record(TaskRecord.create("resume", self.state.task_name()))
        else:
            self.state.pause()
            append_record(TaskRecord.create("pause", self.state.task_name()))
        self._persist_config()
        self._refresh_ui()

    def switch_task(self, task_id: str) -> None:
        if self._find_task(task_id) is None or task_id == self.config.current_task_id:
            return
        self._switch_current_task(task_id)
        self._persist_config()
        self._refresh_ui()

    def stop_task(self, task_id: str | None = None) -> None:
        target_id = task_id or self.config.current_task_id
        if target_id is None:
            return
        if target_id == self.config.current_task_id:
            self._save_current_task_state()
        task = self._find_task(target_id)
        if task is None:
            return
        append_record(TaskRecord.create("stop", task.title))
        self.config.tasks = [entry for entry in self.config.tasks if entry.id != target_id]
        if target_id == self.config.current_task_id:
            self.config.current_task_id = self.config.tasks[0].id if self.config.tasks else None
            self._load_current_task_state()
        self._persist_config()
        self._refresh_ui()

    def edit_task(
        self,
        task_id: str | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> bool:
        target_id = task_id or self.config.current_task_id
        if target_id is None:
            return False
        if target_id != self.config.current_task_id:
            self.switch_task(target_id)
        if self._current_task() is None:
            return False
        dialog_parent = parent or self

        text, ok = QtWidgets.QInputDialog.getText(
            dialog_parent,
            self.tr("prompt_edit_title"),
            self.tr("prompt_edit_message"),
            text=self.state.task_name(),
        )
        if not ok:
            return False
        new_text = text.strip()
        if not new_text:
            QtWidgets.QMessageBox.warning(
                dialog_parent, self.tr("notice_title"), self.tr("error_empty")
            )
            return False
        if self.state.paused:
            prefix = translate(self.state.language, "pause_prefix")
            self.state.message = f"{prefix} {new_text}"
        else:
            self.state.message = new_text
        self._persist_config()
        self._refresh_ui()
        return True

    def _prompt_edit_message(self) -> None:
        self.edit_task(parent=self)

    def show_task_list(self) -> None:
        dialog = TaskListDialog(self, self)
        dialog.exec()

    def apply_session_text(self, text: str, persist: bool = True) -> None:
        normalized = text.strip()
        if not normalized:
            return
        if not persist:
            self.state.message = normalized
            self._refresh_ui()
            return
        if self._current_task() is None:
            self._save_current_task_state()
            new_task = StoredTask(title=normalized)
            self.config.tasks.append(new_task)
            self.config.current_task_id = new_task.id
            self.state.load_stored_task(new_task)
        if self.state.paused:
            prefix = translate(self.state.language, "pause_prefix")
            self.state.message = f"{prefix} {normalized}"
        else:
            self.state.message = normalized
        self._persist_config()
        self._refresh_ui()

    # History dialog
    def show_history(self) -> None:
        history = load_history()
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self.tr("history_title"))
        layout = QtWidgets.QVBoxLayout(dialog)

        dates = sorted(history.keys(), reverse=True)
        combo = QtWidgets.QComboBox(dialog)
        combo.addItems(dates)
        layout.addWidget(combo)

        table = QtWidgets.QTableWidget(dialog)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(
            [
                self.tr("history_column_time"),
                self.tr("history_column_event"),
                self.tr("history_column_title"),
            ]
        )
        layout.addWidget(table)

        def render_date(date_key: str) -> None:
            records = history.get(date_key, [])
            table.setRowCount(len(records) or 1)
            if not records:
                table.setItem(0, 0, QtWidgets.QTableWidgetItem(""))
                table.setItem(0, 1, QtWidgets.QTableWidgetItem(self.tr("history_empty")))
                table.setItem(0, 2, QtWidgets.QTableWidgetItem(""))
                return
            for row, record in enumerate(records):
                table.setItem(row, 0, QtWidgets.QTableWidgetItem(record.timestamp))
                table.setItem(row, 1, QtWidgets.QTableWidgetItem(record.event))
                table.setItem(row, 2, QtWidgets.QTableWidgetItem(record.title))
            table.resizeColumnsToContents()

        if dates:
            render_date(dates[0])
        combo.currentTextChanged.connect(render_date)

        close_btn = QtWidgets.QPushButton(self.tr("history_close"))
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)

        dialog.resize(480, 360)
        dialog.exec()

    # Settings and schedule
    def open_settings(self) -> None:
        self._save_current_task_state()
        config_copy = copy.deepcopy(self.config)
        dialog = SettingsDialog(config_copy, self.tr, self._open_schedule_manager, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        updated = dialog.apply_changes()
        if not updated:
            return
        self._apply_config(updated)
        self._persist_config()
        self._refresh_ui()

    def _apply_config(self, new_config: TaskConfig) -> None:
        self.config = new_config
        self._normalize_task_selection()
        self.state.language = ensure_language(new_config.language, self.state.language)
        self.state.font_family = new_config.font_family
        self.state.font_size = ensure_font_size(new_config.font_size, self.state.font_size)
        self.state.outline_color = ensure_color(new_config.outline_color, self.state.outline_color)
        self.state.transparency = ensure_transparency(
            new_config.transparency, self.state.transparency
        )
        current_task = self._current_task()
        if current_task is not None:
            current_task.title = new_config.message.strip() or current_task.title
            self._replace_task(current_task)
        self._load_current_task_state()
        if current_task is None:
            self.state.text_color = ensure_color(new_config.text_color, self.state.text_color)
        self.schedule_controller.set_font(self.state.font_family, self.state.font_size)
        sanitized_schedule = self.schedule_controller.set_schedule(new_config.schedule)
        self.config.schedule = [asdict(entry) for entry in sanitized_schedule]
        self.schedule_controller.start()
        self.setWindowOpacity(self.state.transparency)
        self.setWindowTitle(self.tr("app_title"))
        self._apply_font()

    def _open_schedule_manager(self, parent: QtWidgets.QWidget | None = None) -> None:
        entries = self.schedule_controller.open_manager(parent)
        target_config: TaskConfig = self.config
        if isinstance(parent, SettingsDialog):
            target_config = parent.config
        target_config.schedule = [asdict(entry) for entry in entries]
        self.schedule_controller.set_schedule(target_config.schedule)
        if parent is None or not isinstance(parent, SettingsDialog):
            self._persist_config()

    # Config helpers
    def _persist_config(self) -> None:
        try:
            self._save_current_task_state()
            self.config.language = self.state.language
            self.config.text_color = self.state.text_color
            self.config.outline_color = self.state.outline_color
            self.config.transparency = self.state.transparency
            self.config.font_family = self.state.font_family
            self.config.font_size = self.state.font_size
            self.config.message = self.state.message
            self.config.schedule = [asdict(entry) for entry in self.schedule_controller.entries]
            self.config.save(self.config_path)
        except OSError as exc:  # pragma: no cover - fs issues
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("notice_title"),
                self.tr("error_save", error=str(exc)),
            )

    def run(self) -> None:
        self.show()
        self.qt_app.exec()
