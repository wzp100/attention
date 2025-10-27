from __future__ import annotations

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

    def _t(self, key: str, **kwargs) -> str:
        return translate(self.language, key, **kwargs)

    def _redraw_text(self) -> None:
        self.canvas.delete("all")
        text = self.message or " "
        time_text = self._format_time_text()
        self._current_time_text = time_text

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

        content_width = max(text_width, time_width)
        width = max(content_width + PADDING * 2, 200)
        height = text_height + (TIME_GAP + time_height if time_text else 0) + PADDING * 2
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

        if time_text:
            time_center_y = (
                text_center_y + text_height / 2 + TIME_GAP + time_height / 2
            )
            self._draw_text_with_outline(
                center_x,
                time_center_y,
                time_text,
                self.time_font,
                TIME_TEXT_COLOR,
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
        prompt = simpledialog.askstring(
            self._t("prompt_start_title"),
            self._t("prompt_start_message"),
            initialvalue=""
            if not self.base_message or self.base_message in NO_TASK_VALUES
            else self.base_message,
            parent=self.root,
        )
        if prompt is None:
            return
        task_name = prompt.strip()
        if not task_name:
            messagebox.showerror(
                self._t("notice_title"),
                self._t("error_empty"),
            )
            return
        self.task_active = True
        self.paused = False
        self.start_time = datetime.now()
        self.elapsed_before_pause = timedelta()
        self.base_message = task_name
        self.text_color = ACTIVE_TEXT_COLOR
        self.config.text_color = self.text_color
        self.set_message(task_name)
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
        if self.tray_icon:
            self.tray_icon.stop()
        if self._time_job is not None:
            try:
                self.root.after_cancel(self._time_job)
            except Exception:
                pass
            self._time_job = None
        self.root.quit()
        self.root.destroy()

    def run(self) -> None:
        self._start_tray()
        self.show_window()
        self.root.mainloop()
