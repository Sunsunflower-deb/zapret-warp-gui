"""Логи приложения в файл с ротацией.

Печатать в консоль из GUI нельзя (windowed-сборка без stdout), а диагностировать
«что было в 14:03» нужно. Поэтому единственный общий сток — файл в
платформенном каталоге состояния:

* Windows: %LOCALAPPDATA%\\zapret-warp\\zapret-warp.log
* Linux:   $XDG_STATE_HOME/zapret-warp/zapret-warp.log (~/.local/state/...)

Ротация: 1 МБ × 3 файла.
"""
import logging
import logging.handlers
import os
import sys

FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
MAX_BYTES = 1 * 1024 * 1024
BACKUPS = 3
_NAME = "zapret-warp"

_configured = False


def log_dir():
    """Каталог для логов (создаётся)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "state"
        )
    path = os.path.join(base, _NAME)
    os.makedirs(path, exist_ok=True)
    return path


def log_path():
    return os.path.join(log_dir(), _NAME + ".log")


def setup(level=logging.INFO, console=None):
    """Настроить единый логгер приложения (идемпотентно).

    console: True — печатать ещё и в stderr (CLI), False — только файл (GUI),
    None — решить по наличию stdout.
    """
    global _configured
    logger = logging.getLogger(_NAME)
    if _configured:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    try:
        handler = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(FMT))
        handler.setLevel(level)
        logger.addHandler(handler)
    except OSError:
        # Нет прав/места — приложение должно работать и без файла
        pass

    if console is None:
        console = sys.stderr is not None and sys.stderr.isatty()
    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(FMT))
        stream.setLevel(level)
        logger.addHandler(stream)

    _configured = True
    return logger


def get(name=None):
    """Дочерний логгер приложения: logs.get("engine") → zapret-warp.engine."""
    root = logging.getLogger(_NAME)
    if not _configured:
        setup()
    return root.getChild(name) if name else root


def reset():
    """Сбросить состояние (для тестов)."""
    global _configured
    logger = logging.getLogger(_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    _configured = False
