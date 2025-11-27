from __future__ import annotations

import ctypes
import sys
try:
    import winreg  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - non-Windows
    winreg = None  # type: ignore[assignment]
import threading
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, simpledialog

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover - dependency guard
    missing = "pystray pillow"
    raise SystemExit(
        f"Missing dependency ({exc.name}). Install with: pip install {missing}"
    ) from exc

from .config import (
    TaskConfig,
    ensure_color,
    ensure_font_size,
    ensure_language,
    ensure_schedule,
    ensure_transparency,
    is_valid_color,
)
from .constants import (
    ACTIVE_TEXT_COLOR,
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_SIZE,
    DEFAULT_MESSAGE,
    DEFAULT_OUTLINE_COLOR,
    DEFAULT_TEXT_COLOR,
    DEFAULT_TRANSPARENCY,
    DEFAULT_LANGUAGE,
    PAUSE_TEXT_COLOR,
    PADDING,
    STOP_TEXT_COLOR,
    TIME_GAP,
    TIME_TEXT_COLOR,
    TRANSPARENT_COLOR,
    WRAP_LENGTH,
)
from .history import ISO_FORMAT, TaskRecord, append_record, load_history
from .i18n import (
    NO_TASK_VALUES,
    SUPPORTED_LANGUAGES,
    strip_pause_prefix,
    translate,
)


class TaskApp:
    def __init__(self, config: TaskConfig, config_path: Path) -> None:
        self.config = config
        self.config_path = config_path
        self.language = ensure_language(config.language, DEFAULT_LANGUAGE)
        self.message = config.message or DEFAULT_MESSAGE
        self.base_message = strip_pause_prefix(self.message)

        self.text_color = ensure_color(config.text_color, DEFAULT_TEXT_COLOR)
        self.outline_color = ensure_color(
            config.outline_color, DEFAULT_OUTLINE_COLOR
        )
        self.transparency = ensure_transparency(
            config.transparency, DEFAULT_TRANSPARENCY
        )
        self.font_family = config.font_family or DEFAULT_FONT_FAMILY
        self.font_size = ensure_font_size(config.font_size, DEFAULT_FONT_SIZE)
        self.config.language = self.language
        self.config.text_color = self.text_color
        self.config.outline_color = self.outline_color
        self.config.transparency = self.transparency
        self.config.font_family = self.font_family
        self.config.font_size = self.font_size
        self.config.message = self.message

        self.root = tk.Tk()
        self.root.title(self._t("app_title"))
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.transparency)
        self.root.configure(bg=TRANSPARENT_COLOR)
        self.root.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)

        self._drag_start_x = 0
        self._drag_start_y = 0
        self.settings_window: tk.Toplevel | None = None
        self.tray_icon: pystray.Icon | None = None
        self.context_menu: tk.Menu | None = None
        self.context_menu_pause_index: int | None = None
        self.history_window: tk.Toplevel | None = None
        self.history_tree: ttk.Treeview | None = None
        self.history_date_var: tk.StringVar | None = None
        self.history_combobox: ttk.Combobox | None = None
        self.history_close_button: tk.Button | None = None
        self.history_date_label: tk.Label | None = None
        self.schedule = [dict(entry) for entry in config.schedule]
        self.schedule_window: tk.Toplevel | None = None
        self.schedule_listbox: tk.Listbox | None = None
        self.schedule_add_button: tk.Button | None = None
        self.schedule_edit_button: tk.Button | None = None
        self.schedule_delete_button: tk.Button | None = None
        self.schedule_overlay: tk.Toplevel | None = None
        self._schedule_overlay_time_label: tk.Label | None = None
        self._schedule_overlay_current_label: tk.Label | None = None
        self._schedule_overlay_schedule_label: tk.Label | None = None
        self._schedule_overlay_time_font: tkfont.Font | None = None
        self._schedule_overlay_current_font: tkfont.Font | None = None
        self._schedule_overlay_schedule_font: tkfont.Font | None = None
        self._active_schedule_marker: tuple[str, str] | None = None
        self._schedule_check_job: str | None = None
        self._last_schedule_lock: tuple[str, str, str] | None = None
        self._last_schedule_lock_timestamp: datetime | None = None
        self._lock_fail_notified = False
        self.text_font = tkfont.Font(
            family=self.font_family,
            size=self.font_size,
            weight="bold",
        )
        self.time_font = tkfont.Font(
            family=self.font_family,
            size=max(10, self.font_size - 6),
            weight="normal",
        )
        self.small_font = tkfont.Font(
            family=self.font_family,
            size=max(8, self.font_size - 8),
            weight="normal",
        )
        self._estimate_minutes: int | None = None

        self.canvas = tk.Canvas(
            self.root,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_button_press)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_button_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<Button-2>", self._on_right_click)

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.bind("<Escape>", lambda _event: self.hide_window())

        self.task_active = False
        self.paused = False
        self.start_time: datetime | None = None
        self.elapsed_before_pause = timedelta()
        self._time_job: str | None = None
        self._current_time_text = ""

        self._build_context_menu()
        self._redraw_text()
        self._apply_geometry()
        self._time_job = self.root.after(1000, self._update_time_display)
        self._start_schedule_monitor()

    def _t(self, key: str, **kwargs) -> str:
        return translate(self.language, key, **kwargs)

    def _redraw_text(self) -> None:
        self.canvas.delete("all")
        text = self.message or " "
        time_text = self._format_time_text()
        self._current_time_text = time_text
        estimate_text, estimate_color = self._format_estimate_text()

        temp_id = self.canvas.create_text(
            0,
            0,
            text=text,
            font=self.text_font,
            width=WRAP_LENGTH,
            anchor="nw",
            justify="center",
            fill=self.text_color,
        )
        self.canvas.update_idletasks()
        bbox = self.canvas.bbox(temp_id)
        self.canvas.delete(temp_id)

        if bbox:
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        else:
            text_width = 200
            text_height = 50

        time_width = 0
        time_height = 0
        if time_text:
            temp_time_id = self.canvas.create_text(
                0,
                0,
                text=time_text,
                font=self.time_font,
                width=WRAP_LENGTH,
                anchor="nw",
                justify="center",
            )
            time_bbox = self.canvas.bbox(temp_time_id)
            self.canvas.delete(temp_time_id)
            if time_bbox:
                time_width = time_bbox[2] - time_bbox[0]
                time_height = time_bbox[3] - time_bbox[1]

        est_width = 0
        est_height = 0
        if estimate_text:
            temp_est_id = self.canvas.create_text(
                0,
                0,
                text=estimate_text,
                font=self.small_font,
                width=WRAP_LENGTH,
                anchor="nw",
                justify="center",
            )
            est_bbox = self.canvas.bbox(temp_est_id)
            self.canvas.delete(temp_est_id)
            if est_bbox:
                est_width = est_bbox[2] - est_bbox[0]
                est_height = est_bbox[3] - est_bbox[1]

        content_width = max(text_width, time_width, est_width)
        width = max(content_width + PADDING * 2, 200)
        blocks_height = text_height
        if time_text:
            blocks_height += TIME_GAP + time_height
        if estimate_text:
            blocks_height += TIME_GAP + est_height
        height = blocks_height + PADDING * 2
        height = max(height, 60)
        self.canvas.config(width=width, height=height)

        center_x = width // 2
        text_center_y = PADDING + text_height / 2

        self._draw_text_with_outline(
            center_x,
            text_center_y,
            text,
            self.text_font,
            self.text_color,
            self.outline_color,
        )

        next_y = text_center_y + text_height / 2
        if time_text:
            time_center_y = next_y + TIME_GAP + time_height / 2
            self._draw_text_with_outline(
                center_x,
                time_center_y,
                time_text,
                self.time_font,
                TIME_TEXT_COLOR,
                self.outline_color,
            )
            next_y = time_center_y + time_height / 2
        if estimate_text:
            est_center_y = next_y + TIME_GAP + est_height / 2
            self._draw_text_with_outline(
                center_x,
                est_center_y,
                estimate_text,
                self.small_font,
                estimate_color,
                self.outline_color,
            )
        self.root.update_idletasks()

    def _draw_text_with_outline(
        self,
        center_x: float,
        center_y: float,
        text: str,
        font: tkfont.Font,
        fill: str,
        outline: str,
    ) -> None:
        if not text.strip():
            return
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue
                self.canvas.create_text(
                    center_x + dx,
                    center_y + dy,
                    text=text,
                    font=font,
                    fill=outline,
                    justify="center",
                    width=WRAP_LENGTH,
                    anchor="center",
                )

        self.canvas.create_text(
            center_x,
            center_y,
            text=text,
            font=font,
            fill=fill,
            justify="center",
            width=WRAP_LENGTH,
            anchor="center",
        )

    @staticmethod
    def _normalize_time_string(value: str) -> str | None:
        try:
            dt = datetime.strptime(value.strip(), "%H:%M")
            return dt.strftime("%H:%M")
        except ValueError:
            return None

    @staticmethod
    def _time_to_minutes(value: str) -> int | None:
        try:
            dt = datetime.strptime(value, "%H:%M")
            return dt.hour * 60 + dt.minute
        except ValueError:
            return None

    def _apply_geometry(self) -> None:
        self.root.update_idletasks()
        width = self.canvas.winfo_reqwidth()
        height = self.canvas.winfo_reqheight()
        if self.config.x is not None and self.config.y is not None:
            x, y = self.config.x, self.config.y
        else:
            screen_width = self.root.winfo_screenwidth()
            x = (screen_width - width) // 2
            y = 40
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _build_context_menu(self) -> None:
        if self.context_menu:
            self.context_menu.destroy()
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(
            label=self._t("menu_start"), command=self.start_task
        )
        self.context_menu.add_command(
            label=self._current_pause_label(), command=self.pause_task
        )
        self.context_menu_pause_index = self.context_menu.index("end")
        self.context_menu.add_command(
            label=self._t("menu_stop"), command=self.stop_task
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(
            label=self._t("menu_history"), command=self.open_history
        )

    def _persist_config(self) -> None:
        try:
            self.config.save(self.config_path)
        except OSError as err:
            messagebox.showerror(
                self._t("notice_title"),
                self._t("error_save", error=err),
            )

    def _on_button_press(self, event: tk.Event) -> None:
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_mouse_drag(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _on_button_release(self, _event: tk.Event) -> None:
        self.config.x = self.root.winfo_x()
        self.config.y = self.root.winfo_y()
        self._persist_config()

    def _on_double_click(self, _event: tk.Event) -> None:
        initial = self.base_message or self.message
        response = simpledialog.askstring(
            self._t("prompt_edit_title"),
            self._t("prompt_edit_message"),
            initialvalue=initial,
            parent=self.root,
        )
        if response is None:
            return
        new_text = response.strip()
        if not new_text:
            messagebox.showerror(
                self._t("notice_title"),
                self._t("error_empty"),
            )
            return
        if not self.task_active and not self.paused and self.base_message in NO_TASK_VALUES:
            self._activate_task(new_text)
            return
        if self.paused:
            self.base_message = new_text
            paused_message = f"{self._t('pause_prefix')} {self.base_message}"
            self.set_message(paused_message)
        else:
            self.set_message(new_text)
        self._trigger_time_update()

    def _on_right_click(self, event: tk.Event) -> None:
        if not self.context_menu:
            return
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def start_task(self) -> None:
        result = self._prompt_start_with_estimate()
        if result is None:
            return
        task_name, est_minutes = result
        self._activate_task(task_name, estimate_minutes=est_minutes)

    def _prompt_start_with_estimate(self) -> tuple[str, int | None] | None:
        title = self._t("prompt_start_title")
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        frm = tk.Frame(dialog, padx=12, pady=12)
        frm.pack(fill="both", expand=True)
        # Task name
        tk.Label(frm, text=self._t("prompt_start_message")).grid(row=0, column=0, sticky="w")
        task_var = tk.StringVar(value=("" if not self.base_message or self.base_message in NO_TASK_VALUES else self.base_message))
        task_entry = tk.Entry(frm, textvariable=task_var, width=40)
        task_entry.grid(row=1, column=0, sticky="we", pady=(4, 8))
        # Estimate (optional)
        tk.Label(frm, text=self._t("prompt_estimate_message")).grid(row=2, column=0, sticky="w")
        est_var = tk.StringVar(value="")
        est_entry = tk.Entry(frm, textvariable=est_var, width=20)
        est_entry.grid(row=3, column=0, sticky="w", pady=(4, 8))
        # Buttons
        btns = tk.Frame(frm)
        btns.grid(row=4, column=0, sticky="e")
        result: list | None = []

        def on_ok() -> None:
            name = task_var.get().strip()
            if not name:
                messagebox.showerror(self._t("notice_title"), self._t("error_empty"), parent=dialog)
                return
            est_raw = est_var.get().strip()
            minutes: int | None = None
            if est_raw:
                try:
                    v = int(est_raw)
                    if v > 0:
                        minutes = v
                except ValueError:
                    # Invalid input: ignore and treat as optional empty
                    minutes = None
            nonlocal_result[0] = (name, minutes)
            dialog.destroy()

        def on_cancel() -> None:
            nonlocal_result.clear()
            dialog.destroy()

        nonlocal_result: list = [None]  # type: ignore[var-annotated]
        ok_btn = tk.Button(btns, text=self._t("button_save"), width=10, command=on_ok)
        ok_btn.pack(side="left", padx=4)
        cancel_btn = tk.Button(btns, text=self._t("button_cancel"), width=10, command=on_cancel)
        cancel_btn.pack(side="left", padx=4)
        dialog.bind("<Return>", lambda _e: on_ok())
        dialog.bind("<Escape>", lambda _e: on_cancel())
        task_entry.focus_set()
        dialog.wait_window()
        if not nonlocal_result:
            return None
        return nonlocal_result[0]  # type: ignore[return-value]

    def _activate_task(self, task_name: str, record_event: bool = True, estimate_minutes: int | None = None) -> None:
        task_name = task_name.strip()
        if not task_name:
            return
        self.task_active = True
        self.paused = False
        self.start_time = datetime.now()
        self.elapsed_before_pause = timedelta()
        self.base_message = task_name
        self._estimate_minutes = estimate_minutes
        self.text_color = ACTIVE_TEXT_COLOR
        self.config.text_color = self.text_color
        self.set_message(task_name)
        if record_event:
            self._record_event("start", task_name)
        self._update_pause_controls()
        self._trigger_time_update()

    def pause_task(self) -> None:
        if not self.task_active:
            return
        if self.paused:
            if self.start_time:
                self.start_time = datetime.now() - self.elapsed_before_pause
            else:
                self.start_time = datetime.now()
            self.elapsed_before_pause = timedelta()
            self.paused = False
            self.text_color = ACTIVE_TEXT_COLOR
            self.config.text_color = self.text_color
            self.set_message(self.base_message)
            self._record_event("resume", self.base_message or self.message)
            self._update_pause_controls()
            self._trigger_time_update()
            return
        if self.start_time:
            self.elapsed_before_pause = datetime.now() - self.start_time
        self.paused = True
        self.text_color = PAUSE_TEXT_COLOR
        self.config.text_color = self.text_color
        paused_message = f"{self._t('pause_prefix')} {self.base_message}"
        self.set_message(paused_message)
        self._record_event("pause", self.base_message or self.message)
        self._update_pause_controls()
        self._trigger_time_update()

    def stop_task(self) -> None:
        previous_title = self.base_message or self.message
        self.task_active = False
        self.paused = False
        self.start_time = None
        self.elapsed_before_pause = timedelta()
        self.base_message = self._t("no_task")
        self._estimate_minutes = None
        self.text_color = STOP_TEXT_COLOR
        self.config.text_color = self.text_color
        self.set_message(self.base_message)
        self._record_event("stop", previous_title or "")
        self._update_pause_controls()
        self._trigger_time_update()

    def _format_time_text(self) -> str:
        if not self.start_time:
            return ""
        elapsed = self.elapsed_before_pause
        if self.task_active and not self.paused and self.start_time:
            elapsed += datetime.now() - self.start_time
        start_label = self._t("time_started")
        start_str = self.start_time.strftime("%H:%M")
        total_seconds = int(elapsed.total_seconds())
        if total_seconds < 60:
            elapsed_text = self._t("time_elapsed_less_minute")
        else:
            total_minutes = total_seconds // 60
            if total_minutes < 60:
                elapsed_text = self._t(
                    "time_elapsed_minutes", minutes=total_minutes
                )
            else:
                hours = total_minutes // 60
                minutes = total_minutes % 60
                if minutes == 0:
                    elapsed_text = self._t(
                        "time_elapsed_hours_only", hours=hours
                    )
                else:
                    elapsed_text = self._t(
                        "time_elapsed_hours", hours=hours, minutes=minutes
                    )
        spacer = "    "
        return f"{start_label} {start_str}{spacer}{elapsed_text}"

    def _update_time_display(self) -> None:
        if not self.root.winfo_exists():
            return
        self._time_job = None
        new_text = self._format_time_text()
        if new_text != self._current_time_text:
            self._current_time_text = new_text
            self._redraw_text()
        self._time_job = self.root.after(1000, self._update_time_display)

    def _trigger_time_update(self) -> None:
        if self._time_job is not None:
            self.root.after_cancel(self._time_job)
            self._time_job = None
        self._update_time_display()

    def _record_event(self, event: str, title: str) -> None:
        try:
            append_record(TaskRecord.create(event=event, title=title.strip()))
        except OSError as err:
            messagebox.showerror(
                self._t("notice_title"),
                self._t("error_history_save", error=err),
            )
            return
        if self.history_window and tk.Toplevel.winfo_exists(self.history_window):
            self._populate_history_tree()

    def _event_label(self, event: str) -> str:
        mapping = {
            "start": self._t("history_event_start"),
            "pause": self._t("history_event_pause"),
            "resume": self._t("history_event_resume"),
            "stop": self._t("history_event_stop"),
        }
        return mapping.get(event, event.title())

    def _current_pause_label(self) -> str:
        return self._t("menu_resume") if self.paused else self._t("menu_pause")

    def _update_pause_controls(self) -> None:
        if self.context_menu and self.context_menu_pause_index is not None:
            self.context_menu.entryconfig(
                self.context_menu_pause_index, label=self._current_pause_label()
            )
        self._restart_tray()

    def _start_schedule_monitor(self) -> None:
        self._reset_schedule_monitor()

    def _reset_schedule_monitor(self) -> None:
        if self._schedule_check_job is not None:
            try:
                self.root.after_cancel(self._schedule_check_job)
            except Exception:
                pass
            self._schedule_check_job = None
        self._last_schedule_lock = None
        self._last_schedule_lock_timestamp = None
        self._active_schedule_marker = None
        if self.schedule:
            self._schedule_check_job = self.root.after(1000, self._schedule_tick)
        self._destroy_schedule_overlay()

    def _schedule_tick(self) -> None:
        self._schedule_check_job = None
        if not self.schedule:
            return
        now = datetime.now()
        minutes = now.hour * 60 + now.minute
        today = now.date().isoformat()
        lock_marker: tuple[str, str, str] | None = None
        overlay_marker: tuple[str, str] | None = None
        for index, entry in enumerate(self.schedule):
            start_minutes = self._time_to_minutes(entry["start"])
            end_minutes = self._time_to_minutes(entry["end"])
            if start_minutes is None or end_minutes is None:
                continue
            if start_minutes <= minutes < end_minutes:
                lock_marker = (today, entry["start"], entry["end"])
                overlay_marker = (entry["start"], entry["end"])
                next_entry = (
                    self.schedule[index + 1]
                    if index + 1 < len(self.schedule)
                    else None
                )
                self._show_schedule_overlay(now, entry, next_entry, index)
                if self._should_lock_again(lock_marker, now):
                    self._lock_workstation(entry.get("label", ""))
                    self._last_schedule_lock = lock_marker
                    self._last_schedule_lock_timestamp = now
                break
        if overlay_marker is None:
            self._destroy_schedule_overlay()
            self._active_schedule_marker = None
        else:
            self._active_schedule_marker = overlay_marker
        if lock_marker is None:
            self._last_schedule_lock = None
            self._last_schedule_lock_timestamp = None
        if self.schedule:
            self._schedule_check_job = self.root.after(1000, self._schedule_tick)

    # Estimated time helpers
    def _current_elapsed_seconds(self) -> int:
        if not self.start_time:
            return 0
        elapsed = self.elapsed_before_pause
        if self.task_active and not self.paused and self.start_time:
            elapsed += datetime.now() - self.start_time
        return max(0, int(elapsed.total_seconds()))

    def _format_estimate_text(self) -> tuple[str, str]:
        if not self._estimate_minutes or not self.start_time:
            return "", "#ffffff"
        elapsed_sec = self._current_elapsed_seconds()
        est_sec = max(1, self._estimate_minutes * 60)
        ratio = elapsed_sec / est_sec
        # Colors
        GREEN = "#4caf50"
        YELLOW = "#ffeb3b"
        ORANGE = "#ff9800"
        RED = "#ff3b30"
        if ratio <= 0.5:
            color = GREEN
        elif ratio <= 0.8:
            color = YELLOW
        elif ratio <= 1.0:
            color = ORANGE
        else:
            color = RED
        minutes = self._estimate_minutes
        if ratio <= 1.0:
            text = self._t("estimate_label", minutes=minutes)
        else:
            over_min = (elapsed_sec - est_sec + 59) // 60
            text = self._t("estimate_over_label", minutes=over_min)
        return text, color

    def _show_schedule_overlay(
        self,
        now: datetime,
        current_entry: dict[str, str],
        next_entry: dict[str, str] | None,
        current_index: int,
    ) -> None:
        overlay = self._ensure_schedule_overlay()
        if overlay is None:
            return
        try:
            overlay.deiconify()
            overlay.attributes("-topmost", True)
            overlay.lift()
            overlay.focus_force()
        except Exception:
            pass
        remaining = self._calculate_schedule_remaining(now, current_entry)
        remaining_text = self._format_overlay_remaining(remaining)
        label = (
            current_entry.get("label", "").strip()
            or self._t("schedule_default_label")
        )
        current_text = self._t(
            "overlay_current",
            label=label,
            start=current_entry["start"],
            end=current_entry["end"],
        )
        remaining_line = self._t("overlay_remaining", time=remaining_text)
        if self._schedule_overlay_time_label:
            self._schedule_overlay_time_label.config(
                text=now.strftime("%H:%M:%S"),
                font=self._schedule_overlay_time_font,
            )
        if self._schedule_overlay_current_label:
            self._schedule_overlay_current_label.config(
                text=f"{current_text}\n{remaining_line}",
                font=self._schedule_overlay_current_font,
            )
        if self._schedule_overlay_schedule_label:
            schedule_lines = [self._t("overlay_schedule_title")]
            for idx, entry in enumerate(self.schedule):
                entry_label = (
                    entry.get("label", "").strip()
                    or self._t("schedule_default_label")
                )
                line = f"{entry['start']} - {entry['end']}  {entry_label}"
                prefix = "> " if idx == current_index else "  "
                schedule_lines.append(f"{prefix}{line}")
            if next_entry:
                next_label = next_entry.get("label", "").strip() or self._t(
                    "schedule_default_label"
                )
                schedule_lines.append(
                    self._t(
                        "overlay_next",
                        label=next_label,
                        start=next_entry["start"],
                        end=next_entry["end"],
                    )
                )
            self._schedule_overlay_schedule_label.config(
                text="\n".join(schedule_lines),
                font=self._schedule_overlay_schedule_font,
            )
        try:
            overlay.update_idletasks()
        except Exception:
            pass

    def _ensure_schedule_overlay(self) -> tk.Toplevel | None:
        if self.schedule_overlay and tk.Toplevel.winfo_exists(self.schedule_overlay):
            return self.schedule_overlay
        try:
            overlay = tk.Toplevel(self.root)
        except Exception:
            return None
        overlay.withdraw()
        overlay.overrideredirect(True)
        overlay.configure(bg="black", cursor="none")
        overlay.protocol("WM_DELETE_WINDOW", lambda: None)
        try:
            overlay.attributes("-fullscreen", True)
        except Exception:
            overlay.attributes("-topmost", True)
            try:
                overlay.state("zoomed")
            except Exception:
                pass
        else:
            overlay.attributes("-topmost", True)
        frame = tk.Frame(overlay, bg="black")
        frame.pack(fill="both", expand=True)
        base_size = max(self.font_size, 18)
        time_size = max(72, base_size * 3)
        focus_size = max(36, base_size * 2)
        schedule_size = max(22, base_size + 6)
        self._schedule_overlay_time_font = tkfont.Font(
            family=self.font_family,
            size=time_size,
            weight="bold",
        )
        self._schedule_overlay_current_font = tkfont.Font(
            family=self.font_family,
            size=focus_size,
            weight="bold",
        )
        self._schedule_overlay_schedule_font = tkfont.Font(
            family=self.font_family,
            size=schedule_size,
            weight="normal",
        )
        self._schedule_overlay_time_label = tk.Label(
            frame,
            fg="white",
            bg="black",
            justify="center",
            font=self._schedule_overlay_time_font,
        )
        self._schedule_overlay_time_label.pack(fill="x", pady=(80, 40))
        self._schedule_overlay_current_label = tk.Label(
            frame,
            fg="white",
            bg="black",
            justify="center",
            font=self._schedule_overlay_current_font,
        )
        self._schedule_overlay_current_label.pack(fill="x", pady=(0, 40))
        self._schedule_overlay_schedule_label = tk.Label(
            frame,
            fg="white",
            bg="black",
            justify="center",
            font=self._schedule_overlay_schedule_font,
        )
        self._schedule_overlay_schedule_label.pack(fill="both", expand=True, padx=40)
        try:
            overlay.update_idletasks()
            wrap_length = max(400, overlay.winfo_screenwidth() - 200)
            if self._schedule_overlay_current_label:
                self._schedule_overlay_current_label.config(wraplength=wrap_length)
            if self._schedule_overlay_schedule_label:
                self._schedule_overlay_schedule_label.config(wraplength=wrap_length)
        except Exception:
            pass
        self.schedule_overlay = overlay
        return overlay

    def _calculate_schedule_remaining(
        self, now: datetime, entry: dict[str, str]
    ) -> timedelta:
        try:
            end_time = datetime.strptime(entry["end"], "%H:%M").time()
        except (KeyError, ValueError):
            return timedelta()
        end_dt = now.replace(
            hour=end_time.hour,
            minute=end_time.minute,
            second=0,
            microsecond=0,
        )
        if end_dt < now:
            end_dt += timedelta(days=1)
        return max(end_dt - now, timedelta())

    def _format_overlay_remaining(self, remaining: timedelta) -> str:
        total_seconds = max(0, int(remaining.total_seconds()))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _should_lock_again(
        self, marker: tuple[str, str, str], now: datetime
    ) -> bool:
        if self._last_schedule_lock != marker:
            return True
        if self._last_schedule_lock_timestamp is None:
            return True
        return now - self._last_schedule_lock_timestamp >= timedelta(seconds=15)

    def _destroy_schedule_overlay(self) -> None:
        if self.schedule_overlay and tk.Toplevel.winfo_exists(self.schedule_overlay):
            try:
                self.schedule_overlay.destroy()
            except Exception:
                pass
        self.schedule_overlay = None
        self._schedule_overlay_time_label = None
        self._schedule_overlay_current_label = None
        self._schedule_overlay_schedule_label = None
        self._schedule_overlay_time_font = None
        self._schedule_overlay_current_font = None
        self._schedule_overlay_schedule_font = None

    def _lock_workstation(self, label: str) -> None:
        if not sys.platform.startswith("win"):
            return
        try:
            ctypes.windll.user32.LockWorkStation()
        except Exception:
            if not self._lock_fail_notified:
                messagebox.showerror(
                    self._t("notice_title"),
                    self._t("error_lock_failed"),
                )
                self._lock_fail_notified = True

    def open_schedule_manager(self) -> None:
        if self.schedule_window and tk.Toplevel.winfo_exists(self.schedule_window):
            self.schedule_window.deiconify()
            self.schedule_window.lift()
            self._refresh_schedule_language()
            return
        self.schedule_window = tk.Toplevel(self.root)
        self.schedule_window.title(self._t("schedule_title"))
        self.schedule_window.resizable(False, False)
        self.schedule_window.attributes("-topmost", True)
        self.schedule_window.protocol("WM_DELETE_WINDOW", self._close_schedule_window)
        self.schedule_window.transient(self.root)

        list_frame = tk.Frame(self.schedule_window)
        list_frame.pack(fill="both", expand=True, padx=12, pady=(12, 8))
        self.schedule_listbox = tk.Listbox(list_frame, height=10, activestyle="none")
        self.schedule_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(
            list_frame, orient="vertical", command=self.schedule_listbox.yview
        )
        scrollbar.pack(side="right", fill="y")
        self.schedule_listbox.config(yscrollcommand=scrollbar.set)

        button_frame = tk.Frame(self.schedule_window)
        button_frame.pack(fill="x", padx=12, pady=(0, 12))
        self.schedule_add_button = tk.Button(
            button_frame,
            text=self._t("schedule_add"),
            width=10,
            command=lambda: self._open_schedule_editor(None),
        )
        self.schedule_add_button.pack(side="left", padx=4)
        self.schedule_edit_button = tk.Button(
            button_frame,
            text=self._t("schedule_edit"),
            width=10,
            command=self._edit_schedule_entry,
        )
        self.schedule_edit_button.pack(side="left", padx=4)
        self.schedule_delete_button = tk.Button(
            button_frame,
            text=self._t("schedule_delete"),
            width=10,
            command=self._delete_schedule_entry,
        )
        self.schedule_delete_button.pack(side="left", padx=4)

        self._refresh_schedule_language()
        self.schedule_window.grab_set()

    def _get_schedule_selection_index(self) -> int | None:
        if not self.schedule_listbox:
            return None
        selection = self.schedule_listbox.curselection()
        if not selection:
            messagebox.showinfo(
                self._t("notice_title"),
                self._t("schedule_no_selection"),
            )
            return None
        return int(selection[0])

    def _open_schedule_editor(self, index: int | None) -> None:
        if index is not None and (index < 0 or index >= len(self.schedule)):
            return
        parent = self.schedule_window or self.root
        editor = tk.Toplevel(parent)
        editor.title(self._t("schedule_title"))
        editor.resizable(False, False)
        editor.attributes("-topmost", True)
        editor.transient(parent)

        current = (
            self.schedule[index]
            if index is not None
            else {
                "label": self._t("schedule_default_label"),
                "start": "12:00",
                "end": "13:00",
            }
        )

        label_var = tk.StringVar(value=current.get("label", ""))
        start_var = tk.StringVar(value=current.get("start", "12:00"))
        end_var = tk.StringVar(value=current.get("end", "13:00"))

        form = tk.Frame(editor, padx=12, pady=12)
        form.pack(fill="both", expand=True)

        tk.Label(form, text=self._t("schedule_label")).grid(row=0, column=0, sticky="w")
        label_entry = tk.Entry(form, textvariable=label_var, width=24)
        label_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        tk.Label(form, text=self._t("schedule_start")).grid(row=1, column=0, sticky="w", pady=(8, 0))
        start_entry = tk.Entry(form, textvariable=start_var, width=12)
        start_entry.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        tk.Label(form, text=self._t("schedule_end")).grid(row=2, column=0, sticky="w", pady=(8, 0))
        end_entry = tk.Entry(form, textvariable=end_var, width=12)
        end_entry.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        form.columnconfigure(1, weight=1)

        button_frame = tk.Frame(editor, pady=12)
        button_frame.pack()

        def save_entry() -> None:
            label_value = label_var.get().strip() or self._t("schedule_default_label")
            start_value = self._normalize_time_string(start_var.get())
            end_value = self._normalize_time_string(end_var.get())
            if not start_value or not end_value:
                messagebox.showerror(
                    self._t("notice_title"),
                    self._t("error_invalid_time"),
                )
                return
            start_minutes = self._time_to_minutes(start_value)
            end_minutes = self._time_to_minutes(end_value)
            if start_minutes is None or end_minutes is None or start_minutes >= end_minutes:
                messagebox.showerror(
                    self._t("notice_title"),
                    self._t("error_time_order"),
                )
                return
            updated = list(self.schedule)
            new_entry = {"label": label_value, "start": start_value, "end": end_value}
            if index is None:
                updated.append(new_entry)
            else:
                updated[index] = new_entry
            self._save_schedule(updated)
            editor.destroy()

        def cancel_entry() -> None:
            editor.destroy()

        tk.Button(
            button_frame, text=self._t("button_save"), width=10, command=save_entry
        ).pack(side="left", padx=4)
        tk.Button(
            button_frame, text=self._t("button_cancel"), width=10, command=cancel_entry
        ).pack(side="left", padx=4)

        editor.grab_set()
        label_entry.focus_set()

    def _edit_schedule_entry(self) -> None:
        index = self._get_schedule_selection_index()
        if index is None:
            return
        self._open_schedule_editor(index)

    def _delete_schedule_entry(self) -> None:
        index = self._get_schedule_selection_index()
        if index is None:
            return
        if not messagebox.askyesno(
            self._t("notice_title"),
            self._t("confirm_delete_schedule"),
        ):
            return
        updated = list(self.schedule)
        updated.pop(index)
        self._save_schedule(updated)

    def _save_schedule(self, entries: list[dict[str, str]]) -> None:
        sanitized = ensure_schedule(entries)
        self.schedule = [dict(entry) for entry in sanitized]
        self.config.schedule = [dict(entry) for entry in sanitized]
        self._persist_config()
        self._refresh_schedule_listbox()
        self._reset_schedule_monitor()

    def _refresh_schedule_listbox(self) -> None:
        if not self.schedule_listbox:
            return
        self.schedule_listbox.delete(0, "end")
        for entry in self.schedule:
            text = f"{entry['start']} - {entry['end']}  {entry['label']}"
            self.schedule_listbox.insert("end", text)

    def _refresh_schedule_language(self) -> None:
        if not self.schedule_window or not tk.Toplevel.winfo_exists(self.schedule_window):
            return
        self.schedule_window.title(self._t("schedule_title"))
        if self.schedule_add_button:
            self.schedule_add_button.config(text=self._t("schedule_add"))
        if self.schedule_edit_button:
            self.schedule_edit_button.config(text=self._t("schedule_edit"))
        if self.schedule_delete_button:
            self.schedule_delete_button.config(text=self._t("schedule_delete"))
        self._refresh_schedule_listbox()

    def _close_schedule_window(self) -> None:
        if self.schedule_window:
            self.schedule_window.destroy()
        self.schedule_window = None
        self.schedule_listbox = None
        self.schedule_add_button = None
        self.schedule_edit_button = None
        self.schedule_delete_button = None

    def open_history(self) -> None:
        if self.history_window and tk.Toplevel.winfo_exists(self.history_window):
            self.history_window.deiconify()
            self.history_window.lift()
            self._populate_history_tree()
            return
        self.history_window = tk.Toplevel(self.root)
        self.history_window.title(self._t("history_title"))
        self.history_window.resizable(False, False)
        self.history_window.attributes("-topmost", True)
        self.history_window.protocol("WM_DELETE_WINDOW", self._close_history)

        top_frame = tk.Frame(self.history_window, padx=12, pady=8)
        top_frame.pack(fill="x")
        self.history_date_label = tk.Label(
            top_frame,
            text=self._t("history_date_label"),
            anchor="w",
        )
        self.history_date_label.pack(side="left")

        self.history_date_var = tk.StringVar()
        self.history_combobox = ttk.Combobox(
            top_frame,
            textvariable=self.history_date_var,
            state="readonly",
            width=12,
        )
        self.history_combobox.pack(side="left", padx=(8, 0))

        def on_history_date_change(_event: object) -> None:
            self._populate_history_tree()

        self.history_combobox.bind("<<ComboboxSelected>>", on_history_date_change)

        tree_frame = tk.Frame(self.history_window, padx=12)
        tree_frame.pack(fill="both", expand=True, pady=(0, 8))
        columns = ("time", "event", "title")
        self.history_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            height=12,
        )
        self.history_tree.heading("time", text=self._t("history_column_time"))
        self.history_tree.heading("event", text=self._t("history_column_event"))
        self.history_tree.heading("title", text=self._t("history_column_title"))
        self.history_tree.column("time", width=100, anchor="center")
        self.history_tree.column("event", width=120, anchor="center")
        self.history_tree.column("title", width=260, anchor="w")
        self.history_tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.history_tree.yview
        )
        scrollbar.pack(side="right", fill="y")
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        button_frame = tk.Frame(self.history_window, pady=8)
        button_frame.pack(fill="x")
        self.history_close_button = tk.Button(
            button_frame,
            text=self._t("history_close"),
            width=12,
            command=self._close_history,
        )
        self.history_close_button.pack()

        self._populate_history_tree()

    def _populate_history_tree(self) -> None:
        if not self.history_tree or not self.history_combobox or not self.history_date_var:
            return
        history = load_history()
        dates = sorted(history.keys(), reverse=True)
        self.history_combobox["values"] = dates
        if dates:
            self.history_combobox.config(state="readonly")
        else:
            self.history_combobox.set("")
            self.history_combobox.config(state="disabled")

        selected = self.history_date_var.get()
        if not dates:
            selected = ""
            self.history_date_var.set("")
        elif selected not in dates:
            selected = dates[0]
            self.history_date_var.set(selected)

        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        if not selected:
            self.history_tree.insert(
                "",
                "end",
                values=("", "", self._t("history_empty")),
            )
            return

        records = history.get(selected, [])
        if not records:
            self.history_tree.insert(
                "",
                "end",
                values=("", "", self._t("history_empty")),
            )
            return

        sorted_records = sorted(
            records,
            key=lambda rec: rec.timestamp,
            reverse=True,
        )
        for record in sorted_records:
            try:
                timestamp = datetime.strptime(record.timestamp, ISO_FORMAT)
            except ValueError:
                continue
            time_value = timestamp.strftime("%H:%M:%S")
            event_label = self._event_label(record.event)
            self.history_tree.insert(
                "",
                "end",
                values=(time_value, event_label, record.title),
            )

    def _refresh_history_language(self) -> None:
        if not self.history_window or not tk.Toplevel.winfo_exists(self.history_window):
            return
        self.history_window.title(self._t("history_title"))
        if self.history_date_label:
            self.history_date_label.config(text=self._t("history_date_label"))
        if self.history_tree:
            self.history_tree.heading("time", text=self._t("history_column_time"))
            self.history_tree.heading("event", text=self._t("history_column_event"))
            self.history_tree.heading("title", text=self._t("history_column_title"))
        if self.history_close_button:
            self.history_close_button.config(text=self._t("history_close"))
        self._populate_history_tree()

    def _close_history(self) -> None:
        if self.history_window:
            self.history_window.destroy()
        self.history_window = None
        self.history_tree = None
        self.history_combobox = None
        self.history_date_var = None
        self.history_close_button = None
        self.history_date_label = None

    def on_ui_thread(self, callback, *args, **kwargs) -> None:
        self.root.after(0, lambda: callback(*args, **kwargs))

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.after(100, lambda: self.root.attributes("-topmost", True))

    def hide_window(self) -> None:
        self.root.withdraw()

    def set_message(self, message: str, persist: bool = True) -> None:
        message = message.strip()
        if not message:
            messagebox.showerror(
                self._t("notice_title"),
                self._t("error_empty"),
            )
            return
        self.message = message
        if not self.paused:
            self.base_message = message
        self._redraw_text()
        self._apply_geometry()
        if persist:
            self.config.message = message
            self._persist_config()

    def set_language(self, language: str) -> None:
        self.language = ensure_language(language, self.language)
        self.config.language = self.language
        self.root.title(self._t("app_title"))
        self.base_message = strip_pause_prefix(self.base_message)
        self._build_context_menu()
        self._update_pause_controls()
        self._refresh_history_language()
        self._refresh_schedule_language()
        if self.paused:
            paused_message = f"{self._t('pause_prefix')} {self.base_message}"
            self.set_message(paused_message)
        else:
            self._redraw_text()
            self._persist_config()
        self._trigger_time_update()

    def open_settings(self) -> None:
        if self.settings_window and tk.Toplevel.winfo_exists(self.settings_window):
            self.settings_window.deiconify()
            self.settings_window.lift()
            return
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title(self._t("settings_title"))
        self.settings_window.resizable(False, False)
        self.settings_window.attributes("-topmost", True)

        main_frame = tk.Frame(self.settings_window, padx=12, pady=12)
        main_frame.pack()

        tk.Label(
            main_frame,
            text=self._t("label_text"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        text_widget = tk.Text(main_frame, width=40, height=4, wrap="word")
        text_widget.insert("1.0", self.message)
        text_widget.grid(row=1, column=0, columnspan=2, sticky="ew")

        tk.Label(main_frame, text=self._t("label_font"), anchor="w").grid(
            row=2, column=0, sticky="w", pady=(12, 0)
        )
        font_entry = tk.Entry(main_frame)
        font_entry.insert(0, self.font_family)
        font_entry.grid(row=3, column=0, sticky="ew")

        tk.Label(main_frame, text=self._t("label_font_size"), anchor="w").grid(
            row=2, column=1, sticky="w", pady=(12, 0)
        )
        font_size_spin = tk.Spinbox(
            main_frame, from_=8, to=96, width=5, increment=1
        )
        font_size_spin.delete(0, "end")
        font_size_spin.insert(0, str(self.font_size))
        font_size_spin.grid(row=3, column=1, sticky="w")

        tk.Label(main_frame, text=self._t("label_text_color"), anchor="w").grid(
            row=4, column=0, sticky="w", pady=(12, 0)
        )
        text_color_entry = tk.Entry(main_frame)
        text_color_entry.insert(0, self.text_color)
        text_color_entry.grid(row=5, column=0, sticky="ew")

        tk.Label(main_frame, text=self._t("label_outline_color"), anchor="w").grid(
            row=4, column=1, sticky="w", pady=(12, 0)
        )
        outline_color_entry = tk.Entry(main_frame)
        outline_color_entry.insert(0, self.outline_color)
        outline_color_entry.grid(row=5, column=1, sticky="ew")

        tk.Label(main_frame, text=self._t("label_transparency"), anchor="w").grid(
            row=6, column=0, sticky="w", pady=(12, 0)
        )
        transparency_var = tk.StringVar(
            value=f"{self.transparency:.2f}".rstrip("0").rstrip(".")
        )
        transparency_entry = tk.Entry(main_frame, textvariable=transparency_var)
        transparency_entry.grid(row=7, column=0, sticky="ew")

        tk.Label(main_frame, text=self._t("label_language"), anchor="w").grid(
            row=6, column=1, sticky="w", pady=(12, 0)
        )
        language_var = tk.StringVar(value=self.language)
        language_option = tk.OptionMenu(main_frame, language_var, *SUPPORTED_LANGUAGES)
        menu = language_option["menu"]
        menu.delete(0, "end")
        for code in SUPPORTED_LANGUAGES:
            menu.add_command(
                label=self._t(f"language_option_{code}"),
                command=lambda value=code: language_var.set(value),
            )

        def update_language_label(*_args: object) -> None:
            code = language_var.get()
            label = (
                self._t(f"language_option_{code}")
                if code in SUPPORTED_LANGUAGES
                else code
            )
            language_option.config(text=label)

        language_var.trace_add("write", update_language_label)
        update_language_label()
        language_option.grid(row=7, column=1, sticky="ew")

        schedule_button = tk.Button(
            main_frame,
            text=self._t("label_schedule_button"),
            command=self.open_schedule_manager,
        )
        schedule_button.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        button_frame = tk.Frame(self.settings_window)
        button_frame.pack(pady=(6, 0))

        def save_and_close() -> None:
            new_message = text_widget.get("1.0", "end").strip()
            if not new_message:
                messagebox.showerror(
                    self._t("notice_title"),
                    self._t("error_empty"),
                )
                return
            new_font_family = font_entry.get().strip()
            new_font_size = ensure_font_size(font_size_spin.get(), self.font_size)
            new_text_color = text_color_entry.get().strip()
            new_outline_color = outline_color_entry.get().strip()
            new_transparency = transparency_var.get().strip()
            new_language = language_var.get()

            if not is_valid_color(new_text_color):
                messagebox.showerror(
                    self._t("notice_title"),
                    self._t("error_invalid_color"),
                )
                return
            if not is_valid_color(new_outline_color):
                messagebox.showerror(
                    self._t("notice_title"),
                    self._t("error_invalid_color"),
                )
                return
            try:
                parsed_transparency = float(new_transparency)
            except ValueError:
                messagebox.showerror(
                    self._t("notice_title"),
                    self._t("error_invalid_transparency"),
                )
                return

            self.set_message(new_message)
            self.font_family = new_font_family or self.font_family
            self.font_size = new_font_size
            self.text_font.config(family=self.font_family, size=self.font_size)
            self.time_font.config(
                family=self.font_family,
                size=max(10, self.font_size - 6),
            )
            self.config.font_family = self.font_family
            self.config.font_size = self.font_size

            self.text_color = ensure_color(new_text_color, self.text_color)
            self.outline_color = ensure_color(new_outline_color, self.outline_color)
            self.config.text_color = self.text_color
            self.config.outline_color = self.outline_color

            self.transparency = ensure_transparency(
                parsed_transparency, self.transparency
            )
            self.root.attributes("-alpha", self.transparency)
            self.config.transparency = self.transparency

            self.set_language(new_language)
            self._redraw_text()
            self._apply_geometry()
            self.settings_window.destroy()
            self.settings_window = None

        def cancel() -> None:
            self.settings_window.destroy()
            self.settings_window = None

        save_btn = tk.Button(
            button_frame,
            text=self._t("button_save"),
            width=10,
            command=save_and_close,
        )
        save_btn.pack(side="left", padx=4)
        cancel_btn = tk.Button(
            button_frame,
            text=self._t("button_cancel"),
            width=10,
            command=cancel,
        )
        cancel_btn.pack(side="left", padx=4)

        self.settings_window.protocol("WM_DELETE_WINDOW", cancel)
        self.settings_window.transient(self.root)
        self.settings_window.grab_set()

    def _create_tray_image(self) -> Image.Image:
        size = (64, 64)
        image = Image.new("RGBA", size, (30, 30, 30, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle([(6, 6), (58, 58)], outline=(255, 255, 255, 255), width=3)
        label = "T" if self.language != "zh" else "任"
        draw.text((20, 18), label, fill=(255, 255, 255, 255))
        return image

    def _start_tray(self) -> None:
        if self.tray_icon:
            return
        menu = pystray.Menu(
            pystray.MenuItem(self._t("tray_show"), self._tray_show),
            pystray.MenuItem(self._t("tray_hide"), self._tray_hide),
            pystray.MenuItem(self._current_pause_label(), self._tray_pause),
            pystray.MenuItem(self._t("tray_edit"), self._tray_edit),
            pystray.MenuItem(
                self._t("tray_autostart"),
                self._tray_autostart,
                checked=lambda item: self._is_autostart_enabled(),
            ),
            pystray.MenuItem(self._t("tray_history"), self._tray_history),
            pystray.MenuItem(self._t("tray_quit"), self._tray_quit),
        )
        self.tray_icon = pystray.Icon(
            "task",
            self._create_tray_image(),
            title=self._t("app_title"),
            menu=menu,
        )
        thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        thread.start()

    # Autostart (Windows) helpers
    def _tray_autostart(self, _icon, _item) -> None:
        self.on_ui_thread(self.toggle_autostart)

    def toggle_autostart(self) -> None:
        if not sys.platform.startswith("win"):
            return
        try:
            if self._is_autostart_enabled():
                self._disable_autostart()
            else:
                self._enable_autostart()
        finally:
            self._restart_tray()

    def _is_autostart_enabled(self) -> bool:
        if not sys.platform.startswith("win"):
            return False
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as key:
                winreg.QueryValueEx(key, self._autostart_value_name())
                return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def _enable_autostart(self) -> None:
        cmd = self._autostart_command()
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key, self._autostart_value_name(), 0, winreg.REG_SZ, cmd
                )
        except OSError as err:
            messagebox.showerror(self._t("notice_title"), str(err))

    def _disable_autostart(self) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                try:
                    winreg.DeleteValue(key, self._autostart_value_name())
                except FileNotFoundError:
                    pass
        except OSError as err:
            messagebox.showerror(self._t("notice_title"), str(err))

    def _autostart_value_name(self) -> str:
        return "AttentionTask"

    def _autostart_command(self) -> str:
        exe = Path(sys.executable)
        if sys.platform.startswith("win"):
            pythonw = exe.with_name("pythonw.exe")
            if pythonw.exists():
                exe = pythonw
        script = Path(sys.argv[0]).resolve()
        config_path = self.config_path.resolve()
        return f'"{exe}" "{script}" --config "{config_path}"'

    def _restart_tray(self) -> None:
        if not self.tray_icon:
            return
        self.tray_icon.stop()
        self.tray_icon = None
        self._start_tray()

    def _tray_show(self, _icon, _item) -> None:
        self.on_ui_thread(self.show_window)

    def _tray_hide(self, _icon, _item) -> None:
        self.on_ui_thread(self.hide_window)

    def _tray_pause(self, _icon, _item) -> None:
        self.on_ui_thread(self.pause_task)

    def _tray_edit(self, _icon, _item) -> None:
        self.on_ui_thread(self.open_settings)

    def _tray_history(self, _icon, _item) -> None:
        self.on_ui_thread(self.open_history)

    def _tray_quit(self, _icon, _item) -> None:
        self.on_ui_thread(self.quit)

    def quit(self) -> None:
        self._close_history()
        self._close_schedule_window()
        self._destroy_schedule_overlay()
        if self.tray_icon:
            self.tray_icon.stop()
        if self._time_job is not None:
            try:
                self.root.after_cancel(self._time_job)
            except Exception:
                pass
            self._time_job = None
        if self._schedule_check_job is not None:
            try:
                self.root.after_cancel(self._schedule_check_job)
            except Exception:
                pass
            self._schedule_check_job = None
        self.root.quit()
        self.root.destroy()

    def run(self) -> None:
        self._start_tray()
        self.show_window()
        self.root.mainloop()
