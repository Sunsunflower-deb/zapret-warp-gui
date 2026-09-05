"""Пути к ресурсам приложения (работает и в обычном режиме, и внутри PyInstaller)."""
import os
import sys

FROZEN = getattr(sys, "frozen", False)


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _data_dir():
    """Каталог с bin/lists/strategies.

    - Обычный режим: корень проекта.
    - PyInstaller: сначала папка рядом с .exe (портативно, списки можно
      править), затем бандл внутри .exe (_MEIPASS).
    """
    if FROZEN:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        meipass = getattr(sys, "_MEIPASS", "")
        for d in (exe_dir, meipass):
            if d and os.path.isdir(os.path.join(d, "bin")):
                return d
        return exe_dir
    return _project_root()


def _config_path():
    """config.json: рядом с exe, если туда можно писать; иначе в APPDATA/~."""
    if FROZEN:
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        if os.access(exe_dir, os.W_OK):
            return os.path.join(exe_dir, "config.json")
        if os.name == "nt" and os.environ.get("APPDATA"):
            d = os.path.join(os.environ["APPDATA"], "zapret-warp")
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, "config.json")
        d = os.path.join(os.path.expanduser("~"), ".config", "zapret-warp")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "config.json")
    return os.path.join(_project_root(), "config.json")


APP_DIR = _data_dir()
BIN_DIR = os.path.join(APP_DIR, "bin")
LISTS_DIR = os.path.join(APP_DIR, "lists")
STRATEGIES_DIR = os.path.join(APP_DIR, "strategies")
WGCF_DIR = os.path.join(APP_DIR, "wgcf")
CONFIG_PATH = _config_path()

IS_WINDOWS = os.name == "nt"


def desync_binary():
    """Бинарь DPI-десинка: winws.exe на Windows, nfqws на Linux."""
    return os.path.join(BIN_DIR, "winws.exe" if IS_WINDOWS else "nfqws")
