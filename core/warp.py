"""Управление Cloudflare WARP (warp-cli)."""
import enum
import getpass
import os
import re
import shutil
import subprocess
import sys
import time

from . import paths
from .logs import get as _log_get


# --- обнаружение warp-cli -----------------------------------------------
def _windows_paths():
    paths = []
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(var, "")
            if base:
                p = os.path.join(base, "Cloudflare", "Cloudflare WARP", "warp-cli.exe")
                paths.append(p)
    return paths


def find_cli():
    """Полный путь к warp-cli или None."""
    if os.name == "nt":
        p = shutil.which("warp-cli.exe")
        if p:
            return p
        for p in _windows_paths():
            if os.path.isfile(p):
                return p
        return None
    return shutil.which("warp-cli")


def installed():
    return find_cli() is not None


def _cli():
    return find_cli() or ("warp-cli.exe" if os.name == "nt" else "warp-cli")


# --- авто-установка из warp.msi (Windows) --------------------------------
def msi_path():
    """Путь к warp.msi рядом с exe/приложением (или None)."""
    if os.name != "nt":
        return None
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
    dirs.append(paths.APP_DIR)
    for d in dirs:
        p = os.path.join(d, "warp.msi")
        if os.path.isfile(p):
            return p
    return None


def install_warp_msi(timeout=180):
    """Тихая установка Cloudflare WARP из warp.msi рядом с exe.

    Требует прав администратора (exe собран с uac_admin). Возвращает True,
    если после установки warp-cli найден.
    """
    m = msi_path()
    if not m:
        return False
    r = subprocess.run(
        ["msiexec", "/i", m, "/quiet", "/norestart"],
        capture_output=True, text=True, **_no_window(),
    )
    # 0 = успех, 3010 = успех + требуется перезагрузка
    if r.returncode not in (0, 3010):
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if installed():
            return True
        time.sleep(3)
    return installed()


# --- подсказки по установке ----------------------------------------------
def _distro():
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.strip().split("=", 1)[1].strip('"')
    except OSError:
        pass
    return "unknown"


def install_guide():
    if os.name == "nt":
        return (
            "Установите официальный Cloudflare WARP (1.1.1.1): "
            "https://developers.cloudflare.com/cloudflare-one/connections/"
            "connect-devices/warp/download-warp/  "
            "или положите установщик warp.msi рядом и выполните:\n"
            "    msiexec /i warp.msi /quiet"
        )
    d = _distro()
    if d in ("arch", "manjaro", "endeavouros"):
        return "AUR:  yay -S cloudflare-warp-bin   (или paru -S cloudflare-warp-bin)"
    if d in ("debian", "ubuntu", "linuxmint", "pop"):
        return ("Официальный репозиторий Cloudflare: "
                "https://pkg.cloudflareclient.com/  затем:\n"
                "    apt install cloudflare-warp")
    if d in ("fedora", "rhel", "centos", "rocky", "almalinux"):
        return ("Официальный репозиторий Cloudflare: "
                "https://pkg.cloudflareclient.com/  затем:\n"
                "    dnf install cloudflare-warp")
    return ("Установите Cloudflare WARP — инструкции: "
            "https://developers.cloudflare.com/cloudflare-one/connections/"
            "connect-devices/warp/install-warp/linux/")


# --- выполнение ----------------------------------------------------------
def _warp_user(cfg):
    u = (cfg.get("warp_user") or "").strip() or "auto"
    if u != "auto":
        return u
    if os.name == "nt":
        return None
    if os.geteuid() == 0:
        sudo_user = os.environ.get("SUDO_USER") or os.environ.get("DOAS_USER")
        if sudo_user and sudo_user != "root":
            return sudo_user
    return None


def _no_window():
    """Windows: не показывать окно консоли у дочерних процессов (иначе из
    windowed-GUI каждые 3 с мигает окно терминала)."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def run(cfg, *args):
    user = _warp_user(cfg)
    cmd = [_cli()] + list(args)
    if user and user != getpass.getuser():
        cmd = ["sudo", "-u", user] + cmd
    return subprocess.run(cmd, capture_output=True, text=True, **_no_window())


def _err(r, what):
    """Человекочитаемая причина падения warp-cli."""
    txt = (r.stderr or r.stdout or "").strip()
    if txt:
        return "{}: {}".format(what, txt)
    return "{}: код возврата {}".format(what, r.returncode)


class WarpState(str, enum.Enum):
    """Состояние туннеля. Строковые значения — как их печатает warp-cli."""

    CONNECTED = "Connected"
    CONNECTING = "Connecting"
    DISCONNECTED = "Disconnected"
    DISCONNECTING = "Disconnecting"
    NO_REGISTRATION = "NoRegistration"
    UNKNOWN = "Unknown"


# Порядок важен: "disconnected" содержит "connected", а "disconnecting" —
# "connecting". Поэтому сначала отрицательные формы.
_WORDS = (
    ("disconnected", WarpState.DISCONNECTED),
    ("disconnecting", WarpState.DISCONNECTING),
    ("connecting", WarpState.CONNECTING),
    ("connected", WarpState.CONNECTED),
    ("registration missing", WarpState.NO_REGISTRATION),
    ("registration", WarpState.NO_REGISTRATION),
)

_STATE_RE = re.compile(r"^\s*Status update:\s*(.+?)\s*$", re.MULTILINE)


def parse_status(raw):
    """Сырой вывод `warp-cli status` → (WarpState, строка статуса).

    Чистая функция без побочных эффектов — её легко тестировать и
    использовать в GUI/watchdog без запуска процессов.
    """
    if not raw:
        return WarpState.UNKNOWN, ""
    text = str(raw).strip()
    match = _STATE_RE.search(text)
    line = (match.group(1) if match else text.splitlines()[0]).strip()
    low = line.lower()
    for word, state in _WORDS:
        if word in low:
            return state, line
    return WarpState.UNKNOWN, line


def state(cfg):
    """Текущее состояние WARP: (WarpState, строка)."""
    return parse_status(status(cfg))


def apply_settings(cfg):
    """Применить режим/протокол/endpoint.

    Возвращает список (что, текст ошибки). Раньше коды возврата молча
    игнорировались, и «не подключается» оставалось без причины: например,
    старый warp-cli не знает `tunnel masque-options`.
    """
    errors = []
    steps = [
        ("mode", ("mode", cfg.get("warp_mode", "warp+doh"))),
        ("protocol", ("tunnel", "protocol", "set", cfg.get("warp_protocol", "MASQUE"))),
        ("masque", ("tunnel", "masque-options", "set",
                    cfg.get("warp_masque", "h3-with-h2-fallback"))),
    ]
    for label, args in steps:
        r = run(cfg, *args)
        if r.returncode != 0:
            errors.append((label, _err(r, "warp-cli " + " ".join(map(str, args)))))
    ep = (cfg.get("warp_endpoint") or "").strip()
    if ep:
        r = run(cfg, "tunnel", "endpoint", "set", ep)
        if r.returncode != 0:
            errors.append(("endpoint", _err(r, "warp-cli tunnel endpoint set " + ep)))
    else:
        # сброс endpoint поддерживается не всеми версиями — не считаем ошибкой
        run(cfg, "tunnel", "endpoint", "reset")
    return errors


def connect(cfg, timeout=45):
    """Подключить WARP и дождаться состояния Connected.

    Возвращает строку статуса. Бросает RuntimeError с реальной причиной:
    вывод warp-cli, ошибки применения настроек и последнее состояние.
    """
    log = _log_get("warp")
    # сбрасываем зависшее состояние (51% / Connecting)
    run(cfg, "disconnect")
    time.sleep(1)

    for what, err in apply_settings(cfg):
        log.warning("настройка не применилась (%s): %s", what, err)

    r = run(cfg, "--accept-tos", "connect")
    if r.returncode != 0:
        raise RuntimeError(_err(r, "warp-cli connect"))

    last_state, last_line = WarpState.UNKNOWN, ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        last_state, last_line = state(cfg)
        if last_state is WarpState.CONNECTED:
            log.info("WARP подключён: %s", last_line)
            return last_line
        if last_state is WarpState.NO_REGISTRATION:
            raise RuntimeError(
                "WARP не зарегистрирован ({!r}).\n"
                "Запустите `python cli.py key` или войдите в приложение "
                "Cloudflare WARP.".format(last_line)
            )
    raise RuntimeError(
        "WARP не вышел в Connected за {} с. Последнее состояние: {} ({!r}).\n"
        "Проверьте: 1) приложение запущено от администратора (WinDivert); "
        "2) DPI-десинк реально работает (статус зелёный); "
        "3) warp-cli registration show — аккаунт зарегистрирован; "
        "4) на сети не режется UDP 443/MASQUE.".format(
            timeout, last_state.value, last_line)
    )


def disconnect(cfg):
    run(cfg, "disconnect")


def status(cfg):
    r = run(cfg, "status")
    return r.stdout.strip()


def registration(cfg):
    """Результат `warp-cli registration show` (пустая строка при ошибке)."""
    if not installed():
        return ""
    r = run(cfg, "registration", "show")
    return (r.stdout or r.stderr or "").strip()
