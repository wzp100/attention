import argparse
import json
import pathlib
import sys
import threading
import tkinter as tk
from dataclasses import asdict, dataclass
from tkinter import messagebox

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover - dependency guard
    missing = "pystray pillow"
    raise SystemExit(
        f"Missing dependency ({exc.name}). Install with: pip install {missing}"
    ) from exc


CONFIG_FILE = pathlib.Path("config.json")
TRANSPARENT_COLOR = "#010101"
FOREGROUND_COLOR = "#f2f2f2"
OUTLINE_COLOR = "#000000"
DEFAULT_MESSAGE = "Set your task..."
TEXT_FONT = ("Segoe UI", 18, "bold")
WRAP_LENGTH = 600
PADDING = 16


@dataclass
class TaskConfig:
    message: str = DEFAULT_MESSAGE
    x: int | None = None
    y: int | None = None

    @classmethod
    def load(cls, path: pathlib.Path) -> "TaskConfig":
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
        return cls(message=message, x=x, y=y)

    def save(self, path: pathlib.Path) -> None:
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class TaskApp:
    def __init__(self, config: TaskConfig, config_path: pathlib.Path) -> None:
        self.config = config
        self.config_path = config_path
        self.message = config.message or DEFAULT_MESSAGE
        self.root = tk.Tk()
        self.root.title("Task Reminder")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_COLOR)
        self.root.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)

        self._drag_start_x = 0
        self._drag_start_y = 0
        self.settings_window: tk.Toplevel | None = None
        self.tray_icon: pystray.Icon | None = None

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

        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.bind("<Escape>", lambda _event: self.hide_window())

        self._redraw_text()
        self._apply_geometry()

    def _redraw_text(self) -> None:
        self.canvas.delete("all")
        text = self.message or " "
        temp_id = self.canvas.create_text(
            0,
            0,
            text=text,
            font=TEXT_FONT,
            width=WRAP_LENGTH,
            anchor="nw",
            justify="center",
            fill=FOREGROUND_COLOR,
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

        width = max(text_width + PADDING * 2, 200)
        height = max(text_height + PADDING * 2, 60)
        self.canvas.config(width=width, height=height)

        center_x = width // 2
        center_y = height // 2

        if text.strip():
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if dx == 0 and dy == 0:
                        continue
                    self.canvas.create_text(
                        center_x + dx,
                        center_y + dy,
                        text=text,
                        font=TEXT_FONT,
                        fill=OUTLINE_COLOR,
                        justify="center",
                        width=WRAP_LENGTH,
                        anchor="center",
                    )

        self.canvas.create_text(
            center_x,
            center_y,
            text=text,
            font=TEXT_FONT,
            fill=FOREGROUND_COLOR,
            justify="center",
            width=WRAP_LENGTH,
            anchor="center",
        )
        self.root.update_idletasks()

    def _apply_geometry(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        if self.config.x is not None and self.config.y is not None:
            self.root.geometry(f"{width}x{height}+{self.config.x}+{self.config.y}")
        else:
            screen_width = self.root.winfo_screenwidth()
            x = (screen_width - width) // 2
            y = 40
            self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _persist_config(self) -> None:
        try:
            self.config.save(self.config_path)
        except OSError as err:
            messagebox.showerror("Notice", f"Failed to save configuration:\n{err}")

    def _on_button_press(self, event: tk.Event) -> None:
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_mouse_drag(self, event: tk.Event) -> None:
        x = event.x_root - self._drag_start_x
        y = event.y_root - self._drag_start_y
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _on_button_release(self, _event: tk.Event) -> None:
        self.config.x = self.root.winfo_x()
        self.config.y = self.root.winfo_y()
        self._persist_config()

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
            messagebox.showerror("Notice", "Task text cannot be empty.")
            return
        self.message = message
        self._redraw_text()
        self._apply_geometry()
        if persist:
            self.config.message = message
            self._persist_config()

    def open_settings(self) -> None:
        if self.settings_window and tk.Toplevel.winfo_exists(self.settings_window):
            self.settings_window.deiconify()
            self.settings_window.lift()
            return
        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("Task Settings")
        self.settings_window.resizable(False, False)
        self.settings_window.attributes("-topmost", True)

        text_widget = tk.Text(self.settings_window, width=40, height=6, wrap="word")
        text_widget.insert("1.0", self.message)
        text_widget.pack(padx=12, pady=(12, 6))

        button_frame = tk.Frame(self.settings_window)
        button_frame.pack(pady=(0, 12))

        def save_and_close() -> None:
            new_message = text_widget.get("1.0", "end").strip()
            if not new_message:
                messagebox.showerror("Notice", "Task text cannot be empty.")
                return
            self.set_message(new_message)
            self.settings_window.destroy()
            self.settings_window = None

        def cancel() -> None:
            self.settings_window.destroy()
            self.settings_window = None

        save_btn = tk.Button(button_frame, text="Save", width=10, command=save_and_close)
        save_btn.pack(side="left", padx=4)
        cancel_btn = tk.Button(button_frame, text="Cancel", width=10, command=cancel)
        cancel_btn.pack(side="left", padx=4)

        self.settings_window.protocol("WM_DELETE_WINDOW", cancel)
        self.settings_window.transient(self.root)
        self.settings_window.grab_set()

    def _create_tray_image(self) -> Image.Image:
        size = (64, 64)
        image = Image.new("RGBA", size, (30, 30, 30, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle([(6, 6), (58, 58)], outline=(255, 255, 255, 255), width=3)
        draw.text((20, 18), "T", fill=(255, 255, 255, 255))
        return image

    def _start_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Show Task", self._tray_show),
            pystray.MenuItem("Hide Window", self._tray_hide),
            pystray.MenuItem("Edit Task...", self._tray_edit),
            pystray.MenuItem("Quit", self._tray_quit),
        )
        self.tray_icon = pystray.Icon(
            "task",
            self._create_tray_image(),
            title="Task Reminder",
            menu=menu,
        )
        thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        thread.start()

    def _tray_show(self, _icon, _item) -> None:
        self.on_ui_thread(self.show_window)

    def _tray_hide(self, _icon, _item) -> None:
        self.on_ui_thread(self.hide_window)

    def _tray_edit(self, _icon, _item) -> None:
        self.on_ui_thread(self.open_settings)

    def _tray_quit(self, _icon, _item) -> None:
        self.on_ui_thread(self.quit)

    def quit(self) -> None:
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()
        self.root.destroy()

    def run(self) -> None:
        self._start_tray()
        self.show_window()
        self.root.mainloop()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Floating always-on-top task window with system tray controls."
    )
    parser.add_argument(
        "--text",
        help="Task text to display for this session.",
    )
    parser.add_argument(
        "--config",
        default=str(CONFIG_FILE),
        help="Path to the JSON configuration file.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write the provided --text into the configuration.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    config_path = pathlib.Path(args.config)
    config = TaskConfig.load(config_path)

    app = TaskApp(config, config_path)

    if args.text is not None:
        session_text = args.text.strip()
        if session_text:
            app.set_message(session_text, persist=not args.no_persist)
            if args.no_persist:
                app.config.message = config.message
        else:
            messagebox.showerror("Notice", "Task text cannot be empty.")

    app.run()


if __name__ == "__main__":
    main(sys.argv[1:])
