from __future__ import annotations

import math


def format_bytes(value: int) -> str:
    value = max(int(value or 0), 0)
    if value == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    unit_index = 0

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    precision = 0 if unit_index == 0 else 2
    return f"{size:.{precision}f} {units[unit_index]}"


def format_speed(value: int) -> str:
    return f"{format_bytes(value)}/s"


def format_progress(progress: float) -> str:
    return f"{progress:.1f}%"


def format_eta(remaining_bytes: int, speed: int) -> str:
    remaining_bytes = max(int(remaining_bytes or 0), 0)
    speed = max(int(speed or 0), 0)

    if remaining_bytes == 0:
        return "Done"
    if speed == 0:
        return "--"

    total_seconds = int(math.ceil(remaining_bytes / speed))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_duration(total_seconds: int) -> str:
    total_seconds = max(int(total_seconds or 0), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
