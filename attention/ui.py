from __future__ import annotations

import sys

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

from .config import (
    TaskConfig,
    ensure_color,
    ensure_font_size,
    ensure_language,
    ensure_transparency,
)
from .constants import (
    ACTIVE_TEXT_COLOR,
    CONFIG_FILE,
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE,
    DEFAULT_LANGUAGE,
    DEFAULT_MESSAGE,
    DEFAULT_OUTLINE_COLOR,
    DEFAULT_TEXT_COLOR,
    DEFAULT_TRANSPARENCY,
    PAUSE_TEXT_COLOR,
    STOP_TEXT_COLOR,
)
from .history import TaskRecord, append_record, load_history
from .i18n import NO_TASK_VALUES, translate


@dataclass
class TaskState:
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
        if not self.message.startswith(prefix):
            self.message = f"{prefix} {self.message}"

    def resume(self) -> None:
        if not self.active or not self.paused:
            return
        self.paused = False
        self.text_color = ACTIVE_TEXT_COLOR
        prefix = translate(self.language, "pause_prefix")
        if self.message.startswith(prefix):
            self.message = self.message[len(prefix) :].lstrip()
        self.start_time = datetime.now()

    def stop(self) -> None:
        self.active = False
        self.paused = False
        self.start_time = None
        self.elapsed_before_pause = timedelta()
        self.message = translate(self.language, "no_task")
        self.text_color = STOP_TEXT_COLOR
        self.estimate_minutes = None

    def elapsed_seconds(self) -> int:
        elapsed = self.elapsed_before_pause
        if self.active and not self.paused and self.start_time:
            elapsed += datetime.now() - self.start_time
        return max(0, int(elapsed.total_seconds()))

    def time_text(self) -> str:
        if not self.active and self.message in NO_TASK_VALUES:
            return ""
        if not self.start_time:
            return translate(self.language, "time_started")
        elapsed = self.elapsed_seconds()
        if elapsed < 60:
            return translate(self.language, "time_elapsed_less_minute")
        minutes = elapsed // 60
        if minutes < 60:
            return translate(self.language, "time_elapsed_minutes", minutes=minutes)
        hours, rem = divmod(minutes, 60)
        if rem == 0:
            return translate(self.language, "time_elapsed_hours_only", hours=hours)
        return translate(self.language, "time_elapsed_hours", hours=hours, minutes=rem)

    def estimate_text(self) -> tuple[str, str]:
        if not self.estimate_minutes or not self.start_time:
            return "", STOP_TEXT_COLOR
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
            text = translate(self.language, "estimate_label", minutes=self.estimate_minutes)
        else:
            over_min = (elapsed - est_seconds + 59) // 60
            text = translate(self.language, "estimate_over_label", minutes=over_min)
        return text, color


class TaskApp(QtWidgetBase):
    def __init__(self, config: TaskConfig, config_path: Path = CONFIG_FILE) -> None:
        if QtWidgets is None:
            raise SystemExit(
                "PyQt6 is required to run the UI. Install with: pip install PyQt6"
            ) from _IMPORT_ERROR
        self.qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
        super().__init__()
        self.config_path = config_path
        language = ensure_language(config.language, DEFAULT_LANGUAGE)
        self.state = TaskState(
            message=config.message or DEFAULT_MESSAGE,
            language=language,
            text_color=ensure_color(config.text_color, DEFAULT_TEXT_COLOR),
            outline_color=ensure_color(config.outline_color, DEFAULT_OUTLINE_COLOR),
            transparency=ensure_transparency(config.transparency, DEFAULT_TRANSPARENCY),
            font_family=config.font_family or DEFAULT_FONT_FAMILY,
            font_size=ensure_font_size(config.font_size, DEFAULT_FONT_SIZE),
        )
        self.config = config
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

        self._restore_geometry()
        self._refresh_labels()

    # Translation helper
    def tr(self, key: str, **kwargs: object) -> str:
        return translate(self.state.language, key, **kwargs)

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
        palette = self._message_label.palette()
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(self.state.text_color))
        self._message_label.setPalette(palette)
        time_palette = self._time_label.palette()
        time_palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#ffffff"))
        self._time_label.setPalette(time_palette)

    def _refresh_labels(self) -> None:
        self._message_label.setText(self.state.message)
        self._time_label.setText(self.state.time_text())
        est_text, est_color = self.state.estimate_text()
        self._estimate_label.setText(est_text)
        est_palette = self._estimate_label.palette()
        est_palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(est_color))
        self._estimate_label.setPalette(est_palette)
        self.adjustSize()

    # Context menu and tray
    def _build_tray_icon(self) -> QtWidgets.QSystemTrayIcon:
        tray = QtWidgets.QSystemTrayIcon(self)
        pixmap = QtGui.QPixmap(64, 64)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setBrush(QtGui.QColor("#ff3b30"))
        painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.white, 2))
        painter.drawEllipse(6, 6, 52, 52)
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "!\n!")
        painter.end()
        tray.setIcon(QtGui.QIcon(pixmap))
        tray.setToolTip(self.state.message)
        tray.activated.connect(self._handle_tray_activated)
        tray.setContextMenu(self._build_menu())
        return tray

    def _handle_tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self.setVisible(not self.isVisible())

    def _build_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        start_action = menu.addAction(self.tr("menu_start"))
        start_action.triggered.connect(self.start_task)
        pause_label = self.tr("menu_resume") if self.state.paused else self.tr("menu_pause")
        pause_action = menu.addAction(pause_label)
        pause_action.triggered.connect(self.toggle_pause)
        stop_action = menu.addAction(self.tr("menu_stop"))
        stop_action.triggered.connect(self.stop_task)
        menu.addSeparator()
        history_action = menu.addAction(self.tr("menu_history"))
        history_action.triggered.connect(self.show_history)
        menu.addSeparator()
        quit_action = menu.addAction(self.tr("tray_quit"))
        quit_action.triggered.connect(QtWidgets.QApplication.quit)
        return menu

    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        menu = self._build_menu()
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

    # Actions
    def start_task(self) -> None:
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            self.tr("prompt_start_title"),
            self.tr("prompt_start_message"),
            text=self.state.message if self.state.message not in NO_TASK_VALUES else "",
        )
        if not ok:
            return
        text = text.strip()
        if not text:
            QtWidgets.QMessageBox.warning(
                self, self.tr("notice_title"), self.tr("error_empty")
            )
            return
        est, ok_est = QtWidgets.QInputDialog.getInt(
            self,
            self.tr("prompt_estimate_title"),
            self.tr("prompt_estimate_message"),
            value=self.state.estimate_minutes or 0,
            min=0,
            max=24 * 60,
        )
        estimate = est if ok_est and est > 0 else None
        self.state.start(text, estimate)
        self.config.message = text
        self.config.text_color = self.state.text_color
        self._persist_config()
        append_record(TaskRecord.create("start", text))
        self._refresh_labels()

    def toggle_pause(self) -> None:
        if not self.state.active:
            return
        if self.state.paused:
            self.state.resume()
            append_record(TaskRecord.create("resume", self.state.message))
        else:
            self.state.pause()
            append_record(TaskRecord.create("pause", self.state.message))
        self._persist_config()
        self._refresh_labels()

    def stop_task(self) -> None:
        if not self.state.active and self.state.message in NO_TASK_VALUES:
            return
        append_record(TaskRecord.create("stop", self.state.message))
        self.state.stop()
        self.config.message = self.state.message
        self.config.text_color = self.state.text_color
        self._persist_config()
        self._refresh_labels()

    def _prompt_edit_message(self) -> None:
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            self.tr("prompt_edit_title"),
            self.tr("prompt_edit_message"),
            text=self.state.message,
        )
        if not ok:
            return
        new_text = text.strip()
        if not new_text:
            QtWidgets.QMessageBox.warning(
                self, self.tr("notice_title"), self.tr("error_empty")
            )
            return
        if self.state.paused:
            prefix = translate(self.state.language, "pause_prefix")
            self.state.message = f"{prefix} {new_text}"
        else:
            self.state.message = new_text
        self.config.message = new_text
        self._persist_config()
        self._refresh_labels()

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

    # Config helpers
    def _persist_config(self) -> None:
        try:
            self.config.language = self.state.language
            self.config.text_color = self.state.text_color
            self.config.outline_color = self.state.outline_color
            self.config.transparency = self.state.transparency
            self.config.font_family = self.state.font_family
            self.config.font_size = self.state.font_size
            self.config.message = self.state.message
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
