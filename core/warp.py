"""Управление Cloudflare WARP (warp-cli)."""
import getpass
import os
import shutil
import subprocess
import time


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


def apply_settings(cfg):
    run(cfg, "mode", cfg.get("warp_mode", "warp+doh"))
    run(cfg, "tunnel", "protocol", "set", cfg.get("warp_protocol", "MASQUE"))
    run(cfg, "tunnel", "masque-options", "set",
        cfg.get("warp_masque", "h3-with-h2-fallback"))
    ep = (cfg.get("warp_endpoint") or "").strip()
    if ep:
        run(cfg, "tunnel", "endpoint", "set", ep)
    else:
        run(cfg, "tunnel", "endpoint", "reset")


def connect(cfg, timeout=45):
    """Подключить WARP и дождаться статуса Connected.

    Возвращает итоговый статус. Бросает RuntimeError с реальной причиной,
    если warp-cli упал или туннель не поднялся за timeout секунд
    (Cloudflare One часто «застревает» на Connecting — см. hints).
    """
    # сбрасываем зависшее состояние (51% / Connecting)
    run(cfg, "disconnect")
    time.sleep(1)

    apply_settings(cfg)

    r = run(cfg, "--accept-tos", "connect")
    if r.returncode != 0:
        raise RuntimeError(_err(r, "warp-cli connect"))

    last = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        st = status(cfg)
        last = st
        if "Connected" in st:
            return st.strip()
    raise RuntimeError(
        "WARP не вышел в Connected за {} с. Последний статус: {!r}.\n"
        "Проверьте: 1) приложение запущено от администратора (WinDivert); "
        "2) DPI-десинк реально работает (статус зелёный); "
        "3) warp-cli registration show — аккаунт зарегистрирован; "
        "4) на сети не режется UDP 443/MASQUE.".format(timeout, last)
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
