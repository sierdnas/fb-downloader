"""
In-memory application logs (lost on container restart — a deliberate
choice for simplicity, as requested). The configured level
(Settings.log_level, persisted like the other settings) acts as a
threshold: only messages with level <= threshold get RECORDED (not just
hidden in the UI) — so raising the level before reproducing a problem
captures the detail, and keeping it low doesn't waste buffer space on
noise nobody wants to see right now.

Levels:
    0 = errors only
    1 = main events (analysis/download started/completed)
    2 = technical detail (commands run, retry attempts)
    3 = everything, including the full raw output of yt-dlp/gallery-dl
"""
import threading
from collections import deque
from datetime import datetime

_MAX_ENTRIES = 2000
_buffer: "deque[str]" = deque(maxlen=_MAX_ENTRIES)
_lock = threading.Lock()

LEVEL_NAMES = {0: "ERROR", 1: "INFO", 2: "DEBUG", 3: "TRACE"}

# limit per single log entry: a huge raw output (level 3) could
# otherwise consume most of the buffer on its own
_MAX_ENTRY_CHARS = 4000


def log(level: int, message: str) -> None:
    from .config import settings  # imported here to avoid a cycle with config.py

    if level > settings.log_level:
        return

    if len(message) > _MAX_ENTRY_CHARS:
        message = message[:_MAX_ENTRY_CHARS] + "… (truncated)"

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    level_name = LEVEL_NAMES.get(level, str(level))
    entry = f"{timestamp} [{level_name}] {message}"

    with _lock:
        _buffer.append(entry)


def get_logs() -> list[str]:
    with _lock:
        return list(_buffer)


def clear_logs() -> None:
    with _lock:
        _buffer.clear()
