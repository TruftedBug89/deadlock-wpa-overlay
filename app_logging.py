"""Application logging (rotating file + optional console)."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "DeadlockWPAOverlay"
_CONFIGURED = False


class _QuietRotatingHandler(RotatingFileHandler):
    def handleError(self, record):
        # A full disk must not recurse through the redirected stderr stream.
        pass


class SafeLogStream:
    """Bound frozen-app print output, including very large diagnostic lines."""

    def __init__(self, path=None, max_bytes=1_000_000, backup_count=2):
        self.handler = None
        try:
            target = Path(path) if path else log_dir() / "app_debug.log"
            target.parent.mkdir(parents=True, exist_ok=True)
            self.handler = _QuietRotatingHandler(
                target, maxBytes=max_bytes, backupCount=backup_count,
                encoding="utf-8", delay=True,
            )
        except OSError:
            pass

    def write(self, text):
        if self.handler is not None:
            # Cap each record too: RotatingFileHandler permits oversized records.
            limit = max(1, min(2048, self.handler.maxBytes // 8))
            for start in range(0, len(text), limit):
                chunk = text[start:start + limit].rstrip("\r\n")
                if chunk:
                    record = logging.LogRecord("console", logging.INFO, "", 0, chunk, (), None)
                    self.handler.handle(record)
        return len(text)

    def flush(self):
        if self.handler is not None:
            self.handler.flush()

    def close(self):
        if self.handler is not None:
            self.handler.close()


def log_dir() -> Path:
    """Folder holding logs, diagnostics and the icon cache."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def setup_logging(level: int = logging.INFO, console: bool = False) -> Path:
    """Configure the root logger once; returns the log file path."""
    global _CONFIGURED
    path = log_dir() / "overlay.log"
    if _CONFIGURED:
        return path

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    try:
        handler = _QuietRotatingHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except Exception:
        pass

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)

    _CONFIGURED = True
    return path


def get_logger(name: str) -> logging.Logger:
    """Named logger (configure with :func:`setup_logging` first)."""
    return logging.getLogger(name)
