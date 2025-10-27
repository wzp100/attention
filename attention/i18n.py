from __future__ import annotations

from typing import Any

from .constants import DEFAULT_LANGUAGE

LANG_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "Task Reminder",
        "tray_show": "Show Task",
        "tray_hide": "Hide Window",
        "tray_edit": "Edit Task...",
        "tray_quit": "Quit",
        "tray_history": "View History",
        "settings_title": "Task Settings",
        "button_save": "Save",
        "button_cancel": "Cancel",
        "error_empty": "Task text cannot be empty.",
        "error_save": "Failed to save configuration:\\n{error}",
        "error_invalid_color": "Invalid color format. Use #RRGGBB.",
        "error_invalid_transparency": "Invalid transparency value. Use 0.2 - 1.0.",
        "error_history_save": "Failed to write history:\\n{error}",
        "notice_title": "Notice",
        "label_text": "Task Text",
        "label_font": "Font Family",
        "label_font_size": "Font Size",
        "label_text_color": "Text Color (#RRGGBB)",
        "label_outline_color": "Outline Color (#RRGGBB)",
        "label_transparency": "Transparency (0.2 - 1.0)",
        "label_language": "Language",
        "language_option_en": "English",
        "language_option_zh": "Chinese",
        "menu_start": "Start Task",
        "menu_pause": "Pause Task",
        "menu_resume": "Resume Task",
        "menu_stop": "Stop Task",
        "menu_history": "Open Task History",
        "prompt_start_title": "Start Task",
        "prompt_start_message": "Enter task name:",
        "prompt_edit_title": "Edit Task",
        "prompt_edit_message": "Update task text:",
        "pause_prefix": "Paused",
        "no_task": "No task",
        "history_title": "Task History",
        "history_close": "Close",
        "history_empty": "No records for today.",
        "history_column_time": "Time",
        "history_column_event": "Event",
        "history_column_title": "Task",
        "history_date_label": "Date",
        "history_event_start": "Started",
        "history_event_pause": "Paused",
        "history_event_resume": "Resumed",
        "history_event_stop": "Stopped",
        "time_started": "Start Time",
        "time_elapsed_less_minute": "Elapsed <1 minute",
        "time_elapsed_minutes": "Elapsed {minutes} minutes",
        "time_elapsed_hours": "Elapsed {hours}h {minutes}m",
        "time_elapsed_hours_only": "Elapsed {hours} hours",
    },
    "zh": {
        "app_title": "任务提醒",
        "tray_show": "显示任务",
        "tray_hide": "隐藏窗口",
        "tray_edit": "编辑任务...",
        "tray_quit": "退出",
        "tray_history": "查看历史",
        "settings_title": "任务设置",
        "button_save": "保存",
        "button_cancel": "取消",
        "error_empty": "任务内容不能为空。",
        "error_save": "保存配置失败：\n{error}",
        "error_invalid_color": "颜色格式不正确，请使用 #RRGGBB。",
        "error_invalid_transparency": "透明度数值不正确，范围 0.2 - 1.0。",
        "error_history_save": "写入历史失败：\n{error}",
        "notice_title": "提示",
        "label_text": "任务内容",
        "label_font": "字体",
        "label_font_size": "字号",
        "label_text_color": "文字颜色 (#RRGGBB)",
        "label_outline_color": "描边颜色 (#RRGGBB)",
        "label_transparency": "透明度 (0.2 - 1.0)",
        "label_language": "语言",
        "language_option_en": "英语",
        "language_option_zh": "中文",
        "menu_start": "开始任务",
        "menu_pause": "暂停任务",
        "menu_resume": "继续任务",
        "menu_stop": "终止任务",
        "menu_history": "查看任务历史",
        "prompt_start_title": "开始任务",
        "prompt_start_message": "请输入任务名称：",
        "prompt_edit_title": "编辑任务",
        "prompt_edit_message": "修改任务内容：",
        "pause_prefix": "暂停中",
        "no_task": "暂无任务",
        "history_title": "任务历史",
        "history_close": "关闭",
        "history_empty": "今天还没有任务记录。",
        "history_column_time": "时间",
        "history_column_event": "状态",
        "history_column_title": "任务",
        "history_date_label": "日期",
        "history_event_start": "已开始",
        "history_event_pause": "已暂停",
        "history_event_resume": "已继续",
        "history_event_stop": "已终止",
        "time_started": "开始时间",
        "time_elapsed_less_minute": "已过去不足1分钟",
        "time_elapsed_minutes": "已过去{minutes}分钟",
        "time_elapsed_hours": "已过去{hours}小时{minutes}分",
        "time_elapsed_hours_only": "已过去{hours}小时",
    },
}

SUPPORTED_LANGUAGES = tuple(LANG_STRINGS.keys())
NO_TASK_VALUES = {data["no_task"] for data in LANG_STRINGS.values()}


def get_strings(language: str) -> dict[str, str]:
    return LANG_STRINGS.get(language, LANG_STRINGS[DEFAULT_LANGUAGE])


def translate(language: str, key: str, **kwargs: Any) -> str:
    strings = get_strings(language)
    template = strings.get(key, key)
    return template.format(**kwargs)


def strip_pause_prefix(text: str) -> str:
    for data in LANG_STRINGS.values():
        prefix = data["pause_prefix"]
        if text.startswith(prefix):
            return text[len(prefix) :].lstrip()
    return text
