from __future__ import annotations

try:  # pragma: no cover - allow headless tests
    from PyQt6 import QtWidgets
except Exception as exc:  # pragma: no cover
    from types import SimpleNamespace

    QtWidgets = SimpleNamespace(QDialog=object)  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:  # pragma: no cover
    _IMPORT_ERROR = None

from .config import (
    TaskConfig,
    ensure_color,
    ensure_font_size,
    ensure_language,
    ensure_transparency,
)
from .i18n import SUPPORTED_LANGUAGES


class SettingsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        config: TaskConfig,
        translator,
        schedule_callback,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.translator = translator
        self.schedule_callback = schedule_callback

        self.setWindowTitle(self.translator("settings_title"))
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self._text_edit = QtWidgets.QPlainTextEdit(self.config.message)
        self._font_edit = QtWidgets.QLineEdit(self.config.font_family)
        self._font_size_spin = QtWidgets.QSpinBox()
        self._font_size_spin.setRange(8, 96)
        self._font_size_spin.setValue(self.config.font_size)
        self._text_color_edit = QtWidgets.QLineEdit(self.config.text_color)
        self._outline_color_edit = QtWidgets.QLineEdit(self.config.outline_color)
        self._transparency_spin = QtWidgets.QDoubleSpinBox()
        self._transparency_spin.setRange(0.2, 1.0)
        self._transparency_spin.setSingleStep(0.05)
        self._transparency_spin.setValue(self.config.transparency)
        self._language_combo = QtWidgets.QComboBox()
        for code in SUPPORTED_LANGUAGES:
            self._language_combo.addItem(self.translator(f"language_option_{code}"), code)
        current_index = self._language_combo.findData(self.config.language)
        self._language_combo.setCurrentIndex(max(0, current_index))

        form.addRow(self.translator("label_text"), self._text_edit)
        form.addRow(self.translator("label_font"), self._font_edit)
        form.addRow(self.translator("label_font_size"), self._font_size_spin)
        form.addRow(self.translator("label_text_color"), self._text_color_edit)
        form.addRow(self.translator("label_outline_color"), self._outline_color_edit)
        form.addRow(self.translator("label_transparency"), self._transparency_spin)
        form.addRow(self.translator("label_language"), self._language_combo)

        layout.addLayout(form)

        schedule_btn = QtWidgets.QPushButton(self.translator("label_schedule_button"))
        schedule_btn.clicked.connect(self._open_schedule)
        layout.addWidget(schedule_btn)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _open_schedule(self) -> None:
        self.schedule_callback(self)

    def apply_changes(self) -> TaskConfig | None:
        message = self._text_edit.toPlainText().strip()
        if not message:
            QtWidgets.QMessageBox.critical(
                self, self.translator("notice_title"), self.translator("error_empty")
            )
            return None
        font_family = self._font_edit.text().strip() or self.config.font_family
        font_size = ensure_font_size(self._font_size_spin.value(), self.config.font_size)
        text_color = ensure_color(self._text_color_edit.text().strip(), self.config.text_color)
        outline_color = ensure_color(
            self._outline_color_edit.text().strip(), self.config.outline_color
        )
        transparency = ensure_transparency(
            self._transparency_spin.value(), self.config.transparency
        )
        language = ensure_language(self._language_combo.currentData(), self.config.language)

        self.config.message = message
        self.config.font_family = font_family
        self.config.font_size = font_size
        self.config.text_color = text_color
        self.config.outline_color = outline_color
        self.config.transparency = transparency
        self.config.language = language
        return self.config
