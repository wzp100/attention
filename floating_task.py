from __future__ import annotations

import argparse
import sys
from pathlib import Path

from attention import CONFIG_FILE, TaskApp, TaskConfig


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Floating always-on-top task window with system tray controls.",
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


def run_app(argv: list[str]) -> None:
    args = parse_args(argv)
    config_path = Path(args.config)
    config = TaskConfig.load(config_path)

    app = TaskApp(config, config_path)

    if args.text is not None:
        session_text = args.text.strip()
        if session_text:
            app.apply_session_text(session_text, persist=not args.no_persist)
        else:
            from PyQt6 import QtWidgets

            QtWidgets.QMessageBox.critical(
                app,
                app.tr("notice_title"),
                app.tr("error_empty"),
            )

    app.run()


def main(argv: list[str]) -> None:
    run_app(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
